# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-08-24

The first public release. `mcpcheckup` audits an MCP server three ways and rolls the result
into one health score you can gate a build on.

### Added

- **`inspect`** — connect to a server over stdio or Streamable HTTP and print the tools it
  advertises, resolving the target the way an MCP client does (`.mcp.json` and friends, or a
  conventional entrypoint).
- **`lint`** — 22 deterministic, offline rules across five families (naming, descriptions,
  parameters, annotations, context budget) for the things that stop a tool being selected.
  Rich, JSON, and SARIF output; `mcpcheckup.toml` for per-rule severity; a docs page per rule.
- **`eval`** — put your real tool definitions in front of a real model at temperature 0 and
  measure top-1 selection accuracy, with a confusion matrix showing which tool steals traffic
  from which. Cases are a committed artifact; every answer is cached, so a re-run is free and
  CI can replay the whole thing offline.
- **`ci`** — one 0–100 health score (`0.5·lint + 0.5·selection`), a threshold gate, a
  shields.io badge, an optional score-history file, and a composite GitHub Action that posts a
  scorecard on the pull request with the delta against the base branch.
- **Dashboard** — a static single-page app with three views (findings, the confusion heatmap,
  score history) over a `ci --json` report. No backend, nothing uploaded.
- Two fixture servers — the same directory-and-ticketing API written once carefully and once
  carelessly — scoring **96** and **28**, so every command has something to show on day one.

[Unreleased]: https://github.com/arijitgupta42/mcpcheckup/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/arijitgupta42/mcpcheckup/releases/tag/v0.1.0
