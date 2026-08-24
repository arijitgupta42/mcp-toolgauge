"""The CI renderers: the terminal scorecard, and the pull-request markdown.

The scorecard is checked the way the other terminal renderers are -- driven with a real
`Console` so colour and width are actually observed, since `CliRunner` output is never a
terminal. The markdown is checked against a golden, because it is a product surface people
read on every pull request and a stray formatting change there is a regression worth failing
on. The delta column -- the reason the comment exists -- gets its own golden with a baseline.

The CiReport builders are module-level so `scripts`-style regeneration of the goldens uses
exactly the same construction the tests assert against.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from rich.console import Console

from mcp_toolgauge.health import health_score
from mcp_toolgauge.model import CiReport, EvalResult, HealthScore, LintResult
from mcp_toolgauge.report import render_ci_markdown, render_ci_table

GOLDEN = Path(__file__).parent / "golden" / "ci_comment.md"
GOLDEN_DELTA = Path(__file__).parent / "golden" / "ci_comment_delta.md"

ANSI = re.compile(r"\x1b\[[0-9;]*m")
COLOUR = re.compile(r"\x1b\[[0-9;]*?(?:3[0-7]|4[0-7]|9[0-7]|10[0-7]|38;|48;)[0-9;]*m")

# A fixed baseline, so the vs-base deltas in the golden are numbers worked out by hand rather
# than whatever a second fixture happened to score.
BASELINE_HEALTH = HealthScore(overall=70, lint_score=64, eval_score=76, errors=3, warnings=12)


def make_ci(lint: LintResult, evaluation: EvalResult | None) -> CiReport:
    scores = evaluation.scores if evaluation is not None else None
    return CiReport(
        target=lint.target,
        server=lint.server,
        health=health_score(lint, scores),
        lint=lint,
        eval=evaluation,
    )


def make_baseline(lint: LintResult, evaluation: EvalResult | None) -> CiReport:
    return CiReport(
        target=lint.target, server=lint.server, health=BASELINE_HEALTH, lint=lint, eval=evaluation
    )


def render_table(
    report: CiReport, *, width: int = 100, verbose: bool = False, tty: bool = False
) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, width=width, force_terminal=tty)
    render_ci_table(report, console, verbose=verbose)
    return buffer.getvalue()


@pytest.fixture
def full(sample_report: LintResult, sample_eval: EvalResult) -> CiReport:
    return make_ci(sample_report, sample_eval)


@pytest.fixture
def lint_only(sample_report: LintResult) -> CiReport:
    return make_ci(sample_report, None)


class TestScorecard:
    def test_the_health_number_and_both_halves_are_shown(self, full: CiReport) -> None:
        output = render_table(full)

        assert f"{full.health.overall} / 100" in output
        assert "lint" in output
        assert "selection" in output

    def test_the_money_line_is_printed(self, full: CiReport) -> None:
        collapsed = " ".join(render_table(full).split())

        assert "search_users captures 83% of the prompts meant for search_orgs" in collapsed

    def test_a_lint_only_run_says_there_was_no_eval_suite(self, lint_only: CiReport) -> None:
        output = render_table(lint_only)

        assert "no eval suite" in output
        assert "%" not in output.split("selection", 1)[1].splitlines()[0]

    def test_backticks_are_stripped(self, full: CiReport) -> None:
        assert "`" not in render_table(full)

    @pytest.mark.parametrize("width", [40, 60, 80, 120])
    def test_no_line_exceeds_the_width(self, full: CiReport, width: int) -> None:
        for line in render_table(full, width=width).splitlines():
            assert len(line) <= width, repr(line)

    def test_output_is_ascii(self, full: CiReport) -> None:
        """The scorecard goes into CI logs and Windows consoles; emoji live in the markdown."""
        assert render_table(full).isascii()

    def test_no_trailing_whitespace(self, full: CiReport) -> None:
        for line in render_table(full, verbose=True).splitlines():
            assert line == line.rstrip(), repr(line)

    def test_verbose_lists_the_findings(self, full: CiReport) -> None:
        assert "findings" in render_table(full, verbose=True)


class TestScorecardColour:
    def test_a_terminal_gets_colour(self, full: CiReport) -> None:
        assert COLOUR.search(render_table(full, tty=True))

    def test_a_pipe_gets_no_escapes(self, full: CiReport) -> None:
        assert not ANSI.search(render_table(full))


class TestMarkdownGolden:
    def test_matches_the_golden(self, full: CiReport) -> None:
        assert render_ci_markdown(full) == GOLDEN.read_text(encoding="utf-8")

    def test_delta_matches_its_golden(self, full: CiReport) -> None:
        baseline = make_baseline(full.lint, full.eval)

        assert render_ci_markdown(full, baseline=baseline) == GOLDEN_DELTA.read_text(
            encoding="utf-8"
        )


class TestMarkdownContent:
    def test_the_header_carries_the_score_and_an_emoji(self, full: CiReport) -> None:
        first = render_ci_markdown(full).splitlines()[0]

        assert f"health: {full.health.overall} / 100" in first
        assert not first.isascii()  # the status emoji

    def test_without_a_baseline_there_is_no_vs_base_column(self, full: CiReport) -> None:
        assert "vs base" not in render_ci_markdown(full)

    def test_a_baseline_adds_the_vs_base_column(self, full: CiReport) -> None:
        assert "vs base" in render_ci_markdown(full, baseline=make_baseline(full.lint, full.eval))

    def test_deltas_render_in_both_directions(self, full: CiReport) -> None:
        """A worse baseline makes the score an improvement (▲); a better one a regression (▼)."""

        def against(overall: int) -> str:
            health = HealthScore(overall=overall, lint_score=overall, eval_score=overall)
            base = CiReport(target="t", server=full.server, health=health, lint=full.lint)
            return render_ci_markdown(full, baseline=base)

        assert "▲" in against(10)  # current score is above 10
        assert "▼" in against(99)  # and below 99

    def test_the_money_line_is_a_bullet_with_code_spans(self, full: CiReport) -> None:
        assert (
            "- `search_users` captures 83% of the prompts meant for `search_orgs`."
            in render_ci_markdown(full)
        )

    def test_a_lint_only_comment_explains_the_missing_eval(self, lint_only: CiReport) -> None:
        output = render_ci_markdown(lint_only)

        assert "No eval suite was found" in output
        assert "| Selection | -- |" in output

    def test_a_lint_only_baseline_reads_as_newly_measured(
        self, full: CiReport, lint_only: CiReport
    ) -> None:
        """A PR that adds an eval suite should say selection is newly measured, not +92."""
        output = render_ci_markdown(full, baseline=lint_only)

        assert "newly measured" in output

    def test_it_is_deterministic(self, full: CiReport) -> None:
        """No timestamps: re-posting over an unchanged run must not churn the thread."""
        assert render_ci_markdown(full) == render_ci_markdown(full)

    def test_it_credits_the_tool(self, full: CiReport) -> None:
        assert "Measured by [mcp-toolgauge]" in render_ci_markdown(full)
