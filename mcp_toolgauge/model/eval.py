"""What an eval run is made of: the cases, what the model did, and what that scored.

The shape of this module encodes the one decision the whole eval rests on. A case is not
"a prompt and an answer" -- it is a prompt, an answer, and a *kind*, because the three
kinds measure different things and are never averaged together. A `positive` case asks
whether a tool can be found at all. A `sibling` case asks whether it can be told apart from
its neighbour, which is where servers actually differ. An `abstain` case asks whether the
server knows when to stay out of the way.

Rolling those into one percentage would let a server improve its headline by adding easy
cases, so the scores keep them apart and the renderer prints them apart.

`Rate` exists for the same reason `LintResult.counts()` always has all three keys: a report
should be able to say "0 of 0" without the renderer special-casing an empty run.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mcp_toolgauge.model.tool import ServerInfo


class CaseKind(StrEnum):
    """What a case is testing. Ordered easiest to hardest, which is also report order."""

    POSITIVE = "positive"
    SIBLING = "sibling"
    ABSTAIN = "abstain"


# Kinds where some tool is the right answer. The headline number is computed over exactly
# these, and abstention is reported separately.
SELECTION_KINDS: tuple[CaseKind, ...] = (CaseKind.POSITIVE, CaseKind.SIBLING)


class EvalCase(BaseModel):
    """One utterance, and the tool it should route to.

    Generated once by `--init`, then owned by a human and read from disk thereafter. That
    is why `note` exists: the file is meant to be edited, and an edit whose reasoning is
    not written down is an edit the next person will undo.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    kind: CaseKind
    prompt: str
    # None exactly when the right behaviour is to call nothing.
    expected: str | None = None
    # For a sibling case, the tool this one is designed to be confusable with. Reported so
    # a failure can say which trap the model fell into rather than just that it missed.
    rival: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _expectation_matches_kind(self) -> EvalCase:
        if self.kind is CaseKind.ABSTAIN:
            if self.expected is not None:
                raise ValueError(
                    f"case {self.id!r} is an abstain case but expects {self.expected!r}; "
                    "an abstain case is one where calling any tool is wrong."
                )
        elif self.expected is None:
            raise ValueError(
                f"case {self.id!r} is a {self.kind} case with no expected tool; "
                "set 'expected', or change 'kind' to abstain."
            )
        return self

    @property
    def is_selection(self) -> bool:
        return self.kind in SELECTION_KINDS


class CaseSuite(BaseModel):
    """A whole case file: the cases, plus what they were written against.

    `tool_digest` is the important field. Scores are only comparable between runs over the
    same tool surface, so the suite records the surface it was generated from and a run can
    tell you when the two have drifted apart.
    """

    model_config = ConfigDict(frozen=True)

    target: str
    tool_digest: str
    generated_with: str | None = None
    cases: tuple[EvalCase, ...] = ()

    @property
    def counts(self) -> dict[CaseKind, int]:
        tally = dict.fromkeys(CaseKind, 0)
        for case in self.cases:
            tally[case.kind] += 1
        return tally


class ArgumentCheck(BaseModel):
    """What was wrong with the arguments the model passed, if anything.

    Four named failures rather than one boolean, because "invalid" is not a fix and
    "`priority` is not one of low, normal, high, urgent" is. Each list holds parameter
    names, so the renderer can name them without re-deriving anything.
    """

    model_config = ConfigDict(frozen=True)

    missing_required: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    wrong_type: tuple[str, ...] = ()
    bad_enum: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not (self.missing_required or self.unknown or self.wrong_type or self.bad_enum)


class CaseOutcome(BaseModel):
    """What happened when one case was put to the model.

    `correct` is derived rather than stored: it is a fact about the case and the selection,
    and storing it would let a serialised run disagree with itself.
    """

    model_config = ConfigDict(frozen=True)

    case: EvalCase
    # None means the model called no tool at all -- right for an abstain case, a miss
    # for any other kind.
    selected: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    # None when no tool was called, so "we did not check" stays distinct from "we checked
    # and it was fine".
    arguments_check: ArgumentCheck | None = None
    cached: bool = False

    @property
    def correct(self) -> bool:
        return self.selected == self.case.expected

    @property
    def arguments_ok(self) -> bool | None:
        """True/False when a tool was called, None when one was not."""
        return None if self.arguments_check is None else self.arguments_check.ok


