"""The `lint` CLI contract: what people and CI actually depend on.

Exit codes matter more than output here. The headline promise of this milestone is that
badserver fails and goodserver passes, so those two assertions are the ones that decide
whether the feature works.

These tests pass `--no-config` wherever the result depends on rule severity, so that a
`mcp-toolgauge.toml` in some ancestor of the checkout cannot quietly change what they prove.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mcp_toolgauge.cli import EXIT_CONNECTION, EXIT_OK, EXIT_THRESHOLD, EXIT_USAGE, app
from mcp_toolgauge.lint import all_rules

runner = CliRunner()


def lint(*args: str) -> object:
    return runner.invoke(app, ["lint", *args], env={"COLUMNS": "100"})


@pytest.mark.integration
class TestTheHeadlinePromise:
    def test_a_careless_server_fails(self, badserver_dir: Path) -> None:
        result = lint(str(badserver_dir), "--no-config")

        assert result.exit_code == EXIT_THRESHOLD

    def test_a_careful_server_passes_with_no_findings_at_all(self, goodserver_dir: Path) -> None:
        result = lint(str(goodserver_dir), "--no-config", "-v")

        assert result.exit_code == EXIT_OK
        assert "No findings." in result.output


@pytest.mark.integration
class TestExitCodes:
    def test_fail_on_off_reports_without_failing(self, badserver_dir: Path) -> None:
        result = lint(str(badserver_dir), "--no-config", "--fail-on", "off")

        assert result.exit_code == EXIT_OK
        assert "MCP013" in result.output

    def test_fail_on_warning_is_stricter(self, badserver_dir: Path) -> None:
        assert lint(str(badserver_dir), "--no-config", "--fail-on", "warning").exit_code == (
            EXIT_THRESHOLD
        )

    def test_fail_on_info_does_not_fail_a_clean_server(self, goodserver_dir: Path) -> None:
        assert lint(str(goodserver_dir), "--no-config", "--fail-on", "info").exit_code == EXIT_OK

    def test_an_unresolvable_target_is_a_usage_error(self, tmp_path: Path) -> None:
        assert lint(str(tmp_path / "nope")).exit_code == EXIT_USAGE

    def test_a_server_that_will_not_start_is_a_connection_failure(self, tmp_path: Path) -> None:
        (tmp_path / "server.py").write_text('raise SystemExit("boom")\n', encoding="utf-8")

        result = lint(str(tmp_path), "--timeout", "20")

        assert result.exit_code == EXIT_CONNECTION

    def test_two_output_formats_at_once_is_a_usage_error(self, goodserver_dir: Path) -> None:
        result = lint(str(goodserver_dir), "--json", "--sarif")

        assert result.exit_code == EXIT_USAGE
        assert "cannot be combined" in result.output


@pytest.mark.integration
class TestOutput:
    def test_the_headline_finding_is_visible_without_flags(self, badserver_dir: Path) -> None:
        """`search_users` versus `search_orgs` is the whole demo. It must not need -v."""
        output = lint(str(badserver_dir), "--no-config").output

        assert "MCP013" in output
        assert "78%" in output

    def test_info_findings_need_verbose(self, badserver_dir: Path) -> None:
        quiet = lint(str(badserver_dir), "--no-config").output
        loud = lint(str(badserver_dir), "--no-config", "-v").output

        detail = "changes state but declares no"
        assert detail not in quiet
        assert detail in loud

    def test_output_stays_ascii(self, badserver_dir: Path) -> None:
        result = runner.invoke(
            app, ["lint", str(badserver_dir), "--no-config"], env={"COLUMNS": "60"}
        )

        assert result.output.isascii()

    def test_piped_output_carries_no_ansi(self, badserver_dir: Path) -> None:
        assert "\x1b[" not in lint(str(badserver_dir), "--no-config").output


@pytest.mark.integration
class TestJsonOutput:
    def test_the_payload_parses(self, badserver_dir: Path) -> None:
        payload = json.loads(lint(str(badserver_dir), "--no-config", "--json").output)

        assert payload["tool_count"] == 10
        assert payload["findings"]

    def test_json_still_sets_the_exit_code(self, badserver_dir: Path) -> None:
        """A machine-readable report that always exits 0 is useless as a gate."""
        assert lint(str(badserver_dir), "--no-config", "--json").exit_code == EXIT_THRESHOLD

    def test_output_is_stable_between_runs(self, goodserver_dir: Path) -> None:
        first = lint(str(goodserver_dir), "--no-config", "--json").output
        second = lint(str(goodserver_dir), "--no-config", "--json").output

        assert first == second

    def test_a_clean_server_reports_an_empty_finding_list(self, goodserver_dir: Path) -> None:
        payload = json.loads(lint(str(goodserver_dir), "--no-config", "--json").output)

        assert payload["findings"] == []


@pytest.mark.integration
class TestSarifOutput:
    def test_the_payload_parses_as_sarif(self, badserver_dir: Path) -> None:
        payload = json.loads(lint(str(badserver_dir), "--no-config", "--sarif").output)

        assert payload["version"] == "2.1.0"
        assert len(payload["runs"][0]["tool"]["driver"]["rules"]) == len(all_rules())

    def test_sarif_still_sets_the_exit_code(self, badserver_dir: Path) -> None:
        assert lint(str(badserver_dir), "--no-config", "--sarif").exit_code == EXIT_THRESHOLD


@pytest.mark.integration
class TestConfiguration:
    def test_a_config_can_silence_a_rule(self, badserver_dir: Path, tmp_path: Path) -> None:
        config = tmp_path / "mcp-toolgauge.toml"
        config.write_text("[lint.rules]\nMCP013 = 'off'\n", encoding="utf-8")

        output = lint(str(badserver_dir), "--config", str(config)).output

        assert "MCP013" not in output

    def test_a_config_can_make_a_server_pass(self, badserver_dir: Path, tmp_path: Path) -> None:
        config = tmp_path / "mcp-toolgauge.toml"
        config.write_text("[lint]\nfail_on = 'off'\n", encoding="utf-8")

        assert lint(str(badserver_dir), "--config", str(config)).exit_code == EXIT_OK

    def test_the_command_line_beats_the_config_file(
        self, badserver_dir: Path, tmp_path: Path
    ) -> None:
        config = tmp_path / "mcp-toolgauge.toml"
        config.write_text("[lint]\nfail_on = 'off'\n", encoding="utf-8")

        result = lint(str(badserver_dir), "--config", str(config), "--fail-on", "error")

        assert result.exit_code == EXIT_THRESHOLD

    def test_an_unknown_rule_in_config_is_a_usage_error(
        self, goodserver_dir: Path, tmp_path: Path
    ) -> None:
        config = tmp_path / "mcp-toolgauge.toml"
        config.write_text("[lint.rules]\nMCP999 = 'off'\n", encoding="utf-8")

        result = lint(str(goodserver_dir), "--config", str(config))

        assert result.exit_code == EXIT_USAGE
        assert "MCP999" in result.output

    def test_a_config_error_is_reported_before_the_server_is_started(
        self, tmp_path: Path
    ) -> None:
        """No point spawning a subprocess we already know we cannot use the result of."""
        config = tmp_path / "mcp-toolgauge.toml"
        config.write_text("[lint.rules]\nMCP999 = 'off'\n", encoding="utf-8")

        result = lint(str(tmp_path / "does-not-exist"), "--config", str(config))

        assert result.exit_code == EXIT_USAGE
        assert "MCP999" in result.output

    def test_verbose_names_the_config_in_use(self, goodserver_dir: Path, tmp_path: Path) -> None:
        config = tmp_path / "mcp-toolgauge.toml"
        config.write_text("[lint.rules]\nMCP013 = 'off'\n", encoding="utf-8")

        result = lint(str(goodserver_dir), "--config", str(config), "-v")

        assert "mcp-toolgauge.toml" in result.output
