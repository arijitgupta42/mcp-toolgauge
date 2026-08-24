"""The `eval` command: wiring, exit codes, and the errors people will actually hit.

Every test here runs against a stubbed server and a pre-seeded cache, so nothing reaches a
network. The exit codes matter as much as the output -- this is a CI tool, and a command
that prints the right thing and exits the wrong way is broken.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mcpcheckup.cli import app
from mcpcheckup.eval.backend import Completion, ToolCall, build_messages
from mcpcheckup.eval.cache import CachedCall, ResponseCache, cache_key, cache_path
from mcpcheckup.eval.cases import CASES_FILENAME, write_suite
from mcpcheckup.model import (
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
        description="Find people in the staff directory by name or email.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="search_orgs",
        description="Find organizations by name or email domain.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
)
DIGEST = tool_digest(TOOLS)
SERVER = ServerInfo(name="acme-directory", version="0.4.2")

CASES = (
    EvalCase(
        id="search_users-p1",
        kind=CaseKind.POSITIVE,
        expected="search_users",
        prompt="Who is Ada Lovelace?",
    ),
    EvalCase(
        id="search_orgs-p1",
        kind=CaseKind.POSITIVE,
        expected="search_orgs",
        prompt="Which company owns acme.test?",
    ),
    EvalCase(id="abstain-1", kind=CaseKind.ABSTAIN, prompt="What is the weather in Paris?"),
)

# What the recorded model did: found the first, lost the second to its sibling, and
# correctly declined the third.
ANSWERS: dict[str, tuple[str | None, dict]] = {
    "Who is Ada Lovelace?": ("search_users", {"query": "Ada Lovelace"}),
    "Which company owns acme.test?": ("search_users", {"query": "acme.test"}),
    "What is the weather in Paris?": (None, {}),
}


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A directory with a case file, a full cache, and a stubbed server behind it."""

    def fake_fetch(target: str, **kwargs) -> InspectResult:
        return InspectResult(target="python server.py", server=SERVER, tools=TOOLS)

    monkeypatch.setattr("mcpcheckup.cli._fetch", fake_fetch)

    write_suite(
        tmp_path / CASES_FILENAME,
        CaseSuite(target="python server.py", tool_digest=DIGEST, cases=CASES),
    )
    seed_cache(tmp_path)
    return tmp_path


def seed_cache(directory: Path, model: str = "openrouter/nvidia/nemotron-3.5-lightning:free"):
    cache = ResponseCache.load(cache_path(directory / CASES_FILENAME))
    for case in CASES:
        tool, arguments = ANSWERS[case.prompt]
        key = cache_key(
            model=model, messages=build_messages(case.prompt, SERVER), tool_digest=DIGEST
        )
        cache.put(key, CachedCall(tool=tool, arguments=arguments), model=model)
    return cache


def run(*args: str):
    return runner.invoke(app, ["eval", *args])


class TestOfflineRun:
    def test_it_scores_from_the_cache_and_exits_zero(self, project: Path) -> None:
        result = run(str(project), "--offline")

        assert result.exit_code == 0
        assert "Selection accuracy" in result.stdout

    def test_the_money_line_appears(self, project: Path) -> None:
        result = run(str(project), "--offline")

        assert "search_users captures 100% of the prompts meant for search_orgs" in " ".join(
            result.stdout.split()
        )

    def test_the_run_is_free(self, project: Path) -> None:
        result = run(str(project), "--offline")

        assert "from cache" in result.stdout
        assert "free" in result.stdout

    def test_json_is_machine_readable(self, project: Path) -> None:
        result = run(str(project), "--offline", "--json")

        payload = json.loads(result.stdout)
        assert payload["scores"]["selection_correct"] == 1
        assert payload["scores"]["selection_total"] == 2

    def test_verbose_shows_the_failing_prompt(self, project: Path) -> None:
        result = run(str(project), "--offline", "-v")

        assert "Which company owns acme.test?" in result.stdout


class TestThresholds:
    def test_below_min_accuracy_exits_one(self, project: Path) -> None:
        result = run(str(project), "--offline", "--min-accuracy", "80")

        assert result.exit_code == 1

    def test_above_min_accuracy_exits_zero(self, project: Path) -> None:
        result = run(str(project), "--offline", "--min-accuracy", "40")

        assert result.exit_code == 0

    def test_the_report_still_prints_when_the_gate_fails(self, project: Path) -> None:
        """A gate that hides the reason it failed is a gate people disable."""
        result = run(str(project), "--offline", "--min-accuracy", "99")

        assert result.exit_code == 1
        assert "Selection accuracy" in result.stdout

    def test_no_threshold_never_fails(self, project: Path) -> None:
        assert run(str(project), "--offline").exit_code == 0


