"""The CLI contract: what people and CI actually depend on.

Exit codes matter more than output here. `mcp-doctor` is meant to sit in a pipeline, and a
tool that returns 0 when it failed is worse than one that does nothing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mcp_doctor.cli import EXIT_CONNECTION, EXIT_OK, EXIT_USAGE, app

runner = CliRunner()

GOLDEN = Path(__file__).parent / "golden" / "inspect_goodserver.json"

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def normalise(payload: dict) -> dict:
    """Blank out anything that legitimately changes between SDK releases.

    The protocol version is the server's, not ours. Pinning it would turn every spec bump
    into a failing golden test for a shape that did not actually change.
    """
    normalised = json.loads(json.dumps(payload))
    if "protocol_version" in normalised.get("server", {}):
        normalised["server"]["protocol_version"] = "<protocol>"
    return normalised


@pytest.mark.integration
class TestExitCodes:
    def test_a_good_run_exits_zero(self, goodserver_dir: Path) -> None:
        result = runner.invoke(app, ["inspect", str(goodserver_dir)])

        assert result.exit_code == EXIT_OK

    def test_an_unresolvable_target_is_a_usage_error(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["inspect", str(tmp_path / "nope")])

        assert result.exit_code == EXIT_USAGE

    def test_an_empty_directory_is_a_usage_error(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["inspect", str(tmp_path)])

        assert result.exit_code == EXIT_USAGE

    def test_a_server_that_will_not_start_is_a_connection_failure(self, tmp_path: Path) -> None:
        (tmp_path / "server.py").write_text('raise SystemExit("boom")\n', encoding="utf-8")

        result = runner.invoke(app, ["inspect", str(tmp_path), "--timeout", "20"])

        # Distinct from a usage error: we knew what to run, it just did not work.
        assert result.exit_code == EXIT_CONNECTION

    def test_no_arguments_is_not_a_crash(self) -> None:
        result = runner.invoke(app, [])

        assert result.exit_code != 1
        assert "inspect" in result.output


@pytest.mark.integration
class TestTableOutput:
    def test_tool_names_are_printed(self, badserver_dir: Path) -> None:
        result = runner.invoke(app, ["inspect", str(badserver_dir)], env={"COLUMNS": "120"})

        assert "search_users" in result.output
        assert "delete_all_tickets" in result.output

    def test_the_tool_count_is_summarised(self, badserver_dir: Path) -> None:
        result = runner.invoke(app, ["inspect", str(badserver_dir)], env={"COLUMNS": "120"})

        assert "10 tools" in result.output

    def test_verbose_adds_parameter_detail(self, goodserver_dir: Path) -> None:
        quiet = runner.invoke(app, ["inspect", str(goodserver_dir)], env={"COLUMNS": "120"})
        loud = runner.invoke(app, ["inspect", str(goodserver_dir), "-v"], env={"COLUMNS": "120"})

        assert "organization_id" not in quiet.output
        assert "organization_id" in loud.output

    def test_undocumented_parameters_are_called_out(self, badserver_dir: Path) -> None:
        result = runner.invoke(app, ["inspect", str(badserver_dir), "-v"], env={"COLUMNS": "120"})

        assert "(undocumented)" in result.output

    def test_a_missing_description_is_called_out(self, badserver_dir: Path) -> None:
        result = runner.invoke(app, ["inspect", str(badserver_dir)], env={"COLUMNS": "120"})

        assert "(no description)" in result.output

    def test_output_stays_ascii(self, badserver_dir: Path) -> None:
        """Windows consoles and CI logs mangle decorative glyphs, so we emit none."""
        result = runner.invoke(app, ["inspect", str(badserver_dir)], env={"COLUMNS": "60"})

        assert result.output.isascii()

    def test_narrow_terminals_keep_every_column(self, badserver_dir: Path) -> None:
        result = runner.invoke(app, ["inspect", str(badserver_dir)], env={"COLUMNS": "60"})

        # The name column collapsing was a real regression; guard it.
        assert "delete_all_tickets" in result.output
        assert "params" in result.output

    def test_piped_output_carries_no_ansi(self, goodserver_dir: Path) -> None:
        result = runner.invoke(app, ["inspect", str(goodserver_dir)], env={"COLUMNS": "120"})

        assert not ANSI.search(result.output)


@pytest.mark.integration
class TestJsonOutput:
    def test_the_payload_parses(self, goodserver_dir: Path) -> None:
        result = runner.invoke(app, ["inspect", str(goodserver_dir), "--json"])

        payload = json.loads(result.output)
        assert payload["server"]["name"] == "acme-directory"
        assert len(payload["tools"]) == 8

    def test_keys_are_sorted(self, goodserver_dir: Path) -> None:
        result = runner.invoke(app, ["inspect", str(goodserver_dir), "--json"])

        payload = json.loads(result.output)
        assert list(payload) == sorted(payload)

    def test_output_is_stable_between_runs(self, goodserver_dir: Path) -> None:
        first = runner.invoke(app, ["inspect", str(goodserver_dir), "--json"]).output
        second = runner.invoke(app, ["inspect", str(goodserver_dir), "--json"]).output

        assert first == second

    def test_matches_the_golden_file(self, goodserver_dir: Path) -> None:
        result = runner.invoke(app, ["inspect", str(goodserver_dir), "--json"])

        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        assert normalise(json.loads(result.output)) == normalise(expected)


class TestVersion:
    def test_version_prints_and_exits_cleanly(self) -> None:
        result = runner.invoke(app, ["--version"])

        assert result.exit_code == EXIT_OK
        assert "mcp-doctor" in result.output
