"""Generating a first draft of a case suite from a server's tools.

Two things make the difference between a suite that measures something and one that
measures nothing.

**Paraphrase, or you are grading string matching.** If a generated prompt reuses the
description's own distinctive words, then any model that can do retrieval scores full
marks and the suite tells you nothing about whether your descriptions are any good. Every
prompt asked for here is asked for in the user's words, not the author's.

**The hard cases have to be found, not hoped for.** A suite of one-obvious-answer prompts
flatters every server. The cases that separate a good server from a bad one are the ones
where two tools both plausibly fit -- so those pairs are located deliberately, using the
same overlap measure the linter uses. The pairs `MCP013` and `MCP014` complain about are
exactly the pairs that get hard cases written for them, which is the point where the static
and dynamic halves of this tool meet.

Everything here is a first draft. `--init` writes the file, and then it belongs to a human
who knows what their users actually say.
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from mcp_doctor.eval.backend import Completion

# The threshold MCP014 uses for "these two could be confused". Imported rather than
# restated so the linter and the eval cannot drift apart on what counts as overlap: a pair
# the linter warns about is a pair the eval writes hard cases for.
from mcp_doctor.lint.rules.description import CONFUSABLE_SIMILARITY
from mcp_doctor.lint.text import content_bag, jaccard, meaningful_name_tokens
from mcp_doctor.model import CaseKind, EvalCase, ToolSpec

DEFAULT_CASES_PER_TOOL = 4
DEFAULT_SIBLING_CASES = 2
DEFAULT_ABSTAIN_CASES = 3

# Names alone can make two tools confusable even when neither has a description worth
# comparing -- `ticket` and `ticket2` being the obvious shape. Half the subject tokens
# shared is enough to be worth a hard case.
NAME_SIMILARITY = 0.5

# A server with thirty overlapping tools would otherwise generate hundreds of sibling
# cases. The worst pairs are the ones worth paying for.
MAX_PAIRS = 6

# Searched for in this order rather than as one alternation. A single pattern would scan
# left to right and, on a reply like `[note] {"prompts": [...]}`, latch onto the bracket
# first and swallow the object. Objects are what we asked for, so objects are looked for
# first; the array pattern exists only so that a model which replied with a bare list gets
# told precisely that, rather than "no JSON at all".
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
_JSON_ARRAY = re.compile(r"\[.*\]", re.DOTALL)

# The seam every model call in this module goes through. The runner's cache wraps it, so
# an --init interrupted at tool seven does not re-buy tools one through six -- which
# matters more than it sounds when the default model is on a rate-limited free tier.
TextCompleter = Callable[[list[dict[str, str]]], tuple[str, Completion]]


class SynthesisFailed(Exception):
    """The model did not return anything usable, after being asked plainly."""


@dataclass(frozen=True)
class Draft:
    """A generated suite, plus what it cost to generate."""

    cases: tuple[EvalCase, ...]
    cost_usd: float = 0.0
    calls: int = 0


def _parameter_lines(tool: ToolSpec, names: Iterable[str]) -> list[str]:
    """Each parameter with its own documentation, which is where formats live.

    A well-written schema says `e.g. 'usr_1a2b'` in the parameter description, and that is
    the single most useful thing the generator can be shown -- it is how a prompt ends up
    quoting an identifier in the shape the tool actually accepts.
    """
    rendered = []
    for name in names:
        schema = tool.parameters.get(name)
        detail = schema.get("description") if isinstance(schema, dict) else None
        documented = f" -- {detail}" if isinstance(detail, str) and detail else ""
        rendered.append(f"  {name}{documented}")
    return rendered


def _describe(tool: ToolSpec) -> str:
    """One tool, as the generator sees it.

    Required and optional parameters are split apart, because the distinction changes what
    a usable prompt looks like. A request that never mentions a required identifier cannot
    be answered by the tool it names -- a model that declines it is behaving correctly, and
    the case measures nothing.
    """
    lines = [f"name: {tool.name}", f"description: {tool.description or '(none)'}"]
    required = tool.required_parameters
    optional = tuple(name for name in sorted(tool.parameters) if name not in required)
    if required:
        lines.append("required parameters (a request must supply these):")
        lines.extend(_parameter_lines(tool, required))
    if optional:
        lines.append("optional parameters:")
        lines.extend(_parameter_lines(tool, optional))
    return "\n".join(lines)


def _catalogue(tools: Sequence[ToolSpec]) -> str:
    return "\n".join(f"- {tool.name}: {tool.description or '(no description)'}" for tool in tools)


_RULES = (
    "Rules:\n"
    "- Write what a real person would type or say, not documentation.\n"
    "- Do not reuse the distinctive words from the tool's name or description. "
    "Paraphrase. A prompt that echoes the description tests string matching, not "
    "understanding.\n"
    "- Keep each one to a single sentence.\n"
    "- Vary the phrasing between them: different verbs, different level of formality.\n"
)

# Added to the positive and sibling instructions, and deliberately not to the abstain one:
# an abstain prompt is *supposed* to be unanswerable.
#
# Without this, a generator writes fluent, natural-sounding requests that quietly omit the
# identifiers the tool requires -- "can you mark my ticket as resolved?" for a tool that
# needs a ticket id. A model then declines, correctly, and the case records a miss that is
# nothing to do with the description under test. Measured on the goodserver fixture: three
# tools scored 0% purely because their prompts never named the thing to act on.
_SUPPLY_ARGUMENTS = (
    "- If the tool has required parameters, the request must contain the information they "
    "need, written the way the parameter documentation shows it -- quote an identifier in "
    "the documented format rather than inventing a different one. A request that omits a "
    "required identifier cannot be answered by that tool at all, so it tests nothing.\n"
)


def _messages(instruction: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You write realistic user utterances for testing which tool an assistant "
                "picks. You reply with JSON only -- no prose, no code fences."
            ),
        },
        {"role": "user", "content": instruction},
    ]


def _extract_json(text: str) -> dict[str, object]:
    """Parse the model's reply, forgiving the wrappers small models like to add."""
    match = _JSON_OBJECT.search(text) or _JSON_ARRAY.search(text)
    if match is None:
        raise SynthesisFailed(f"The model replied with no JSON object:\n{text[:400]}")
    try:
        parsed = json.loads(match.group())
    except ValueError as exc:
        raise SynthesisFailed(f"The model's JSON did not parse: {exc}\n{text[:400]}") from exc
    if not isinstance(parsed, dict):
        raise SynthesisFailed(
            f"The model returned JSON that was not an object:\n{text[:400]}"
        )
    return parsed


