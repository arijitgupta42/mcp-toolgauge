"""The `ci` command: the score, the gate, the badge, the comment, and lint-only.

Like the eval tests, every run here is offline against a stubbed server and a pre-seeded
cache, so nothing reaches a network. The gate is exercised at the extremes (--min-score 0
and 101) rather than at the exact fixture score, so the tests assert "the gate fires below
the line and not above it" without pinning a number a rule tweak would move.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mcp_toolgauge.cli import app
from mcp_toolgauge.eval.backend import build_messages
from mcp_toolgauge.eval.cache import CachedCall, ResponseCache, cache_key, cache_path
from mcp_toolgauge.eval.cases import CASES_FILENAME, write_suite
from mcp_toolgauge.model import (
    CaseKind,
    CaseSuite,
    EvalCase,
    InspectResult,
    ServerInfo,
    ToolSpec,
    tool_digest,
)

runner = CliRunner()

TOOLS = (
    ToolSpec(
        name="search_users",
        description="Find individual people in the staff directory by name or email.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "A name, e.g. 'Ada'."}},
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="search_orgs",
        description="Find organizations by name or email domain, such as 'acme.test'.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "A domain, e.g. 'acme'."}},
            "required": ["query"],
        },
    ),
)
DIGEST = tool_digest(TOOLS)
SERVER = ServerInfo(name="acme-directory", version="0.4.2")
MODEL = "openrouter/nvidia/nemotron-3.5-lightning:free"

CASES = (
    EvalCase(
        id="u1", kind=CaseKind.POSITIVE, expected="search_users", prompt="Who is Ada Lovelace?"
    ),
    EvalCase(
        id="o1", kind=CaseKind.POSITIVE, expected="search_orgs", prompt="Who owns acme.test?"
    ),
    EvalCase(id="a1", kind=CaseKind.ABSTAIN, prompt="What is the weather in Paris?"),
)

# A clean recorded run: both tools found, the off-topic prompt declined.
ANSWERS: dict[str, tuple[str | None, dict]] = {
    "Who is Ada Lovelace?": ("search_users", {"query": "Ada Lovelace"}),
    "Who owns acme.test?": ("search_orgs", {"query": "acme.test"}),
    "What is the weather in Paris?": (None, {}),
}


def _stub_fetch(target: str, **kwargs: object) -> InspectResult:
    return InspectResult(target="python server.py", server=SERVER, tools=TOOLS)


def _seed(directory: Path) -> None:
    cache = ResponseCache.load(cache_path(directory / CASES_FILENAME))
    for case in CASES:
        tool, arguments = ANSWERS[case.prompt]
        messages = build_messages(case.prompt, SERVER)
        key = cache_key(model=MODEL, messages=messages, tool_digest=DIGEST)
        cache.put(key, CachedCall(tool=tool, arguments=arguments), model=MODEL)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A directory with a committed suite, a full cache, and a stubbed server behind it."""
    monkeypatch.setattr("mcp_toolgauge.cli._fetch", _stub_fetch)
    suite = CaseSuite(target="python server.py", tool_digest=DIGEST, cases=CASES)
    write_suite(tmp_path / CASES_FILENAME, suite)
    _seed(tmp_path)
    return tmp_path


