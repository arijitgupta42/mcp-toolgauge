"""The one place a model gets called, and the only place LiteLLM is imported.

The import is inside the function rather than at module scope, and that is load-bearing
twice over. LiteLLM is a large install, so it lives in the `eval` extra rather than the
base package -- `uvx mcp-doctor lint` is the command that runs on every pull request and it
must stay fast to install. And `mcp-doctor eval --offline`, which replays a recorded cache
and calls nothing, has to work on a base install; a module-level import would break that
for no reason.

Everything above this module speaks in `ToolCall` and `Completion`. Nothing else in the
codebase knows what a provider response looks like, which is what makes the runner
testable without a network and what would make swapping the backend a one-file change.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from mcp_doctor.model import ServerInfo, ToolSpec

# A free model, so that `mcp-doctor eval` costs a new user nothing on the first run. Pass
# --model to use anything else LiteLLM can reach.
#
# OpenRouter's free roster turns over, and a retired model is the one way this default can
# rot. When it does, `eval` fails with a message naming --model rather than a stack trace,
# and CI is unaffected because it replays a committed cache and never reaches the network.
DEFAULT_MODEL = "openrouter/nvidia/nemotron-3.5-lightning:free"

DEFAULT_REQUEST_TIMEOUT = 120.0

# The instruction the model is answering under. Deliberately plain: the point is to measure
# the server's own tool descriptions, so anything clever here would be measuring the
# prompt instead. The one thing it must do is make *not* calling a tool a legitimate
# answer, or every abstain case is lost before it starts.
SYSTEM_PROMPT = (
    "You are an assistant with access to the tools listed below. "
    "When one of them fits the user's request, call it. "
    "When none of them fits, answer in plain text and call nothing. "
    "Never guess at a tool that is only approximately right."
)


class BackendUnavailable(Exception):
    """No usable model backend -- LiteLLM is not installed, or no credentials are set.

    Always names the command that fixes it. This is the first error a new user hits, and
    "ModuleNotFoundError: litellm" is not an answer to it.
    """


class BackendError(Exception):
    """A model call failed.

    `retryable` distinguishes "wait and it will work" -- rate limits, timeouts, a dropped
    connection -- from "this will fail identically forever", so the runner can back off
    from one and stop on the other instead of hammering a bad API key for ten minutes.

    A plain exception rather than a frozen dataclass: dataclass-generated `__init__` never
    calls `Exception.__init__`, which leaves `args` empty and makes the exception behave
    oddly under `raise ... from` and pickling. Not worth the three lines it saves.
    """

    def __init__(
        self, message: str, retryable: bool = False, retry_after: float | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.retry_after = retry_after


@dataclass(frozen=True)
class ToolCall:
    """What the model decided to do. `tool` of None means it called nothing."""

    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Completion:
    call: ToolCall
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


def tool_definitions(tools: tuple[ToolSpec, ...]) -> list[dict[str, Any]]:
    """The server's tools in the shape a chat model expects them.

    This is the whole experiment: the model sees the author's real names, real
    descriptions, and real schemas, exactly as a client would hand them over. Nothing is
    rewritten or improved on the way through -- a description that does not work here is a
    description that does not work in production either.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.input_schema or {"type": "object", "properties": {}},
            },
        }
        for tool in tools
    ]


def build_messages(prompt: str, server: ServerInfo | None = None) -> list[dict[str, str]]:
    """The conversation for one case: a system instruction and the user's utterance.

    A server's own `instructions` string is appended to the system prompt when it has one,
    because a real client passes it along too. That means an author's instructions text is
    part of what gets measured -- which is right, since it is part of what the model reads
    before choosing.
    """
    system = SYSTEM_PROMPT
    if server is not None and server.instructions:
        system = f"{system}\n\nAbout this server:\n{server.instructions}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]


def _require_litellm() -> Any:
    try:
        import litellm
    except ImportError as exc:  # pragma: no cover - exercised by the packaging, not tests
        raise BackendUnavailable(
            "Calling a model needs LiteLLM, which is not installed.\n"
            "  Install it with:  uv pip install 'mcp-doctor[eval]'\n"
            "  Or run against a recorded cache with:  mcp-doctor eval <target> --offline"
        ) from exc

    # LiteLLM retries and falls back on its own by default. Both are wrong here: a run has
    # to be reproducible and cheap, and a silent fallback to another model would put two
    # models' answers in one score. Retries are the runner's job, where the pacing is.
    litellm.drop_params = True
    litellm.suppress_debug_info = True
    return litellm


