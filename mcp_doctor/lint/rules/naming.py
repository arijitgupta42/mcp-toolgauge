"""Naming rules -- MCP001 to MCP004.

The name is the first thing a model reads and the shortest, so it carries more weight per
character than anything else a server publishes. These rules ask four questions of it: is
it unique, does it say anything, does the description back it up, and does it look like it
belongs to the same server as its neighbours.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable

from mcp_doctor.lint.engine import LintContext, rule
from mcp_doctor.lint.text import (
    BARE_VERBS,
    EMPTY_NOUNS,
    FILLER_TOKENS,
    naming_style,
    singular,
    token_appears,
)
from mcp_doctor.model import Problem, Severity

_GENERIC_TOKENS = BARE_VERBS | EMPTY_NOUNS | FILLER_TOKENS


@rule(
    "MCP001",
    "near-duplicate-tool-names",
    severity=Severity.ERROR,
    summary="Two tools have names that reduce to the same words.",
)
def near_duplicate_names(ctx: LintContext) -> Iterable[Problem]:
    """Group tools whose names differ only by digits, plurals, or word separators.

    `ticket` and `ticket2` both reduce to `("ticket",)`. So do `getUser` and `get_user`.
    From a model's point of view those are the same string with noise on it.
    """
    groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for tool in ctx.tools:
        key = tuple(singular(token) for token in tool.name_tokens if not token.isdigit())
        if key:
            groups[key].append(tool.name)

    for names in groups.values():
        if len(names) < 2:
            continue
        first, *rest = names
        others = ", ".join(f"`{name}`" for name in rest)
        exact = len(set(names)) == 1
        detail = (
            f"Two tools are both named `{first}`."
            if exact
            else f"`{first}` and {others} reduce to the same words, so only the "
            "descriptions tell them apart."
        )
        yield Problem(
            message=detail,
            suggestion=(
                "Rename at least one of them so the name itself carries the difference -- "
                "`create_support_ticket` versus `create_incident_ticket`, not `ticket` "
                "versus `ticket2`. A trailing digit is not a distinguishing feature, and "
                "a model that cannot tell two tools apart by name has to fall back on "
                "descriptions that are usually just as similar."
            ),
            tool=first,
            related=tuple(rest),
        )


@rule(
    "MCP002",
    "non-descriptive-tool-name",
    severity=Severity.WARNING,
    summary="Every word in the name is generic, so it says nothing about what the tool does.",
)
def non_descriptive_name(ctx: LintContext) -> Iterable[Problem]:
    """Fire when the name is built entirely from filler.

    `get_data` is two words and still says nothing: a verb that applies to everything and a
    noun that names nothing. `get_user_profile` uses the same verb and is fine, because
    `user` and `profile` are doing work.
    """
    for tool in ctx.tools:
        tokens = [token for token in tool.name_tokens if not token.isdigit()]
        if not tokens or not all(token in _GENERIC_TOKENS for token in tokens):
            continue
        yield Problem(
            message=(
                f"Every word in `{tool.name}` is generic, so the name says nothing about "
                "what the tool operates on."
            ),
            suggestion=(
                f"Rename `{tool.name}` to verb-plus-object form that names the subject -- "
                "`search_users`, `create_support_ticket`, `archive_ticket`. A model ranks "
                "tools by name before it reads a single description, and a name that "
                "would fit on any server in the world gives it nothing to match against."
            ),
            tool=tool.name,
        )


@rule(
    "MCP003",
    "name-subject-missing-from-description",
    severity=Severity.WARNING,
    summary="A subject named in the tool name never appears in its description.",
)
def name_subject_missing(ctx: LintContext) -> Iterable[Problem]:
    """Check that the description backs up the nouns in the name.

    Only the *subject* tokens are checked -- verbs are stripped first -- because a good
    description is free to say "Find people" where the name says "search". What it is not
    free to do is never mention users at all when the tool is called `search_users`, which
    is exactly how two sibling search tools end up indistinguishable.
    """
    for tool in ctx.tools:
        if tool.description is None or not tool.subject_tokens:
            continue
        missing = [
            token for token in tool.subject_tokens if not token_appears(token, tool.description_bag)
        ]
        if not missing:
            continue
        quoted = ", ".join(f"`{token}`" for token in missing)
        yield Problem(
            message=(
                f"`{tool.name}` promises {quoted} in its name, but the description never "
                "mentions it."
            ),
            suggestion=(
                f"Say what {quoted} means here in the first sentence of `{tool.name}`'s "
                "description. Retrieval matches a user's phrasing against the description "
                "as much as the name, so a description that never names its own subject "
                "loses to any sibling whose description does."
            ),
            tool=tool.name,
        )


@rule(
    "MCP004",
    "mixed-naming-conventions",
    severity=Severity.WARNING,
    summary="The server mixes naming conventions across its tools.",
)
def mixed_naming_conventions(ctx: LintContext) -> Iterable[Problem]:
    """Fire once, at server level, when tool names do not agree on a convention.

    Single lowercase words are excluded: `search` conforms to snake_case and camelCase
    alike, and accusing a server of inconsistency on the strength of a name that fits both
    would be wrong.
    """
    styles = [(tool.name, naming_style(tool.name)) for tool in ctx.tools]
    decided = [(name, style) for name, style in styles if style != "flat"]
    counted = Counter(style for _, style in decided)
    if len(counted) < 2:
        return

    (majority, _), = counted.most_common(1)
    odd = [name for name, style in decided if style != majority]
    listed = ", ".join(f"`{name}`" for name in odd)
    breakdown = ", ".join(f"{count} {style}" for style, count in counted.most_common())
    yield Problem(
        message=f"Tool names mix conventions: {breakdown}. The odd ones out are {listed}.",
        suggestion=(
            f"Rename {listed} to {majority} so the whole server reads as one API. Mixed "
            "conventions make a tool list look assembled rather than designed, and give a "
            "model one more axis of variation that carries no meaning."
        ),
        related=tuple(odd),
    )
