"""The health score. Pure arithmetic, so every number here is worked out by hand.

The formula is the product's one composite, and the whole design is that it cannot be gamed
and cannot hide what it is made of. So these tests pin each of those properties against a
number derived by hand: the equal weighting, the info findings that do not count, the
lint-only collapse that is not the same as a zero eval, the flooring, and the colour bands.
"""

from __future__ import annotations

import pytest

from mcp_doctor.health import EVAL_WEIGHT, LINT_WEIGHT, color_for, health_score, lint_subscore
from mcp_doctor.model import EvalScores, Finding, LintResult, ServerInfo, Severity

_RULE = {Severity.ERROR: "MCP013", Severity.WARNING: "MCP020", Severity.INFO: "MCP025"}


def lint_of(errors: int = 0, warnings: int = 0, infos: int = 0) -> LintResult:
    def some(severity: Severity, count: int) -> list[Finding]:
        return [
            Finding(rule=_RULE[severity], severity=severity, message="m.", suggestion="s" * 50)
            for _ in range(count)
        ]

    findings = (
        *some(Severity.ERROR, errors),
        *some(Severity.WARNING, warnings),
        *some(Severity.INFO, infos),
    )
    return LintResult(target="t", server=ServerInfo(name="x"), tool_count=1, findings=findings)


def eval_of(correct: int, total: int, **extra: int) -> EvalScores:
    return EvalScores(selection_correct=correct, selection_total=total, **extra)


class TestLintSubscore:
    def test_a_clean_run_is_100(self) -> None:
        assert lint_subscore(0, 0) == 100

    def test_errors_and_warnings_deduct_at_their_weights(self) -> None:
        assert lint_subscore(1, 2) == 100 - 10 - 6  # 84

    def test_it_floors_at_zero_rather_than_going_negative(self) -> None:
        assert lint_subscore(20, 0) == 0


class TestComposite:
    def test_the_two_reference_servers_land_where_the_readme_says(self) -> None:
        good = health_score(lint_of(), eval_of(92, 100))
        bad = health_score(lint_of(5, 53, 16), eval_of(55, 100))

        assert (good.overall, good.lint_score, good.eval_score) == (96, 100, 92)
        assert (bad.overall, bad.lint_score, bad.eval_score) == (28, 0, 55)

    def test_the_weighting_is_equal(self) -> None:
        # lint 70 (ten warnings), eval 50 -> 60.
        health = health_score(lint_of(0, 10), eval_of(50, 100))

        assert LINT_WEIGHT == EVAL_WEIGHT == 0.5
        assert health.overall == round(0.5 * 70 + 0.5 * 50) == 60

    def test_info_findings_do_not_move_the_score(self) -> None:
        """Only errors and warnings count; info is advisory, as the report already treats it."""
        with_info = health_score(lint_of(0, 0, 25), eval_of(80, 100))
        without = health_score(lint_of(0, 0, 0), eval_of(80, 100))

        assert with_info.lint_score == 100
        assert with_info.overall == without.overall

    def test_the_counts_are_carried_for_self_description(self) -> None:
        health = health_score(lint_of(2, 5, 9), eval_of(80, 100))

        assert (health.errors, health.warnings) == (2, 5)


class TestLintOnly:
    def test_no_eval_is_the_lint_score_outright(self) -> None:
        health = health_score(lint_of(0, 3), None)

        assert health.eval_score is None
        assert health.overall == health.lint_score == 91
        assert health.is_lint_only

    def test_a_suite_of_only_abstain_cases_is_lint_only(self) -> None:
        """No selection cases means selection was never measured -- not measured at zero."""
        health = health_score(lint_of(), eval_of(0, 0, abstention_correct=1, abstention_total=3))

        assert health.eval_score is None
        assert health.overall == 100

    def test_all_wrong_is_folded_in_and_is_not_the_same_as_lint_only(self) -> None:
        """A suite that has selection cases and gets them all wrong scores zero on that half."""
        health = health_score(lint_of(), eval_of(0, 10))

        assert health.eval_score == 0
        assert health.overall == 50  # (100 + 0) / 2


class TestColourBands:
    @pytest.mark.parametrize(
        ("score", "colour"),
        [
            (100, "brightgreen"),
            (90, "brightgreen"),
            (89, "green"),
            (75, "green"),
            (74, "yellowgreen"),
            (60, "yellowgreen"),
            (59, "yellow"),
            (45, "yellow"),
            (44, "orange"),
            (30, "orange"),
            (29, "red"),
            (0, "red"),
        ],
    )
    def test_the_band_boundaries(self, score: int, colour: str) -> None:
        assert color_for(score) == colour
