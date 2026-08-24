"""The registry and the runner.

Most of this file is integrity checking rather than behaviour testing. The house rule is
that a rule ships with an ID, a severity, a concrete suggestion, and a docs page explaining
why it matters -- and a checklist nobody runs is a checklist nobody follows. These tests
run it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mcp_toolgauge.lint import LintContext, all_rules, lint, rule_ids, run_rules
from mcp_toolgauge.model import InspectResult, ServerInfo, Severity, ToolSpec

REPO_ROOT = Path(__file__).parent.parent
DOCS = REPO_ROOT / "docs" / "rules"

RULE_ID = re.compile(r"^MCP\d{3}$")
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# A server bad enough that most rules have something to say about it, so the whole registry
# is exercised rather than just the rules a specific test remembered to name.
AWFUL = (
    ToolSpec(name="run", description=None, input_schema={"properties": {"payload": {}}}),
    ToolSpec(name="get_data", description="Get data."),
    ToolSpec(
        name="search_users",
        description="Searches the database and returns matching records for the given query.",
        input_schema={"properties": {"when": {"type": "string"}}},
    ),
    ToolSpec(
        name="search_orgs",
        description="Searches the database and returns matching records for the query given.",
    ),
    ToolSpec(name="doStuff", description="TODO: write this."),
    ToolSpec(name="delete_all_tickets", description="Deletes every ticket. There is no undo."),
)


def _context(*specs: ToolSpec) -> LintContext:
    return LintContext.build(ServerInfo(name="acme"), specs or AWFUL)


class TestRegistryIntegrity:
    def test_every_rule_has_a_well_formed_id(self) -> None:
        for rule in all_rules():
            assert RULE_ID.match(rule.id), rule.id

    def test_ids_are_unique(self) -> None:
        ids = [rule.id for rule in all_rules()]

        assert len(ids) == len(set(ids))

    def test_rules_come_back_in_id_order(self) -> None:
        """Registration order depends on which module Python imported first, which must
        not leak into report ordering or a golden file."""
        ids = [rule.id for rule in all_rules()]

        assert ids == sorted(ids)

    def test_every_rule_has_a_slug_and_a_summary(self) -> None:
        for rule in all_rules():
            assert SLUG.match(rule.name), f"{rule.id}: {rule.name!r} is not a kebab-case slug"
            assert rule.summary.strip(), rule.id
            assert rule.summary.endswith("."), f"{rule.id}: summary should be a sentence"

    def test_no_rule_is_registered_as_off(self) -> None:
        """`off` is a configuration value, not a severity a rule can ship with."""
        for rule in all_rules():
            assert rule.severity is not Severity.OFF, rule.id

    @pytest.mark.parametrize("rule", all_rules(), ids=lambda rule: rule.id)
    def test_every_rule_has_a_docs_page(self, rule) -> None:
        """The docs are the marketing: a rule without a persuasive "why" gets disabled."""
        page = REPO_ROOT / rule.docs_path

        assert page.is_file(), f"{rule.id} has no {rule.docs_path}"
        text = page.read_text(encoding="utf-8")
        assert "## Why it matters" in text
        assert "## Triggers when" in text
        assert "## Before" in text and "## After" in text

    def test_the_docs_index_lists_every_rule(self) -> None:
        index = (DOCS / "README.md").read_text(encoding="utf-8")

        for rule in all_rules():
            assert f"[{rule.id}]({rule.id}.md)" in index, f"{rule.id} missing from the index"

    def test_the_docs_index_has_no_rules_that_do_not_exist(self) -> None:
        index = (DOCS / "README.md").read_text(encoding="utf-8")
        listed = set(re.findall(r"\[(MCP\d{3})\]", index))

        assert listed == set(rule_ids())

    def test_there_are_no_orphaned_docs_pages(self) -> None:
        pages = {path.stem for path in DOCS.glob("MCP*.md")}

        assert pages == set(rule_ids())


class TestFindingQuality:
    """Enforced here rather than in review, because review does not scale."""

    def test_every_finding_carries_a_concrete_suggestion(self) -> None:
        for finding in run_rules(_context()):
            assert finding.suggestion.strip(), f"{finding.rule} reported a problem with no fix"
            assert len(finding.suggestion) > 40, f"{finding.rule}: suggestion is not concrete"

    def test_every_finding_has_a_message_that_ends_in_a_sentence(self) -> None:
        for finding in run_rules(_context()):
            assert finding.message.strip().endswith("."), finding.rule

    def test_a_tool_level_finding_names_a_tool_that_exists(self) -> None:
        names = {spec.name for spec in AWFUL}

        for finding in run_rules(_context()):
            if finding.tool is not None:
                assert finding.tool in names, finding.rule


class TestOrdering:
    def test_server_level_findings_come_first(self) -> None:
        findings = run_rules(
            LintContext.build(
                ServerInfo(name="acme"),
                (ToolSpec(name="search_users", description="x"), ToolSpec(name="doStuff")),
            )
        )

        assert findings[0].tool is None

    def test_findings_follow_the_server_s_tool_order(self) -> None:
        """Not alphabetical: the order the server advertises is the order the author reads
        their own code in."""
        findings = run_rules(_context())
        tools = [finding.tool for finding in findings if finding.tool is not None]
        first_seen = list(dict.fromkeys(tools))
        expected = [spec.name for spec in AWFUL if spec.name in set(first_seen)]

        assert first_seen == expected

    def test_the_same_input_always_produces_the_same_order(self) -> None:
        assert run_rules(_context()) == run_rules(_context())


class TestSeverityOverrides:
    def test_an_override_changes_a_finding_s_severity(self) -> None:
        findings = run_rules(_context(), severities={"MCP025": Severity.ERROR})
        info = [finding for finding in findings if finding.rule == "MCP025"]

        assert info and all(finding.severity is Severity.ERROR for finding in info)

    def test_off_removes_a_rule_entirely(self) -> None:
        findings = run_rules(_context(), severities={"MCP020": Severity.OFF})

        assert not [finding for finding in findings if finding.rule == "MCP020"]

    def test_an_override_for_one_rule_leaves_the_others_alone(self) -> None:
        baseline = run_rules(_context())
        adjusted = run_rules(_context(), severities={"MCP020": Severity.OFF})
        untouched = [finding for finding in baseline if finding.rule != "MCP020"]

        assert adjusted == tuple(untouched)


class TestLintResult:
    def _result(self) -> InspectResult:
        return InspectResult(target="python server.py", server=ServerInfo(name="acme"), tools=AWFUL)

    def test_the_result_carries_the_target_and_the_tool_count(self) -> None:
        report = lint(self._result())

        assert report.target == "python server.py"
        assert report.tool_count == len(AWFUL)

    def test_counts_always_have_all_three_severities(self) -> None:
        counts = lint(self._result()).counts()

        assert set(counts) == {Severity.ERROR, Severity.WARNING, Severity.INFO}

    def test_worst_is_none_for_a_clean_run(self) -> None:
        clean = InspectResult(target="t", server=ServerInfo(name="acme"), tools=())

        assert lint(clean).worst() is None

    def test_at_or_above_respects_the_floor(self) -> None:
        report = lint(self._result())

        assert len(report.at_or_above(Severity.ERROR)) < len(report.at_or_above(Severity.WARNING))

    def test_fail_on_off_never_matches_anything(self) -> None:
        assert lint(self._result()).at_or_above(Severity.OFF) == ()

    def test_a_server_with_no_tools_produces_no_findings(self) -> None:
        empty = InspectResult(target="t", server=ServerInfo(name="acme"), tools=())

        assert lint(empty).findings == ()
