"""The runner: cache first, model second, and the retry policy in between.

Everything here stubs the completer, so no test in this file can reach a network even if
the code tried to. That is the point of the seam -- `Never assert on a live model's output.
Mock at the cache boundary.`

The invariant test is `TestCaching::test_a_second_run_makes_no_calls_at_all`. It is the one
that keeps "re-running a green build costs nothing" true.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mcpcheckup.eval.backend import BackendError, Completion, ToolCall, build_messages
from mcpcheckup.eval.cache import CachedCall, CacheMiss, ResponseCache, cache_key
from mcpcheckup.eval.runner import (
    BACKOFF_SECONDS,
    MAX_ATTEMPTS,
    MAX_BACKOFF_SECONDS,
    BudgetExceeded,
    cached_text_completer,
    run_suite,
)
from mcpcheckup.model import CaseKind, CaseSuite, EvalCase, ServerInfo, ToolSpec, tool_digest

TOOLS = (
    ToolSpec(
        name="search_users",
        description="Find people.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
    ToolSpec(name="search_orgs", description="Find organizations.", input_schema={}),
)
DIGEST = tool_digest(TOOLS)


class Stub:
    """A completer that answers from a script and counts how often it was asked."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls = 0
        self.seen: list[list[dict[str, str]]] = []

    def __call__(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> Completion:
        self.calls += 1
        self.seen.append(messages)
        answer = self.answers[min(self.calls - 1, len(self.answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return answer


def picks(tool: str | None, arguments: dict[str, Any] | None = None, cost: float = 0.0):
    return Completion(
        call=ToolCall(tool=tool, arguments=arguments if arguments is not None else {}),
        cost_usd=cost,
    )


def suite(*cases: EvalCase) -> CaseSuite:
    return CaseSuite(target="t", tool_digest=DIGEST, cases=cases or (positive(),))


def positive(name: str = "c1", expected: str = "search_users") -> EvalCase:
    return EvalCase(id=name, kind=CaseKind.POSITIVE, expected=expected, prompt=f"prompt {name}")


def run(cache: ResponseCache, stub: Stub | None = None, **overrides):
    return run_suite(
        overrides.pop("suite", suite()),
        TOOLS,
        model="m",
        tool_digest=DIGEST,
        cache=cache,
        complete=stub,
        sleep=lambda _: None,
        **overrides,
    )


@pytest.fixture
def cache(tmp_path: Path) -> ResponseCache:
    return ResponseCache.load(tmp_path / "cache" / "responses.jsonl")


class TestCaching:
    def test_a_miss_reaches_the_model(self, cache: ResponseCache) -> None:
        stub = Stub(picks("search_users", {"query": "ada"}))

        result = run(cache, stub)

        assert stub.calls == 1
        assert result.stats.called == 1
        assert result.stats.cached == 0

    def test_a_second_run_makes_no_calls_at_all(self, cache: ResponseCache) -> None:
        """The invariant the whole design exists to serve. If this ever fails, re-running a
        green build has started costing money."""
        stub = Stub(picks("search_users", {"query": "ada"}))
        first = run(cache, stub)

        reloaded = ResponseCache.load(cache.path)
        second = run(reloaded, Stub())  # an empty script: any call raises IndexError

        assert stub.calls == 1
        assert second.stats.called == 0
        assert second.stats.cached == len(second.outcomes)
        assert [o.selected for o in second.outcomes] == [o.selected for o in first.outcomes]

    def test_the_second_run_scores_identically(self, cache: ResponseCache) -> None:
        cases = suite(positive("a"), positive("b", "search_orgs"))
        run(cache, Stub(picks("search_users", {"query": "x"}), picks("search_users")), suite=cases)

        replayed = run(ResponseCache.load(cache.path), suite=cases)

        assert [o.correct for o in replayed.outcomes] == [True, False]

    def test_outcomes_are_marked_as_cached(self, cache: ResponseCache) -> None:
        run(cache, Stub(picks("search_users", {"query": "ada"})))

        replayed = run(ResponseCache.load(cache.path))

        assert all(outcome.cached for outcome in replayed.outcomes)

    def test_changing_the_tools_invalidates_the_answer(self, cache: ResponseCache) -> None:
        """Editing a description is the thing you are trying to measure, so the cached
        answer for the old description must not be reused."""
        run(cache, Stub(picks("search_users", {"query": "ada"})))

        stub = Stub(picks("search_orgs"))
        run_suite(
            suite(),
            TOOLS,
            model="m",
            tool_digest="a-different-surface",
            cache=ResponseCache.load(cache.path),
            complete=stub,
            sleep=lambda _: None,
        )

        assert stub.calls == 1


class TestOffline:
    def test_a_hit_is_served_without_a_completer(self, cache: ResponseCache) -> None:
        run(cache, Stub(picks("search_users", {"query": "ada"})))

        replayed = run(ResponseCache.load(cache.path), offline=True)

        assert replayed.outcomes[0].selected == "search_users"

    def test_a_miss_is_an_error_that_says_what_to_do(self, cache: ResponseCache) -> None:
        with pytest.raises(CacheMiss) as caught:
            run(cache, offline=True)

        assert "c1" in str(caught.value)
        assert "--offline" in str(caught.value)

    def test_offline_never_builds_a_completer(self, cache: ResponseCache) -> None:
        """No litellm import, no credentials, no network -- that is what makes an offline
        replay runnable in CI on a base install."""
        run(cache, Stub(picks("search_users", {"query": "ada"})))

        replayed = run_suite(
            suite(),
            TOOLS,
            model="m",
            tool_digest=DIGEST,
            cache=ResponseCache.load(cache.path),
            offline=True,
        )

        assert replayed.stats.called == 0


class TestOutcomes:
    def test_arguments_are_checked_against_the_tool_that_was_called(
        self, cache: ResponseCache
    ) -> None:
        """Not against the one that should have been. The question is whether a model can
        fill in your schema, and that stands whichever tool it picked."""
        stub = Stub(picks("search_users", {}))
        result = run(cache, stub, suite=suite(positive("c1", "search_orgs")))

        check = result.outcomes[0].arguments_check
        assert check is not None
        assert check.missing_required == ("query",)

    def test_calling_nothing_leaves_the_check_unset(self, cache: ResponseCache) -> None:
        result = run(cache, Stub(picks(None)))

        assert result.outcomes[0].arguments_check is None
        assert result.outcomes[0].arguments_ok is None

    def test_an_unknown_tool_name_is_recorded_and_not_checked(self, cache: ResponseCache) -> None:
        result = run(cache, Stub(picks("invented_tool", {"x": 1})))

        assert result.outcomes[0].selected == "invented_tool"
        assert result.outcomes[0].arguments_check is None
        assert not result.outcomes[0].correct

    def test_outcomes_come_back_in_suite_order(self, cache: ResponseCache) -> None:
        cases = suite(positive("a"), positive("b"), positive("c"))

        result = run(cache, Stub(picks("search_users", {"query": "x"})), suite=cases)

        assert [outcome.case.id for outcome in result.outcomes] == ["a", "b", "c"]

    def test_the_server_instructions_reach_the_model(self, cache: ResponseCache) -> None:
        """A real client passes them along, so an author's instructions are part of what
        gets measured."""
        stub = Stub(picks("search_users", {"query": "x"}))
        run(cache, stub, server=ServerInfo(name="s", instructions="Prefer people."))

        assert "Prefer people." in stub.seen[0][0]["content"]

    def test_progress_is_reported_per_case(self, cache: ResponseCache) -> None:
        seen: list[tuple[int, int]] = []
        run(
            cache,
            Stub(picks("search_users", {"query": "x"})),
            suite=suite(positive("a"), positive("b")),
            on_case=lambda index, total, _: seen.append((index, total)),
        )

        assert seen == [(1, 2), (2, 2)]


class TestRetries:
    def rate_limited(self, retry_after: float | None = None) -> BackendError:
        return BackendError("Rate limited by the provider", retryable=True, retry_after=retry_after)

    def test_a_retryable_failure_is_retried(self, cache: ResponseCache) -> None:
        stub = Stub(self.rate_limited(), picks("search_users", {"query": "x"}))

        result = run(cache, stub)

        assert stub.calls == 2
        assert result.outcomes[0].correct

    def test_it_gives_up_eventually(self, cache: ResponseCache) -> None:
        stub = Stub(self.rate_limited())

        with pytest.raises(BackendError):
            run(cache, stub)

        assert stub.calls == MAX_ATTEMPTS

    def test_a_permanent_failure_is_not_retried(self, cache: ResponseCache) -> None:
        """No amount of waiting improves a bad API key."""
        stub = Stub(BackendError("The provider rejected our credentials"))

        with pytest.raises(BackendError):
            run(cache, stub)

        assert stub.calls == 1

    def test_the_provider_is_obeyed_when_it_says_how_long(self, cache: ResponseCache) -> None:
        slept: list[float] = []
        stub = Stub(self.rate_limited(retry_after=2.5), picks("search_users", {"query": "x"}))

        run_suite(
            suite(),
            TOOLS,
            model="m",
            tool_digest=DIGEST,
            cache=cache,
            complete=stub,
            sleep=slept.append,
        )

        assert slept == [2.5]

    def test_an_absurd_retry_after_is_capped(self, cache: ResponseCache) -> None:
        """Some providers send an interval measured in hours. That is a reason to stop, not
        a reason to sleep."""
        slept: list[float] = []
        stub = Stub(self.rate_limited(retry_after=99999), picks("search_users", {"query": "x"}))

        run_suite(
            suite(),
            TOOLS,
            model="m",
            tool_digest=DIGEST,
            cache=cache,
            complete=stub,
            sleep=slept.append,
        )

        assert slept == [MAX_BACKOFF_SECONDS]

    def test_backoff_grows_when_the_provider_says_nothing(self, cache: ResponseCache) -> None:
        slept: list[float] = []
        stub = Stub(self.rate_limited(), self.rate_limited(), picks("search_users", {"query": "x"}))

        run_suite(
            suite(),
            TOOLS,
            model="m",
            tool_digest=DIGEST,
            cache=cache,
            complete=stub,
            sleep=slept.append,
        )

        assert slept == list(BACKOFF_SECONDS[:2])

    def test_a_retry_is_announced(self, cache: ResponseCache) -> None:
        notes: list[str] = []
        stub = Stub(self.rate_limited(), picks("search_users", {"query": "x"}))

        run(cache, stub, on_retry=notes.append)

        assert len(notes) == 1
        assert "waiting" in notes[0]


class TestPacing:
    def test_no_wait_before_the_first_call(self, cache: ResponseCache) -> None:
        slept: list[float] = []
        run_suite(
            suite(),
            TOOLS,
            model="m",
            tool_digest=DIGEST,
            cache=cache,
            complete=Stub(picks("search_users", {"query": "x"})),
            sleep=slept.append,
            pace=3.0,
        )

        assert slept == []

    def test_a_wait_between_calls(self, cache: ResponseCache) -> None:
        slept: list[float] = []
        run_suite(
            suite(positive("a"), positive("b"), positive("c")),
            TOOLS,
            model="m",
            tool_digest=DIGEST,
            cache=cache,
            complete=Stub(picks("search_users", {"query": "x"})),
            sleep=slept.append,
            pace=3.0,
        )

        assert slept == [3.0, 3.0]

    def test_cached_cases_are_not_paced(self, cache: ResponseCache) -> None:
        """Pacing exists to be kind to a rate limiter. A cache hit does not touch one."""
        cases = suite(positive("a"), positive("b"))
        run(cache, Stub(picks("search_users", {"query": "x"})), suite=cases)

        slept: list[float] = []
        run_suite(
            cases,
            TOOLS,
            model="m",
            tool_digest=DIGEST,
            cache=ResponseCache.load(cache.path),
            complete=Stub(),
            sleep=slept.append,
            pace=3.0,
        )

        assert slept == []


class TestBudget:
    def test_a_run_under_budget_finishes(self, cache: ResponseCache) -> None:
        result = run(
            cache,
            Stub(picks("search_users", {"query": "x"}, cost=0.01)),
            suite=suite(positive("a"), positive("b")),
            max_cost=1.0,
        )

        assert len(result.outcomes) == 2

    def test_a_run_over_budget_stops(self, cache: ResponseCache) -> None:
        with pytest.raises(BudgetExceeded) as caught:
            run(
                cache,
                Stub(picks("search_users", {"query": "x"}, cost=0.5)),
                suite=suite(positive("a"), positive("b"), positive("c")),
                max_cost=0.6,
            )

        assert caught.value.completed == 2
        assert caught.value.total == 3

    def test_the_message_says_the_work_is_not_lost(self, cache: ResponseCache) -> None:
        with pytest.raises(BudgetExceeded) as caught:
            run(
                cache,
                Stub(picks("search_users", {"query": "x"}, cost=1.0)),
                suite=suite(positive("a"), positive("b")),
                max_cost=0.5,
            )

        assert "cached" in str(caught.value)
        assert "--max-cost" in str(caught.value)

    def test_the_calls_already_made_really_are_kept(self, cache: ResponseCache) -> None:
        with pytest.raises(BudgetExceeded):
            run(
                cache,
                Stub(picks("search_users", {"query": "x"}, cost=1.0)),
                suite=suite(positive("a"), positive("b")),
                max_cost=0.5,
            )

        assert len(ResponseCache.load(cache.path)) == 1


class TestTextCompleter:
    """Synthesis goes through the same cache, for the same reason."""

    def test_a_second_call_is_served_from_the_cache(
        self, cache: ResponseCache, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}

        def fake(*, model: str, messages: list[dict[str, str]], timeout: float):
            calls["n"] += 1
            return "generated text", Completion(call=ToolCall())

        monkeypatch.setattr("mcpcheckup.eval.backend.complete_text", fake)
        messages = [{"role": "user", "content": "write cases"}]

        first = cached_text_completer(model="m", cache=cache, tool_digest=DIGEST)(messages)
        reloaded = ResponseCache.load(cache.path)
        second = cached_text_completer(model="m", cache=reloaded, tool_digest=DIGEST)(messages)

        assert calls["n"] == 1
        assert first[0] == second[0] == "generated text"

    def test_a_rate_limit_is_retried(
        self, cache: ResponseCache, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempts = {"n": 0}

        def flaky(*, model: str, messages: list[dict[str, str]], timeout: float):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise BackendError("Rate limited", retryable=True)
            return "ok", Completion(call=ToolCall())

        monkeypatch.setattr("mcpcheckup.eval.backend.complete_text", flaky)

        complete = cached_text_completer(
            model="m", cache=cache, tool_digest=DIGEST, sleep=lambda _: None
        )
        text, _ = complete([{"role": "user", "content": "go"}])

        assert attempts["n"] == 2
        assert text == "ok"


class TestNoToolInvocation:
    def test_the_runner_never_touches_the_server(self, cache: ResponseCache) -> None:
        """The read-only invariant. The runner is handed `ToolSpec`s, which are inert data;
        there is no client here to call anything with."""
        stub = Stub(picks("search_users", {"query": "x"}))
        result = run(cache, stub)

        assert result.outcomes[0].selected == "search_users"
        assert all(isinstance(spec, ToolSpec) for spec in TOOLS)


class TestCachedCallShape:
    def test_a_recorded_answer_is_filed_under_the_key_the_runner_will_look_up(
        self, cache: ResponseCache
    ) -> None:
        """Derived here the same way the runner derives it, so the two cannot drift: if the
        runner ever changed how it builds messages, this would stop finding the entry."""
        run(cache, Stub(picks("search_users", {"query": "x"}, cost=0.25)))

        key = cache_key(
            model="m", messages=build_messages("prompt c1", None), tool_digest=DIGEST
        )
        stored = ResponseCache.load(cache.path).get(key)

        assert stored == CachedCall(tool="search_users", arguments={"query": "x"}, cost_usd=0.25)
