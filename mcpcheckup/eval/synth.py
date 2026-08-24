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

from mcpcheckup.eval.backend import Completion

# The threshold MCP014 uses for "these two could be confused". Imported rather than
# restated so the linter and the eval cannot drift apart on what counts as overlap: a pair
# the linter warns about is a pair the eval writes hard cases for.
from mcpcheckup.lint.rules.description import CONFUSABLE_SIMILARITY
from mcpcheckup.lint.text import content_bag, jaccard, meaningful_name_tokens
from mcpcheckup.model import CaseKind, EvalCase, ToolSpec

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

# The keys a reply may carry prompts under: "prompts" for a positive or abstain request,
# "a" and "b" for the two halves of a sibling pair.
_PROMPT_KEYS = ("prompts", "a", "b")

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
    """A generated suite, plus what it cost to generate.

    `skipped` names the steps whose reply could not be used. Small models occasionally
    return JSON with an unterminated string, and losing an entire eleven-call `--init`
    to one of them would be a poor trade -- so the step is dropped, named, and the rest
    of the suite is written.
    """

    cases: tuple[EvalCase, ...]
    cost_usd: float = 0.0
    calls: int = 0
    skipped: tuple[str, ...] = ()


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
# The first half exists because a generator otherwise writes fluent requests that quietly
# omit the identifiers the tool requires -- "can you mark my ticket as resolved?" for a tool
# that needs a ticket id. A model then declines, correctly, and the case records a miss that
# is nothing to do with the description under test. Measured on goodserver: three tools
# scored 0% purely because their prompts never named the thing to act on.
#
# The second half exists because the first one, alone, made things worse. Told to supply
# required values and shown the parameter documentation, the generator started naming the
# parameters -- "user 'dave' priority high" for `ticket`, "user 'ops_team' urgency critical"
# for `ticket2`. Those two tools have near-identical descriptions and differ only in that
# one parameter, so the prompts handed over the entire discriminator. Measured on badserver:
# both scored 8/8, a pair the linter flags as near-duplicates, because the model could match
# a parameter name without reading a description at all.
_SUPPLY_ARGUMENTS = (
    "- If the tool has required parameters, the request must contain the information they "
    "need, written the way the parameter documentation shows it -- quote an identifier in "
    "the documented format rather than inventing a different one. A request that omits a "
    "required identifier cannot be answered by that tool at all, so it tests nothing.\n"
    "- Supply that information the way a person would say it, and never name the parameter "
    "itself. Write \"mark it as urgent\" or \"this one is critical\", never \"urgency: "
    "high\" or \"priority=high\". A prompt that names a parameter hands the model the "
    "answer: it can match the parameter and never read a single description.\n"
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
        # strict=False allows raw newlines and tabs inside string values, which small
        # models emit constantly and which are unambiguous to read. It does not rescue
        # genuinely broken JSON -- an unterminated string still fails, and should.
        parsed = json.loads(match.group(), strict=False)
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
    skipped: list[str] = []
    totals = [0.0, 0]  # cost, calls

    def attempt(
        label: str, produce: Callable[[], tuple[tuple[EvalCase, ...], Completion]]
    ) -> None:
        """Run one generation step, and let it fail without taking the run with it.

        Only `SynthesisFailed` is caught. A rate limit or a bad API key is not something to
        paper over -- those come back as `BackendError` and stop the run, because
        continuing would produce a suite full of holes for a reason the user can fix.
        """
        if on_step is not None:
            on_step(label)
        try:
            drafted, completion = produce()
        except SynthesisFailed:
            skipped.append(label)
            totals[1] += 1
            return
        totals[0] += completion.cost_usd
        totals[1] += 1
        if not drafted:
            # Readable JSON with nothing usable in it -- the right keys missing, or every
            # prompt too short to keep. Silence here once cost badserver its abstain cases
            # with nothing in the output to say so, which is worse than the loud failure.
            skipped.append(label)
            return
        cases.extend(drafted)

    for tool in tools:
        attempt(
            f"prompts for {tool.name}",
            lambda tool=tool: _positive_cases(tool, tools, per_tool, complete),  # type: ignore[misc]
        )

    for left, right in confusable_pairs(tools):
        attempt(
            f"hard cases for {left.name} vs {right.name}",
            lambda left=left, right=right: _sibling_cases(left, right, per_pair, complete),  # type: ignore[misc]
        )

    if abstain > 0 and tools:
        attempt(
            "prompts nothing should answer",
            lambda: _abstain_cases(tools, abstain, complete),
        )

    if not cases:
        raise SynthesisFailed(
            "The model produced no usable cases. Try a different --model, or write "
            "a few cases by hand -- the file format is documented in its own header."
        )
    return Draft(
        cases=tuple(cases),
        cost_usd=totals[0],
        calls=int(totals[1]),
        skipped=tuple(skipped),
    )


def looks_usable(text: str) -> bool:
    """Whether a reply can be read *and* has prompts in it.

    Handed to the cache so a recorded but unusable reply is not served back forever. Without
    it, a bad answer is pinned and its step is skipped on every subsequent run -- the cache
    would be remembering a failure rather than a result.

    Parseability alone is not enough. A model that returns tidy JSON under the wrong key
    passes `_extract_json` and yields nothing, so re-running would keep replaying the same
    empty answer and never retry it.
    """
    try:
        payload = _extract_json(text)
    except SynthesisFailed:
        return False
    return any(
        isinstance(payload.get(key), list) and payload[key] for key in _PROMPT_KEYS
    )


def tool_order(tools: Iterable[ToolSpec]) -> dict[str, int]:
    """Tool name to position, for sorting cases the way the server lists its tools."""
    return {tool.name: index for index, tool in enumerate(tools)}
