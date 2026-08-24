"""Connecting to a server, reading what it advertises, and leaving.

The whole module is read-only by construction: initialize, `list_tools`, disconnect. There
is no code path here that calls a tool, and there must never be one -- people point this at
production servers, and an audit tool that mutates the thing it audits is worse than no
audit tool.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, TextIO, cast

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from mcp_toolgauge.connect.target import HttpTarget, ServerTarget, StdioTarget
from mcp_toolgauge.model import InspectResult, ServerInfo, ToolAnnotations, ToolSpec

DEFAULT_TIMEOUT_SECONDS = 30.0

# Truncation guard: a crashing server can emit a great deal of traceback, and we only need
# enough of the tail to say what went wrong.
_MAX_STDERR_CHARS = 2000


class ConnectionFailed(Exception):
    """We understood the target but could not get a tool list out of it (exit code 3)."""


def _describe_cause(exc: BaseException) -> str:
    """Name the exception a user can act on.

    anyio task groups wrap real failures in an ExceptionGroup, and
    "unhandled errors in a TaskGroup (1 sub-exception)" tells nobody anything. Unwrap to
    the leaves and report those instead.
    """
    if isinstance(exc, BaseExceptionGroup):
        leaves = [_describe_cause(inner) for inner in exc.exceptions]
        unique = list(dict.fromkeys(leaves))
        return "; ".join(unique) if unique else f"{type(exc).__name__}: {exc}"
    return f"{type(exc).__name__}: {exc}"


def _clean_stderr(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= _MAX_STDERR_CHARS:
        return stripped
    return "..." + stripped[-_MAX_STDERR_CHARS:]


def _to_annotations(raw: Any) -> ToolAnnotations | None:
    if raw is None:
        return None
    return ToolAnnotations(
        title=getattr(raw, "title", None),
        read_only_hint=getattr(raw, "read_only_hint", None),
        destructive_hint=getattr(raw, "destructive_hint", None),
        idempotent_hint=getattr(raw, "idempotent_hint", None),
        open_world_hint=getattr(raw, "open_world_hint", None),
    )


def _to_tool_spec(tool: Any) -> ToolSpec:
    """Map an SDK tool onto our own vocabulary."""
    return ToolSpec(
        name=tool.name,
        title=getattr(tool, "title", None),
        description=tool.description,
        input_schema=tool.input_schema or {},
        output_schema=getattr(tool, "output_schema", None),
        annotations=_to_annotations(getattr(tool, "annotations", None)),
    )


def _to_server_info(client: Client) -> ServerInfo:
    info = client.server_info
    return ServerInfo(
        name=getattr(info, "name", None),
        version=getattr(info, "version", None) or None,
        protocol_version=str(client.protocol_version) if client.protocol_version else None,
        instructions=client.instructions,
    )


@asynccontextmanager
async def _open(target: ServerTarget, timeout: float) -> AsyncIterator[Client]:
    """Yield a connected client for either transport, with the server's stderr captured."""
    if isinstance(target, HttpTarget):
        transport = streamable_http_client(target.url)
        async with Client(transport, read_timeout_seconds=timeout) as client:
            yield client
        return

    params = StdioServerParameters(
        command=target.command,
        args=list(target.args),
        env=target.env,
        cwd=target.cwd,
    )
    # A real file, not StringIO: this becomes the subprocess's stderr and so needs an fd.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errlog:
        try:
            async with Client(
                # cast, not a type: ignore -- typeshed types TemporaryFile differently on
                # Windows and POSIX, so an ignore is "unused" on one platform and required
                # on the other. A cast is correct on both.
                stdio_client(params, errlog=cast(TextIO, errlog)),
                read_timeout_seconds=timeout,
            ) as client:
                yield client
        except Exception as exc:
            errlog.seek(0)
            captured = _clean_stderr(errlog.read())
            raise _stdio_failure(target, exc, captured) from exc


def _stdio_failure(target: StdioTarget, exc: Exception, stderr: str) -> ConnectionFailed:
    lines = [f"Could not start or talk to the server: {target.describe()}"]
    if target.cwd is not None:
        lines.append(f"  working directory: {target.cwd}")
    lines.append(f"  cause: {_describe_cause(exc)}")
    if stderr:
        lines.append("  the server wrote this to stderr before failing:")
        lines.extend(f"    {line}" for line in stderr.splitlines())
    else:
        lines.append(
            "  the server produced no stderr output, which usually means the command was "
            "not found or exited immediately."
        )
    return ConnectionFailed("\n".join(lines))


async def inspect_server(
    target: ServerTarget,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> InspectResult:
    """Connect, read the server's identity and tool list, and disconnect.

    Raises `ConnectionFailed` with an actionable message if any of that does not happen
    within `timeout` seconds.
    """
    try:
        async with asyncio.timeout(timeout):
            async with _open(target, timeout) as client:
                listed = await client.list_tools()
                return InspectResult(
                    target=target.describe(),
                    server=_to_server_info(client),
                    tools=tuple(_to_tool_spec(tool) for tool in listed.tools),
                )
    except ConnectionFailed:
        raise
    except TimeoutError as exc:
        raise ConnectionFailed(
            f"The server did not respond within {timeout:g}s: {target.describe()}\n"
            "  Raise the limit with --timeout, or check whether the server is waiting on "
            "something (a prompt, a missing credential, a port already in use)."
        ) from exc
    except Exception as exc:
        raise ConnectionFailed(
            f"Could not talk to the server: {target.describe()}\n"
            f"  cause: {_describe_cause(exc)}"
        ) from exc


def inspect_server_sync(
    target: ServerTarget,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> InspectResult:
    """Synchronous seam for the CLI: Typer commands are sync, the SDK is not."""
    return asyncio.run(inspect_server(target, timeout=timeout))
