"""The health score: one 0-100 number from a lint run and an optional eval run.

Pure, like `eval/score.py` -- data in, data out, no network, no filesystem, no clock -- and
tested the same way, because a badge that is confidently wrong is worse than no badge.

The formula, stated once so the README can quote it:

    lint_score  = clamp(100 - 10*errors - 3*warnings, 0, 100)   # info is advisory
    eval_score  = round(selection_accuracy * 100)               # positives + siblings only
    overall     = round(0.5*lint_score + 0.5*eval_score)   with an eval suite
                = lint_score                                lint-only

Three choices, each with another reasonable answer:

**The eval half is selection accuracy alone.** Abstention and argument validity are reported
beside the score and never folded in -- the same rule `eval` already follows. Averaging
abstention in would let a server raise its badge by adding abstain cases to its own suite,
which changes the test rather than the server.

**Info findings do not move the score.** Only errors and warnings -- the findings the report
shows by default and expects you to act on -- count against `lint_score`. A server should not
be graded down for advisory polish it was told is optional.

**Lint-only is `lint_score`, not `lint_score` averaged with a zero.** Most servers have no
eval suite, and scoring them as if their model never picked the right tool would be a lie
about a measurement that was never taken. `eval_score` stays `None` and the weight collapses
onto the half that exists.

The weights and penalties were fixed by their effect on the two reference servers, the way
the MCP013 similarity threshold was: goodserver lands at 96 (100 lint / 92 eval) and
badserver at 28 (0 lint / 55 eval). badserver's lint floors at zero because it genuinely is
riddled; the composite still carries eval, so the number is 28, not 0.
"""

from __future__ import annotations

from mcp_toolgauge.model import EvalScores, HealthScore, LintResult, Severity

# Deduction per finding. Errors are the findings that actively cost calls or are a safety
# problem; a warning measurably degrades selection but is not on its own disqualifying. Info
# is advisory and costs nothing here. A server riddled with errors floors at zero rather than
# going negative -- there is no "worse than nothing", and the composite still carries eval.
ERROR_PENALTY = 10
WARNING_PENALTY = 3

# The lint/eval split. Equal weight: the offline proxy and the measured signal are each worth
# acting on, and neither is trusted enough to dominate the other. Only consulted when both
# halves exist; a lint-only run is its lint score outright.
LINT_WEIGHT = 0.5
EVAL_WEIGHT = 0.5

# Score -> shields.io colour. Anchored on the GOOD=90 / FAIR=70 opinion the eval report
# already prints, then widened so a mediocre-but-honest server reads as "okay" rather than
# alarming red -- the badge has to be worth adopting at a middling score, not only a perfect
# one. Highest floor first.
_BANDS: tuple[tuple[int, str], ...] = (
    (90, "brightgreen"),
    (75, "green"),
    (60, "yellowgreen"),
    (45, "yellow"),
    (30, "orange"),
)
_WORST_COLOUR = "red"


def _clamp(value: int) -> int:
    return max(0, min(100, value))


def lint_subscore(errors: int, warnings: int) -> int:
    """100 minus the weighted finding penalty, floored at 0. Info does not count."""
    return _clamp(100 - ERROR_PENALTY * errors - WARNING_PENALTY * warnings)


def color_for(overall: int) -> str:
    """The shields.io colour name for a score."""
    for floor, colour in _BANDS:
        if overall >= floor:
            return colour
    return _WORST_COLOUR


def health_score(lint: LintResult, eval_scores: EvalScores | None) -> HealthScore:
    """Combine a lint result and an optional eval into the 0-100 headline.

    `eval_scores` is treated as absent when it has no selection cases: a suite of nothing but
    abstain cases measures no selection, and a score over zero selection cases would be a
    fraction with a zero denominator dressed up as a fact.
    """
    counts = lint.counts()
    errors = counts[Severity.ERROR]
    warnings = counts[Severity.WARNING]
    lint_score = lint_subscore(errors, warnings)

    if eval_scores is None or eval_scores.selection.total == 0:
        return HealthScore(
            overall=lint_score,
            lint_score=lint_score,
            eval_score=None,
            errors=errors,
            warnings=warnings,
        )

    eval_score = eval_scores.selection.percent
    overall = round(LINT_WEIGHT * lint_score + EVAL_WEIGHT * eval_score)
    return HealthScore(
        overall=overall,
        lint_score=lint_score,
        eval_score=eval_score,
        errors=errors,
        warnings=warnings,
    )
