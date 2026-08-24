"""Rendering a `CiReport`: the terminal scorecard, the PR comment, and the JSON.

Three surfaces, one number. The scorecard is what you read at the command line; the markdown
is what lands on a pull request, where the delta against the base branch is the thing worth
seeing -- a score is a fact, but "this PR moved it from 88 to 81" is a decision. The JSON is
the committed artifact the next run diffs against, so `render_ci_json` is just
`canonical_json`: deterministic, and the exact shape `--baseline` reads back in.

The health number never appears without its two halves beside it. A composite that hides what
it is made of is a composite nobody trusts, so lint and selection are always on the next two
lines -- and when there was no eval suite, the selection line says so rather than showing a
zero that would read as a failure.
"""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

from mcp_toolgauge.eval.score import describe_confusion, notable_confusions
from mcp_toolgauge.model import (
    CiReport,
    EvalResult,
    HealthScore,
    Severity,
    at_least,
    canonical_json,
)
from mcp_toolgauge.report.style import print_wrapped, styled

_LABEL_WIDTH = 12
_VALUE_WIDTH = 4  # "100%"

# The verbose findings list. Its prefix is "  <rule>  <severity>  ", a fixed width the body
# is wrapped inside of -- wrapping to the full terminal and then prepending the prefix would
# overflow the line and leave rich to re-wrap it, trailing space and all.
_RULE_WIDTH = 6  # "MCP013"
_SEVERITY_WIDTH = 7  # "warning"
_FINDING_PREFIX = 2 + _RULE_WIDTH + 2 + _SEVERITY_WIDTH + 2

# How many confusion sentences the scorecard and the comment print. The rest are in --json.
_TOP_CONFUSIONS = 3

_REPO_URL = "https://github.com/arijitgupta42/mcp-toolgauge"


def render_ci_json(report: CiReport) -> str:
    """Deterministic JSON -- the artifact `--baseline` reads and diffs against."""
    return canonical_json(report)


def _tone(overall: int) -> str:
    """Terminal colour for a score. Three bands, collapsed from the six the badge uses."""
    if overall >= 75:
        return "green"
    if overall >= 45:
        return "yellow"
    return "red"


def _findings_detail(health: HealthScore) -> str:
    errors = f"{health.errors} error" + ("" if health.errors == 1 else "s")
    warnings = f"{health.warnings} warning" + ("" if health.warnings == 1 else "s")
    return f"{errors}, {warnings}"


def _money_lines(evaluation: EvalResult) -> list[str]:
    """The confusion sentences the whole project exists to print, biggest first."""
    cells = notable_confusions(evaluation.scores, limit=_TOP_CONFUSIONS)
    return [describe_confusion(cell) for cell in cells]


def _backticked(sentence: str) -> Text:
    text = Text()
    for index, part in enumerate(sentence.split("`")):
        text.append(part, style="bold cyan" if index % 2 else "")
    return text


def _print_confusions(console: Console, sentences: list[str]) -> None:
    if not sentences:
        return
    console.print()
    for sentence in sentences:
        print_wrapped(console, _backticked(sentence), first=None, width=console.width, indent=0)


def _print_findings(console: Console, report: CiReport) -> None:
    """Under -v, the errors and warnings that drove the lint half, compactly."""
    shown = [f for f in report.lint.findings if at_least(f.severity, Severity.WARNING)]
    if not shown:
        return
    console.print()
    console.print(Text("findings", style="bold"))
    width = max(20, console.width - _FINDING_PREFIX)
    for finding in shown:
        style = "bold red" if finding.severity is Severity.ERROR else "yellow"
        prefix = Text("  ")
        prefix.append(finding.rule.ljust(_RULE_WIDTH), style="dim")
        prefix.append("  ")
        prefix.append(str(finding.severity).ljust(_SEVERITY_WIDTH), style=style)
        prefix.append("  ")
        print_wrapped(
            console, styled(finding.message), first=prefix, width=width, indent=_FINDING_PREFIX
        )