@pytest.fixture
def bare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A directory with a server but no eval suite -- the lint-only path."""
    monkeypatch.setattr("mcp_toolgauge.cli._fetch", _stub_fetch)
    return tmp_path


def run(*args: str):
    return runner.invoke(app, ["ci", *args])


class TestScore:
    def test_it_prints_the_scorecard_and_exits_zero(self, project: Path) -> None:
        result = run(str(project))

        assert result.exit_code == 0
        assert "Health" in result.stdout
        assert "selection" in result.stdout

    def test_json_carries_the_health_and_both_halves(self, project: Path) -> None:
        payload = json.loads(run(str(project), "--json").stdout)

        health = payload["health"]
        assert 0 <= health["overall"] <= 100
        assert 0 <= health["lint_score"] <= 100
        assert health["eval_score"] is not None
        assert payload["eval"]["scores"]["selection_total"] == 2


class TestGate:
    def test_below_min_score_exits_one(self, project: Path) -> None:
        result = run(str(project), "--min-score", "101")

        assert result.exit_code == 1

    def test_at_or_above_min_score_exits_zero(self, project: Path) -> None:
        assert run(str(project), "--min-score", "0").exit_code == 0

    def test_no_threshold_never_fails(self, project: Path) -> None:
        assert run(str(project)).exit_code == 0

    def test_the_scorecard_still_prints_when_the_gate_fails(self, project: Path) -> None:
        """A gate that hides why it failed is a gate people disable."""
        result = run(str(project), "--min-score", "101")

        assert result.exit_code == 1
        assert "Health" in result.stdout


class TestLintOnly:
    def test_a_server_with_no_suite_is_scored_on_lint_alone(self, bare: Path) -> None:
        result = run(str(bare))

        assert result.exit_code == 0
        assert "no eval suite" in result.stdout

    def test_json_marks_the_eval_absent(self, bare: Path) -> None:
        payload = json.loads(run(str(bare), "--json").stdout)

        # canonical_json drops None, so a lint-only run omits both the eval block and the
        # eval_score key -- absent is how "not measured" reads to a JSON consumer.
        assert "eval" not in payload
        assert "eval_score" not in payload["health"]


class TestBadge:
    def test_it_writes_a_shields_endpoint(self, project: Path, tmp_path: Path) -> None:
        out = tmp_path / "badge.json"
        result = run(str(project), "--badge", str(out))

        assert result.exit_code == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["schemaVersion"] == 1
        assert payload["label"] == "mcp-toolgauge"
        assert payload["message"].isdigit()
        assert payload["color"] in {
            "brightgreen", "green", "yellowgreen", "yellow", "orange", "red"
        }


class TestComment:
    def test_it_writes_the_markdown_to_a_file(self, project: Path, tmp_path: Path) -> None:
        out = tmp_path / "comment.md"
        run(str(project), "--markdown", str(out))

        text = out.read_text(encoding="utf-8")
        assert "mcp-toolgauge health" in text

    def test_dash_writes_the_comment_to_stdout(self, project: Path) -> None:
        result = run(str(project), "--markdown", "-")

        assert "mcp-toolgauge health" in result.stdout

    def test_a_baseline_adds_the_delta_column(self, project: Path, tmp_path: Path) -> None:
        baseline = tmp_path / "base.json"
        baseline.write_text(run(str(project), "--json").stdout, encoding="utf-8")

        result = run(str(project), "--markdown", "-", "--baseline", str(baseline))

        assert "vs base" in result.stdout

    def test_a_missing_baseline_is_not_fatal(self, project: Path, tmp_path: Path) -> None:
        """A base branch with no prior run still gets a comment, just without deltas."""
        result = run(str(project), "--markdown", "-", "--baseline", str(tmp_path / "absent.json"))

        assert result.exit_code == 0
        assert "vs base" not in result.stdout


class TestHistory:
    def test_it_creates_the_file_on_the_first_run(self, project: Path, tmp_path: Path) -> None:
        out = tmp_path / "history.json"
        result = run(str(project), "--history", str(out))

        assert result.exit_code == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert len(payload["points"]) == 1
        assert 0 <= payload["points"][0]["health"]["overall"] <= 100

    def test_a_second_run_appends_rather_than_replaces(
        self, project: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "history.json"
        run(str(project), "--history", str(out), "--history-label", "one")
        run(str(project), "--history", str(out), "--history-label", "two")

        payload = json.loads(out.read_text(encoding="utf-8"))
        assert [p["label"] for p in payload["points"]] == ["one", "two"]

    def test_the_series_is_embedded_in_json(self, project: Path, tmp_path: Path) -> None:
        out = tmp_path / "history.json"
        payload = json.loads(run(str(project), "--history", str(out), "--json").stdout)

        assert len(payload["history"]) == 1
        assert payload["history"][0]["health"]["overall"] == payload["health"]["overall"]

    def test_no_history_flag_omits_the_key(self, project: Path) -> None:
        """A run without --history is byte-identical in shape to before the field existed."""
        payload = json.loads(run(str(project), "--json").stdout)

        assert "history" not in payload

    def test_it_records_even_when_the_gate_fails(self, project: Path, tmp_path: Path) -> None:
        """The point of a chart is to show the drop, so a failing run must still be recorded."""
        out = tmp_path / "history.json"
        result = run(str(project), "--history", str(out), "--min-score", "101")

        assert result.exit_code == 1
        assert len(json.loads(out.read_text(encoding="utf-8"))["points"]) == 1

    def test_a_malformed_history_file_is_a_usage_error(
        self, project: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "history.json"
        out.write_text("not a history{", encoding="utf-8")

        result = run(str(project), "--history", str(out))

        assert result.exit_code == 2
        assert "history" in result.stderr.lower()


class TestErrors:
    def test_an_explicit_missing_case_file_is_a_usage_error(
        self, bare: Path, tmp_path: Path
    ) -> None:
        result = run(str(bare), "--cases", str(tmp_path / "nope.yaml"))

        assert result.exit_code == 2

    def test_a_cache_miss_offline_is_a_usage_error(self, project: Path) -> None:
        unrecorded = EvalCase(
            id="new", kind=CaseKind.POSITIVE, expected="search_users", prompt="Unrecorded."
        )
        write_suite(
            project / CASES_FILENAME,
            CaseSuite(target="t", tool_digest=DIGEST, cases=(*CASES, unrecorded)),
            force=True,
        )

        result = run(str(project))

        assert result.exit_code == 2
        assert "new" in result.stderr
