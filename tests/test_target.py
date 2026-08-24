"""Target resolution: the part users hit first, and so the part that must not surprise them."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from mcp_toolgauge.connect.target import (
    HttpTarget,
    StdioTarget,
    TargetResolutionError,
    resolve_target,
)


class TestExplicitCommand:
    def test_command_wins_over_everything(self, badserver_dir: Path) -> None:
        target = resolve_target(str(badserver_dir), command="my-server --flag x")

        assert isinstance(target, StdioTarget)
        assert target.command == "my-server"
        assert target.args == ("--flag", "x")

    def test_command_runs_in_the_target_directory(self, badserver_dir: Path) -> None:
        target = resolve_target(str(badserver_dir), command="my-server")

        assert isinstance(target, StdioTarget)
        assert target.cwd == badserver_dir

    def test_quoted_arguments_survive_splitting(self) -> None:
        target = resolve_target("", command='server --name "two words"')

        assert isinstance(target, StdioTarget)
        assert target.args == ("--name", "two words")

    def test_empty_command_is_rejected(self) -> None:
        with pytest.raises(TargetResolutionError, match="empty"):
            resolve_target("", command="   ")


class TestUrls:
    @pytest.mark.parametrize("url", ["http://localhost:8000/mcp", "https://example.test/mcp"])
    def test_urls_become_http_targets(self, url: str) -> None:
        target = resolve_target(url)

        assert isinstance(target, HttpTarget)
        assert target.url == url

    def test_a_non_url_string_is_not_mistaken_for_one(self) -> None:
        with pytest.raises(TargetResolutionError, match="nothing to inspect"):
            resolve_target("ftp://example.test/mcp")


class TestManifests:
    def test_single_server_needs_no_flags(self, write_manifest) -> None:
        directory = write_manifest(
            {"mcpServers": {"only": {"command": "python", "args": ["server.py"]}}}
        )

        target = resolve_target(str(directory))

        assert isinstance(target, StdioTarget)
        assert target.command == "python"
        assert target.args == ("server.py",)

    def test_relative_args_resolve_against_the_manifest(self, write_manifest) -> None:
        directory = write_manifest({"mcpServers": {"only": {"command": "python"}}})

        target = resolve_target(str(directory))

        assert isinstance(target, StdioTarget)
        assert target.cwd == directory

    def test_explicit_cwd_in_the_manifest_is_honoured(self, write_manifest) -> None:
        directory = write_manifest(
            {"mcpServers": {"only": {"command": "python", "cwd": "/somewhere/else"}}}
        )

        target = resolve_target(str(directory))

        assert isinstance(target, StdioTarget)
        assert target.cwd == Path("/somewhere/else")

    def test_vscode_servers_key_is_accepted(self, write_manifest) -> None:
        directory = write_manifest({"servers": {"only": {"command": "node", "args": ["s.js"]}}})

        target = resolve_target(str(directory))

        assert isinstance(target, StdioTarget)
        assert target.command == "node"

    def test_http_entries_become_http_targets(self, write_manifest) -> None:
        directory = write_manifest(
            {"mcpServers": {"remote": {"type": "http", "url": "https://example.test/mcp"}}}
        )

        target = resolve_target(str(directory))

        assert isinstance(target, HttpTarget)
        assert target.url == "https://example.test/mcp"

    def test_a_bare_url_entry_is_treated_as_http(self, write_manifest) -> None:
        directory = write_manifest({"mcpServers": {"remote": {"url": "https://example.test/mcp"}}})

        assert isinstance(resolve_target(str(directory)), HttpTarget)

    def test_headers_are_carried_through(self, write_manifest) -> None:
        directory = write_manifest(
            {
                "mcpServers": {
                    "remote": {"url": "https://example.test/mcp", "headers": {"X-Key": "abc"}}
                }
            }
        )

        target = resolve_target(str(directory))

        assert isinstance(target, HttpTarget)
        assert target.headers == {"X-Key": "abc"}

    def test_env_is_carried_through(self, write_manifest) -> None:
        directory = write_manifest(
            {"mcpServers": {"only": {"command": "python", "env": {"TOKEN": "xyz"}}}}
        )

        target = resolve_target(str(directory))

        assert isinstance(target, StdioTarget)
        assert target.env == {"TOKEN": "xyz"}

    def test_several_servers_require_a_choice(self, write_manifest) -> None:
        directory = write_manifest(
            {"mcpServers": {"alpha": {"command": "a"}, "beta": {"command": "b"}}}
        )

        # The error has to name the options, or the user cannot act on it.
        with pytest.raises(TargetResolutionError, match="alpha, beta"):
            resolve_target(str(directory))

    def test_choosing_one_of_several_works(self, write_manifest) -> None:
        directory = write_manifest(
            {"mcpServers": {"alpha": {"command": "a"}, "beta": {"command": "b"}}}
        )

        target = resolve_target(str(directory), server="beta")

        assert isinstance(target, StdioTarget)
        assert target.command == "b"

    def test_an_unknown_server_name_lists_the_real_ones(self, write_manifest) -> None:
        directory = write_manifest(
            {"mcpServers": {"alpha": {"command": "a"}, "beta": {"command": "b"}}}
        )

        with pytest.raises(TargetResolutionError, match="alpha, beta"):
            resolve_target(str(directory), server="gamma")

    def test_malformed_json_reports_the_file(self, tmp_path: Path) -> None:
        (tmp_path / ".mcp.json").write_text("{not json", encoding="utf-8")

        with pytest.raises(TargetResolutionError, match="not valid JSON"):
            resolve_target(str(tmp_path))

    def test_a_manifest_without_a_server_table_is_an_error(self, write_manifest) -> None:
        directory = write_manifest({"somethingElse": {}})

        with pytest.raises(TargetResolutionError, match="mcpServers"):
            resolve_target(str(directory))

    def test_an_entry_with_neither_command_nor_url_is_an_error(self, write_manifest) -> None:
        directory = write_manifest({"mcpServers": {"broken": {"args": ["x"]}}})

        with pytest.raises(TargetResolutionError, match="nothing"):
            resolve_target(str(directory))

    def test_a_manifest_can_be_passed_directly(self, write_manifest) -> None:
        directory = write_manifest({"mcpServers": {"only": {"command": "python"}}})

        target = resolve_target(str(directory / ".mcp.json"))

        assert isinstance(target, StdioTarget)
        assert target.command == "python"

    def test_the_first_manifest_name_wins(self, tmp_path: Path) -> None:
        (tmp_path / ".mcp.json").write_text(
            '{"mcpServers": {"a": {"command": "first"}}}', encoding="utf-8"
        )
        (tmp_path / "mcp.json").write_text(
            '{"mcpServers": {"a": {"command": "second"}}}', encoding="utf-8"
        )

        target = resolve_target(str(tmp_path))

        assert isinstance(target, StdioTarget)
        assert target.command == "first"


class TestConventions:
    @pytest.mark.parametrize("entrypoint", ["server.py", "main.py", "__main__.py", "app.py"])
    def test_a_conventional_entrypoint_is_found(self, tmp_path: Path, entrypoint: str) -> None:
        (tmp_path / entrypoint).write_text("", encoding="utf-8")

        target = resolve_target(str(tmp_path))

        assert isinstance(target, StdioTarget)
        # The current interpreter, not bare "python": the server shares our environment.
        assert target.command == sys.executable
        assert target.args == (entrypoint,)

    def test_a_manifest_beats_a_conventional_entrypoint(self, tmp_path: Path) -> None:
        (tmp_path / "server.py").write_text("", encoding="utf-8")
        (tmp_path / ".mcp.json").write_text(
            '{"mcpServers": {"a": {"command": "from-manifest"}}}', encoding="utf-8"
        )

        target = resolve_target(str(tmp_path))

        assert isinstance(target, StdioTarget)
        assert target.command == "from-manifest"

    def test_a_python_file_can_be_named_directly(self, tmp_path: Path) -> None:
        script = tmp_path / "custom_name.py"
        script.write_text("", encoding="utf-8")

        target = resolve_target(str(script))

        assert isinstance(target, StdioTarget)
        assert target.args == ("custom_name.py",)
        assert target.cwd == tmp_path


class TestFailures:
    def test_a_missing_path_is_a_usage_error(self, tmp_path: Path) -> None:
        with pytest.raises(TargetResolutionError, match="nothing to inspect"):
            resolve_target(str(tmp_path / "does-not-exist"))

    def test_an_empty_target_is_a_usage_error(self) -> None:
        with pytest.raises(TargetResolutionError, match="No target given"):
            resolve_target("")

    def test_an_unrecognised_directory_lists_what_was_tried(self, tmp_path: Path) -> None:
        with pytest.raises(TargetResolutionError) as caught:
            resolve_target(str(tmp_path))

        message = str(caught.value)
        assert ".mcp.json" in message
        assert "server.py" in message
        assert "--command" in message

    def test_an_unsupported_file_type_is_rejected(self, tmp_path: Path) -> None:
        script = tmp_path / "server.rb"
        script.write_text("", encoding="utf-8")

        with pytest.raises(TargetResolutionError, match="--command"):
            resolve_target(str(script))


class TestDescribe:
    def test_stdio_describe_is_copy_pasteable(self) -> None:
        target = StdioTarget(command="python", args=("server.py", "--flag"))

        assert target.describe() == "python server.py --flag"

    def test_http_describe_is_the_url(self) -> None:
        assert HttpTarget(url="https://example.test/mcp").describe() == "https://example.test/mcp"