def _prompts(payload: dict[str, object], key: str, wanted: int) -> tuple[str, ...]:
    """The strings under `key`, cleaned up and capped.

    Short strings are dropped rather than kept: a two-word "prompt" is a label, and a suite
    padded with labels reports a number that means nothing.
    """
    raw = payload.get(key)
    if not isinstance(raw, list):
        return ()
    cleaned = [
        " ".join(str(item).split())
        for item in raw
        if isinstance(item, str) and len(str(item).split()) >= 3
    ]
    return tuple(dict.fromkeys(cleaned))[:wanted]


def _positive_cases(
    tool: ToolSpec, others: Sequence[ToolSpec], wanted: int, complete: TextCompleter
) -> tuple[tuple[EvalCase, ...], Completion]:
    instruction = (
        f"An assistant has access to these tools:\n{_catalogue(others)}\n\n"
        f"Write {wanted} things a user might ask that should be answered by this one, and "
        f"only this one:\n\n{_describe(tool)}\n\n"
        f"{_RULES}{_SUPPLY_ARGUMENTS}"
        "- Each request must be answerable by this tool and by none of the others listed.\n\n"
        'Reply with JSON: {"prompts": ["...", "..."]}'
    )
    text, completion = complete(_messages(instruction))
    prompts = _prompts(_extract_json(text), "prompts", wanted)
    cases = tuple(
        EvalCase(
            id=f"{tool.name}-p{index}",
            kind=CaseKind.POSITIVE,
            expected=tool.name,
            prompt=prompt,
        )
        for index, prompt in enumerate(prompts, start=1)
    )
    return cases, completion


def _sibling_cases(
    left: ToolSpec, right: ToolSpec, wanted: int, complete: TextCompleter
) -> tuple[tuple[EvalCase, ...], Completion]:
    instruction = (
        "These two tools are easy to confuse:\n\n"
        f"A:\n{_describe(left)}\n\nB:\n{_describe(right)}\n\n"
        f"Write {wanted} requests that belong to A and {wanted} that belong to B. Each one "
        "should be tempting to route to the other tool, but have exactly one correct "
        "answer -- the difficulty should come from the situation, not from ambiguity.\n\n"
        f"{_RULES}{_SUPPLY_ARGUMENTS}\n"
        'Reply with JSON: {"a": ["...", "..."], "b": ["...", "..."]}'
    )
    text, completion = complete(_messages(instruction))
    payload = _extract_json(text)

    cases: list[EvalCase] = []
    for key, tool, rival in (("a", left, right), ("b", right, left)):
        for index, prompt in enumerate(_prompts(payload, key, wanted), start=1):
            cases.append(
                EvalCase(
                    id=f"{tool.name}-vs-{rival.name}-s{index}",
                    kind=CaseKind.SIBLING,
                    expected=tool.name,
                    rival=rival.name,
                    prompt=prompt,
                )
            )
    return tuple(cases), completion


