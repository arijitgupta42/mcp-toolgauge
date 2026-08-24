# Security Policy

## Reporting a vulnerability

Please report security issues privately, not in a public issue. Use GitHub's
[private vulnerability reporting](https://github.com/arijitgupta42/mcpcheckup/security/advisories/new)
(the **Security** tab → **Report a vulnerability**), which opens a confidential channel with
the maintainer.

You can expect an acknowledgement within a few days. Once a fix is available, the advisory is
published and the reporter credited unless they'd rather not be.

## What's in scope

`mcpcheckup` connects to MCP servers and reads their tool definitions. The parts worth
scrutiny:

- **The connection layer** — it starts a server you point it at (a subprocess for stdio, an
  HTTP client for a URL). `mcpcheckup` is read-only by design: it lists tools and disconnects,
  and **never invokes one of your tools**. A path that violates that read-only contract is a
  security bug, not just a correctness one.
- **The eval backend** — `eval` (without `--offline`) sends your tool definitions to whatever
  model `--model` names, through your own API key. It sends nothing anywhere else, and
  `--offline` sends nothing at all.
- **Untrusted report input** — the dashboard and the `--baseline` path parse JSON reports that
  may come from elsewhere. Parser crashes or unsafe handling of a hostile report are in scope.

## What's not

- Findings from linting a deliberately malicious server. `mcpcheckup` reports on a server's
  tool definitions; it does not sandbox or defend against a server that is itself hostile.
  Point it at servers you're willing to start.
- The two fixtures under `tests/fixtures/badserver/` are *intentionally* full of bad practice
  — that's their job as the demo villain. Findings there are the tool working, not a vuln.
