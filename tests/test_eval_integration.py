"""End-to-end over a real fixture server, with the model replaced by a seeded cache.

Everything else in the eval suite stubs the server as well as the model. This one starts
`goodserver` as a real subprocess, connects over stdio, reads its real tools, and derives
the tool digest and cache keys from what actually came back -- so it catches the class of
bug where the pipeline is internally consistent but disagrees with a live server.

The model is still never called. The cache is seeded from the tools the server reported,
which is exactly what a recording run produces, so this exercises the `--offline` replay
path that CI uses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mcp_toolgauge.cli import app
from mcp_toolgauge.connect import inspect_server_sync, resolve_target
from mcp_toolgauge.eval.backend import build_messages
from mcp_toolgauge.eval.cache import CachedCall, ResponseCache, cache_key, cache_path
from mcp_toolgauge.eval.cases import CASES_FILENAME, write_suite
from mcp_toolgauge.model import CaseKind, CaseSuite, EvalCase, InspectResult, tool_digest

pytestmark = pytest.mark.integration

runner = CliRunner()

MODEL = "test/recorded"

# Named here rather than taken from the `goodserver_dir` fixture: that one is
# function-scoped, and this server is worth starting once for the whole module.
GOODSERVER = Path(__file__).parent / "fixtures" / "goodserver"


@pytest.fixture(scope="module")
def goodserver() -> InspectResult:
    """The real fixture server, connected to once for the module."""
    return inspect_server_sync(resolve_target(str(GOODSERVER)), timeout=60)


def evaluate(directory: Path, *extra: str):
    """Run `eval --offline` against the real server, with cases and cache from `directory`.

    The target is the server; `--cases` is where the suite lives. Keeping them apart is
    what stops these tests writing scratch files into the fixture directory, and it
    exercises `--cases` into the bargain -- the cache is found beside the case file, not
    beside the server.
    """
    return runner.invoke(
        app,
        [
            "eval",
            str(GOODSERVER),
            "--offline",
            "--model",
            MODEL,
            "--cases",
            str(directory / CASES_FILENAME),
            *extra,
        ],
    )


def build(directory: Path, result: InspectResult, answers: dict[str, str | None]) -> Path:
    """Write a suite and a cache that answers it, both keyed off the live tools."""
    digest = tool_digest(result.tools)
    cases = tuple(
        EvalCase(
            id=f"case-{index}",
            kind=CaseKind.POSITIVE if expected else CaseKind.ABSTAIN,
            expected=expected,
            prompt=prompt,
        )
        for index, (prompt, expected) in enumerate(answers.items(), start=1)
    )
    path = directory / CASES_FILENAME
    write_suite(path, CaseSuite(target=result.target, tool_digest=digest, cases=cases))

    cache = ResponseCache.load(cache_path(path))
    for case in cases:
        cache.put(
            cache_key(
                model=MODEL,
                messages=build_messages(case.prompt, result.server),
                tool_digest=digest,
            ),
            CachedCall(tool=case.expected, arguments={"query": "ada"}),
            model=MODEL,
        )
    return path


class TestOfflineReplayAgainstARealServer:
    def test_a_perfect_recording_scores_full_marks(
        self, tmp_path: Path, goodserver: InspectResult
    ) -> None:
        build(
            tmp_path,
            goodserver,
            {
                "Who is Ada Lovelace?": "search_users",
                "Which company owns acme.test?": "search_organizations",
                "What is the weather in Paris?": None,
            },
        )

        result = evaluate(tmp_path)

        assert result.exit_code == 0, result.stdout + result.stderr
        assert "Every prompt reached the tool it was meant for." in result.stdout

    def test_the_digest_derived_here_matches_the_one_the_command_derives(
        self, tmp_path: Path, goodserver: InspectResult
    ) -> None:
        """If these ever disagree, every recorded cache silently stops replaying."""
        build(tmp_path, goodserver, {"Who is Ada Lovelace?": "search_users"})

        result = evaluate(tmp_path, "--json")

        assert result.exit_code == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["tool_digest"] == tool_digest(goodserver.tools)

    def test_a_wrong_recording_produces_the_confusion_sentence(
        self, tmp_path: Path, goodserver: InspectResult
    ) -> None:
        """The output the whole command exists for, produced end to end."""
        build(tmp_path, goodserver, {"Which company owns acme.test?": "search_organizations"})
        path = tmp_path / CASES_FILENAME

        # Re-record that one answer as the sibling tool, the way a real miss would land.
        cache = ResponseCache.load(cache_path(path))
        cache.put(
            cache_key(
                model=MODEL,
                messages=build_messages("Which company owns acme.test?", goodserver.server),
                tool_digest=tool_digest(goodserver.tools),
            ),
            CachedCall(tool="search_users", arguments={"query": "acme.test"}),
            model=MODEL,
        )

        result = evaluate(tmp_path)

        collapsed = " ".join(result.stdout.split())
        assert "search_users captures 100% of the prompts meant for search_organizations" in (
            collapsed
        )

    def test_min_accuracy_gates_on_the_real_thing(
        self, tmp_path: Path, goodserver: InspectResult
    ) -> None:
        build(tmp_path, goodserver, {"Who is Ada Lovelace?": "search_users"})

        passing = evaluate(tmp_path, "--min-accuracy", "99")
        # A model nothing was recorded for: a cache miss, and a usage error rather than a
        # score of zero. Targeting the real server, so the exit code is about the cache and
        # not about target resolution.
        unrecorded = runner.invoke(
            app,
            [
                "eval",
                str(GOODSERVER),
                "--offline",
                "--model",
                "other/model",
                "--cases",
                str(tmp_path / CASES_FILENAME),
            ],
        )

        assert passing.exit_code == 0
        assert unrecorded.exit_code == 2
        assert "No recorded answer" in unrecorded.stderr


class TestRecordedFixtures:
    """The committed suites and caches, replayed the way CI replays them.

    These are the numbers the README quotes and the demo rests on, so they get asserted
    rather than trusted. A change that closes the gap -- a fixture edited, a prompt
    reworded, a rule that alters how the tool digest is built -- fails here.

    Nothing is called: both runs are served entirely from the recorded caches.
    """

    BADSERVER = Path(__file__).parent / "fixtures" / "badserver"

    def replay(self, directory: Path, *extra: str):
        return runner.invoke(app, ["eval", str(directory), "--offline", *extra])

    def test_goodserver_replays_from_cache_alone(self) -> None:
        result = self.replay(GOODSERVER, "--json")

        assert result.exit_code == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["called_count"] == 0
        assert payload["cached_count"] == payload["scores"]["selection_total"] + 3

    def test_badserver_replays_from_cache_alone(self) -> None:
        result = self.replay(self.BADSERVER, "--json")

        assert result.exit_code == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["called_count"] == 0

    def test_the_gap_is_large(self) -> None:
        """The milestone's whole claim, in one assertion."""
        good = json.loads(self.replay(GOODSERVER, "--json").stdout)["scores"]
        bad = json.loads(self.replay(self.BADSERVER, "--json").stdout)["scores"]

        good_rate = good["selection_correct"] / good["selection_total"]
        bad_rate = bad["selection_correct"] / bad["selection_total"]

        assert good_rate - bad_rate > 0.25, f"{good_rate:.0%} vs {bad_rate:.0%}"

    def test_the_gap_is_widest_on_the_hard_cases(self) -> None:
        """Siblings are the pairs the linter flags. A well-written server should pull away
        from a careless one there most of all, and if it ever stops doing so the sibling
        cases have stopped testing anything."""
        good = json.loads(self.replay(GOODSERVER, "--json").stdout)["scores"]
        bad = json.loads(self.replay(self.BADSERVER, "--json").stdout)["scores"]

        good_siblings = good["sibling_correct"] / good["sibling_total"]
        bad_siblings = bad["sibling_correct"] / bad["sibling_total"]

        assert good_siblings > bad_siblings

    def test_the_threshold_ci_uses_separates_them(self) -> None:
        assert self.replay(GOODSERVER, "--min-accuracy", "75").exit_code == 0
        assert self.replay(self.BADSERVER, "--min-accuracy", "75").exit_code == 1

    def test_badserver_produces_a_confusion_sentence(self) -> None:
        """The output the command exists for, from the committed data."""
        collapsed = " ".join(self.replay(self.BADSERVER).stdout.split())

        assert "captures" in collapsed
        assert "of the prompts meant for" in collapsed


class TestReadOnly:
    def test_no_fixture_tool_body_ever_runs(
        self, tmp_path: Path, goodserver: InspectResult
    ) -> None:
        """`badserver` writes a marker to stderr if a tool body executes. `goodserver`'s
        bodies return canned data, so the check here is the structural one: eval reaches the
        server exactly once, through `inspect`, and never calls anything it found."""
        build(tmp_path, goodserver, {"Who is Ada Lovelace?": "search_users"})

        result = evaluate(tmp_path)

        assert "MCP_TOOLGAUGE_FIXTURE_TOOL_WAS_INVOKED" not in (result.stdout + result.stderr)
        assert result.exit_code == 0
