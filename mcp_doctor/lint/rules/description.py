"""Description rules -- MCP010 to MCP015.

The description is where a tool earns its selection. A model reading a tool list is doing
retrieval against these strings, so the failure modes are retrieval failure modes: nothing
to match against, nothing that distinguishes one tool from its neighbour, or text the
author never came back and wrote.

MCP013 and MCP014 are the pair that matter. They split one intuition -- "these two tools
look the same" -- into two findings, because overlap is not in itself a defect. Two search
tools over the same directory *should* have similar descriptions. What makes one server
good and another bad is whether the descriptions say which to prefer.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from collections.abc import Iterable

from mcp_doctor.lint.engine import LintContext, LintTool, rule
from mcp_doctor.lint.text import (
    DISAMBIGUATION_PATTERN,
    PLACEHOLDER_PATTERN,
    all_words,
    has_terminal_punctuation,
    is_subset_of_name,
    jaccard,
    mentions,
)
from mcp_doctor.model import Problem, Severity

# A description shorter than this is a label, not an explanation. Six words is roughly the
# shortest string that can name a subject and say something about it: "Find people in the
# staff directory" is six.
MIN_DESCRIPTION_WORDS = 6

# Below this many meaningful words, similarity stops meaning anything -- two three-word
# stubs collide trivially. Those are already reported as too short, and reporting them
# twice would bury the pairs that matter.
MIN_WORDS_FOR_COMPARISON = 6

# Near-copy-paste. Measured against the fixtures: the two carelessly-written sibling search
# tools score 0.78, while two carefully-written ones covering the same domain score 0.57.
NEAR_DUPLICATE_SIMILARITY = 0.70

# Enough shared vocabulary that a model could plausibly confuse them. Deliberately much
# lower than the near-duplicate threshold: at this level overlap is normal and expected,
# and the finding is about the missing guidance rather than about the overlap.
CONFUSABLE_SIMILARITY = 0.35


@rule(
    "MCP010",
    "missing-description",
    severity=Severity.ERROR,
    summary="The tool has no description at all.",
)
def missing_description(ctx: LintContext) -> Iterable[Problem]:
    """The most expensive defect on this list, and the cheapest to fix.

    Tests for `None` only. `ToolSpec` collapses blank descriptions to `None` on ingest, so
    a server that sends `""` and one that omits the field arrive here identically.
    """
    for tool in ctx.tools:
        if tool.description is not None:
            continue
        yield Problem(
            message=f"`{tool.name}` has no description.",
            suggestion=(
                f"Give `{tool.name}` a description that says what it does, when to reach "
                "for it, and what it returns. Without one, a model has only the name and "
                "the parameter list to go on, and will skip the tool in favour of any "
                "sibling that explains itself."
            ),
            tool=tool.name,
        )


@rule(
    "MCP011",
    "description-too-short",
    severity=Severity.WARNING,
    summary="The description is a fragment rather than a sentence.",
)
def description_too_short(ctx: LintContext) -> Iterable[Problem]:
    for tool in ctx.tools:
        if tool.description is None:
            continue
        count = len(all_words(tool.description))
        unpunctuated = not has_terminal_punctuation(tool.description)
        if count >= MIN_DESCRIPTION_WORDS and not unpunctuated:
            continue

        if count < MIN_DESCRIPTION_WORDS:
            noun = "word" if count == 1 else "words"
            detail = f"`{tool.name}`'s description is {count} {noun} long."
        else:
            detail = f"`{tool.name}`'s description is not a complete sentence."
        yield Problem(
            message=detail,
            suggestion=(
                "Write at least one full sentence saying what the tool does and when to "
                "use it, then a second saying what it returns. A fragment gives retrieval "
                "almost nothing to match a user's phrasing against."
            ),
            tool=tool.name,
        )


@rule(
    "MCP012",
    "description-restates-name",
    severity=Severity.WARNING,
    summary="The description only repeats the words already in the name.",
)
def description_restates_name(ctx: LintContext) -> Iterable[Problem]:
    """`search` described as "Search." has a description in the protocol sense only."""
    for tool in ctx.tools:
        if tool.description is None or not is_subset_of_name(tool.description, tool.name):
            continue
        flattened = " ".join(tool.description.split())
        yield Problem(
            message=f"`{tool.name}`'s description ({flattened!r}) only restates its name.",
            suggestion=(
                "Say something the name cannot: which of several similar tools this is, "
                "what it returns, what it costs, when not to use it. A description that "
                "repeats the name doubles the weight of the name and adds no new signal."
            ),
            tool=tool.name,
        )


def _comparable(tool: LintTool) -> bool:
    return len(tool.description_bag) >= MIN_WORDS_FOR_COMPARISON


def _overlapping_pairs(
    ctx: LintContext, threshold: float
) -> Iterable[tuple[LintTool, LintTool, float]]:
    """Every pair of tools whose descriptions share at least `threshold` of their words."""
    for left, right in itertools.combinations(ctx.tools, 2):
        if not _comparable(left) or not _comparable(right):
            continue
        score = jaccard(left.description_bag, right.description_bag)
        if score >= threshold:
            yield left, right, score


@rule(
    "MCP013",
    "overlapping-descriptions",
    severity=Severity.ERROR,
    summary="Two tools' descriptions are near-identical.",
)
def overlapping_descriptions(ctx: LintContext) -> Iterable[Problem]:
    """Report each near-duplicate pair once, from the earlier tool.

    The percentage goes in the message on purpose. "Shares 78% of its meaningful words
    with `search_orgs`" is a sentence an author can argue with, which is the difference
    between a finding they fix and a rule they disable.
    """
    for left, right, score in _overlapping_pairs(ctx, NEAR_DUPLICATE_SIMILARITY):
        percentage = round(score * 100)
        yield Problem(
            message=(
                f"`{left.name}` and `{right.name}` share {percentage}% of their "
                "meaningful words -- their descriptions are near-identical."
            ),
            suggestion=(
                f"Rewrite one of them around what makes it different. If `{left.name}` "
                f"and `{right.name}` really do the same thing, delete one; if they do not, "
                "the first sentence of each should name the thing only that one handles. "
                "Two descriptions this close are a coin flip at selection time, and the "
                "model has no way to know it guessed wrong."
            ),
            tool=left.name,
            related=(right.name,),
        )


@rule(
    "MCP014",
    "no-disambiguation-guidance",
    severity=Severity.WARNING,
    summary="A tool overlaps with a sibling and never says which to prefer.",
)
def no_disambiguation_guidance(ctx: LintContext) -> Iterable[Problem]:
    """Fire per tool, not per pair, because disambiguating is each tool's own job.

    A tool passes if its description names the sibling, or if it contains steering language
    of any kind. That is generous by design: the aim is to reward an author who wrote
    "use this only when you already have a user ID", not to insist on a house phrasing.
    """
    confusable: dict[str, list[str]] = defaultdict(list)
    for left, right, _ in _overlapping_pairs(ctx, CONFUSABLE_SIMILARITY):
        for tool, sibling in ((left, right), (right, left)):
            text = tool.description or ""
            if mentions(text, sibling.name) or DISAMBIGUATION_PATTERN.search(text):
                continue
            confusable[tool.name].append(sibling.name)

    for tool in ctx.tools:
        siblings = confusable.get(tool.name)
        if not siblings:
            continue
        listed = ", ".join(f"`{name}`" for name in siblings)
        one = siblings[0]
        yield Problem(
            message=(
                f"`{tool.name}` overlaps with {listed}, and its description never says "
                "which to prefer."
            ),
            suggestion=(
                f"Add a sentence to `{tool.name}` of the form \"Use this when X. If you "
                f"need Y, use `{one}` instead.\" Overlap between sibling tools is normal "
                "and usually unavoidable; what separates a server whose tools get picked "
                "correctly from one whose tools do not is whether the descriptions say "
                "how to choose."
            ),
            tool=tool.name,
            related=tuple(siblings),
        )


@rule(
    "MCP015",
    "placeholder-text",
    severity=Severity.ERROR,
    summary="A description still contains placeholder text.",
)
def placeholder_text(ctx: LintContext) -> Iterable[Problem]:
    """Catch `TODO`, `lorem ipsum`, and the rest, in tool and parameter descriptions."""
    for tool in ctx.tools:
        found = PLACEHOLDER_PATTERN.search(tool.description or "")
        if found:
            yield Problem(
                message=(
                    f"`{tool.name}`'s description still contains placeholder text "
                    f"({found.group().strip()!r})."
                ),
                suggestion=(
                    f"Replace it with a real description of what `{tool.name}` does. "
                    "Placeholder text is not neutral: the model reads it, and a tool "
                    "whose description says TODO reads as unfinished and unsafe to call."
                ),
                tool=tool.name,
            )

        for parameter, schema in tool.parameters.items():
            if not isinstance(schema, dict):
                continue
            hit = PLACEHOLDER_PATTERN.search(str(schema.get("description") or ""))
            if not hit:
                continue
            yield Problem(
                message=(
                    f"`{tool.name}.{parameter}`'s description still contains placeholder "
                    f"text ({hit.group().strip()!r})."
                ),
                suggestion=(
                    f"Describe what `{parameter}` actually expects, including an example "
                    "value. A parameter description is the only place a model can learn "
                    "the shape of a value it has to invent."
                ),
                tool=tool.name,
                parameter=parameter,
            )
