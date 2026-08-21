"""Rendering a `LintResult` as SARIF 2.1.0, so findings land in a code-scanning UI.

One thing about this output is unusual and worth stating plainly: there are no
`physicalLocation`s in it. SARIF is built for tools that read files, and mcp-doctor reads a
*running server* -- we ask it over the protocol what tools it has, and it answers with
strings. There is no file and no line number to point at, and inventing one by guessing at
the author's source layout would produce annotations on the wrong lines.

So every result carries a `logicalLocation` instead: the tool name, or `tool.parameter`.
Consumers that expect physical locations degrade to showing the finding without a source
anchor, which is the honest outcome.
"""

from __future__ import annotations

import hashlib
import json

from mcp_doctor.lint import all_rules
from mcp_doctor.model import Finding, LintResult, Severity

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
INFORMATION_URI = "https://github.com/arijitgupta42/mcp-doctor"

# SARIF has four levels and none of them is "info".
_LEVELS: dict[Severity, str] = {
    Severity.ERROR: "error",
    Severity.WARNING: "warning",
    Severity.INFO: "note",
    Severity.OFF: "none",
}


def _pascal(slug: str) -> str:
    """`near-duplicate-tool-names` -> `NearDuplicateToolNames`, for SARIF's rule name."""
    return "".join(part[:1].upper() + part[1:] for part in slug.split("-") if part)


def _fingerprint(finding: Finding) -> str:
    """A stable identity for a finding, for deduplication across runs.

    Deliberately built from the rule and the location only, never the message. Rewording a
    rule's message is an improvement to the report; it should not make every existing
    finding look new and reopen a pile of closed alerts.
    """
    parts = (finding.rule, finding.tool or "", finding.parameter or "")
    return hashlib.sha256(json.dumps(parts).encode("utf-8")).hexdigest()[:16]


def _location(finding: Finding) -> dict[str, object]:
    name = finding.parameter or finding.tool or "server"
    qualified = finding.tool or "server"
    if finding.parameter:
        qualified = f"{qualified}.{finding.parameter}"
    return {
        "logicalLocations": [
            {
                "name": name,
                "fullyQualifiedName": qualified,
                "kind": "parameter" if finding.parameter else "function",
            }
        ]
    }


def _result(finding: Finding) -> dict[str, object]:
    return {
        "level": _LEVELS.get(finding.severity, "none"),
        "locations": [_location(finding)],
        # The suggestion rides along in the message. A finding that arrives in someone's
        # security tab without its fix is a finding they cannot act on from there.
        "message": {"text": f"{finding.message}\n\n{finding.suggestion}"},
        "partialFingerprints": {"mcpDoctorFinding/v1": _fingerprint(finding)},
        "ruleId": finding.rule,
    }


def _driver_rules() -> list[dict[str, object]]:
    """The full rule catalogue, whether or not this run produced findings for each.

    Publishing all of them makes the SARIF file self-describing: a viewer can explain a
    rule the run happened not to trigger, and the docs link is right there.
    """
    return [
        {
            "defaultConfiguration": {"level": _LEVELS.get(rule.severity, "none")},
            "help": {
                "text": f"{rule.summary} See {rule.help_uri} for why this matters.",
            },
            "helpUri": rule.help_uri,
            "id": rule.id,
            "name": _pascal(rule.name),
            "shortDescription": {"text": rule.summary},
        }
        for rule in all_rules()
    ]


def render_lint_sarif(result: LintResult, *, version: str) -> str:
    """Serialise a lint run as SARIF. Sorted keys, so it is golden-testable."""
    document = {
        "$schema": SARIF_SCHEMA,
        "runs": [
            {
                "results": [_result(finding) for finding in result.findings],
                "tool": {
                    "driver": {
                        "informationUri": INFORMATION_URI,
                        "name": "mcp-doctor",
                        "rules": _driver_rules(),
                        "version": version,
                    }
                },
            }
        ],
        "version": SARIF_VERSION,
    }
    return json.dumps(document, indent=2, sort_keys=True)
