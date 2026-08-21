"""goodserver -- a directory and ticketing MCP server, written the way we want people to write them.

This is the counterpart to ``badserver``: same API surface, same eight tools, but every
name is descriptive, every description is a full sentence that says when to use the tool
*instead of its siblings*, every parameter is documented and constrained, and every tool
carries the annotations a client needs to decide whether it is safe to call.

Nothing here does real work. mcp-doctor never invokes a tool (read-only invariant), so the
bodies return canned data and exist only to give the decorators something to hang on.
"""

from __future__ import annotations

import argparse
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field

mcp = MCPServer(
    name="acme-directory",
    version="1.0.0",
    instructions=(
        "Look up people and organizations in the Acme staff directory, and manage the "
        "support tickets attached to them. Search tools are read-only; ticket tools "
        "mutate state."
    ),
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)
MUTATING = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True)


@mcp.tool(annotations=READ_ONLY)
def search_users(
    query: Annotated[
        str, Field(description="Full or partial name, email address, or employee ID to match on.")
    ],
    organization_id: Annotated[
        str | None,
        Field(
            default=None,
            description="Restrict results to one organization, e.g. 'org_9f2b'. Omit to search all.",
            pattern=r"^org_[a-z0-9]+$",
        ),
    ] = None,
    limit: Annotated[
        int, Field(default=20, ge=1, le=100, description="Maximum number of people to return.")
    ] = 20,
) -> list[dict[str, Any]]:
    """Find individual people in the staff directory by name, email, or employee ID.

    Use this when the user is looking for a *person*. If they are looking for a company,
    team, or other organization, use `search_organizations` instead. Returns one entry per
    matching person with their name, email, title, and organization.
    """
    return [{"user_id": "usr_1", "name": "Ada Lovelace", "email": "ada@acme.test"}][:limit]


@mcp.tool(annotations=READ_ONLY)
def search_organizations(
    query: Annotated[
        str, Field(
            description=(
                "Full or partial organization name or email domain to match on, "
                "e.g. 'Acme' or 'acme.test'."
            )
        )
    ],
    include_inactive: Annotated[
        bool,
        Field(default=False, description="Include organizations that have been marked inactive."),
    ] = False,
    limit: Annotated[
        int, Field(default=20, ge=1, le=100, description="Maximum number of organizations to return.")
    ] = 20,
) -> list[dict[str, Any]]:
    """Find organizations -- companies, teams, and departments -- by name or email domain.

    Use this when the user is looking for a *group*, not a person. To find an individual
    inside one of these organizations, use `search_users` instead. Returns one entry per
    matching organization with its ID, display name, primary domain, and member count.
    """
    return [{"organization_id": "org_9f2b", "name": "Acme Corp", "domain": "acme.test"}][:limit]


@mcp.tool(annotations=READ_ONLY)
def get_user_profile(
    user_id: Annotated[
        str,
        Field(
            description="The user's stable identifier, e.g. 'usr_1a2b'. Get one from `search_users`.",
            pattern=r"^usr_[a-z0-9]+$",
        ),
    ],
) -> dict[str, Any]:
    """Retrieve the full profile for one known person, including contact details and manager.

    Use this only when you already have a user ID. If you have a name or email and need to
    resolve it to an ID first, call `search_users`.
    """
    return {"user_id": user_id, "name": "Ada Lovelace", "title": "Principal Engineer"}


@mcp.tool(annotations=MUTATING)
def create_support_ticket(
    subject: Annotated[
        str, Field(min_length=1, max_length=200, description="One-line summary of the problem.")
    ],
    body: Annotated[
        str, Field(description="Full description of the problem, including any error messages.")
    ],
    requester_id: Annotated[
        str,
        Field(
            description="User ID of the person reporting the problem, e.g. 'usr_1a2b'.",
            pattern=r"^usr_[a-z0-9]+$",
        ),
    ],
    priority: Annotated[
        Literal["low", "normal", "high", "urgent"],
        Field(default="normal", description="How quickly the ticket needs attention."),
    ] = "normal",
) -> dict[str, Any]:
    """Open a new support ticket on behalf of a user and return the created ticket.

    Use this to file a *new* problem. To change something about a ticket that already
    exists, use `update_ticket_status` instead.
    """
    return {"ticket_id": "tkt_1", "subject": subject, "status": "open", "priority": priority}


