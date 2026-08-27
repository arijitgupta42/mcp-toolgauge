# mcp-toolgauge

[![mcp-toolgauge health](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/arijitgupta42/mcp-toolgauge/main/badge.json)](docs/ci.md#the-badge)
[![PyPI](https://img.shields.io/pypi/v/mcp-toolgauge)](https://pypi.org/project/mcp_toolgauge/)
[![CI](https://github.com/arijitgupta42/mcp-toolgauge/actions/workflows/ci.yml/badge.svg)](https://github.com/arijitgupta42/mcp-toolgauge/actions/workflows/ci.yml)
[![licence: MIT](https://img.shields.io/badge/licence-MIT-blue)](LICENSE)

`mcp-toolgauge` audits an MCP server and helps answer why an LLM isn't calling its tools
the way you'd expect. It checks your tool names, descriptions, and schemas for problems
(`lint`), measures whether a model actually picks the right tool (`eval`), and rolls both
into a single score you can gate CI on (`ci`).

![mcp-toolgauge finds a near-duplicate description, measures the tool-selection confusion it causes, and rolls it into one health score](https://raw.githubusercontent.com/arijitgupta42/mcp-toolgauge/main/docs/assets/demo.svg)

All three commands are read-only: they connect to your server, list its tools, and
disconnect. None of them ever calls one of your tools for real.

## Install

No install needed. [`uvx`](https://docs.astral.sh/uv/) runs it directly:

```bash
uvx mcp-toolgauge lint ./your-server
```

Or install it properly:

```bash
uv tool install mcp-toolgauge
# or
pipx install mcp-toolgauge
```

The rest of this README uses the bare `mcp-toolgauge` command; prefix any of them with
`uvx` if you didn't install it.

## Quickstart

Point any command at a directory, a script, or a URL. It finds your server the same way
an MCP client would (via `.mcp.json`, or a conventional entrypoint like `server.py`).

```bash
mcp-toolgauge inspect ./your-server   # list its tools
mcp-toolgauge lint ./your-server      # check names, descriptions, schemas
mcp-toolgauge eval ./your-server      # does a model actually pick the right tool?
mcp-toolgauge ci ./your-server        # one 0-100 score, for gating a build
```

## inspect

Lists the tools a server exposes, along with their parameter count and annotations
(`readOnlyHint`, `destructiveHint`, `idempotentHint`):

```bash
mcp-toolgauge inspect ./your-server
```

```
acme-directory 1.0.0  protocol 2026-07-28
python server.py

tool                   description                                    params  R D I
search_users           Find individual people in the staff direct...       3  R d I
create_support_ticket  Open a new support ticket on behalf of a u...       4  r d i

2 tools   -v for parameter detail
```

## lint

Static, offline checks against 22 rules covering naming, descriptions, parameters,
annotations, and tool-surface size. No model is called and nothing leaves your machine.

```bash
mcp-toolgauge lint ./your-server
```

```
acme-directory 0.4.2
python server.py

search_users
  MCP013  error    search_users and search_orgs share 78% of their meaningful words
                   -- their descriptions are near-identical.
  MCP020  warning  search_users.limit has no description.

10 tools, 74 findings   5 errors, 53 warnings, 16 info
```

Each rule has a docs page under [docs/rules/](docs/rules/README.md) explaining why it
matters, with a before/after fix.

Useful flags:

```bash
mcp-toolgauge lint . -v                      # show info findings and suggestions
mcp-toolgauge lint . --fail-on warning       # fail the build on warnings too
mcp-toolgauge lint . --json                  # machine-readable output
mcp-toolgauge lint . --sarif > results.sarif # for GitHub code scanning
```

You can configure it via `mcp-toolgauge.toml` (or `[tool.mcp-toolgauge]` in
`pyproject.toml`):

```toml
[lint]
fail_on = "error"

[lint.rules]
MCP025 = "off"
```

## eval

Puts your real tool definitions in front of a real model and checks whether it calls the
right one:

```bash
mcp-toolgauge eval ./your-server --init   # generate a suite of test cases, then edit it
mcp-toolgauge eval ./your-server          # run it
```

```
Selection accuracy     55%  31/56
  positives            60%  24/40
  siblings             44%   7/16
Abstention             33%    1/3
Argument validity      98%  50/51

tool                 hit       went instead to
ticket2              12%  1/8  search_users 88%
search_users        100%  4/4
```

Cases are written once by `--init`, then committed and edited by hand. A run never
regenerates them silently, so scores stay comparable across runs. Every model answer is
cached by `hash(model, prompt, tool_digest)`, so re-running an unchanged suite makes no
network calls.

Useful flags:

```bash
mcp-toolgauge eval . --model openai/gpt-4.1-mini   # any model LiteLLM supports
mcp-toolgauge eval . --offline                     # replay the cache, no API key needed
mcp-toolgauge eval . --min-accuracy 80             # exit 1 below this
mcp-toolgauge eval . --json                        # full confusion matrix
```

Calling a live model needs the `eval` extra:

```bash
uv pip install 'mcp-toolgauge[eval]'
```

The default model is free on OpenRouter, so a first run only needs an
`OPENROUTER_API_KEY`.

## ci

Combines lint and eval into one 0–100 health score:

```bash
mcp-toolgauge ci ./your-server --min-score 80
```

```
Health        96 / 100
  lint       100   0 errors, 0 warnings
  selection  92%   37 of 40 prompts
```

```
lint_score  = clamp(100 - 10*errors - 3*warnings, 0, 100)
eval_score  = round(selection_accuracy * 100)
overall     = round(0.5*lint_score + 0.5*eval_score)
```

A server with no eval suite is scored on lint alone. `ci` never calls a model: the eval
half always replays the committed cache, so it's reproducible in CI. See
[docs/ci.md](docs/ci.md) for the full reasoning.

Exit codes across all three commands: `0` pass, `1` threshold failure, `2` usage error,
`3` couldn't reach the server.

### Badge

```bash
mcp-toolgauge ci . --badge badge.json
```

Writes a [shields.io endpoint](https://shields.io/badges/endpoint-badge) file. Publish it
and point a badge at it:

```markdown
![mcp-toolgauge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/OWNER/REPO/main/badge.json)
```

### GitHub Action

```yaml
- uses: actions/checkout@v4
# install your server's own dependencies first, so mcp-toolgauge can start it
- uses: arijitgupta42/mcp-toolgauge@v1
  with:
    target: .
    min-score: "80"
```

Fails the build under `min-score`, writes the badge, and posts a pull-request comment
with the score delta against your base branch. See [docs/ci.md](docs/ci.md) for every
input.

## Dashboard

A static single-page app for the two things a terminal doesn't show well: the confusion
matrix and score history over time.

```bash
cd dashboard
npm install
npm run dev      # http://localhost:5173
npm run build    # static files in dashboard/dist/
```

It reads a `mcp-toolgauge ci --json` report: a bundled demo, `?report=<raw-url>`, or a
file dropped on the page. Keep a history file across runs to get the trend chart:

```bash
mcp-toolgauge ci ./your-server --history history.json --json > report.json
```

More detail, including how to publish your own, is in [docs/dashboard.md](docs/dashboard.md).

## Other ways to point it at a server

```bash
mcp-toolgauge lint https://example.com/mcp             # a running server over HTTP
mcp-toolgauge lint ./server.py                         # a single script
mcp-toolgauge lint . --server backend                  # pick one from a multi-server manifest
mcp-toolgauge lint . --command "node dist/server.js"   # say it yourself
```

## Try it without a server of your own

The repo ships two fixture servers with the same API: one written carefully, one
carelessly.

```bash
uv run mcp-toolgauge lint tests/fixtures/goodserver     # 0 findings
uv run mcp-toolgauge lint tests/fixtures/badserver      # 74 findings

uv run mcp-toolgauge eval tests/fixtures/goodserver --offline   # 92%
uv run mcp-toolgauge eval tests/fixtures/badserver --offline    # 55%

uv run mcp-toolgauge ci tests/fixtures/goodserver   # 96 / 100
uv run mcp-toolgauge ci tests/fixtures/badserver    # 28 / 100
```

## Development

```bash
uv sync                  # base install
uv sync --extra eval     # adds LiteLLM, for `eval` without --offline
uv run pytest
uv run pytest -m "not integration"   # skip tests that spawn real servers
uv run ruff check .
uv run mypy mcp_toolgauge
```

No test calls a live model. The eval suite stubs the backend or replays a recorded
cache.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Rule proposals, false-positive reports, and
[`good first issue`](https://github.com/arijitgupta42/mcp-toolgauge/labels/good%20first%20issue)s
are all welcome.

## Licence

MIT. See [LICENSE](LICENSE).
