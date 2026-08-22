"""Putting the cases to a model, one at a time, through the cache.

Nothing in here calls a provider directly. Every question goes to the cache first, and only
a miss reaches the backend -- which is what makes the second run of an unchanged suite
free, and what lets every test in this project stub one seam instead of mocking a network.

The retry policy is here rather than in the backend because it belongs next to the pacing.
A rate limit is not really an error, it is the provider telling us to slow down, so the
runner waits the interval it was given and tries again. A bad API key is an error, and no
amount of waiting improves it -- so `BackendError.retryable` decides which of those two
things is happening and the runner does not have to guess.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from mcp_doctor.eval import backend
from mcp_doctor.eval.arguments import check_arguments
from mcp_doctor.eval.backend import BackendError, Completion, ToolCall
from mcp_doctor.eval.cache import CachedCall, CacheMiss, ResponseCache, cache_key
from mcp_doctor.model import CaseOutcome, CaseSuite, EvalCase, ServerInfo, ToolSpec

# Four attempts spanning a bit over half a minute. Enough to ride out a per-minute quota,
# short enough that a genuinely wedged provider fails the run instead of hanging it.
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = (4.0, 8.0, 16.0)

# Never wait longer than this on a provider's say-so. Some send a retry-after measured in
# hours, which is a reason to stop, not a reason to sleep.
MAX_BACKOFF_SECONDS = 60.0

# The seam. The runner is handed a callable, so a test passes a function and never
# discovers whether a network exists.
Completer = Callable[[list[dict[str, str]], list[dict[str, Any]]], Completion]


class BudgetExceeded(Exception):
    """The run cost more than `--max-cost` allowed, and stopped.

    Carries how far it got, because the calls already made are cached: raising the limit
    and running again resumes rather than starting over, and the message says so.
    """

    def __init__(self, spent: float, limit: float, completed: int, total: int) -> None:
        super().__init__(
            f"Stopped after {completed} of {total} cases, having spent ${spent:.4f} of a "
            f"${limit:.2f} budget.\n"
            "  The calls already made are cached, so raising --max-cost and running again "
            "picks up where this left off."
        )
        self.spent = spent
        self.limit = limit
        self.completed = completed
        self.total = total


@dataclass
class RunStats:
    """What the run cost in calls, cache hits, and money."""

    cached: int = 0
    called: int = 0
    cost_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class RunResult:
    outcomes: tuple[CaseOutcome, ...] = ()
    stats: RunStats = field(default_factory=RunStats)


def _default_completer(model: str, timeout: float) -> Completer:
    def call(messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> Completion:
        return backend.complete(model=model, messages=messages, tools=tools, timeout=timeout)

    return call


def _wait_for(error: BackendError, attempt: int) -> float:
    """How long to sleep before retry `attempt`, honouring the provider when it says."""
    if error.retry_after is not None and error.retry_after > 0:
        return min(error.retry_after, MAX_BACKOFF_SECONDS)
    index = min(attempt, len(BACKOFF_SECONDS) - 1)
    return BACKOFF_SECONDS[index]


def _call_with_retries(
    complete: Completer,
    messages: list[dict[str, str]],
    tools: list[dict[str, Any]],
    *,
    sleep: Callable[[float], None],
    on_retry: Callable[[str], None] | None = None,
) -> Completion:
    last: BackendError | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return complete(messages, tools)
        except BackendError as error:
            if not error.retryable:
                raise
            last = error
            if attempt == MAX_ATTEMPTS - 1:
                break
            delay = _wait_for(error, attempt)
            if on_retry is not None:
                on_retry(f"{error.message.splitlines()[0]} -- waiting {delay:g}s")
            sleep(delay)
    assert last is not None  # only reachable after a retryable failure
    raise last


def run_case(
    case: EvalCase,
    *,
    tool_definitions: list[dict[str, Any]],
    by_name: dict[str, ToolSpec],
    server: ServerInfo | None,
    model: str,
    tool_digest: str,
    cache: ResponseCache,
    complete: Completer | None,
    offline: bool,
    stats: RunStats,
    sleep: Callable[[float], None],
    pace: float,
    on_retry: Callable[[str], None] | None,
) -> CaseOutcome:
    """One case: cache lookup, then a model call if it has to."""
    messages = backend.build_messages(case.prompt, server)
    key = cache_key(model=model, messages=messages, tool_digest=tool_digest)

    recorded = cache.get(key)
    cached = recorded is not None
    if recorded is None:
        if offline:
            raise CacheMiss(
                f"No recorded answer for case {case.id} at model {model}.\n"
                f"  {cache.path} has {len(cache)} entries, none matching.\n"
                "  Either the cases or the server's tools have changed since the "
                "recording. Re-record without --offline, or restore the cache."
            )
        if complete is None:  # pragma: no cover - guarded by the caller
            raise CacheMiss("No completer available and the answer is not cached.")
        if pace > 0 and stats.called:
            sleep(pace)
        completion = _call_with_retries(
            complete, messages, tool_definitions, sleep=sleep, on_retry=on_retry
        )
        recorded = CachedCall.from_completion(completion)
        cache.put(key, recorded, model=model)
        stats.called += 1
        stats.cost_usd += recorded.cost_usd
        stats.prompt_tokens += recorded.prompt_tokens
        stats.completion_tokens += recorded.completion_tokens
    else:
        stats.cached += 1

    call: ToolCall = recorded.as_tool_call()
    selected = by_name.get(call.tool or "")
    return CaseOutcome(
        case=case,
        selected=call.tool,
        arguments=call.arguments,
        # Checked against the tool that was actually called, not the one that should have
        # been: the question is whether a model can fill in your schema, and that stands
        # whether or not it picked the tool you wanted.
        arguments_check=check_arguments(selected, call.arguments) if selected else None,
        cached=cached,
    )


def cached_text_completer(
    *,
    model: str,
    cache: ResponseCache,
    tool_digest: str,
    pace: float = 0.0,
    timeout: float = backend.DEFAULT_REQUEST_TIMEOUT,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[str], None] | None = None,
    stats: RunStats | None = None,
) -> Callable[[list[dict[str, str]]], tuple[str, Completion]]:
    """A text completer for case synthesis, wrapped in the same cache and retry policy.

    `--init` is a rate-limited free model's worst case: a dozen sequential calls, any of
    which can be throttled. Caching them means an --init that dies on tool seven does not
    re-buy tools one through six, and re-running it after a rate limit finishes the job
    rather than starting it again.

    The generated text is stored in the `arguments` field of a cache entry -- the record
    has a slot for structured data and this is structured data. Slightly off-label, and
    much better than a second cache format for the one command that runs once.
    """
    tally = stats if stats is not None else RunStats()

    def complete(messages: list[dict[str, str]]) -> tuple[str, Completion]:
        key = cache_key(model=model, messages=messages, tool_digest=tool_digest)
        recorded = cache.get(key)
        if recorded is not None:
            tally.cached += 1
            text = recorded.arguments.get("text", "")
            return str(text), Completion(call=ToolCall())

        if pace > 0 and tally.called:
            sleep(pace)

        last: BackendError | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                text, completion = backend.complete_text(
                    model=model, messages=messages, timeout=timeout
                )
                break
            except BackendError as error:
                if not error.retryable or attempt == MAX_ATTEMPTS - 1:
                    raise
                last = error
                delay = _wait_for(error, attempt)
                if on_retry is not None:
                    on_retry(f"{error.message.splitlines()[0]} -- waiting {delay:g}s")
                sleep(delay)
        else:  # pragma: no cover - the loop always breaks or raises
            raise last if last is not None else BackendError("The model call failed.")

        cache.put(
            key,
            CachedCall(
                tool=None,
                arguments={"text": text},
                prompt_tokens=completion.prompt_tokens,
                completion_tokens=completion.completion_tokens,
                cost_usd=completion.cost_usd,
            ),
            model=model,
        )
        tally.called += 1
        tally.cost_usd += completion.cost_usd
        tally.prompt_tokens += completion.prompt_tokens
        tally.completion_tokens += completion.completion_tokens
        return text, completion

    return complete


def run_suite(
    suite: CaseSuite,
    tools: Sequence[ToolSpec],
    *,
    model: str,
    tool_digest: str,
    cache: ResponseCache,
    server: ServerInfo | None = None,
    offline: bool = False,
    max_cost: float | None = None,
    pace: float = 0.0,
    timeout: float = backend.DEFAULT_REQUEST_TIMEOUT,
    complete: Completer | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_case: Callable[[int, int, CaseOutcome], None] | None = None,
    on_retry: Callable[[str], None] | None = None,
) -> RunResult:
    """Run every case in the suite and return the outcomes.

    `complete` and `sleep` are injected so a test can run the whole path -- cache, retries,
    argument checking, ordering -- without a network and without waiting.
    """
    definitions: list[dict[str, Any]] = list(backend.tool_definitions(tuple(tools)))
    by_name = {tool.name: tool for tool in tools}
    if complete is None and not offline:
        complete = _default_completer(model, timeout)

    stats = RunStats()
    outcomes: list[CaseOutcome] = []
    total = len(suite.cases)

    for index, case in enumerate(suite.cases, start=1):
        # Checked before the call rather than after, so the budget is a limit on what gets
        # spent rather than a report on what already was.
        if max_cost is not None and stats.cost_usd > max_cost:
            raise BudgetExceeded(stats.cost_usd, max_cost, len(outcomes), total)
        outcome = run_case(
            case,
            tool_definitions=definitions,
            by_name=by_name,
            server=server,
            model=model,
            tool_digest=tool_digest,
            cache=cache,
            complete=complete,
            offline=offline,
            stats=stats,
            sleep=sleep,
            pace=pace,
            on_retry=on_retry,
        )
        outcomes.append(outcome)
        if on_case is not None:
            on_case(index, total, outcome)

    return RunResult(outcomes=tuple(outcomes), stats=stats)