def render_ci_table(report: CiReport, console: Console, *, verbose: bool = False) -> None:
    """Print the scorecard: the health number, then the two halves it came from."""
    server = report.server
    heading = Text(server.name or "(unnamed server)", style="bold")
    if server.version:
        heading.append(f" {server.version}", style="dim")
    console.print(heading)
    console.print(Text(report.target, style="dim"))
    console.print()

    health = report.health

    overall = Text("Health".ljust(_LABEL_WIDTH))
    overall.append(str(health.overall).rjust(_VALUE_WIDTH), style=f"bold {_tone(health.overall)}")
    overall.append(" / 100", style="dim")
    console.print(overall)

    lint_line = Text("  lint".ljust(_LABEL_WIDTH))
    lint_line.append(str(health.lint_score).rjust(_VALUE_WIDTH), style=_tone(health.lint_score))
    lint_line.append(f"   {_findings_detail(health)}", style="dim")
    console.print(lint_line)

    selection = Text("  selection".ljust(_LABEL_WIDTH))
    if report.eval is not None and health.eval_score is not None:
        rate = report.eval.scores.selection
        value = f"{health.eval_score}%".rjust(_VALUE_WIDTH)
        selection.append(value, style=_tone(health.eval_score))
        selection.append(f"   {rate.correct} of {rate.total} prompts", style="dim")
    else:
        selection.append("--".rjust(_VALUE_WIDTH), style="dim")
        selection.append("   no eval suite (lint only)", style="dim")
    console.print(selection)

    if report.eval is not None:
        _print_confusions(console, _money_lines(report.eval))

    if verbose:
        _print_findings(console, report)


# --------------------------------------------------------------------------------------
# Markdown, for the pull-request comment and the job summary
# --------------------------------------------------------------------------------------

_EMOJI = {"green": "\U0001f7e2", "yellow": "\U0001f7e1", "red": "\U0001f534"}


def _signed(change: int) -> str:
    if change > 0:
        return f"▲ +{change}"
    if change < 0:
        return f"▼ {change}"
    return "—"  # em dash: measured, and unchanged


def _delta(current: int, previous: int | None) -> str:
    """A signed change against the base branch, or empty when there is no baseline."""
    return "" if previous is None else _signed(current - previous)


def _eval_delta(current: HealthScore, previous: HealthScore | None) -> str:
    if previous is None:
        return ""
    if current.eval_score is None and previous.eval_score is None:
        return "—"
    if current.eval_score is None:
        return "lint-only now"
    if previous.eval_score is None:
        return "newly measured"
    return _signed(current.eval_score - previous.eval_score)


def _findings_delta(current: HealthScore, previous: HealthScore | None) -> str:
    if previous is None:
        return ""
    return _signed((current.errors + current.warnings) - (previous.errors + previous.warnings))


def render_ci_markdown(report: CiReport, *, baseline: CiReport | None = None) -> str:
    """The pull-request comment: the score, its two halves, and the delta against the base.

    When `baseline` is given, every row carries how it moved -- which is the reason the
    comment exists, because a number on its own does not tell a reviewer whether this change
    helped. Deterministic and free of timestamps, so it is golden-testable and so re-posting
    it over an unchanged run does not churn the thread.
    """
    health = report.health
    base = baseline.health if baseline is not None else None
    show_delta = base is not None

    def row(label: str, value: str, delta: str) -> str:
        return f"| {label} | {value} |" + (f" {delta} |" if show_delta else "")

    server = report.server.name or "(unnamed server)"
    eval_value = "--" if health.eval_score is None else f"{health.eval_score}%"
    findings_value = f"{health.errors} errors, {health.warnings} warnings"
    overall_delta = _delta(health.overall, base.overall if base else None)
    lint_delta = _delta(health.lint_score, base.lint_score if base else None)

    lines: list[str] = [
        f"## {_EMOJI[_tone(health.overall)]} mcp-toolgauge health: {health.overall} / 100",
        "",
        f"`{server}` — {report.target}",
        "",
        "| | score |" + (" vs base |" if show_delta else ""),
        "|---|---|" + ("---|" if show_delta else ""),
        row("**Health**", f"**{health.overall}**", overall_delta),
        row("Lint", str(health.lint_score), lint_delta),
        row("Selection", eval_value, _eval_delta(health, base)),
        row("Findings", findings_value, _findings_delta(health, base)),
    ]

    if report.eval is not None:
        sentences = _money_lines(report.eval)
        if sentences:
            lines.append("")  # one blank line before the list; the bullets stay tight
            lines.extend(f"- {sentence}" for sentence in sentences)

    if health.is_lint_only:
        lines.append("")
        lines.append(
            "_No eval suite was found, so this score reflects lint alone._ "
            "Add one with `mcp-toolgauge eval . --init`."
        )

    lines.append("")
    lines.append(f"<sub>Measured by [mcp-toolgauge]({_REPO_URL}).</sub>")
    return "\n".join(lines)
