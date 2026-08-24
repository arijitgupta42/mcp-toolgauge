"""The response cache. Every model call in this codebase goes through it.

The invariant it exists to serve: **a second run of an unchanged suite makes zero network
calls and costs nothing.** That is what lets scores be re-checked on every branch without
anybody thinking about the bill, and it is asserted by a test rather than left to habit.

The key is `hash(model, messages, tool_digest)`. All three belong in it. The model, because
two models are two different answers. The messages, because that is the question. And the
tool digest, because the *other* tools on the server are part of the question too -- adding
a competitor changes what the right answer looks like, and a cache that ignored that would
serve yesterday's answer to today's server.

Stored on disk as JSON Lines: one object per line, last occurrence wins on read, appended
on write. That shape is chosen for the fixture caches, which are committed and reviewed --
one file diffs, and a directory of a hundred and twenty hashes does not. Append-only also
means a run interrupted halfway keeps every call it already paid for.

What is stored is normalised -- the tool, the arguments, the token counts -- not the raw
provider response. Smaller, provider-neutral, readable in a diff, and pleasant to
hand-write in a test, which is where every test in this project mocks.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcpcheckup.eval.backend import Completion, ToolCall

CACHE_DIRNAME = ".mcpcheckup-cache"
CACHE_FILENAME = "responses.jsonl"

_KEY_LENGTH = 32


class CacheMiss(Exception):
    """`--offline` was asked for an answer the cache does not have.

    Its own exception because it is a usage error with an obvious fix, not a failure: the
    suite grew, or the tools changed, and somebody needs to do a recording run.
    """


def cache_path(base: Path) -> Path:
    """Where the cache for a case file at `base` lives."""
    return base.parent / CACHE_DIRNAME / CACHE_FILENAME


def cache_key(*, model: str, messages: list[dict[str, str]], tool_digest: str) -> str:
    """The content address of one question."""
    payload = json.dumps(
        {"model": model, "messages": messages, "tools": tool_digest},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:_KEY_LENGTH]


@dataclass(frozen=True)
class CachedCall:
    """One recorded answer."""

    tool: str | None
    arguments: dict[str, Any]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    @classmethod
    def from_completion(cls, completion: Completion) -> CachedCall:
        return cls(
            tool=completion.call.tool,
            arguments=completion.call.arguments,
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
            cost_usd=completion.cost_usd,
        )

    def as_tool_call(self) -> ToolCall:
        return ToolCall(tool=self.tool, arguments=dict(self.arguments))


class ResponseCache:
    """A read-through cache over a JSONL file.

    Loaded once into memory. These files hold hundreds of entries, not millions, and an
    in-memory dict means a run's cache lookups cost nothing and the file is opened for
    writing only when there is genuinely something new to write.
    """

    def __init__(self, path: Path, entries: dict[str, CachedCall] | None = None) -> None:
        self.path = path
        self._entries: dict[str, CachedCall] = entries or {}
        self.hits = 0
        self.writes = 0

    @classmethod
    def load(cls, path: Path) -> ResponseCache:
        """Read a cache file, tolerating a truncated final line.

        A run killed mid-write leaves a partial line. Skipping it silently is right: the
        entry was never confirmed, and refusing to start because of it would throw away
        every other answer in the file over one that was already lost.
        """
        entries: dict[str, CachedCall] = {}
        if path.is_file():
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    record = _parse(line)
                    if record is not None:
                        entries[record[0]] = record[1]
        return cls(path, entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def get(self, key: str) -> CachedCall | None:
        found = self._entries.get(key)
        if found is not None:
            self.hits += 1
        return found

    def put(self, key: str, call: CachedCall, *, model: str) -> None:
        """Record an answer, in memory and on disk.

        Written through immediately rather than flushed at the end, so a run that dies on
        case ninety keeps the eighty-nine calls it already made.
        """
        self._entries[key] = call
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(_serialise(key, call, model=model) + "\n")
        self.writes += 1


def _serialise(key: str, call: CachedCall, *, model: str) -> str:
    """One cache line. Sorted keys, so a committed cache diffs on content, not on ordering."""
    return json.dumps(
        {
            "key": key,
            "model": model,
            "tool": call.tool,
            "arguments": call.arguments,
            "prompt_tokens": call.prompt_tokens,
            "completion_tokens": call.completion_tokens,
            "cost_usd": call.cost_usd,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _parse(line: str) -> tuple[str, CachedCall] | None:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        record = json.loads(stripped)
    except ValueError:
        return None
    if not isinstance(record, dict):
        return None
    key = record.get("key")
    if not isinstance(key, str):
        return None
    arguments = record.get("arguments")
    tool = record.get("tool")
    return key, CachedCall(
        tool=tool if isinstance(tool, str) else None,
        arguments=arguments if isinstance(arguments, dict) else {},
        prompt_tokens=int(record.get("prompt_tokens") or 0),
        completion_tokens=int(record.get("completion_tokens") or 0),
        cost_usd=float(record.get("cost_usd") or 0.0),
    )