class Rate:
    """A hit count over an attempt count, and the fraction between them.

    Deliberately not a Pydantic model: it is arithmetic, it is created in loops, and it
    serialises through `EvalScores` as two integers and a float rather than as itself.
    """

    __slots__ = ("correct", "total")

    def __init__(self, correct: int = 0, total: int = 0) -> None:
        self.correct = correct
        self.total = total

    @property
    def fraction(self) -> float:
        """0.0 for an empty rate. Nothing measured is not the same as nothing right, but a
        report has to print something, and 0/0 is the honest rendering of it."""
        return self.correct / self.total if self.total else 0.0

    @property
    def percent(self) -> int:
        return round(self.fraction * 100)


class ToolScore(BaseModel):
    """How one tool fared over the cases that expected it."""

    model_config = ConfigDict(frozen=True)

    tool: str
    correct: int
    total: int

    @property
    def fraction(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def percent(self) -> int:
        return round(self.fraction * 100)


class ConfusionCell(BaseModel):
    """One entry of the confusion matrix: cases meant for `expected` that went to `selected`.

    `selected` of None is the row for "the model called nothing", which is a different and
    much more benign failure than calling the wrong thing -- worth keeping visible rather
    than folding into an "incorrect" bucket.

    `share` is normalised across the row, so it reads as "N% of the prompts meant for
    `expected`". That sentence is the output the whole command exists to produce.
    """

    model_config = ConfigDict(frozen=True)

    expected: str
    # Defaults to None so the cell round-trips through `canonical_json`, which drops null
    # keys: a "called nothing" cell serialises without `selected`, and must read back as the
    # same None rather than failing validation on a missing field. Every producer passes it
    # explicitly, so the default only ever matters on the way back in.
    selected: str | None = None
    count: int
    share: float

    @property
    def is_diagonal(self) -> bool:
        return self.expected == self.selected

    @property
    def percent(self) -> int:
        return round(self.share * 100)


class EvalScores(BaseModel):
    """Everything `score.py` computes. Pure data, no behaviour beyond arithmetic.

    Five headline numbers, kept apart on purpose:

    * `selection` -- the headline. Positives and siblings together, abstains excluded, so
      the number cannot be moved by changing how many abstain cases the suite has.
    * `positives` / `siblings` -- the same number split by difficulty. A server whose
      positives are perfect and whose siblings are a coin flip has a very specific problem,
      and it is not the same problem as one that fails both.
    * `abstention` -- reported, never averaged in.
    * `arguments` -- of the tools that were called, how many were called correctly.
    """

    model_config = ConfigDict(frozen=True)

    selection_correct: int = 0
    selection_total: int = 0
    positive_correct: int = 0
    positive_total: int = 0
    sibling_correct: int = 0
    sibling_total: int = 0
    abstention_correct: int = 0
    abstention_total: int = 0
    argument_correct: int = 0
    argument_total: int = 0
    per_tool: tuple[ToolScore, ...] = ()
    # The full matrix, diagonal included, so a JSON consumer gets real data. The terminal
    # renderer filters it down to the mistakes.
    confusion: tuple[ConfusionCell, ...] = ()

    @property
    def selection(self) -> Rate:
        return Rate(self.selection_correct, self.selection_total)

    @property
    def positives(self) -> Rate:
        return Rate(self.positive_correct, self.positive_total)

    @property
    def siblings(self) -> Rate:
        return Rate(self.sibling_correct, self.sibling_total)

    @property
    def abstention(self) -> Rate:
        return Rate(self.abstention_correct, self.abstention_total)

    @property
    def arguments(self) -> Rate:
        return Rate(self.argument_correct, self.argument_total)


class EvalResult(BaseModel):
    """Everything one `mcp-toolgauge eval` run produced.

    Self-describing for the same reason `LintResult` is: target, server identity, and the
    model are all recorded, so a saved report says what it measured and what measured it
    without the shell history that produced it. For eval the model matters most of all --
    a score without a model name is not a score.
    """

    model_config = ConfigDict(frozen=True)

    target: str
    server: ServerInfo
    model: str
    tool_digest: str
    scores: EvalScores
    outcomes: tuple[CaseOutcome, ...] = ()
    # Money and network, recorded so a report can prove the second run was free.
    cached_count: int = 0
    called_count: int = 0
    cost_usd: float = 0.0

    @property
    def case_count(self) -> int:
        return len(self.outcomes)

    def failures(self) -> tuple[CaseOutcome, ...]:
        """Every case the model got wrong, in suite order. What `-v` prints."""
        return tuple(outcome for outcome in self.outcomes if not outcome.correct)
