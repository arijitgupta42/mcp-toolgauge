"""Connecting to the fixture servers for real, over both transports.

These spawn subprocesses, so they carry the `integration` marker. They are also where the
read-only invariant is actually enforced: `badserver`'s tool bodies write a marker to
stderr if they ever run, and nothing here should ever see it.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mcpcheckup.connect import ConnectionFailed, StdioTarget, inspect_server, resolve_target
from mcpcheckup.connect.target import HttpTarget

pytestmark = pytest.mark.integration

NEVER_CALLED_MARKER = "MCPCHECKUP_FIXTURE_TOOL_WAS_INVOKED"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def http_goodserver(goodserver_dir: Path):
    """Run goodserver over Streamable HTTP for the duration of one test."""
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "server.py", "--http", "--port", str(port)],
        cwd=goodserver_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = f"http://127.0.0.1:{port}/mcp"
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"server exited early:\n{process.communicate()[0]}")
            with socket.socket() as probe:
                probe.settimeout(0.5)
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.2)
        else:
            raise RuntimeError(f"server did not open port {port} within 30s")
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()


class TestStdio:
    async def test_badserver_advertises_its_tools(self, badserver_dir: Path) -> None:
        result = await inspect_server(resolve_target(str(badserver_dir)))

        assert "search_users" in result.tool_names
        assert "search_orgs" in result.tool_names
        assert len(result.tools) == 10

    async def test_goodserver_advertises_its_tools(self, goodserver_dir: Path) -> None:
        result = await inspect_server(resolve_target(str(goodserver_dir)))

        assert "search_users" in result.tool_names
        assert "search_organizations" in result.tool_names
        assert len(result.tools) == 8

    async def test_server_identity_is_captured(self, goodserver_dir: Path) -> None:
        result = await inspect_server(resolve_target(str(goodserver_dir)))

        assert result.server.name == "acme-directory"
        assert result.server.version == "1.0.0"
        assert result.server.protocol_version
        assert result.server.instructions and "directory" in result.server.instructions

    async def test_annotations_survive_the_round_trip(self, goodserver_dir: Path) -> None:
        result = await inspect_server(resolve_target(str(goodserver_dir)))
        by_name = {tool.name: tool for tool in result.tools}

        archive = by_name["archive_ticket"].annotations
        assert archive is not None and archive.destructive_hint is True

        search = by_name["search_users"].annotations
        assert search is not None and search.read_only_hint is True

    async def test_a_server_that_declares_nothing_reports_none_not_false(
        self, badserver_dir: Path
    ) -> None:
        """badserver sets no annotations at all, which must stay distinguishable from False."""
        result = await inspect_server(resolve_target(str(badserver_dir)))
        by_name = {tool.name: tool for tool in result.tools}

        annotations = by_name["delete_all_tickets"].annotations
        assert annotations is None or annotations.destructive_hint is None

    async def test_parameter_schemas_are_captured(self, goodserver_dir: Path) -> None:
        result = await inspect_server(resolve_target(str(goodserver_dir)))
        by_name = {tool.name: tool for tool in result.tools}

        parameters = by_name["search_users"].parameters
        assert "query" in parameters
        assert parameters["query"]["description"]
        assert by_name["search_users"].required_parameters == ("query",)

    async def test_the_target_is_recorded_on_the_result(self, goodserver_dir: Path) -> None:
        result = await inspect_server(resolve_target(str(goodserver_dir)))

        assert "server.py" in result.target


class TestReadOnlyInvariant:
    async def test_inspecting_never_invokes_a_tool(
        self, badserver_dir: Path, capfd: pytest.CaptureFixture[str]
    ) -> None:
        """The whole product depends on this: we look, we do not touch."""
        await inspect_server(resolve_target(str(badserver_dir)))

        captured = capfd.readouterr()
        assert NEVER_CALLED_MARKER not in captured.out
        assert NEVER_CALLED_MARKER not in captured.err


class TestHttp:
    async def test_tools_come_back_over_http(self, http_goodserver: str) -> None:
        result = await inspect_server(HttpTarget(url=http_goodserver))

        assert len(result.tools) == 8
        assert "search_users" in result.tool_names

    async def test_http_and_stdio_agree(self, http_goodserver: str, goodserver_dir: Path) -> None:
        """The transport must not change what we observe about a server."""
        over_http = await inspect_server(HttpTarget(url=http_goodserver))
        over_stdio = await inspect_server(resolve_target(str(goodserver_dir)))

        assert over_http.tool_names == over_stdio.tool_names


class TestFailures:
    async def test_a_crashing_server_reports_its_stderr(self, tmp_path: Path) -> None:
        script = tmp_path / "server.py"
        script.write_text('raise RuntimeError("no API key configured")\n', encoding="utf-8")

        with pytest.raises(ConnectionFailed) as caught:
            await inspect_server(resolve_target(str(tmp_path)), timeout=20)

        # Without the server's own stderr this error would be unactionable.
        assert "no API key configured" in str(caught.value)

    async def test_a_missing_executable_is_reported(self, tmp_path: Path) -> None:
        target = StdioTarget(command="definitely-not-a-real-command-xyz", cwd=tmp_path)

        with pytest.raises(ConnectionFailed) as caught:
            await inspect_server(target, timeout=20)

        assert "definitely-not-a-real-command-xyz" in str(caught.value)

    async def test_a_silent_server_times_out_with_advice(self, tmp_path: Path) -> None:
        script = tmp_path / "server.py"
        # Reads nothing, writes nothing, never exits: the classic hung-server shape.
        script.write_text("import time\ntime.sleep(120)\n", encoding="utf-8")

        with pytest.raises(ConnectionFailed) as caught:
            await inspect_server(resolve_target(str(tmp_path)), timeout=3)

        message = str(caught.value)
        assert "--timeout" in message

    async def test_an_unreachable_url_fails_rather_than_hangs(self) -> None:
        target = HttpTarget(url=f"http://127.0.0.1:{_free_port()}/mcp")

        with pytest.raises(ConnectionFailed):
            await inspect_server(target, timeout=15)
