"""Rendering an `EvalResult` for humans.

The whole report is arranged around one line. Not the headline percentage -- a percentage
tells an author that something is wrong without telling them what -- but the sentence
underneath it:

    `search_users` captures 62% of the prompts meant for `search_orgs`.

That is a specific, falsifiable claim about two named tools, and it points straight at the
description that needs rewriting. Everything above it is context for it: the headline says
how bad things are, the per-tool table says which tool is worst, and the sentence says who
is taking its traffic. So the table is sorted worst-first, and the sentences come last,
where the eye finishes.

Splitting the headline into positives and siblings is the other deliberate choice. A server
that finds its tools when there is no competition and loses them when there is has a very
particular defect -- overlapping descriptions -- and it is not the same defect as a server
that cannot be found at all. One number would hide that; two make it obvious at a glance.

JSON note: `selected` is absent from a confusion cell when the model called nothing, since
`canonical_json` drops nulls. Absent and null read the same in every consumer that matters,
and dropping them keeps the payload terse.
"""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import Console
from rich.text import Text

from mcp_doctor.eval.arguments import describe
from mcp_doctor.eval.score import describe_confusion, notable_confusions
from mcp_doctor.model import (
    CaseOutcome,
    ConfusionCell,
    EvalResult,
    EvalScores,
    Rate,
    ToolScore,
    canonical_json,
)
from mcp_doctor.report.style import print_wrapped

# Scores at or above these read as fine and as merely worrying. Opinionated on purpose: a
# tool that refuses to say what "good" is leaves every reader to invent their own bar.
GOOD = 0.90
FAIR = 0.70

_GUTTER = 2
_LABEL_WIDTH = 20
_PERCENT_WIDTH = 4  # "100%"
_MAX_NAME_WIDTH = 30
_MIN_NAME_WIDTH = 8

# Below this, the "went instead to" column is dropped rather than squeezed. A two-word
# fragment of a tool name helps nobody, and the sentences underneath say the same thing in
# full -- so a narrow terminal loses the column, not the finding.
_MIN_TAIL_WIDTH = 24

# Where the traffic went, when it went nowhere. Parenthesised so it cannot be mistaken for
# a tool that happens to be called "nothing".
_NOTHING = "(nothing)"


def render_eval_json(result: EvalResult) -> str:
    """Deterministic JSON -- diffable between runs and golden-testable."""
    return canonical_json(result)


def _tone(fraction: float) -> str:
    if fraction >= GOOD:
        return "green"
    if fraction >= FAIR:
        return "yellow"
    return "red"


def _percent(rate: Rate | ToolScore, *, tone: bool = True) -> Text:
    return Text(
        f"{rate.percent}%".rjust(_PERCENT_WIDTH),
        style=_tone(rate.fraction) if tone else "",
    )


def _fraction(correct: int, total: int, width: int) -> Text:
    return Text(f"{correct}/{total}".rjust(width), style="dim")


def _headline_row(label: str, rate: Rate, width: int, *, indent: int = 0) -> Text:
    row = Text(" " * indent)
    row.append(label.ljust(_LABEL_WIDTH - indent))
    row.append(" " * _GUTTER)
    row.append_text(_percent(rate))
    row.append(" " * _GUTTER)
    row.append_text(_fraction(rate.correct, rate.total, width))
    row.rstrip()
    return row


def _headline(console: Console, scores: EvalScores) -> None:
    rates = (
        scores.selection,
        scores.positives,
        scores.siblings,
        scores.abstention,
        scores.arguments,
    )
    width = max(len(f"{rate.correct}/{rate.total}") for rate in rates)

    console.print(_headline_row("Selection accuracy", scores.selection, width))
    # The split only says something when both halves exist. On a suite with no sibling
    # cases it would be the headline printed twice.
    if scores.positives.total and scores.siblings.total:
        console.print(_headline_row("positives", scores.positives, width, indent=2))
        console.print(_headline_row("siblings", scores.siblings, width, indent=2))
    if scores.abstention.total:
        console.print(_headline_row("Abstention", scores.abstention, width))
    if scores.arguments.total:
        console.print(_headline_row("Argument validity", scores.arguments, width))


def _thieves(cells: Sequence[ConfusionCell], tool: str) -> str:
    """Where one tool's missing traffic went, biggest share first."""
    taken = [
        cell
        for cell in cells
        if cell.expected == tool and not cell.is_diagonal and cell.count
    ]
    taken.sort(key=lambda cell: (-cell.share, cell.selected or ""))
    return ", ".join(f"{cell.selected or _NOTHING} {cell.percent}%" for cell in taken)


