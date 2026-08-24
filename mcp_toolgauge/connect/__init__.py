"""Reaching an MCP server and reading what it advertises. Read-only, always."""

from mcp_toolgauge.connect.client import (
    DEFAULT_TIMEOUT_SECONDS,
    ConnectionFailed,
    inspect_server,
    inspect_server_sync,
)
from mcp_toolgauge.connect.target import (
    HttpTarget,
    ServerTarget,
    StdioTarget,
    TargetResolutionError,
    resolve_target,
)

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "ConnectionFailed",
    "HttpTarget",
    "ServerTarget",
    "StdioTarget",
    "TargetResolutionError",
    "inspect_server",
    "inspect_server_sync",
    "resolve_target",
]
