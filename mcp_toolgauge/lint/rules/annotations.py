"""Annotation rules -- MCP040 to MCP042.

Tool annotations are how a server tells a client what a tool *does to the world*, so that
the client can decide whether to call it without asking, ask first, or refuse. A missing
annotation is not a neutral omission: a client that cannot tell a read from a delete has to
treat everything as a delete, and the safe default costs the author every call that would
otherwise have gone through unattended.

All three rules turn on the tri-state in `ToolAnnotations`. `None` means the server said
nothing; `False` means it said no. Only `None` is a finding here -- a server that has
thought about the question and answered "no" has done the thing we are asking for.
"""

from __future__ import annotations

from collections.abc import Iterable

from mcp_toolgauge.lint.engine import LintContext, LintTool, rule
from mcp_toolgauge.lint.text import (
    DESTRUCTIVE_PHRASE_PATTERN,
    DESTRUCTIVE_VERBS,
    READ_OPENING_PATTERN,
    READ_VERBS,
)
from mcp_toolgauge.model import Problem, Severity


def _unset(tool: LintTool, hint: str) -> bool:
    annotations = tool.annotations
    return annotations is None or getattr(annotations, hint) is None


def _reads_like_a_query(tool: LintTool) -> bool:
    """Whether the tool presents itself as a read.

    Two signals, either sufficient: the name opens with a reading verb, or the description
    opens with one. Both are about the *opening* rather than the whole string, because
    "returns the updated record" turns up in the description of plenty of writes.
    """
    if tool.name_tokens and tool.name_tokens[0] in READ_VERBS:
        return True
    return bool(READ_OPENING_PATTERN.match(tool.description or ""))


def _reads_like_a_deletion(tool: LintTool) -> bool:
    if set(tool.name_tokens) & DESTRUCTIVE_VERBS:
        return True
    return bool(DESTRUCTIVE_PHRASE_PATTERN.search(tool.description or ""))


@rule(
    "MCP040",
    "destructive-tool-without-hint",
    severity=Severity.ERROR,
    summary="A tool that looks destructive declares no destructiveHint.",
)
def destructive_without_hint(ctx: LintContext) -> Iterable[Problem]:
    """The one finding on this list that is about safety rather than selection."""
    for tool in ctx.tools:
        if not _reads_like_a_deletion(tool) or not _unset(tool, "destructive_hint"):
            continue
        yield Problem(
            message=(
                f"`{tool.name}` reads as destructive but declares no `destructiveHint`."
            ),
            suggestion=(
                f"Set `destructiveHint: true` on `{tool.name}` (and `readOnlyHint: false`) "
                "so clients can prompt before calling it. A client that cannot tell this "
                "apart from a read has two options, and both are bad: confirm everything, "
                "which trains users to click through, or confirm nothing."
            ),
            tool=tool.name,
        )


@rule(
    "MCP041",
    "read-only-tool-without-hint",
    severity=Severity.WARNING,
    summary="A tool that looks read-only declares no readOnlyHint.",
)
def read_only_without_hint(ctx: LintContext) -> Iterable[Problem]:
    for tool in ctx.tools:
        if not _reads_like_a_query(tool) or not _unset(tool, "read_only_hint"):
            continue
        yield Problem(
            message=f"`{tool.name}` reads as read-only but declares no `readOnlyHint`.",
            suggestion=(
                f"Set `readOnlyHint: true` on `{tool.name}`. This is the annotation that "
                "*earns* you calls rather than costing them: clients use it to run safe "
                "tools without interrupting the user, and an unmarked read gets the same "
                "confirmation prompt as a delete."
            ),
            tool=tool.name,
        )


@rule(
    "MCP042",
    "missing-idempotent-hint",
    severity=Severity.INFO,
    summary="A tool that changes state declares no idempotentHint.",
)
def missing_idempotent_hint(ctx: LintContext) -> Iterable[Problem]:
    """Only asked of tools that write.

    Tools that look like reads are skipped, so a server gets one annotation finding per
    tool rather than two, and so the advice arrives where it changes behaviour: whether a
    client is allowed to retry a failed call.
    """
    for tool in ctx.tools:
        if _reads_like_a_query(tool) or not _unset(tool, "idempotent_hint"):
            continue
        yield Problem(
            message=f"`{tool.name}` changes state but declares no `idempotentHint`.",
            suggestion=(
                f"Say whether calling `{tool.name}` twice with the same arguments is the "
                "same as calling it once. Clients use this to decide whether a timed-out "
                "call can be retried; without it the safe assumption is no, and the user "
                "is asked to sort out a call that may or may not have happened."
            ),
            tool=tool.name,
        )