def _traffic(console: Console, scores: EvalScores, width: int) -> None:
    """The per-tool table: hit rate, and who took the rest.

    This is the confusion matrix, printed the way it is actually read. A square grid of
    counts is the correct data structure and the wrong report -- nobody scans a 10x10 grid
    for the off-diagonal cells. One row per victim, worst first, with the thieves named
    inline, says the same thing in the order somebody would ask it.

    Every column is sized against the real terminal width rather than assumed to fit. A row
    that overflows gets wrapped by Rich, which both breaks the alignment the table exists
    for and leaves a trailing space on every wrapped line.
    """
    if not scores.per_tool:
        return

    counts = max(len(f"{item.correct}/{item.total}") for item in scores.per_tool)
    # Everything between the name and the thieves: two gutters, the percentage, the count.
    fixed = _GUTTER + _PERCENT_WIDTH + _GUTTER + counts
    longest = max(len(item.tool) for item in scores.per_tool)
    name_width = max(_MIN_NAME_WIDTH, min(longest, _MAX_NAME_WIDTH, width - fixed))

    tail_width = width - (name_width + fixed + _GUTTER)
    show_tail = tail_width >= _MIN_TAIL_WIDTH

    console.print()
    header = Text("tool".ljust(name_width), style="dim")
    header.append(" " * _GUTTER)
    header.append("hit".rjust(_PERCENT_WIDTH), style="dim")
    if show_tail:
        header.append(" " * (_GUTTER + counts + _GUTTER))
        header.append("went instead to", style="dim")
    header.rstrip()
    console.print(header)

    for item in scores.per_tool:
        row = Text(item.tool[:name_width].ljust(name_width), style="bold")
        row.append(" " * _GUTTER)
        row.append_text(_percent(item))
        row.append(" " * _GUTTER)
        row.append_text(_fraction(item.correct, item.total, counts))
        thieves = _thieves(scores.confusion, item.tool) if show_tail else ""
        if thieves:
            row.append(" " * _GUTTER)
            # Truncated rather than wrapped: a row that spills onto three lines stops the
            # table being scannable, and the sentences below name the ones that matter.
            row.append(
                thieves if len(thieves) <= tail_width else thieves[: tail_width - 3] + "...",
                style="cyan",
            )
        row.rstrip()
        console.print(row)


def _verdicts(console: Console, scores: EvalScores) -> bool:
    """The sentences the command exists to print. True if it printed any.

    Wrapped through `print_wrapped` rather than `console.print`, so that a narrow terminal
    gets the sentence over two lines instead of over two lines with a trailing space on the
    first -- which is invisible on screen and noise in a CI log and a diff.
    """
    cells = notable_confusions(scores)
    if not cells:
        return False
    console.print()
    for cell in cells:
        text = Text()
        parts = describe_confusion(cell).split("`")
        for index, part in enumerate(parts):
            text.append(part, style="bold cyan" if index % 2 else "")
        print_wrapped(console, text, first=None, width=console.width, indent=0)
    return True


def _failures(console: Console, outcomes: Sequence[CaseOutcome]) -> None:
    """Every case that went wrong, with the prompt that caused it. What `-v` adds.

    The prompt is printed because a failure nobody can reproduce is a failure nobody fixes,
    and the whole prompt is three lines away in a YAML file the reader would otherwise have
    to go and find.
    """
    failed = [outcome for outcome in outcomes if not outcome.correct]
    if not failed:
        return

    console.print()
    console.print(Text("failures", style="bold"))
    for outcome in failed:
        case = outcome.case
        row = Text()
        row.append(case.id, style="dim")
        row.append("  wanted ")
        row.append(case.expected or _NOTHING, style="cyan")
        row.append(", got ")
        row.append(outcome.selected or _NOTHING, style="red")
        print_wrapped(console, row, first=Text("  "), width=console.width - 2, indent=2)
        print_wrapped(
            console,
            Text(f'"{case.prompt}"', style="dim"),
            first=Text("    "),
            width=console.width - 4,
            indent=4,
        )


def _argument_problems(console: Console, outcomes: Sequence[CaseOutcome]) -> None:
    """Schema complaints, deduplicated across cases.

    Deduplicated because a parameter that is hard to fill in is hard to fill in every time,
    and forty identical lines say nothing that one line does not.
    """
    seen: dict[str, None] = {}
    for outcome in outcomes:
        check = outcome.arguments_check
        if check is not None and not check.ok and outcome.selected is not None:
            for line in describe(check, outcome.selected):
                seen.setdefault(line, None)
    if not seen:
        return
    console.print()
    console.print(Text("argument problems", style="bold"))
    for line in seen:
        print_wrapped(
            console, Text(line, style="dim"), first=Text("  "), width=console.width - 2, indent=2
        )


def _provenance(result: EvalResult) -> Text:
    """The line that makes a score mean something: what ran it, and what it cost."""
    cases = f"{result.case_count} case" if result.case_count == 1 else f"{result.case_count} cases"
    line = Text(result.model, style="cyan")
    line.append(f"   {cases}", style="dim")
    if result.cached_count:
        line.append(f"   {result.cached_count} from cache", style="dim")
    if result.called_count:
        line.append(f", {result.called_count} called", style="dim")
    if result.cost_usd:
        line.append(f"   ${result.cost_usd:.4f}", style="dim")
    elif not result.called_count:
        line.append("   free", style="dim")
    return line


def render_eval_table(result: EvalResult, console: Console, *, verbose: bool = False) -> None:
    """Print the scores, the per-tool traffic, and the confusions worth acting on."""
    server = result.server
    heading = Text(server.name or "(unnamed server)", style="bold")
    if server.version:
        heading.append(f" {server.version}", style="dim")
    console.print(heading)
    console.print(Text(result.target, style="dim"))
    # Wrapped, not soft-wrapped: this line can be long, and a report that runs off the side
    # of a narrow terminal is worse than one that takes two lines. The model name has no
    # spaces in it, so word wrapping keeps it whole.
    print_wrapped(console, _provenance(result), first=None, width=console.width, indent=0)
    console.print()

    if not result.outcomes:
        console.print(Text("No cases ran.", style="bold red"))
        return

    scores = result.scores
    _headline(console, scores)
    _traffic(console, scores, console.width)
    printed = _verdicts(console, scores)

    if verbose:
        _failures(console, result.outcomes)
        _argument_problems(console, result.outcomes)
    elif not printed and scores.selection.correct == scores.selection.total:
        console.print()
        print_wrapped(
            console,
            Text("Every prompt reached the tool it was meant for.", style="green"),
            first=None,
            width=console.width,
            indent=0,
        )

    failures = result.failures()
    if not verbose and failures:
        console.print()
        console.print(Text(f"{len(failures)} failing cases, -v to see them", style="dim"))
