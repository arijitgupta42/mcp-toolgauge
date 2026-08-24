"""Rendering a `LintResult` for humans.

Two decisions shape this file. The first is that findings are grouped by tool rather than
by rule: an author fixes one tool at a time, so the report should read the way the work
happens. The second is that errors carry their suggestion inline while warnings do not --
there are few errors and they have to be acted on, and printing sixty suggestions would
bury the three that matter.

Layout comes from `report/style.py`, which both terminal renderers share. Output is ASCII
throughout, for the same reason `inspect`'s renderer is: this gets piped into CI logs and
Windows consoles, where a decorative glyph comes back as a replacement character.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator

from rich.console import Console
from rich.text import Text

from mcpcheckup.model import Finding, LintResult, Severity, at_least, canonical_json
from mcpcheckup.report.style import print_wrapped, styled

_SEVERITY_STYLE: dict[Severity, str] = {
    Severity.ERROR: "bold red",
    Severity.WARNING: "yellow",
    Severity.INFO: "dim",
}

# "info" is uncountable; the other two are not. Adding an "s" to everything produced
# "16 infos", which reads as a typo in the one line most people actually read.
_PLURAL: dict[Severity, str] = {
    Severity.ERROR: "errors",
    Severity.WARNING: "warnings",
    Severity.INFO: "info",
}

_INDENT = 2
_RULE_WIDTH = 6  # "MCP013"
_SEVERITY_WIDTH = max(len(str(severity)) for severity in _SEVERITY_STYLE)
_GUTTER = 2
_PREFIX_WIDTH = _INDENT + _RULE_WIDTH + _GUTTER + _SEVERITY_WIDTH + _GUTTER

# Narrow enough for a split terminal, wide enough that wrapping every two words does not
# make the report unreadable.
_MIN_MESSAGE_WIDTH = 30

# How many rules the "most common" footer line names before it stops being a summary.
_TOP_RULES = 3


def render_lint_json(result: LintResult) -> str:
    """Deterministic JSON -- diffable between runs and golden-testable."""
    return canonical_json(result)


def _groups(findings: Iterable[Finding]) -> Iterator[tuple[str, list[Finding]]]:
    """Consecutive findings sharing a tool. Relies on the engine's ordering."""
    current: str | None = None
    batch: list[Finding] = []
    for finding in findings:
        heading = finding.tool or "(server)"
        if heading != current:
            if batch:
                yield current or "(server)", batch
            current, batch = heading, []
        batch.append(finding)
    if batch:
        yield current or "(server)", batch


def _message_width(console: Console) -> int:
    return max(_MIN_MESSAGE_WIDTH, console.width - _PREFIX_WIDTH)


def _print_finding(console: Console, finding: Finding, *, verbose: bool, width: int) -> None:
    prefix = Text(" " * _INDENT)
    prefix.append(finding.rule.ljust(_RULE_WIDTH), style="dim")
    prefix.append(" " * _GUTTER)
    prefix.append(
        str(finding.severity).ljust(_SEVERITY_WIDTH),
        style=_SEVERITY_STYLE.get(finding.severity, ""),
    )
    prefix.append(" " * _GUTTER)
    print_wrapped(
        console, styled(finding.message), first=prefix, width=width, indent=_PREFIX_WIDTH
    )

    # The fix travels with the finding when it is an error, or when asked for. Anything you
    # must act on should not need a second command to find out how.
    if verbose or finding.severity is Severity.ERROR:
        suggestion = styled(finding.suggestion)
        suggestion.stylize("dim")
        print_wrapped(console, suggestion, first=None, width=width, indent=_PREFIX_WIDTH)


def _footer(result: LintResult, *, shown: int, verbose: bool) -> Text:
    counts = result.counts()
    tools = f"{result.tool_count} tool" if result.tool_count == 1 else f"{result.tool_count} tools"
    total = len(result.findings)
    noun = "finding" if total == 1 else "findings"
    tally = ", ".join(
        f"{count} {severity if count == 1 else _PLURAL[severity]}"
        for severity, count in counts.items()
        if count
    )
    line = Text(f"{tools}, {total} {noun}", style="dim")
    if tally:
        line.append(f"   {tally}", style="dim")
    hidden = total - shown
    if hidden and not verbose:
        line.append(f"   {hidden} hidden, -v to show", style="dim")
    return line


def render_lint_table(result: LintResult, console: Console, *, verbose: bool = False) -> None:
    """Print the findings, grouped by tool, with a summary underneath."""
    server = result.server
    heading = Text(server.name or "(unnamed server)", style="bold")
    if server.version:
        heading.append(f" {server.version}", style="dim")
    console.print(heading)
    console.print(Text(result.target, style="dim"))
    console.print()

    if not result.findings:
        console.print(Text("No findings.", style="bold green"))
        console.print()
        checked = (
            f"{result.tool_count} tool checked."
            if result.tool_count == 1
            else f"{result.tool_count} tools checked."
        )
        console.print(Text(checked, style="dim"))
        return

    floor = Severity.INFO if verbose else Severity.WARNING
    visible = [finding for finding in result.findings if at_least(finding.severity, floor)]
    width = _message_width(console)

    for name, batch in _groups(visible):
        console.print(Text(name, style="bold"))
        for finding in batch:
            _print_finding(console, finding, verbose=verbose, width=width)
        console.print()

    console.print(_footer(result, shown=len(visible), verbose=verbose))

    common = Counter(finding.rule for finding in result.findings).most_common(_TOP_RULES)
    if len(common) > 1:
        listed = ", ".join(f"{rule_id} ({count})" for rule_id, count in common)
        console.print(Text(f"Most common: {listed}", style="dim"))
