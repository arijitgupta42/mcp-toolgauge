# The health score, the badge, and the Action

`mcp-doctor ci` rolls the two signals the tool already produces -- lint findings and eval
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
uv run mcp-doctor ci ./path/to/your/server
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
reproducible and free. A server with no `mcp-doctor-cases.yaml` beside it is scored on lint
alone and says so.

```bash
uv run mcp-doctor ci . --min-score 80          # exit 1 below this
uv run mcp-doctor ci . --badge badge.json       # write the shields.io endpoint JSON
uv run mcp-doctor ci . --json                    # the full report, for --baseline later
uv run mcp-doctor ci . --markdown comment.md     # the PR-comment body
uv run mcp-doctor ci . --markdown comment.md --baseline main.json   # with a vs-base delta
uv run mcp-doctor ci . -v                         # the findings behind the lint score
```

Exit codes match the rest of the tool: `0` at or above `--min-score` (or no gate), `1` below
it, `2` a usage error, `3` could not reach the server.

## The badge

`--badge badge.json` writes a [shields.io endpoint](https://shields.io/badges/endpoint-badge)
document:

```json
{ "schemaVersion": 1, "label": "mcp-doctor", "message": "96", "color": "brightgreen" }
```

Publish that file anywhere with a raw URL -- committing it to your repo is enough -- and point
a badge at it:

```markdown
![mcp-doctor](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/OWNER/REPO/main/badge.json)
```

## The GitHub Action

The composite Action wraps all of the above: it scores your server, fails the job under a
threshold, writes the badge, posts a sticky comment on the pull request, and shows the delta
against the score your base branch last recorded.

```yaml
# .github/workflows/mcp-doctor.yml
on: [push, pull_request]
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # Install your server's own dependencies here, so mcp-doctor can start it.
      - uses: arijitgupta42/mcp-doctor@v1
        with:
          target: .
          min-score: "80"
```

Inputs: `target`, `min-score`, `model`, `cases`, `badge-path`, `comment`, `track-score`,
`package-spec`, `python-version`. Outputs: `score` and `color`.

Until mcp-doctor is published to PyPI (that lands with the launch), pin `package-spec` to a
git ref so the Action has something to install:

```yaml
        with:
          package-spec: git+https://github.com/arijitgupta42/mcp-doctor
```