def _extract(response: Any) -> ToolCall:
    """Pull the tool choice out of a provider response.

    Unparseable arguments degrade to `{}` rather than raising. The argument checker then
    reports the required parameters as missing, which is both true and the more useful
    reading -- a call whose arguments did not survive JSON is a call that would have failed.
    """
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ToolCall()
    message = getattr(choices[0], "message", None)
    calls = getattr(message, "tool_calls", None) or []
    if not calls:
        return ToolCall()

    function = getattr(calls[0], "function", None)
    name = getattr(function, "name", None)
    if not name:
        return ToolCall()

    raw = getattr(function, "arguments", None) or "{}"
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        parsed = {}
    return ToolCall(tool=str(name), arguments=parsed if isinstance(parsed, dict) else {})


def _usage(response: Any) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    return int(prompt), int(completion)


def _cost(litellm: Any, response: Any) -> float:
    """What the call cost, or 0.0 when LiteLLM has no price for the model.

    An unknown price is not an error. Free models and self-hosted endpoints are both
    legitimate, and refusing to run because a cost cannot be computed would be absurd.
    """
    try:
        return float(litellm.completion_cost(completion_response=response) or 0.0)
    except Exception:
        return 0.0


def _translate(litellm: Any, exc: Exception) -> BackendError:
    """Map a provider failure onto our two-state vocabulary."""
    name = type(exc).__name__
    if isinstance(exc, getattr(litellm, "AuthenticationError", ())):
        return BackendError(
            f"The model provider rejected our credentials ({name}).\n"
            "  Set the API key for your provider, e.g. OPENROUTER_API_KEY, and try again."
        )
    if isinstance(exc, getattr(litellm, "RateLimitError", ())):
        return BackendError(
            f"Rate limited by the model provider ({name}): {exc}",
            retryable=True,
            retry_after=_retry_after(exc),
        )
    transient = tuple(
        cls
        for cls in (
            getattr(litellm, "Timeout", None),
            getattr(litellm, "APIConnectionError", None),
            getattr(litellm, "ServiceUnavailableError", None),
            getattr(litellm, "InternalServerError", None),
        )
        if isinstance(cls, type)
    )
    if transient and isinstance(exc, transient):
        return BackendError(f"Temporary failure from the model provider ({name}): {exc}", True)
    return BackendError(f"The model call failed ({name}): {exc}")


def _retry_after(exc: Exception) -> float | None:
    value = getattr(exc, "retry_after", None)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def credentials_present(model: str) -> bool:
    """A cheap guess at whether a key is set, for a message before the first call.

    Only a guess -- LiteLLM resolves credentials from more places than environment
    variables. It is used to say something useful up front, never to refuse a run.
    """
    provider = model.split("/", 1)[0].upper().replace("-", "_")
    return bool(os.environ.get(f"{provider}_API_KEY") or os.environ.get("LITELLM_API_KEY"))


def complete(
    *,
    model: str,
    messages: list[dict[str, str]],
    tools: list[dict[str, Any]],
    timeout: float = DEFAULT_REQUEST_TIMEOUT,
) -> Completion:
    """One tool-selection call, at temperature 0.

    Temperature is fixed rather than exposed. A configurable temperature would make two
    runs of the same suite incomparable, and comparability between runs is the entire
    reason the cases are a committed file.
    """
    litellm = _require_litellm()
    try:
        response = litellm.completion(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0,
            timeout=timeout,
            num_retries=0,
        )
    except Exception as exc:
        raise _translate(litellm, exc) from exc

    prompt_tokens, completion_tokens = _usage(response)
    return Completion(
        call=_extract(response),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=_cost(litellm, response),
    )


def complete_text(
    *,
    model: str,
    messages: list[dict[str, str]],
    timeout: float = DEFAULT_REQUEST_TIMEOUT,
) -> tuple[str, Completion]:
    """A plain completion with no tools attached. Used only by case synthesis.

    Synthesis is writing prose, not selecting a tool, so routing it through the tool-calling
    path would be asking a model to fill in a schema when what is wanted is a list of
    sentences -- more to go wrong, and worse output from the small models this defaults to.

    Temperature is 0 here too, so that `--init` twice over an unchanged server proposes the
    same cases rather than a fresh set nobody asked for.
    """
    litellm = _require_litellm()
    try:
        response = litellm.completion(
            model=model,
            messages=messages,
            temperature=0,
            timeout=timeout,
            num_retries=0,
        )
    except Exception as exc:
        raise _translate(litellm, exc) from exc

    choices = getattr(response, "choices", None) or []
    message = getattr(choices[0], "message", None) if choices else None
    content = getattr(message, "content", None) or ""
    prompt_tokens, completion_tokens = _usage(response)
    return str(content), Completion(
        call=ToolCall(),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=_cost(litellm, response),
    )
