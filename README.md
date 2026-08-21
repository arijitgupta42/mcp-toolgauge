# mcp-doctor

**Find out why your MCP server's tools don't get called.**

`mcp-doctor` audits MCP servers three ways: a static linter for tool names, descriptions
and schemas; a dynamic evaluator that measures whether a model actually picks the right
tool; and a CI gate with a score badge.

> **Status: early.** Milestones 1 and 2 of 6 are done — you can inspect a server and lint
> it against 19 rules. `eval` and `ci` are not built yet. This README describes only what
> works today.

## Lint

```bash
uv run mcp-doctor lint ./path/to/your/server
```

```
acme-directory 0.4.2
python server.py

(server)
  MCP004  warning  Tool names mix conventions: 4 snake_case, 1 camelCase. The odd
                   ones out are doStuff.

  [... one tool trimmed ...]

search_users
  MCP003  warning  search_users promises user in its name, but the description never
                   mentions it.
  MCP013  error    search_users and search_orgs share 78% of their meaningful words
                   -- their descriptions are near-identical.
                   Rewrite one of them around what makes it different. If
                   search_users and search_orgs really do the same thing, delete one;
                   if they do not, the first sentence of each should name the thing
                   only that one handles. Two descriptions this close are a coin flip
                   at selection time, and the model has no way to know it guessed
                   wrong.
  MCP014  warning  search_users overlaps with search_orgs, and its description never
                   says which to prefer.
  MCP020  warning  search_users.limit has no description.
  MCP020  warning  search_users.query has no description.
  MCP041  warning  search_users reads as read-only but declares no readOnlyHint.

  [... eight tools trimmed ...]

10 tools, 74 findings   5 errors, 53 warnings, 16 info   16 hidden, -v to show
Most common: MCP020 (25), MCP025 (10), MCP042 (6)
```

That `MCP013` line is the whole point. Two sibling tools whose descriptions are near-copies
are a coin flip at selection time, and it is a coin flip nobody observes: the call
succeeds, returns plausible data, and the wrong tool quietly takes a share of the traffic
meant for its sibling.

**Every rule is deterministic and offline.** No model is called, nothing is sent anywhere,
and nothing is charged — which is what makes this runnable on every pull request. Like
`inspect`, it never invokes one of your tools.

### What it checks

19 rules in four families. Each has [a page](docs/rules/README.md) explaining *why it matters*, with
a before and after.

| | |
|---|---|
| **[Naming](docs/rules/README.md#naming)** | Near-duplicate names, names built only from filler, names whose subject never appears in the description, mixed conventions |
| **[Descriptions](docs/rules/README.md#description)** | Missing, fragmentary, restating the name, near-identical to a sibling's, overlapping with no guidance on which to prefer, placeholder text |
| **[Parameters](docs/rules/README.md#parameters)** | Undocumented, restating their own name, free strings that should be enums, dates and emails with no format, untyped objects, no example values |
| **[Annotations](docs/rules/README.md#annotations)** | Destructive tools with no `destructiveHint`, reads with no `readOnlyHint`, writes with no `idempotentHint` |

### Options

```bash
uv run mcp-doctor lint . -v                      # info findings, and every suggestion
uv run mcp-doctor lint . --fail-on warning       # stricter gate
uv run mcp-doctor lint . --fail-on off           # report without ever failing
uv run mcp-doctor lint . --json                  # machine-readable, stable key order
uv run mcp-doctor lint . --sarif > results.sarif # for GitHub code scanning
uv run mcp-doctor lint . --no-config             # ignore any mcp-doctor.toml on disk
```

Exit codes: `0` clean, `1` a finding reached `--fail-on` (default `error`), `2` usage
error, `3` could not reach the server.

### Configuration

Optional. Put an `mcp-doctor.toml` next to your server, or a `[tool.mcp-doctor]` section in
your `pyproject.toml`:

```toml
[lint]
fail_on = "error"

[lint.rules]
MCP025 = "off"      # we do not want example values in descriptions
MCP041 = "error"    # annotations are not optional on this server
```

A typo in a rule ID is a usage error rather than a silent no-op, because a rule you think
you turned off is worse than one you never touched.

## Inspect

```bash
uv run mcp-doctor inspect ./path/to/your/server
```

Point it at a directory and it finds your server the way your MCP client does — by reading
`.mcp.json` (or `mcp.json`, `.vscode/mcp.json`, `claude_desktop_config.json`). No manifest?
It falls back to a conventional entrypoint like `server.py`. Either way, no flags needed:

```
acme-directory 1.0.0  protocol 2026-07-28
python server.py

tool                   description                                    params  R D I
search_users           Find individual people in the staff direct...       3  R d I
search_organizations   Find organizations -- companies, teams, an...       3  R d I
get_user_profile       Retrieve the full profile for one known pe...       1  R d I
create_support_ticket  Open a new support ticket on behalf of a u...       4  r d i
update_ticket_status   Move an existing support ticket to a new s...       3  r d i
list_ticket_comments   Read the comment thread on one support tic...       2  R d I
archive_ticket         Permanently archive a support ticket, remo...       2  r D I
export_directory_csv   Export one organization's slice of the sta...       2  R d I

8 tools   -v for parameter detail
```

The `R D I` column is `readOnlyHint`, `destructiveHint`, `idempotentHint`. Uppercase means
the server declared it true, lowercase false, and `-` means it said nothing at all — which
is a different problem, and one `lint` has opinions about.

### Other ways to point it at a server

Both commands take the same target flags:

```bash
uv run mcp-doctor lint https://example.com/mcp             # a running server over HTTP
uv run mcp-doctor lint ./server.py                         # a single script
uv run mcp-doctor lint . --server backend                  # pick one from a multi-server manifest
uv run mcp-doctor lint . --command "node dist/server.js"   # say it yourself
```

**Both commands are read-only.** They connect, list tools, and disconnect. Neither ever
calls one of your tools.

## Try it without a server of your own

The repo ships two fixture servers with the same API — one written well, one written
carelessly:

```bash
uv run mcp-doctor lint tests/fixtures/goodserver
uv run mcp-doctor lint tests/fixtures/badserver
```

The first is clean. The second produces 74 findings. The difference between them is the
entire point of this project.

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
| `lint` — static rules for names, descriptions, schemas, annotations | done |
| `eval` — tool-selection accuracy and a confusion matrix | next |
| `ci` — health score, threshold gate, badge, GitHub Action | planned |
| Dashboard | planned |
| Ship to PyPI so `uvx mcp-doctor` needs no install | planned |

## Licence

MIT