def _abstain_cases(
    tools: Sequence[ToolSpec], wanted: int, complete: TextCompleter
) -> tuple[tuple[EvalCase, ...], Completion]:
    instruction = (
        f"An assistant has access to exactly these tools:\n{_catalogue(tools)}\n\n"
        f"Write {wanted} requests that are plainly about the same subject area but that "
        "none of these tools can satisfy. They should be tempting -- close enough that a "
        "careless assistant would reach for one of the tools anyway -- but genuinely "
        "outside what any of them does.\n\n"
        f"{_RULES}\n"
        'Reply with JSON: {"prompts": ["...", "..."]}'
    )
    text, completion = complete(_messages(instruction))
    cases = tuple(
        EvalCase(id=f"abstain-{index}", kind=CaseKind.ABSTAIN, prompt=prompt)
        for index, prompt in enumerate(_prompts(_extract_json(text), "prompts", wanted), start=1)
    )
    return cases, completion


def confusable_pairs(tools: Sequence[ToolSpec], limit: int = MAX_PAIRS) -> tuple[
    tuple[ToolSpec, ToolSpec], ...
]:
    """The tool pairs worth writing hard cases for, most confusable first.

    Two signals, because they catch different servers. Description overlap is the linter's
    measure and finds the copy-paste siblings. Name overlap catches the pairs whose
    descriptions are too thin to compare at all -- `ticket` and `ticket2` share no prose
    worth measuring, and are still the most confusable pair on the server.
    """
    scored: list[tuple[float, int, int]] = []
    for (left_index, left), (right_index, right) in itertools.combinations(
        enumerate(tools), 2
    ):
        description = jaccard(content_bag(left.description), content_bag(right.description))
        names = jaccard(
            frozenset(meaningful_name_tokens(left.name)),
            frozenset(meaningful_name_tokens(right.name)),
        )
        if description >= CONFUSABLE_SIMILARITY or names >= NAME_SIMILARITY:
            scored.append((max(description, names), left_index, right_index))

    # Score descending, then by position, so the same server always yields the same pairs
    # in the same order and `--init` is reproducible.
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return tuple((tools[left], tools[right]) for _, left, right in scored[:limit])


def draft_cases(
    tools: Sequence[ToolSpec],
    complete: TextCompleter,
    *,
    per_tool: int = DEFAULT_CASES_PER_TOOL,
    per_pair: int = DEFAULT_SIBLING_CASES,
    abstain: int = DEFAULT_ABSTAIN_CASES,
    on_step: Callable[[str], None] | None = None,
) -> Draft:
    """Generate a first-draft suite: positives for every tool, siblings for the pairs that
    overlap, and a few prompts nothing should answer.

    One call per tool and one per pair, rather than one call for the whole server. Small
    models write markedly better prompts when they are looking at one tool at a time, and a
    failure costs one tool's cases instead of the suite.
    """
    cases: list[EvalCase] = []
    cost = 0.0
    calls = 0

    def step(label: str) -> None:
        if on_step is not None:
            on_step(label)

    for tool in tools:
        step(f"prompts for {tool.name}")
        drafted, completion = _positive_cases(tool, tools, per_tool, complete)
        cases.extend(drafted)
        cost += completion.cost_usd
        calls += 1

    for left, right in confusable_pairs(tools):
        step(f"hard cases for {left.name} vs {right.name}")
        drafted, completion = _sibling_cases(left, right, per_pair, complete)
        cases.extend(drafted)
        cost += completion.cost_usd
        calls += 1

    if abstain > 0 and tools:
        step("prompts nothing should answer")
        drafted, completion = _abstain_cases(tools, abstain, complete)
        cases.extend(drafted)
        cost += completion.cost_usd
        calls += 1

    if not cases:
        raise SynthesisFailed(
            "The model produced no usable cases. Try a different --model, or write "
            "a few cases by hand -- the file format is documented in its own header."
        )
    return Draft(cases=tuple(cases), cost_usd=cost, calls=calls)


def tool_order(tools: Iterable[ToolSpec]) -> dict[str, int]:
    """Tool name to position, for sorting cases the way the server lists its tools."""
    return {tool.name: index for index, tool in enumerate(tools)}
