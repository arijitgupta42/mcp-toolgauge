# Contributing to mcp-toolgauge

Thanks for wanting to help. This project has a narrow, defensible job — tell MCP server
authors *why their tools don't get called* — and the fastest way to get a change merged is to
show how it serves that job.

## What belongs here, and what doesn't

The product is three things and no more: a static **lint**, a tool-selection **eval**, and a
**CI** gate that rolls both into one score. If a feature request doesn't make a server
author's tools get selected more reliably, it's probably out of scope. In particular, these
are deliberate non-goals, not gaps:

- Trace storage or production observability (that market is saturated)
- An agent framework or runtime
- General-purpose LLM evals unrelated to tool selection
- A hosted backend or accounts system

A good idea that's out of scope still deserves a home — open an issue and we'll label it
rather than pretend it doesn't exist.

## Setting up

```bash
uv sync                  # base install; enough for everything except calling a live model
uv sync --extra eval     # adds LiteLLM, only needed for `eval` without --offline
```

The checks CI runs, which you can run locally:

```bash
uv run pytest                     # the whole suite
uv run pytest -m "not integration"  # fast subset, no subprocesses, sub-second
uv run ruff check .
uv run mypy mcp-toolgauge
```

No test calls a live model — the eval suite stubs the backend or replays a committed cache.
Tests that spawn a real fixture server are marked `integration`; keep that marker on anything
that starts a subprocess so the unit suite stays fast.

The dashboard is a separate npm project:

```bash
cd dashboard
npm install
npm run typecheck && npm run test && npm run build
```

## The branch-and-PR rule

Nothing lands on `main` by direct commit — every change goes through a branch and a pull
request, including docs-only ones. There's no second reviewer, so a PR isn't an approval
gate; it exists to force CI to run before merge and to leave a written record of *why* a
change was made that the diff can't carry. Self-merging is expected.

- Branch names are `<type>/<short-slug>` — `feat/…`, `fix/…`, `docs/…`, `chore/…`. The prefix
  files the branch; it does **not** go in commit messages.
- Commit messages are plain English, imperative mood, no `feat:`/`fix:` prefixes, no trailers.
  A subject under ~70 characters, and a body in prose when the change needs a *why*.
- Squash-merge, one clean commit per change: `gh pr merge --squash --delete-branch`.
- CI must be green before merge. Check the run's `conclusion`, not a piped exit code.

The PR description should say what the diff can't: the problem and the shape of the fix, any
decision that had more than one reasonable answer, what you actually ran to verify, and any
new dependency (which needs justifying — prefer the standard library; this tool must stay
fast to install).

## Writing a lint rule

This is the most common contribution, and the bar is fixed. Every rule needs, without
exception:

1. **An ID** (`MCP0xx`), a **severity**, and a one-line **message**.
2. **A concrete `suggestion` string.** Never report a problem without proposing a fix — a
   finding that only says what's wrong is a finding people learn to ignore.
3. **A positive fixture that triggers it and a negative fixture that does not.** Both are
   asserted; a rule with only a positive test can start firing on clean input and nobody
   notices.
4. **A docs page** in [`docs/rules/`](docs/rules/) explaining *why it matters*, with a before
   and after. The docs are the marketing — a rule without a persuasive "why" is a rule people
   disable.

Rules live in [`mcp_toolgauge/lint/rules/`](mcp_toolgauge/lint/rules/), one module per family, and
register through the engine's decorator. Two hard invariants:

- **Lint rules never call a model.** Deterministic, offline, free — that's what makes lint
  runnable on every pull request. LLM assistance is allowed only in the opt-in `--fix` path,
  never in rule evaluation.
- **Text reaches rules already normalised.** `ToolSpec` runs `cleandoc().strip()` on ingest
  and collapses blank strings to `None`. Rules must not re-normalise, must not assume raw
  docstring indentation, and should test for `None` — `""` never reaches a rule.

## Touching the eval scorer

`mcp_toolgauge/eval/score.py` is pure — no network, no filesystem, no clock — and has the
highest test coverage in the repo. Keep it that way: every function takes data and returns
data, and new behaviour comes with a hand-built fixture whose correct answer is known. The
scoring formula is the intellectual content of the project; a change to *what the number
means* is a discussion to have in an issue first, not a silent tweak.

## The release process

Releases are cut from a tag and published to PyPI by **trusted publishing** — there is no API
token anywhere.

1. Bump `version` in `pyproject.toml` and add a dated section to `CHANGELOG.md`.
2. Merge that through a PR as usual.
3. Tag the release and push it: `git tag v0.1.1 && git push --tags`.
4. The [`release`](.github/workflows/release.yml) workflow checks the tag matches the
   packaged version, builds, publishes via OIDC, and then smoke-tests the published package by
   installing it fresh with `uvx` and running it. If that last job is red, the release didn't
   work even if the upload succeeded.

## Licence

By contributing, you agree that your contributions are licensed under the project's
[MIT licence](LICENSE).
