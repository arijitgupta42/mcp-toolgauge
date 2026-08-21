"""The SARIF renderer.

SARIF exists so findings can land in a code-scanning UI. The unusual thing about ours is
that it carries no `physicalLocation`: we lint a running server, not a file, so there is no
line to point at and guessing one would annotate the wrong lines. These tests pin that
decision down, along with the fingerprint stability that stops a reworded message from
reopening every closed alert.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp_doctor.lint import all_rules
from mcp_doctor.model import Finding, LintResult, ServerInfo, Severity
from mcp_doctor.report import render_lint_sarif

GOLDEN = Path(__file__).parent / "golden" / "lint_report.sarif"

PINNED_VERSION = "0.1.0"


def document(report: LintResult) -> dict[str, Any]:
    return json.loads(render_lint_sarif(report, version=PINNED_VERSION))


def only_run(report: LintResult) -> dict[str, Any]:
    return document(report)["runs"][0]


def finding(**overrides: Any) -> Finding:
    defaults: dict[str, Any] = {
        "rule": "MCP020",
        "severity": Severity.WARNING,
        "message": "`search_users.query` has no description.",
        "suggestion": "Describe what `query` is for.",
        "tool": "search_users",
        "parameter": "query",
    }
    return Finding(**{**defaults, **overrides})


def report_of(*findings: Finding) -> LintResult:
    return LintResult(
        target="python server.py",
        server=ServerInfo(name="acme"),
        tool_count=1,
        findings=findings,
    )


class TestGolden:
    def test_matches_the_golden_file(self, sample_report: LintResult) -> None:
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))

        assert document(sample_report) == expected


class TestDocumentShape:
    def test_it_declares_sarif_2_1_0(self, sample_report: LintResult) -> None:
        payload = document(sample_report)

        assert payload["version"] == "2.1.0"
        assert payload["$schema"].endswith("sarif-2.1.0.json")

    def test_there_is_exactly_one_run(self, sample_report: LintResult) -> None:
        assert len(document(sample_report)["runs"]) == 1

    def test_one_result_per_finding(self, sample_report: LintResult) -> None:
        assert len(only_run(sample_report)["results"]) == len(sample_report.findings)

    def test_the_driver_publishes_the_whole_rule_catalogue(self, sample_report: LintResult) -> None:
        """Including rules this run did not trigger, so a viewer can explain any of them."""
        rules = only_run(sample_report)["tool"]["driver"]["rules"]

        assert {entry["id"] for entry in rules} == {rule.id for rule in all_rules()}

    def test_every_catalogue_entry_links_to_its_docs_page(self, sample_report: LintResult) -> None:
        for entry in only_run(sample_report)["tool"]["driver"]["rules"]:
            assert entry["helpUri"].endswith(f"docs/rules/{entry['id']}.md")

    def test_catalogue_names_are_pascal_case(self, sample_report: LintResult) -> None:
        for entry in only_run(sample_report)["tool"]["driver"]["rules"]:
            assert entry["name"][:1].isupper()
            assert "-" not in entry["name"]

    def test_the_driver_reports_our_version(self, sample_report: LintResult) -> None:
        assert only_run(sample_report)["tool"]["driver"]["version"] == PINNED_VERSION

    def test_keys_are_sorted_so_the_output_is_diffable(self, sample_report: LintResult) -> None:
        text = render_lint_sarif(sample_report, version=PINNED_VERSION)
        payload = json.loads(text)

        assert list(payload) == sorted(payload)


class TestLevels:
    def test_info_becomes_note(self) -> None:
        result = only_run(report_of(finding(severity=Severity.INFO)))["results"][0]

        assert result["level"] == "note", "SARIF has no 'info' level"

    def test_error_and_warning_pass_through(self) -> None:
        report = report_of(finding(severity=Severity.ERROR), finding(severity=Severity.WARNING))

        assert [r["level"] for r in only_run(report)["results"]] == ["error", "warning"]

    def test_the_catalogue_records_each_rule_s_default_level(
        self, sample_report: LintResult
    ) -> None:
        catalogue = only_run(sample_report)["tool"]["driver"]["rules"]
        rules = {e["id"]: e["defaultConfiguration"]["level"] for e in catalogue}

        assert rules["MCP013"] == "error"
        assert rules["MCP025"] == "note"


class TestLocations:
    def test_a_parameter_finding_is_a_logical_location(self) -> None:
        result = only_run(report_of(finding()))["results"][0]
        location = result["locations"][0]["logicalLocations"][0]

        assert location["fullyQualifiedName"] == "search_users.query"
        assert location["kind"] == "parameter"

    def test_a_tool_finding_is_a_function(self) -> None:
        result = only_run(report_of(finding(parameter=None)))["results"][0]
        location = result["locations"][0]["logicalLocations"][0]

        assert location["fullyQualifiedName"] == "search_users"
        assert location["kind"] == "function"

    def test_a_server_finding_falls_back_to_the_server(self) -> None:
        result = only_run(report_of(finding(tool=None, parameter=None)))["results"][0]

        assert result["locations"][0]["logicalLocations"][0]["fullyQualifiedName"] == "server"

    def test_nothing_claims_a_physical_location(self, sample_report: LintResult) -> None:
        """We lint a live server. Inventing a file and a line would annotate the wrong
        lines of somebody's source."""
        for result in only_run(sample_report)["results"]:
            assert "physicalLocation" not in json.dumps(result)


class TestMessages:
    def test_the_suggestion_travels_with_the_finding(self) -> None:
        result = only_run(report_of(finding()))["results"][0]

        assert "Describe what `query` is for." in result["message"]["text"]

    def test_the_message_leads_with_the_problem(self) -> None:
        result = only_run(report_of(finding()))["results"][0]

        assert result["message"]["text"].startswith("`search_users.query` has no description.")


class TestFingerprints:
    def _fingerprint(self, item: Finding) -> str:
        result = only_run(report_of(item))["results"][0]
        return str(result["partialFingerprints"]["mcpDoctorFinding/v1"])

    def test_the_same_finding_fingerprints_the_same_way(self) -> None:
        assert self._fingerprint(finding()) == self._fingerprint(finding())

    def test_rewording_a_message_does_not_change_the_fingerprint(self) -> None:
        """Otherwise improving a rule's wording reopens every alert it ever raised."""
        assert self._fingerprint(finding()) == self._fingerprint(
            finding(message="Rephrased entirely.", suggestion="Also rephrased.")
        )

    def test_a_different_location_fingerprints_differently(self) -> None:
        assert self._fingerprint(finding()) != self._fingerprint(finding(parameter="limit"))

    def test_a_different_rule_fingerprints_differently(self) -> None:
        assert self._fingerprint(finding()) != self._fingerprint(finding(rule="MCP021"))
