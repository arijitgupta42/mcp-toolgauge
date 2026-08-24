# The health score, the badge, and the Action

`mcp-toolgauge ci` rolls the two signals the tool already produces -- lint findings and eval
selection accuracy -- into one 0-100 number you can gate a build on, put on a badge, and
watch move on a pull request. This page is the methodology: what the number means, and what
it deliberately does *not*.

## The formula

```
lint_score  = clamp(100 - 10*errors - 3*warnings, 0, 100)   # info is advisory
eval_score  = round(selection_accuracy * 100)               # positives + siblings only
overall     = round(0.5*lint_score + 0.5*eval_score)   when an eval suite ran
            = lint_score                                lint-only (no suite / no selection cases)
```

Three choices shape it, and each had another reasonable answer.

**The eval half is selection accuracy alone.** Abstention accuracy and argument validity are
reported next to the score, never folded into it -- the same rule `eval` follows. If
abstention counted, a server could raise its badge by adding abstain cases to its own suite,
which changes the test rather than the server. The score measures the thing you cannot fake:
does the model pick the right tool.

**Info findings do not move the score.** Only errors and warnings -- the findings the report
shows by default and expects you to act on -- count against the lint half. Info is polish;
grading a server down for polish it was told is optional would just teach people to turn info
off.

**A server with no eval suite is scored on lint alone**, not on lint averaged with a zero.
Most servers have no committed eval suite, and pretending their model never picks the right
tool would be a lie about a measurement nobody took. The eval weight collapses onto lint, and
the badge still means something on day one -- which is the point, because the badge only helps
if it is trivial to adopt.

The weights and penalties were fixed by their effect on the two fixture servers in this repo,
the same way the lint similarity threshold was: the careful server scores **96** (100 lint,
92 eval) and the careless one **28** (0 lint, 55 eval). The careless server's lint floors at
zero because it genuinely is riddled; its score is still 28 rather than 0 because the eval
half carries it.

### Colours

The badge colour follows the score, anchored on the same 90 / 70 opinion the eval report
prints and widened so a middling-but-honest server does not read as alarming red:

| Score | Colour |
|---|---|
| 90-100 | brightgreen |
| 75-89 | green |
| 60-74 | yellowgreen |
| 45-59 | yellow |
| 30-44 | orange |
| 0-29 | red |

## The command

```bash
uv run mcp-toolgauge ci ./path/to/your/server
```

```
acme-directory 1.0.0
python server.py

Health        96 / 100
  lint       100   0 errors, 0 warnings
  selection  92%   37 of 40 prompts

get_user_profile captures 50% of the prompts meant for create_support_ticket.
```

The eval half is replayed from the committed cache and never calls a model, so `ci` is
reproducible and free. A server with no `mcp-toolgauge-cases.yaml` beside it is scored on lint
alone and says so.

```bash
uv run mcp-toolgauge ci . --min-score 80          # exit 1 below this
uv run mcp-toolgauge ci . --badge badge.json       # write the shields.io endpoint JSON
uv run mcp-toolgauge ci . --json                    # the full report, for --baseline later
uv run mcp-toolgauge ci . --markdown comment.md     # the PR-comment body
uv run mcp-toolgauge ci . --markdown comment.md --baseline main.json   # with a vs-base delta
uv run mcp-toolgauge ci . --history history.json    # append this score to a trajectory
uv run mcp-toolgauge ci . -v                         # the findings behind the lint score
```

Exit codes match the rest of the tool: `0` at or above `--min-score` (or no gate), `1` below
it, `2` a usage error, `3` could not reach the server.

## Score history

`--baseline` compares this run against one earlier one. `--history` keeps the *whole* line:

```bash
uv run mcp-toolgauge ci ./server --history history.json --history-label "$(git rev-parse --short HEAD)"
```

Each run appends one point — the timestamp, an optional label, and the same `HealthScore` the
badge shows — to the file, creating it on the first run. Commit the file and it accumulates a
trajectory across builds, which the [dashboard](dashboard.md)'s history view draws. The point
is recorded *before* the `--min-score` gate, so a run that fails the gate still lands on the
chart — a history that quietly skipped the bad runs would be a history of nothing but good
news.

The file is capped at the most recent 500 points, so a committed history cannot grow without
bound. Its shape:

```json
{
  "target": "./server",
  "points": [
    { "recorded_at": "2026-08-22T16:03:44+00:00", "label": "eval", "health": { "overall": 96, "lint_score": 100, "eval_score": 92, "errors": 0, "warnings": 0 } }
  ]
}
```

A `ci --json` run embeds whatever the history file holds under a top-level `history` key, so
one published `--json` document drives all three dashboard views at once. Pointing `--history`
at a file recorded for a different `target` warns and appends anyway — keep a per-server path
to keep their trends apart.

## The badge

`--badge badge.json` writes a [shields.io endpoint](https://shields.io/badges/endpoint-badge)
document:

```json
{ "schemaVersion": 1, "label": "mcp-toolgauge", "message": "96", "color": "brightgreen" }
```

Publish that file anywhere with a raw URL -- committing it to your repo is enough -- and point
a badge at it:

```markdown
![mcp-toolgauge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/OWNER/REPO/main/badge.json)
```

## The GitHub Action

The composite Action wraps all of the above: it scores your server, fails the job under a
threshold, writes the badge, posts a sticky comment on the pull request, and shows the delta
against the score your base branch last recorded.

```yaml
# .github/workflows/mcp-toolgauge.yml
on: [push, pull_request]
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # Install your server's own dependencies here, so mcp-toolgauge can start it.
      - uses: arijitgupta42/mcp-toolgauge@v1
        with:
          target: .
          min-score: "80"
```

Inputs: `target`, `min-score`, `model`, `cases`, `badge-path`, `comment`, `track-score`,
`package-spec`, `python-version`. Outputs: `score` and `color`.

`@v1` is a moving major-version tag that follows the latest `v1.x` release, so you get fixes
without re-pinning. Pin an exact tag like `@v0.1.0` if you'd rather freeze it. The Action
installs mcp-toolgauge from PyPI by default; `package-spec` overrides what it installs — point it
at a git ref (`git+https://github.com/arijitgupta42/mcp-toolgauge@main`) to run an unreleased
version.
