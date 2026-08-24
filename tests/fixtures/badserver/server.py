"""badserver -- the same directory and ticketing API as ``goodserver``, written carelessly.

This is mcp-toolgauge's demo villain. It is deliberately bad, but it is meant to look like a
real server that grew without review: tools bolted on over time, names that made sense to
the author, descriptions copy-pasted between siblings and never differentiated. It is not
a checklist of every lint rule -- per-rule micro-fixtures live next to their rules.

The headline problem is `search_users` versus `search_orgs`: near-identical descriptions
with nothing telling a model when to prefer one over the other.

Nothing here does real work. mcp-toolgauge never invokes a tool (read-only invariant), so
every body calls `_never_called`, which writes a marker to stderr. If that marker ever
shows up in a test run, the invariant is broken.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

mcp = MCPServer(name="acme-directory", version="0.4.2")

NEVER_CALLED_MARKER = "MCP_TOOLGAUGE_FIXTURE_TOOL_WAS_INVOKED"


def _never_called(tool: str) -> dict[str, Any]:
    """Mark, loudly, that a fixture tool body actually ran."""
    print(f"{NEVER_CALLED_MARKER}: {tool}", file=sys.stderr, flush=True)
    return {"ok": True}


@mcp.tool()
def search(q: str, type: str = "user") -> Any:
    """Search."""
    return _never_called("search")


@mcp.tool()
def search_users(query: str, limit: int = 10) -> Any:
    """Searches the database and returns matching records for the given query string."""
    return _never_called("search_users")


@mcp.tool()
def search_orgs(query: str, limit: int = 10) -> Any:
    """Searches the database and returns matching records for the query string provided."""
    return _never_called("search_orgs")


@mcp.tool()
def get_data(id: str, opts: dict[str, Any] | None = None) -> Any:
    """Get data."""
    return _never_called("get_data")


@mcp.tool(description="")
def run(payload: dict[str, Any]) -> Any:
    return _never_called("run")


@mcp.tool()
def ticket(subject: str, body: str, user: str, priority: str = "normal") -> Any:
    """Creates a ticket in the support system with the supplied subject and body."""
    return _never_called("ticket")


@mcp.tool()
def ticket2(subject: str, body: str, user: str, urgency: str = "normal") -> Any:
    """Creates a ticket."""
    return _never_called("ticket2")


@mcp.tool()
def doStuff(action: str, target: str, params: Any = None) -> Any:
    """TODO: document this properly."""
    return _never_called("doStuff")


@mcp.tool()
def update(ticket_id: str, status: str, when: str = "") -> Any:
    """Updates the status. Pass the status you want and the date it changed."""
    return _never_called("update")


@mcp.tool()
def delete_all_tickets(org: str, confirm: bool = False) -> Any:
    """Deletes every ticket belonging to an org. There is no undo for this operation."""
    return _never_called("delete_all_tickets")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the badserver fixture.")
    parser.add_argument("--http", action="store_true", help="Serve Streamable HTTP instead of stdio.")
    parser.add_argument("--port", type=int, default=8001, help="Port to bind when using --http.")
    args = parser.parse_args()

    if args.http:
        mcp.run(transport="streamable-http", port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