class TestCaseFileErrors:
    def test_a_missing_case_file_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "mcpcheckup.cli._fetch",
            lambda target, **kw: InspectResult(target="t", server=SERVER, tools=TOOLS),
        )

        result = run(str(tmp_path), "--offline")

        assert result.exit_code == 2
        assert "--init" in result.stderr

    def test_a_case_naming_a_missing_tool_is_a_usage_error(self, project: Path) -> None:
        write_suite(
            project / CASES_FILENAME,
            CaseSuite(
                target="t",
                tool_digest=DIGEST,
                cases=(
                    EvalCase(
                        id="gone", kind=CaseKind.POSITIVE, expected="deleted_tool", prompt="p"
                    ),
                ),
            ),
            force=True,
        )

        result = run(str(project), "--offline")

        assert result.exit_code == 2
        assert "deleted_tool" in result.stderr

    def test_a_cache_miss_offline_is_a_usage_error_that_explains_itself(
        self, project: Path
    ) -> None:
        write_suite(
            project / CASES_FILENAME,
            CaseSuite(
                target="t",
                tool_digest=DIGEST,
                cases=(
                    *CASES,
                    EvalCase(
                        id="new-one",
                        kind=CaseKind.POSITIVE,
                        expected="search_users",
                        prompt="A prompt nobody recorded.",
                    ),
                ),
            ),
            force=True,
        )

        result = run(str(project), "--offline")

        assert result.exit_code == 2
        assert "new-one" in result.stderr
        assert "Re-record" in result.stderr


class TestWarnings:
    def test_drifted_tools_warn_but_still_run(self, project: Path) -> None:
        """Re-measuring after an edit is exactly what somebody is usually here to do."""
        write_suite(
            project / CASES_FILENAME,
            CaseSuite(target="t", tool_digest="stale-digest", cases=CASES),
            force=True,
        )

        result = run(str(project), "--offline")

        assert result.exit_code == 0
        assert "not comparable" in " ".join(result.stdout.split())

    def test_an_unmeasured_tool_is_called_out(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        extra = (*TOOLS, ToolSpec(name="archive_ticket", description="Archive a ticket."))
        monkeypatch.setattr(
            "mcpcheckup.cli._fetch",
            lambda target, **kw: InspectResult(target="t", server=SERVER, tools=extra),
        )

        result = run(str(project), "--offline")

        assert "archive_ticket" in result.stdout

    def test_json_output_carries_no_warning_chatter(self, project: Path) -> None:
        """A payload with a warning line stapled to the front is not JSON."""
        write_suite(
            project / CASES_FILENAME,
            CaseSuite(target="t", tool_digest="stale-digest", cases=CASES),
            force=True,
        )

        result = run(str(project), "--offline", "--json")

        json.loads(result.stdout)


DRAFT_REPLY = json.dumps(
    {
        "prompts": [
            "Who handles billing over there?",
            "Find the person who filed this ticket.",
        ],
        "a": ["Who runs the platform team?"],
        "b": ["Which firm owns that domain?"],
    }
)


class TestInit:
    def draft(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Stub the text completer so `--init` drafts a suite without a model."""

        def reply(**kwargs: object) -> tuple[str, Completion]:
            return DRAFT_REPLY, Completion(call=ToolCall())

        monkeypatch.setattr("mcpcheckup.eval.backend.complete_text", reply)

    def test_it_writes_a_case_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "mcpcheckup.cli._fetch",
            lambda target, **kw: InspectResult(target="t", server=SERVER, tools=TOOLS),
        )
        self.draft(monkeypatch)

        result = run(str(tmp_path), "--init", "--cases-per-tool", "2")

        assert result.exit_code == 0
        assert (tmp_path / CASES_FILENAME).is_file()
        assert "Read them before you trust the score" in result.stdout

    def test_it_refuses_to_overwrite(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The committed-artifact invariant, at the command line."""
        self.draft(monkeypatch)

        result = run(str(project), "--init")

        assert result.exit_code == 2
        assert "already exists" in result.stderr

    def test_force_overwrites(self, project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.draft(monkeypatch)

        result = run(str(project), "--init", "--force", "--cases-per-tool", "2")

        assert result.exit_code == 0

    def test_a_server_with_no_tools_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "mcpcheckup.cli._fetch",
            lambda target, **kw: InspectResult(target="t", server=SERVER, tools=()),
        )

        result = run(str(tmp_path), "--init")

        assert result.exit_code == 2
        assert "no tools" in result.stderr


class TestCasesOption:
    def test_an_explicit_path_is_used(self, project: Path, tmp_path: Path) -> None:
        elsewhere = tmp_path / "nested" / "suite.yaml"
        write_suite(
            elsewhere, CaseSuite(target="t", tool_digest=DIGEST, cases=CASES[:1])
        )
        seed = ResponseCache.load(cache_path(elsewhere))
        seed.put(
            cache_key(
                model="openrouter/nvidia/nemotron-3.5-lightning:free",
                messages=build_messages(CASES[0].prompt, SERVER),
                tool_digest=DIGEST,
            ),
            CachedCall(tool="search_users", arguments={"query": "Ada"}),
            model="openrouter/nvidia/nemotron-3.5-lightning:free",
        )

        result = run(str(project), "--offline", "--cases", str(elsewhere))

        assert result.exit_code == 0
        assert "1 case" in result.stdout


class TestModelSelection:
    def test_a_different_model_does_not_reuse_the_recorded_answers(
        self, project: Path
    ) -> None:
        """Two models are two different questions, so the cache must not answer for one
        with the other's recording."""
        result = run(str(project), "--offline", "--model", "openrouter/someone/else:free")

        assert result.exit_code == 2
        assert "No recorded answer" in result.stderr

    def test_the_named_model_appears_in_the_report(self, project: Path) -> None:
        """A score without a model name is not a score."""
        result = run(str(project), "--offline")

        assert "openrouter/nvidia/nemotron-3.5-lightning:free" in result.stdout
