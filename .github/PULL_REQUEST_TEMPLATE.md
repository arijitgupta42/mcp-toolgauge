<!--
A PR description isn't a changelog — `git log` is already that. Write what a stranger reading
the repo in six months can't recover from the diff. Delete any heading that doesn't apply.
-->

## What and why

<!-- The problem, and the shape of the fix, in a few sentences. -->

## Decisions

<!-- Anything that had more than one reasonable answer, and why this one won. -->

## Verification

<!-- What you actually ran and what it proved. Name platforms when it matters, and say
plainly what you could not verify. -->

## Checklist

- [ ] `uv run pytest` passes (and `ruff`, `mypy mcp_toolgauge`)
- [ ] New behaviour has a test; a new lint rule has a positive **and** a negative fixture
- [ ] A new lint rule has a `docs/rules/MCP0xx.md` page explaining *why it matters*
- [ ] Any new dependency is justified above (prefer the standard library)
