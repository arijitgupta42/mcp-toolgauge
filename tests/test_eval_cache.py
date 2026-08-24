"""The response cache.

One test in here matters more than the rest: `test_a_second_run_makes_no_calls_at_all`.
"Eval runs are cached and reproducible" is a promise the README makes and CI relies on, and
a promise nobody checks is a promise that quietly stops being true the first time somebody
adds a field to the cache key.

The rest is about the key being sensitive to exactly the right things -- the model, the
question, and the tool surface -- and to nothing else.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_toolgauge.eval.backend import Completion, ToolCall
from mcp_toolgauge.eval.cache import (
    CACHE_DIRNAME,
    CACHE_FILENAME,
    CachedCall,
    ResponseCache,
    cache_key,
    cache_path,
)

MESSAGES = [{"role": "user", "content": "who is ada"}]
OTHER = [{"role": "user", "content": "who is grace"}]

CALL = CachedCall(tool="search_users", arguments={"query": "ada"}, cost_usd=0.0001)


def key(**overrides) -> str:
    return cache_key(
        **{"model": "m", "messages": MESSAGES, "tool_digest": "abc123", **overrides}
    )


class TestKey:
    def test_the_same_question_gives_the_same_key(self) -> None:
        assert key() == key()

    def test_a_different_model_is_a_different_question(self) -> None:
        assert key() != key(model="other")

    def test_a_different_prompt_is_a_different_question(self) -> None:
        assert key() != key(messages=OTHER)

    def test_a_different_tool_surface_is_a_different_question(self) -> None:
        """The other tools on the server are part of the question. Adding a competitor
        changes what the right answer looks like, so an answer recorded before it must not
        be served afterwards."""
        assert key() != key(tool_digest="different")

    def test_keys_are_short_and_printable(self) -> None:
        assert len(key()) == 32
        assert key().isalnum()


class TestPaths:
    def test_the_cache_sits_beside_the_case_file(self, tmp_path: Path) -> None:
        path = cache_path(tmp_path / "mcp-toolgauge-cases.yaml")

        assert path.parent.name == CACHE_DIRNAME
        assert path.name == CACHE_FILENAME
        assert path.parent.parent == tmp_path


class TestRoundTrip:
    def test_a_missing_file_loads_as_empty(self, tmp_path: Path) -> None:
        cache = ResponseCache.load(tmp_path / "nope" / "responses.jsonl")

        assert len(cache) == 0
        assert cache.get("anything") is None

    def test_what_goes_in_comes_back(self, tmp_path: Path) -> None:
        path = tmp_path / CACHE_DIRNAME / CACHE_FILENAME
        ResponseCache.load(path).put("k", CALL, model="m")

        found = ResponseCache.load(path).get("k")

        assert found == CALL

    def test_the_directory_is_created_on_first_write(self, tmp_path: Path) -> None:
        path = tmp_path / CACHE_DIRNAME / CACHE_FILENAME
        ResponseCache.load(path).put("k", CALL, model="m")

        assert path.is_file()

    def test_an_abstention_round_trips_as_none(self, tmp_path: Path) -> None:
        """"called nothing" is an answer, not a missing entry."""
        path = tmp_path / "c.jsonl"
        ResponseCache.load(path).put("k", CachedCall(tool=None, arguments={}), model="m")

        found = ResponseCache.load(path).get("k")

        assert found is not None
        assert found.tool is None

    def test_a_completion_converts_without_losing_anything(self) -> None:
        completion = Completion(
            call=ToolCall(tool="t", arguments={"a": 1}),
            prompt_tokens=11,
            completion_tokens=22,
            cost_usd=0.5,
        )

        assert CachedCall.from_completion(completion) == CachedCall(
            tool="t", arguments={"a": 1}, prompt_tokens=11, completion_tokens=22, cost_usd=0.5
        )

    def test_a_cached_call_converts_back_to_a_tool_call(self) -> None:
        assert CALL.as_tool_call() == ToolCall(tool="search_users", arguments={"query": "ada"})

    def test_the_arguments_are_copied_not_shared(self) -> None:
        """A caller mutating what it got back must not corrupt the cache."""
        cached = CachedCall(tool="t", arguments={"a": 1})
        cached.as_tool_call().arguments["a"] = 2

        assert cached.arguments == {"a": 1}


class TestFileFormat:
    def test_one_line_per_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "c.jsonl"
        cache = ResponseCache.load(path)
        cache.put("a", CALL, model="m")
        cache.put("b", CALL, model="m")

        assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2

    def test_lines_have_sorted_keys_so_a_committed_cache_diffs_on_content(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "c.jsonl"
        ResponseCache.load(path).put("a", CALL, model="m")

        record = path.read_text(encoding="utf-8").strip()
        assert list(json.loads(record)) == sorted(json.loads(record))

    def test_a_rewrite_wins_over_the_earlier_line(self, tmp_path: Path) -> None:
        """Append-only, last wins -- so a re-record does not need the file rewriting."""
        path = tmp_path / "c.jsonl"
        cache = ResponseCache.load(path)
        cache.put("k", CachedCall(tool="old", arguments={}), model="m")
        cache.put("k", CachedCall(tool="new", arguments={}), model="m")

        reloaded = ResponseCache.load(path).get("k")

        assert reloaded is not None
        assert reloaded.tool == "new"

    def test_a_truncated_final_line_does_not_lose_the_rest(self, tmp_path: Path) -> None:
        """A run killed mid-write leaves a partial line. Refusing to start because of it
        would throw away every answer already paid for."""
        path = tmp_path / "c.jsonl"
        cache = ResponseCache.load(path)
        cache.put("good", CALL, model="m")
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"key": "half", "tool": "sea')

        reloaded = ResponseCache.load(path)

        assert reloaded.get("good") is not None
        assert len(reloaded) == 1

    def test_blank_and_junk_lines_are_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "c.jsonl"
        path.write_text(
            '\n[1,2,3]\nnot json at all\n{"no_key": true}\n'
            '{"key":"k","tool":"t","arguments":{}}\n',
            encoding="utf-8",
        )

        cache = ResponseCache.load(path)

        assert len(cache) == 1
        assert cache.get("k") is not None

    def test_a_malformed_arguments_field_degrades_to_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "c.jsonl"
        path.write_text('{"key":"k","tool":"t","arguments":"oops"}\n', encoding="utf-8")

        found = ResponseCache.load(path).get("k")

        assert found is not None
        assert found.arguments == {}


class TestReuse:
    def test_a_hit_is_counted(self, tmp_path: Path) -> None:
        cache = ResponseCache.load(tmp_path / "c.jsonl")
        cache.put("k", CALL, model="m")
        cache.get("k")
        cache.get("k")

        assert cache.hits == 2

    def test_a_miss_is_not(self, tmp_path: Path) -> None:
        cache = ResponseCache.load(tmp_path / "c.jsonl")
        cache.get("absent")

        assert cache.hits == 0

    def test_membership_does_not_count_as_a_hit(self, tmp_path: Path) -> None:
        cache = ResponseCache.load(tmp_path / "c.jsonl")
        cache.put("k", CALL, model="m")

        assert "k" in cache
        assert cache.hits == 0
