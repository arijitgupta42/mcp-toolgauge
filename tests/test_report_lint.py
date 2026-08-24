"""The lint renderer, driven directly so colour and layout can actually be observed.

Going through the CLI is not enough: `CliRunner` output is never a terminal, so Rich
disables colour regardless and a NO_COLOR assertion there passes whether or not NO_COLOR
is honoured. These tests build their own `Console` and force a terminal where it matters.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest
from rich.console import Console

from mcp_toolgauge.model import Finding, LintResult, ServerInfo, Severity
from mcp_toolgauge.report import render_lint_json, render_lint_table

GOLDEN = Path(__file__).parent / "golden" / "lint_report.txt"

ANSI = re.compile(r"\x1b\[[0-9;]*m")

# Colour specifically -- foreground/background SGR codes, not attributes like bold (1) or
# dim (2). NO_COLOR governs colour; Rich keeps text attributes, which the spec allows.
COLOUR = re.compile(r"\x1b\[[0-9;]*?(?:3[0-7]|4[0-7]|9[0-7]|10[0-7]|38;|48;)[0-9;]*m")


def render(
    report: LintResult,
    *,
    width: int = 100,
    verbose: bool = False,
    force_terminal: bool = False,
) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, width=width, force_terminal=force_terminal)
    render_lint_table(report, console, verbose=verbose)
    return buffer.getvalue()


def clean(server_name: str = "acme") -> LintResult:
    return LintResult(target="python server.py", server=ServerInfo(name=server_name), tool_count=8)


class TestGolden:
    def test_matches_the_golden_file(self, sample_report: LintResult) -> None:
        assert render(sample_report) == GOLDEN.read_text(encoding="utf-8")


class TestColour:
    def test_a_terminal_gets_colour(self, sample_report: LintResult) -> None:
        assert COLOUR.search(render(sample_report, force_terminal=True))

    def test_no_color_removes_colour_on_a_terminal(
        self, sample_report: LintResult, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NO_COLOR", "1")

        assert not COLOUR.search(render(sample_report, force_terminal=True))

    def test_a_pipe_gets_no_escapes_at_all(self, sample_report: LintResult) -> None:
        assert not ANSI.search(render(sample_report))


class TestLayout:
    @pytest.mark.parametrize("width", [40, 60, 80, 120, 200])
    def test_no_line_exceeds_the_terminal_width(
        self, sample_report: LintResult, width: int
    ) -> None:
        for line in render(sample_report, width=width).splitlines():
            assert len(line) <= width, repr(line)

    @pytest.mark.parametrize("width", [40, 60, 80, 120, 200])
    def test_output_is_ascii_at_any_width(self, sample_report: LintResult, width: int) -> None:
        """Windows consoles and CI logs mangle decorative glyphs, so we emit none."""
        assert render(sample_report, width=width).isascii()

    def test_no_line_carries_trailing_whitespace(self, sample_report: LintResult) -> None:
        for line in render(sample_report).splitlines():
            assert line == line.rstrip(), repr(line)

    def test_the_rule_id_is_never_truncated_away(self, sample_report: LintResult) -> None:
        assert "MCP013" in render(sample_report, width=40)

    def test_findings_are_grouped_under_their_tool(self, sample_report: LintResult) -> None:
        lines = render(sample_report).splitlines()

        assert "search_users" in lines
        assert "doStuff" in lines

    def test_server_level_findings_get_their_own_heading(self, sample_report: LintResult) -> None:
        assert "(server)" in render(sample_report).splitlines()


class TestContent:
    def test_backticks_are_stripped_from_messages(self, sample_report: LintResult) -> None:
        """They are formatting for a pipe; a terminal gets colour instead."""
        assert "`" not in render(sample_report)

    def test_info_findings_are_hidden_by_default(self, sample_report: LintResult) -> None:
        assert "shows an example value" not in render(sample_report)

    def test_verbose_reveals_info_findings(self, sample_report: LintResult) -> None:
        assert "shows an example value" in render(sample_report, verbose=True)

    def test_the_tally_still_counts_findings_it_did_not_print(
        self, sample_report: LintResult
    ) -> None:
        """Hiding the detail is a display choice; pretending the findings do not exist
        would be a lie, and the footer says how many were held back."""
        assert "MCP025 (3)" in render(sample_report)

    def test_the_footer_says_how_many_were_hidden(self, sample_report: LintResult) -> None:
        assert "hidden, -v to show" in render(sample_report)

    def test_the_footer_does_not_promise_hidden_findings_when_verbose(
        self, sample_report: LintResult
    ) -> None:
        assert "hidden" not in render(sample_report, verbose=True)

    def test_an_error_carries_its_suggestion_without_asking(
        self, sample_report: LintResult
    ) -> None:
        """The few findings you must act on should not need a second command."""
        assert "Rewrite one of them" in render(sample_report)

    def test_a_warning_keeps_its_suggestion_for_verbose(self, sample_report: LintResult) -> None:
        fix = "Rename doStuff to snake_case"

        assert fix not in render(sample_report)
        assert fix in render(sample_report, verbose=True)

    def test_severity_counts_read_as_english(self, sample_report: LintResult) -> None:
        """"16 infos" is not a word, and this is the one line everybody reads."""
        output = render(sample_report)

        assert "infos" not in output
        assert re.search(r"\d+ info\b", output)

    def test_the_most_common_rules_are_summarised(self, sample_report: LintResult) -> None:
        assert "Most common:" in render(sample_report)


class TestCleanRun:
    def test_a_clean_run_says_so(self) -> None:
        assert "No findings." in render(clean())

    def test_a_clean_run_does_not_also_say_zero_findings(self) -> None:
        assert "0 findings" not in render(clean())

    def test_a_clean_run_reports_what_was_checked(self) -> None:
        assert "8 tools checked." in render(clean())

    def test_an_unnamed_server_still_renders(self) -> None:
        report = LintResult(target="t", server=ServerInfo(), tool_count=0)

        assert "(unnamed server)" in render(report)


class TestJson:
    def test_the_payload_parses_and_has_sorted_keys(self, sample_report: LintResult) -> None:
        payload = json.loads(render_lint_json(sample_report))

        assert list(payload) == sorted(payload)
        assert payload["tool_count"] == 3

    def test_every_finding_carries_its_suggestion(self, sample_report: LintResult) -> None:
        payload = json.loads(render_lint_json(sample_report))

        assert all(finding["suggestion"] for finding in payload["findings"])

    def test_severities_serialise_as_their_names(self, sample_report: LintResult) -> None:
        payload = json.loads(render_lint_json(sample_report))

        assert {finding["severity"] for finding in payload["findings"]} <= {
            "error",
            "warning",
            "info",
        }

    def test_output_is_stable_between_runs(self, sample_report: LintResult) -> None:
        assert render_lint_json(sample_report) == render_lint_json(sample_report)


class TestFindingModel:
    def test_a_parameter_finding_reads_as_a_path(self) -> None:
        finding = Finding(
            rule="MCP020",
            severity=Severity.WARNING,
            message="m",
            suggestion="s",
            tool="search_users",
            parameter="query",
        )

        assert finding.location == "search_users.query"

    def test_a_server_finding_has_no_tool(self) -> None:
        finding = Finding(rule="MCP004", severity=Severity.WARNING, message="m", suggestion="s")

        assert finding.location == "(server)"