@mcp.tool(annotations=MUTATING)
def update_ticket_status(
    ticket_id: Annotated[
        str, Field(
            description="Identifier of the ticket to update, e.g. 'tkt_4c8d'.",
            pattern=r"^tkt_[a-z0-9]+$",
        )
    ],
    status: Annotated[
        Literal["open", "pending", "solved", "closed"],
        Field(description="The status to move the ticket to."),
    ],
    comment: Annotated[
        str | None,
        Field(default=None, description="Optional note explaining the status change."),
    ] = None,
) -> dict[str, Any]:
    """Move an existing support ticket to a new status, optionally attaching a note.

    Use this to progress or resolve a ticket. To permanently remove a ticket from the
    active queue, use `archive_ticket` instead.
    """
    return {"ticket_id": ticket_id, "status": status, "comment": comment}


@mcp.tool(annotations=READ_ONLY)
def list_ticket_comments(
    ticket_id: Annotated[
        str, Field(description="Identifier of the ticket to read.", pattern=r"^tkt_[a-z0-9]+$")
    ],
    since: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Only return comments posted on or after this date, as ISO-8601, "
                "e.g. '2026-01-31'."
            ),
            json_schema_extra={"format": "date"},
        ),
    ] = None,
) -> list[dict[str, Any]]:
    """Read the comment thread on one support ticket, oldest first.

    Use this to understand a ticket's history before acting on it. This returns only the
    conversation; the ticket's own fields come from `create_support_ticket`'s response or
    from `update_ticket_status`.
    """
    return [{"author_id": "usr_1", "posted_at": "2026-01-31T09:00:00Z", "body": "Looking into it."}]


@mcp.tool(annotations=DESTRUCTIVE)
def archive_ticket(
    ticket_id: Annotated[
        str, Field(
            description="Identifier of the ticket to archive, e.g. 'tkt_4c8d'.",
            pattern=r"^tkt_[a-z0-9]+$",
        )
    ],
    reason: Annotated[
        str, Field(min_length=1, description="Why the ticket is being archived, for the audit log.")
    ],
) -> dict[str, Any]:
    """Permanently archive a support ticket, removing it from the active queue.

    This cannot be undone from this API -- archived tickets are restorable only by an
    administrator. To close a ticket in a way that can be reopened, use
    `update_ticket_status` with status 'closed' instead.
    """
    return {"ticket_id": ticket_id, "archived": True, "reason": reason}


@mcp.tool(annotations=READ_ONLY)
def export_directory_csv(
    organization_id: Annotated[
        str,
        Field(
            description="Organization whose members should be exported, e.g. 'org_9f2b'.",
            pattern=r"^org_[a-z0-9]+$",
        ),
    ],
    fields: Annotated[
        list[Literal["name", "email", "title", "manager", "start_date"]] | None,
        Field(default=None, description="Columns to include. Defaults to name, email, and title."),
    ] = None,
) -> str:
    """Export one organization's slice of the staff directory as a CSV document, as text.

    Use this when the user wants the whole membership as a file or table rather than a
    handful of matches; for looking up specific people, `search_users` is cheaper.
    """
    return "name,email,title\nAda Lovelace,ada@acme.test,Principal Engineer\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the goodserver fixture.")
    parser.add_argument("--http", action="store_true", help="Serve Streamable HTTP instead of stdio.")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind when using --http.")
    args = parser.parse_args()

    if args.http:
        mcp.run(transport="streamable-http", port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
