# Lint rules

Every rule is deterministic and offline. No rule calls a model, sends anything
anywhere, or invokes one of your tools -- `mcp-toolgauge lint` connects, lists tools,
disconnects, and does the rest locally. That is what makes it cheap enough to run on
every pull request.

Each page says *why the rule matters*, not just what it checks. If a rule's reasoning
does not apply to your server, turn it off -- that is a supported outcome, not a
workaround.

## Naming

What a model reads first, and weighs most.

| Rule | Severity | Checks |
|---|---|---|
| [MCP001](MCP001.md) | error | Two tools have names that reduce to the same words. |
| [MCP002](MCP002.md) | warning | Every word in the name is generic, so it says nothing about what the tool does. |
| [MCP003](MCP003.md) | warning | A subject named in the tool name never appears in its description. |
| [MCP004](MCP004.md) | warning | The server mixes naming conventions across its tools. |

## Description

Where a tool earns its selection.

| Rule | Severity | Checks |
|---|---|---|
| [MCP010](MCP010.md) | error | The tool has no description at all. |
| [MCP011](MCP011.md) | warning | The description is a fragment rather than a sentence. |
| [MCP012](MCP012.md) | warning | The description only repeats the words already in the name. |
| [MCP013](MCP013.md) | error | Two tools' descriptions are near-identical. |
| [MCP014](MCP014.md) | warning | A tool overlaps with a sibling and never says which to prefer. |
| [MCP015](MCP015.md) | error | A description still contains placeholder text. |

## Parameters

What the model has to invent once it has chosen.

| Rule | Severity | Checks |
|---|---|---|
| [MCP020](MCP020.md) | warning | A parameter has no description. |
| [MCP021](MCP021.md) | info | A parameter's description only repeats its name. |
| [MCP022](MCP022.md) | warning | A free-form string parameter looks like it has a fixed set of valid values. |
| [MCP023](MCP023.md) | warning | A date, email, or URL parameter declares no format or pattern. |
| [MCP024](MCP024.md) | warning | A parameter has no declared type, or is an object with no declared shape. |
| [MCP025](MCP025.md) | info | Nothing in the tool's schema shows an example value. |

## Annotations

What the tool does to the world, and who is allowed to skip asking.

| Rule | Severity | Checks |
|---|---|---|
| [MCP040](MCP040.md) | error | A tool that looks destructive declares no destructiveHint. |
| [MCP041](MCP041.md) | warning | A tool that looks read-only declares no readOnlyHint. |
| [MCP042](MCP042.md) | info | A tool that changes state declares no idempotentHint. |

## Budget

What every request pays before it reads the user.

| Rule | Severity | Checks |
|---|---|---|
| [MCP050](MCP050.md) | info | A single tool's definition is large enough to crowd out its neighbours. |
| [MCP051](MCP051.md) | warning | The server's tool definitions add up to a large context cost. |
| [MCP052](MCP052.md) | warning | The server has enough tools that selection accuracy suffers. |

## Severities

| Severity | Means |
|---|---|
| `error` | Actively costs you calls, or is a safety problem. Fails the build by default. |
| `warning` | Measurably degrades selection. Shown by default, does not fail the build. |
| `info` | Polish. Hidden unless you pass `-v`. |

`mcp-toolgauge lint` exits `1` when any finding reaches `--fail-on`, which defaults to
`error`. Use `--fail-on warning` to be stricter, or `--fail-on off` to report without
ever failing.

## Configuration

Put an `mcp-toolgauge.toml` next to your server, or a `[tool.mcp-toolgauge]` section in your
`pyproject.toml`. Discovery walks up from the target directory and stops at the first
file it finds.

```toml
[lint]
fail_on = "error"

[lint.rules]
MCP025 = "off"      # we do not want example values in descriptions
MCP041 = "error"    # annotations are not optional on this server
```

A rule set to `off` is not run at all. An unknown rule ID is a usage error rather than
a silent no-op, because a typo in this file is a rule somebody believes they turned
off.

Pass `--config PATH` to use one file explicitly, or `--no-config` to ignore whatever is
on disk -- useful when you want a CI run to be independent of what is checked in.
