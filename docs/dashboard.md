# The dashboard

`mcpcheckup` is a terminal tool, and two of its best outputs do not fit a terminal. The
confusion matrix is a *matrix* — the eval report itself gives up and drops the "went instead
to" column on a narrow terminal — and a health score is only interesting as a *trajectory*,
which a single run cannot show. The dashboard is where those two live.

It is a static single-page app. There is no backend, no account, and nothing you load is ever
uploaded anywhere — a URL is fetched by your browser and a dropped file is read in your
browser. That is deliberate: you can point it at a private server's report without it leaving
your machine.

## Three views, and nothing else

- **Findings** — every lint finding, grouped by where it is (the server, then a tool, then a
  parameter), each with its suggestion in full and a link to the rule's docs page. The
  suggestion is the product; it is never behind a click.
- **Selection** — the confusion heatmap. A row per tool the traffic was *meant* for, a column
  per tool that captured some, the diagonal (correct) in the accent and everything off it in a
  warm ramp, so stolen traffic is the thing your eye lands on. Below it, per-tool hit rate
  worst-first, then the "`search_users` captures 88% of the prompts meant for `ticket2`"
  sentences the whole eval exists to produce.
- **History** — the health score over time, with lint and selection drawn beneath it and the
  six badge colour bands behind. It needs a history file; see below.

A persistent scorecard header carries the one health number and its two halves. That is a
header, not a fourth view — there are deliberately only three.

## Where a report comes from

The dashboard reads a `mcpcheckup ci --json` document. It gets one of three ways:

1. **The bundled demos.** It opens showing the two fixture servers — one clean, one riddled —
   with a switcher. Nothing to set up.
2. **A URL.** Add `?report=<url>` to the address, or paste a URL into the bar. A raw GitHub
   link to a committed report works untouched, because `raw.githubusercontent.com` is
   CORS-open — the same publish-a-raw-URL move the [badge](ci.md#badge) already relies on.
3. **A file.** Drop a `ci --json` file onto the page, or paste its text. Read locally, never
   uploaded — this is the path for a server whose tool list you would rather not publish.

Produce a report for your own server with:

```bash
mcpcheckup ci ./path/to/your/server --json > report.json
```

and, for the history view, keep appending to a history file across runs:

```bash
mcpcheckup ci ./path/to/your/server --history history.json --json > report.json
```

The `--json` document embeds whatever history the file holds, so one published file drives all
three views. See [the CI docs](ci.md#score-history) for the `--history` flag.

## Running and publishing it

```bash
cd dashboard
npm install
npm run dev      # http://localhost:5173
npm run build    # static files in dashboard/dist/
```

The build is plain static files behind no server, so it hosts anywhere. This repository ships
a GitHub Pages workflow (`.github/workflows/pages.yml`) that builds and publishes it; because
Pages serves from a repo subpath, that build sets `VITE_BASE=/mcpcheckup/`. Serving from a
domain root instead is `VITE_BASE=/`.

## A note on the demo data

The two bundled reports in `dashboard/public/reports/` are real `mcpcheckup ci` output, not
mock-ups. Their history series were produced by checking out each of this repository's
milestone commits and scoring the fixture at that commit — which is why goodserver's line
reads 97 → 100 → 96 → 96, the dip being the composite honestly falling the moment selection
was first *measured* rather than assumed. badserver's 0 → 0 → 28 → 28 is the mirror image: the
composite *rises* to 28 once selection is measured and turns out not to be zero.

## Design

Type and colour are lifted from a reference the terminal tool has no room for: a near-black
ink with a green cast on warm paper, a single lime accent, and mono uppercase eyebrow labels
with wide tracking. The six score colours are the same bands `health.py` uses, so the
dashboard, the badge, and the terminal never disagree about what a number is worth — the unit
tests in `dashboard/src/lib/` pin that agreement to the Python.
