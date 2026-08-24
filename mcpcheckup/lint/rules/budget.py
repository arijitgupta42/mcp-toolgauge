"""Context-budget rules -- MCP050 to MCP052.

Every other family in this package is about one tool being unclear. This one is about the
tool list being *expensive*: the whole set of definitions is prepended to every request, so
a server that spends four thousand tokens describing forty tools has spent that budget
before the model has read a word the user said. Past a point, more tools and bigger
definitions do not add capability -- they add lookalikes for the model to confuse, which is
the same failure `eval` measures, reached from the other side.

Sizes come from `estimate_tokens`, a characters-over-four approximation. It is deliberately
crude: a budget rule asks "is this too big to select reliably?", and an exact count would
mean a tokeniser dependency that downloads a model, which lint must never have.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from mcpcheckup.lint.engine import LintContext, rule
from mcpcheckup.lint.text import estimate_tokens
from mcpcheckup.model import Problem, Severity, ToolSpec

# Token budgets, as estimate_tokens() counts them. Fixed rather than configured, like the
# MCP013 similarity threshold: a budget someone can quietly raise is a budget that never
# fails. Pinned with headroom over the careful fixture -- goodserver's whole surface is
# ~1600 tokens and its largest tool ~240 -- so a well-documented server stays clean and only
# genuine bloat trips these.
SINGLE_TOOL_LIMIT = 800
SERVER_BUDGET = 5000

# Tool-count ceiling. Selection accuracy falls off as the option list grows: past this many
# tools a model is choosing between more lookalikes than it can hold apart. Well above
# goodserver's 8 and badserver's 10, so neither fixture trips it.
TOOL_COUNT_LIMIT = 40


def _definition_text(spec: ToolSpec) -> str:
    """The part of a tool the model weighs when selecting: name, description, input schema.

    Serialised the way the model is handed it -- the schema as JSON -- so the estimate is of
    the real cost rather than of our internal model. Output schema and annotations are left
    out: they are small next to the input schema and do not drive selection.
    """
    return "\n".join(
        (
            spec.name,
            spec.description or "",
            json.dumps(spec.input_schema, sort_keys=True),
        )
    )


def _definition_tokens(spec: ToolSpec) -> int:
    return estimate_tokens(_definition_text(spec))


@rule(
    "MCP050",
    "single-tool-definition-too-large",
    severity=Severity.INFO,
    summary="A single tool's definition is large enough to crowd out its neighbours.",
)
def single_tool_definition_too_large(ctx: LintContext) -> Iterable[Problem]:
    for tool in ctx.tools:
        tokens = _definition_tokens(tool.spec)
        if tokens <= SINGLE_TOOL_LIMIT:
            continue
        yield Problem(
            message=(
                f"`{tool.name}`'s definition is about {tokens} tokens, well past the "
                f"~{SINGLE_TOOL_LIMIT} where one tool starts to crowd the others."
            ),
            suggestion=(
                "Cut the description down to what a model needs to *choose* this tool, and "
                "push exhaustive parameter detail into the parameter descriptions, which are "
                "only read once the tool is already selected. Every prompt pays for this "
                "definition in full whether or not the tool is the one being called."
            ),
            tool=tool.name,
        )


@rule(
    "MCP051",
    "server-tool-budget-exceeded",
    severity=Severity.WARNING,
    summary="The server's tool definitions add up to a large context cost.",
)
def server_tool_budget_exceeded(ctx: LintContext) -> Iterable[Problem]:
    total = sum(_definition_tokens(tool.spec) for tool in ctx.tools)
    if total <= SERVER_BUDGET:
        return
    yield Problem(
        message=(
            f"The server's {len(ctx.tools)} tool definitions total about {total} tokens, "
            f"above the ~{SERVER_BUDGET}-token budget every request has to carry."
        ),
        suggestion=(
            f"Keep the whole tool surface under about {SERVER_BUDGET} tokens. Shorten the "
            "longest definitions (MCP050 names them), fold near-duplicate tools into one, or "
            "split rarely-used tools onto a separate server. The full set of definitions is "
            "prepended to every prompt, so this is context spent before the user is read."
        ),
    )


@rule(
    "MCP052",
    "too-many-tools",
    severity=Severity.WARNING,
    summary="The server has enough tools that selection accuracy suffers.",
)
def too_many_tools(ctx: LintContext) -> Iterable[Problem]:
    count = len(ctx.tools)
    if count <= TOOL_COUNT_LIMIT:
        return
    yield Problem(
        message=(
            f"The server advertises {count} tools, past the ~{TOOL_COUNT_LIMIT} where "
            "model tool-selection measurably degrades."
        ),
        suggestion=(
            f"Group these into a handful of tools the model chooses between, or split them "
            f"across focused servers. Past roughly {TOOL_COUNT_LIMIT} options a model spends "
            "its attention telling lookalikes apart and picks wrong more often -- the same "
            "failure `eval` measures. Fewer, clearer tools beat many precise ones."
        ),
    )
