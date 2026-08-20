# mcp-doctor

**Find out why your MCP server's tools don't get called.**

`mcp-doctor` audits MCP servers three ways: a static linter for tool names, descriptions
and schemas; a dynamic evaluator that measures whether a model actually picks the right
tool; and a CI gate with a score badge.

> **Status: early.** Milestone 1 of 6 is done — you can connect to a server and inspect
> what it advertises. `lint`, `eval`, and `ci` are not built yet. This README describes
> only what works today.

## What works today

```bash
uv run mcp-doctor inspect ./path/to/your/server
```

Point it at a directory and it finds your server the way your MCP client does — by reading
`.mcp.json` (or `mcp.json`, `.vscode/mcp.json`, `claude_desktop_config.json`). No manifest?
It falls back to a conventional entrypoint like `server.py`. Either way, no flags needed:

```
acme-directory 1.0.0  protocol 2026-07-28
python server.py

tool                   description                                       params  R D I
search_users           Find individual people in the staff directory...       3  R d I
search_organizations   Find organizations -- companies, teams, and de...      3  R d I
get_user_profile       Retrieve the full profile for one known person...      1  R d I
create_support_ticket  Open a new support ticket on behalf of a user ...      4  r d i
update_ticket_status   Move an existing support ticket to a new status...     3  r d i
list_ticket_comments   Read the comment thread on one support ticket, ...     2  R d I
archive_ticket         Permanently archive a support ticket, removing ...     2  r D I
export_directory_csv   Export one organization's member list as a CSV ...     2  R d I

8 tools   -v for parameter detail
```

The `R D I` column is `readOnlyHint`, `destructiveHint`, `idempotentHint`. Uppercase means
the server declared it true, lowercase false, and `-` means it said nothing at all — which
is a different problem, and one the linter will have opinions about.

### Other ways to point it at a server

```bash
uv run mcp-doctor inspect https://example.com/mcp        # a running server over HTTP
uv run mcp-doctor inspect ./server.py                    # a single script
uv run mcp-doctor inspect . --server backend             # pick one from a multi-server manifest
uv run mcp-doctor inspect . --command "node dist/server.js"   # say it yourself
uv run mcp-doctor inspect . --json                       # machine-readable, stable key order
uv run mcp-doctor inspect . -v                           # parameters, types, and descriptions
```

**`inspect` is read-only.** It connects, lists tools, and disconnects. It never calls one.

Exit codes: `0` fine, `2` usage error, `3` could not reach the server. (`1` is reserved for
the threshold failure that `mcp-doctor ci` will return.)

## Try it without a server of your own

The repo ships two fixture servers with the same API — one written well, one written
carelessly:

```bash
uv run mcp-doctor inspect tests/fixtures/goodserver
uv run mcp-doctor inspect tests/fixtures/badserver
```

The difference between them is the entire point of this project.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy mcp_doctor
```

Skip the tests that spawn real servers with `uv run pytest -m "not integration"`.

## Roadmap

| Milestone | Status |
|---|---|
| Connection and `inspect` | done |
| `lint` — static rules for names, descriptions, schemas, annotations | next |
| `eval` — tool-selection accuracy and a confusion matrix | planned |
| `ci` — health score, threshold gate, badge, GitHub Action | planned |
| Dashboard | planned |
| Ship to PyPI so `uvx mcp-doctor` needs no install | planned |

## Licence

MIT
