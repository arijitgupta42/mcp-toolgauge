"""What a lint rule reports, and what a lint run produces.

The split between `Problem` and `Finding` is the important part of this module. A rule
returns a `Problem` -- what is wrong and what to do about it -- and the engine turns that
into a `Finding` by stamping on the rule's ID and whatever severity the configuration says
that rule has. A rule therefore cannot report the wrong ID, and cannot quietly ignore a
severity override someone put in their `mcpcheckup.toml`.

`suggestion` has no default anywhere in this file. "Never report a problem without
proposing a fix" is the house rule for lint rules, and making it a required argument means
it is checked by the type system rather than by whoever reviews the rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from mcpcheckup.model.tool import ServerInfo


class Severity(StrEnum):
    """How much a finding matters, and the vocabulary config files speak.

    `OFF` is not a severity a finding can carry -- it only ever appears in configuration,
    where it means "do not run this rule". Keeping it in the same enum means a config file
    has one vocabulary rather than a severity list plus a separate disable list.
    """

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    OFF = "off"


# Most-severe first. Used for sorting, for `--fail-on` comparisons, and for deciding what
# the default (non-verbose) report shows.
SEVERITY_ORDER: tuple[Severity, ...] = (Severity.ERROR, Severity.WARNING, Severity.INFO)


def severity_rank(severity: Severity) -> int:
    """0 for the most severe. `OFF` sorts past everything real."""
    try:
        return SEVERITY_ORDER.index(severity)
    except ValueError:
        return len(SEVERITY_ORDER)


def at_least(severity: Severity, floor: Severity) -> bool:
    """True when `severity` is as severe as `floor`, or worse.

    `floor` of `OFF` means nothing qualifies, which is what `--fail-on off` should do.
    """
    if floor is Severity.OFF:
        return False
    return severity_rank(severity) <= severity_rank(floor)


@dataclass(frozen=True)
class Problem:
    """One thing a rule found wrong. Not yet attributed to a rule -- the engine does that.

    A plain dataclass rather than a Pydantic model: these are created in tight loops inside
    rules, never crosses a process boundary, and never gets validated from untrusted input.
    """

    message: str
    suggestion: str
    tool: str | None = None
    parameter: str | None = None
    # Other tools the finding is about -- the sibling in an overlap, the rest of a
    # near-duplicate name group. Reported so the message can name them without the reader
    # having to go and look.
    related: tuple[str, ...] = field(default_factory=tuple)


class Finding(BaseModel):
    """A `Problem` attributed to a rule and given a severity."""

    model_config = ConfigDict(frozen=True)

    rule: str
    severity: Severity
    message: str
    suggestion: str
    tool: str | None = None
    parameter: str | None = None
    related: tuple[str, ...] = ()

    @property
    def location(self) -> str:
        """Where the finding is, as a human reads it: `tool.parameter`, or the server."""
        if self.tool is None:
            return "(server)"
        if self.parameter is None:
            return self.tool
        return f"{self.tool}.{self.parameter}"


class LintResult(BaseModel):
    """Everything one `mcpcheckup lint` run produced.

    Carries the server identity and target alongside the findings so a saved report is
    self-describing -- you can tell what was linted without the shell history that did it,
    which is the same reasoning behind `InspectResult.target`.
    """

    model_config = ConfigDict(frozen=True)

    target: str
    server: ServerInfo
    tool_count: int
    findings: tuple[Finding, ...] = ()

    def counts(self) -> dict[Severity, int]:
        """How many findings at each severity. Always has all three keys, so a report can
        render "0 errors" without special-casing the empty run."""
        tally = dict.fromkeys(SEVERITY_ORDER, 0)
        for finding in self.findings:
            if finding.severity in tally:
                tally[finding.severity] += 1
        return tally

    def worst(self) -> Severity | None:
        """The most severe finding present, or None for a clean run."""
        present = [f.severity for f in self.findings if f.severity is not Severity.OFF]
        if not present:
            return None
        return min(present, key=severity_rank)

    def at_or_above(self, floor: Severity) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if at_least(f.severity, floor))
