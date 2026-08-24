"""Turning whatever the user typed into something we can actually connect to.

The resolution order is deliberate. Most people pointing mcp-toolgauge at a project already
have an `.mcp.json` there, because that is what their MCP client reads. Honouring it means
`mcp-toolgauge inspect .` works with no flags in a directory that already works elsewhere --
and that matters, because every flag someone has to discover is a person who never adds
the badge.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

# Searched in order. The first that exists wins, whether or not it parses -- a broken
# `.mcp.json` should produce a parse error, not a silent fallback to a different file.
MANIFEST_NAMES: tuple[str, ...] = (
    ".mcp.json",
    "mcp.json",
    ".vscode/mcp.json",
    "claude_desktop_config.json",
)

# Checked in order when a directory has no manifest at all.
CONVENTION_ENTRYPOINTS: tuple[str, ...] = ("server.py", "main.py", "__main__.py", "app.py")

_HTTP_TYPES = frozenset({"http", "sse", "streamable-http", "streamable_http"})


class TargetResolutionError(Exception):
    """The target could not be turned into a connectable server.

    This is a usage error (exit code 2), not a connection failure -- we never got as far as
    trying to connect.
    """


class StdioTarget(BaseModel):
    """A server we launch ourselves and speak to over stdin/stdout."""

    model_config = ConfigDict(frozen=True)

    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    cwd: Path | None = None

    def describe(self) -> str:
        return shlex.join([self.command, *self.args])


class HttpTarget(BaseModel):
    """A server already running somewhere, reached over Streamable HTTP."""

    model_config = ConfigDict(frozen=True)

    url: str
    headers: dict[str, str] | None = None

    def describe(self) -> str:
        return self.url


ServerTarget = StdioTarget | HttpTarget


def _looks_like_url(raw: str) -> bool:
    return raw.startswith(("http://", "https://"))


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TargetResolutionError(f"{path} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise TargetResolutionError(f"Could not read {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise TargetResolutionError(
            f"{path} should contain a JSON object, got {type(data).__name__}."
        )
    return data


def _servers_in(manifest: dict[str, Any], path: Path) -> dict[str, Any]:
    """Pull the server table out of a manifest, accepting both dialects in the wild."""
    for key in ("mcpServers", "servers"):
        table = manifest.get(key)
        if isinstance(table, dict):
            return table
    raise TargetResolutionError(
        f"{path} has no 'mcpServers' or 'servers' entry. "
        "Add one, or point mcp-toolgauge at the server directly with --command."
    )


def _pick_server(servers: dict[str, Any], path: Path, requested: str | None) -> tuple[str, Any]:
    if not servers:
        raise TargetResolutionError(f"{path} declares no servers.")

    if requested is not None:
        if requested not in servers:
            available = ", ".join(sorted(servers))
            raise TargetResolutionError(
                f"{path} has no server named {requested!r}. Available: {available}."
            )
        return requested, servers[requested]

    if len(servers) > 1:
        available = ", ".join(sorted(servers))
        raise TargetResolutionError(
            f"{path} declares {len(servers)} servers, so mcp-toolgauge cannot guess which one "
            f"you mean. Re-run with --server NAME. Available: {available}."
        )

    return next(iter(servers.items()))


def _entry_to_target(entry: Any, name: str, path: Path) -> ServerTarget:
    """Convert one manifest entry into a target, whichever transport it declares."""
    if not isinstance(entry, dict):
        raise TargetResolutionError(
            f"Server {name!r} in {path} should be a JSON object, got {type(entry).__name__}."
        )

    declared_type = str(entry.get("type", "")).lower()
    url = entry.get("url")

    if declared_type in _HTTP_TYPES or (url and not entry.get("command")):
        if not isinstance(url, str) or not url:
            raise TargetResolutionError(
                f"Server {name!r} in {path} declares an HTTP transport but has no 'url'."
            )
        headers = entry.get("headers")
        return HttpTarget(url=url, headers=headers if isinstance(headers, dict) else None)

    command = entry.get("command")
    if not isinstance(command, str) or not command:
        raise TargetResolutionError(
            f"Server {name!r} in {path} has no 'command' and no 'url', so there is nothing "
            "to connect to."
        )

    raw_args = entry.get("args", [])
    if not isinstance(raw_args, list):
        raise TargetResolutionError(f"Server {name!r} in {path} has an 'args' that is not a list.")

    env = entry.get("env")
    # Relative paths in a manifest are relative to the manifest, which is how every other
    # MCP client reads them.
    cwd = Path(entry["cwd"]) if isinstance(entry.get("cwd"), str) else path.parent

    return StdioTarget(
        command=command,
        args=tuple(str(arg) for arg in raw_args),
        env={str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else None,
        cwd=cwd,
    )


def _find_manifest(directory: Path) -> Path | None:
    for name in MANIFEST_NAMES:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def _resolve_directory(directory: Path, server: str | None) -> ServerTarget:
    manifest_path = _find_manifest(directory)
    if manifest_path is not None:
        manifest = _load_manifest(manifest_path)
        name, entry = _pick_server(_servers_in(manifest, manifest_path), manifest_path, server)
        return _entry_to_target(entry, name, manifest_path)

    for entrypoint in CONVENTION_ENTRYPOINTS:
        candidate = directory / entrypoint
        if candidate.is_file():
            # sys.executable, not "python": the fixture servers and most local projects
            # depend on the interpreter that mcp-toolgauge itself is running under.
            return StdioTarget(command=sys.executable, args=(entrypoint,), cwd=directory)

    tried = ", ".join((*MANIFEST_NAMES, *CONVENTION_ENTRYPOINTS))
    raise TargetResolutionError(
        f"{directory} does not look like an MCP server. Looked for: {tried}. "
        "Pass --command 'your-server --flags' to say how to start it."
    )


def resolve_target(
    raw: str,
    *,
    command: str | None = None,
    server: str | None = None,
) -> ServerTarget:
    """Work out how to reach the server the user meant.

    `command` always wins, then a URL, then a manifest in the directory, then a
    conventional entrypoint. Raises `TargetResolutionError` with the paths it tried.
    """
    if command:
        parts = shlex.split(command)
        if not parts:
            raise TargetResolutionError("--command was empty.")
        cwd = Path(raw) if raw and Path(raw).is_dir() else None
        return StdioTarget(command=parts[0], args=tuple(parts[1:]), cwd=cwd)

    if not raw:
        raise TargetResolutionError("No target given. Pass a directory, a .py file, or a URL.")

    if _looks_like_url(raw):
        return HttpTarget(url=raw)

    path = Path(raw)
    if path.is_dir():
        return _resolve_directory(path, server)

    if path.is_file():
        if path.suffix == ".json":
            manifest = _load_manifest(path)
            name, entry = _pick_server(_servers_in(manifest, path), path, server)
            return _entry_to_target(entry, name, path)
        if path.suffix == ".py":
            return StdioTarget(command=sys.executable, args=(path.name,), cwd=path.parent)
        raise TargetResolutionError(
            f"{path} is not a file mcp-toolgauge knows how to start. Expected a .py server or a "
            ".json manifest, or use --command."
        )

    raise TargetResolutionError(
        f"{raw!r} is not a directory, a file, or an http(s) URL, so there is nothing to inspect."
    )
