"""Turning outcomes into numbers. Pure -- no network, no filesystem, no clock.

Every function here takes data and returns data, so the metrics can be tested against
hand-built outcomes with known-correct answers. That matters more than usual: a harness
with a bug in its arithmetic is worse than no harness, because it is confidently wrong and
nobody re-derives a percentage by hand.

Three choices are worth stating, because each had another reasonable answer.

**The headline covers selection only.** `selection` is computed over positive and sibling
cases; abstention is reported beside it and never folded in. Averaging them would mean a
server could raise its headline by adding abstain cases, which is a change to the test
rather than to the server. The same reasoning keeps argument validity separate: "the model
cannot tell your two search tools apart" and "your schema is hard to fill in" are different
defects with different fixes, and one number covering both points at neither.

**Argument validity counts every call the model made**, checked against the schema of the
tool it actually called -- not only the calls where it picked correctly. The question being
answered is "when something calls your tools, does it fill them in right?", and that is a
property of your schemas that holds whether or not the selection was the one you wanted.

**Confusion shares are normalised across the row.** A cell is a fraction of the cases
*meant for* `expected`, which is what makes the sentence "search_users captures 62% of the
prompts meant for search_orgs" true as written. Normalising down the column instead would
produce a number about the thief rather than about the victim, and the victim is who the
author has to go and fix.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable

from mcp_toolgauge.model import (
    CaseKind,
    CaseOutcome,
    ConfusionCell,
    EvalScores,
    ToolScore,
)

# Below this share, a confusion cell is one stray answer rather than a pattern. Reporting
# "tool X captures 8% of Y" invites someone to rewrite a description over a single case.
NOTABLE_SHARE = 0.20

# How many "steals this many" sentences the headline prints before it stops being a
# headline. The full matrix is always in --json.
TOP_CONFUSIONS = 5


def _sort_key(cell: ConfusionCell) -> tuple[str, int, bool, str]:
    """Deterministic matrix order: by victim, then by size, then by name.

    `selected` can be None, which does not compare against a string, so the "called
    nothing" cell sorts last within its row by an explicit flag rather than by luck.
    """
    return (cell.expected, -cell.count, cell.selected is None, cell.selected or "")


def confusion_matrix(outcomes: Iterable[CaseOutcome]) -> tuple[ConfusionCell, ...]:
    """Where the traffic meant for each tool actually went.

    Built over selection cases only: an abstain case has no intended tool, so it has no row
    to belong to. The diagonal is included, because a matrix missing its diagonal is not a
    matrix and a JSON consumer should get the real thing. The terminal renderer is the
    thing that narrows it down to the mistakes.
    """
    rows: defaultdict[str, Counter[str | None]] = defaultdict(Counter)
    for outcome in outcomes:
        case = outcome.case
        if case.is_selection and case.expected is not None:
            rows[case.expected][outcome.selected] += 1

    cells = [
        ConfusionCell(
            expected=expected,
            selected=selected,
            count=count,
            share=count / total,
        )
        for expected, tally in rows.items()
        # `total` is the row sum, so a row's shares add to 1.0 whatever else is on the
        # server. A cell is a statement about this tool's traffic and nothing else.
        for total in (sum(tally.values()),)
        for selected, count in tally.items()
    ]
    return tuple(sorted(cells, key=_sort_key))


def per_tool_scores(outcomes: Iterable[CaseOutcome]) -> tuple[ToolScore, ...]:
    """One score per tool that some case expected, worst first.

    Worst first because the report exists to be acted on, and the tool at 25% is the one
    worth reading about. Ties break alphabetically so the order is stable between runs.
    """
    totals: Counter[str] = Counter()
    correct: Counter[str] = Counter()
    for outcome in outcomes:
        expected = outcome.case.expected
        if outcome.case.is_selection and expected is not None:
            totals[expected] += 1
            if outcome.correct:
                correct[expected] += 1

    scores = [
        ToolScore(tool=tool, correct=correct[tool], total=total) for tool, total in totals.items()
    ]
    return tuple(sorted(scores, key=lambda item: (item.fraction, item.tool)))


def score(outcomes: Iterable[CaseOutcome]) -> EvalScores:
    """Every number a run produces, from the outcomes alone."""
    materialised = tuple(outcomes)

    tally: Counter[str] = Counter()
    for outcome in materialised:
        kind = outcome.case.kind
        if outcome.case.is_selection:
            tally["selection_total"] += 1
            tally[f"{kind.value}_total"] += 1
            if outcome.correct:
                tally["selection_correct"] += 1
                tally[f"{kind.value}_correct"] += 1
        elif kind is CaseKind.ABSTAIN:
            tally["abstention_total"] += 1
            if outcome.correct:
                tally["abstention_correct"] += 1

        # Every call, not only the correct ones -- see the module docstring.
        if outcome.arguments_check is not None:
            tally["argument_total"] += 1
            if outcome.arguments_check.ok:
                tally["argument_correct"] += 1

    return EvalScores(
        selection_correct=tally["selection_correct"],
        selection_total=tally["selection_total"],
        positive_correct=tally["positive_correct"],
        positive_total=tally["positive_total"],
        sibling_correct=tally["sibling_correct"],
        sibling_total=tally["sibling_total"],
        abstention_correct=tally["abstention_correct"],
        abstention_total=tally["abstention_total"],
        argument_correct=tally["argument_correct"],
        argument_total=tally["argument_total"],
        per_tool=per_tool_scores(materialised),
        confusion=confusion_matrix(materialised),
    )


def notable_confusions(
    scores: EvalScores,
    *,
    minimum_share: float = NOTABLE_SHARE,
    limit: int = TOP_CONFUSIONS,
) -> tuple[ConfusionCell, ...]:
    """The off-diagonal cells worth printing a sentence about, biggest first.

    Cells where the model called nothing are excluded: "your tool was not found" is already
    the headline number, and this list is about tools taking each other's traffic, which is
    the failure an author cannot see from the outside.
    """
    candidates = [
        cell
        for cell in scores.confusion
        if not cell.is_diagonal and cell.selected is not None and cell.share >= minimum_share
    ]
    candidates.sort(key=lambda cell: (-cell.share, -cell.count, cell.expected, cell.selected or ""))
    return tuple(candidates[:limit])


def describe_confusion(cell: ConfusionCell) -> str:
    """One confusion cell as the sentence the whole command exists to print."""
    return (
        f"`{cell.selected}` captures {cell.percent}% of the prompts meant for "
        f"`{cell.expected}`."
    )
