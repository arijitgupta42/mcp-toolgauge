"""Shared fixtures.

The two fixture servers are real subprocesses, so anything that spawns them is marked
`integration` and can be deselected with `-m "not integration"` to keep the unit suite fast.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mcp_toolgauge.eval import check_arguments, score
from mcp_toolgauge.lint import LintContext, get_rule, lint
from mcp_toolgauge.model import (
    CaseKind,
    CaseOutcome,
    CaseSuite,
    EvalCase,
    EvalResult,
    InspectResult,
    LintResult,
    Problem,
    ServerInfo,
    ToolSpec,
    tool_digest,
)

REPO_ROOT = Path(__file__).parent.parent

FIXTURES = Path(__file__).parent / "fixtures"
BADSERVER = FIXTURES / "badserver"
GOODSERVER = FIXTURES / "goodserver"

# Rich decides colour from the environment, so a suite that inherits it is testing the
# environment as much as the code. CI once set FORCE_COLOR for prettier logs and turned
# three unrelated assertions red. Tests that care about colour set these themselves.
COLOUR_ENV = ("FORCE_COLOR", "NO_COLOR", "CLICOLOR", "CLICOLOR_FORCE", "TERM")


@pytest.fixture(autouse=True)
def neutral_colour_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in COLOUR_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def badserver_dir() -> Path:
    return BADSERVER


@pytest.fixture
def goodserver_dir() -> Path:
    return GOODSERVER


@pytest.fixture
def write_manifest(tmp_path: Path):
    """Write a manifest into a temp directory and hand back the directory."""

    def _write(payload: dict[str, Any], *, name: str = ".mcp.json") -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return tmp_path

    return _write


@pytest.fixture
def tool():
    """Build a `ToolSpec` for a rule test.

    The defaults describe a perfectly good tool, so a test only states the thing it is
    actually about. A negative fixture is usually the defaults untouched.
    """

    def _tool(
        name: str = "search_users",
        description: str | None = (
            "Find individual people in the staff directory by name, email, or employee ID."
        ),
        **overrides: Any,
    ) -> ToolSpec:
        return ToolSpec(name=name, description=description, **overrides)

    return _tool


@pytest.fixture
def problems():
    """Run one rule over some tools and return what it reported.

    Rules are called directly rather than through the engine, so a rule test observes the
    `Problem`s a rule produced without configuration or severity in the way.
    """

    def _problems(rule_id: str, *specs: ToolSpec) -> tuple[Problem, ...]:
        rule = get_rule(rule_id)
        assert rule is not None, f"no rule registered as {rule_id}"
        return tuple(rule.check(LintContext.build(ServerInfo(name="acme"), specs)))

    return _problems


# A deliberately bad three-tool server, small enough to golden-file and broad enough to
# exercise a server-level finding, a tool-level one, a parameter-level one, and all three
# severities. Hand-built rather than fetched, so the golden files do not move when the MCP
# SDK changes how it renders a schema.
_QUERY_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string", "title": "Query"}},
    "required": ["query"],
}

SAMPLE_TOOLS = (
    ToolSpec(
        name="search_users",
        description=(
            "Searches the database and returns matching records for the given query string."
        ),
        input_schema=_QUERY_SCHEMA,
    ),
    ToolSpec(
        name="search_orgs",
        description=(
            "Searches the database and returns matching records for the query string provided."
        ),
        input_schema=_QUERY_SCHEMA,
    ),
    ToolSpec(
        name="doStuff",
        description="TODO: document this properly.",
        input_schema={"type": "object", "properties": {"params": {"title": "Params"}}},
    ),
)


@pytest.fixture
def sample_report() -> LintResult:
    """A lint run over `SAMPLE_TOOLS`, for the renderer tests and their golden files."""
    return lint(
        InspectResult(
            target="python server.py",
            server=ServerInfo(name="acme-directory", version="0.4.2"),
            tools=SAMPLE_TOOLS,
        )
    )


# --------------------------------------------------------------------------------------
# Eval fixtures
# --------------------------------------------------------------------------------------

# A hand-built run over SAMPLE_TOOLS with known-correct answers, so the scoring tests and
# the renderer's golden file are both checkable by hand. Every number this produces is
# written out in tests/test_eval_score.py, which is the point: a metrics module nobody can
# verify by counting is a metrics module nobody should trust.
#
# The story it tells is the one the product is about -- `search_users` takes most of the
# traffic meant for `search_orgs`, because their descriptions are near-identical.
SAMPLE_MODEL = "openrouter/example/tiny:free"


def _case(name: str, kind: CaseKind, expected: str | None, rival: str | None = None) -> EvalCase:
    return EvalCase(
        id=name,
        kind=kind,
        expected=expected,
        rival=rival,
        prompt=f"A user utterance for {name}.",
    )


def _plan() -> tuple[tuple[EvalCase, str | None], ...]:
    """Each case paired with the tool the model picked. Hand-written, not measured."""
    entries: list[tuple[EvalCase, str | None]] = []

    # search_users is found three times in four; once it loses to its sibling.
    for index in range(1, 5):
        picked = "search_users" if index < 4 else "search_orgs"
        entries.append((_case(f"search_users-p{index}", CaseKind.POSITIVE, "search_users"), picked))

    # search_orgs is found once in four. This is the defect the whole report is about.
    for index in range(1, 5):
        picked = "search_orgs" if index == 1 else "search_users"
        entries.append((_case(f"search_orgs-p{index}", CaseKind.POSITIVE, "search_orgs"), picked))

    # doStuff has no competition, and is still missed once -- the model called nothing.
    for index, picked in ((1, "doStuff"), (2, None)):
        entries.append((_case(f"doStuff-p{index}", CaseKind.POSITIVE, "doStuff"), picked))

    # The hard cases, where the two siblings are deliberately confusable.
    for index, picked in ((1, "search_users"), (2, "search_orgs")):
        entries.append(
            (
                _case(
                    f"search_users-vs-search_orgs-s{index}",
                    CaseKind.SIBLING,
                    "search_users",
                    "search_orgs",
                ),
                picked,
            )
        )
    for index in (1, 2):
        entries.append(
            (
                _case(
                    f"search_orgs-vs-search_users-s{index}",
                    CaseKind.SIBLING,
                    "search_orgs",
                    "search_users",
                ),
                "search_users",
            )
        )

    # One abstain honoured, one not.
    entries.append((_case("abstain-1", CaseKind.ABSTAIN, None), None))
    entries.append((_case("abstain-2", CaseKind.ABSTAIN, None), "search_users"))
    return tuple(entries)


# Argument payloads by case id, for the three calls that are meant to be wrong. Everything
# else gets a valid payload for whichever tool was called, so a test that cares about
# arguments states only the calls it is about.
_ARGUMENTS: dict[str, dict[str, Any]] = {
    "search_users-p2": {},  # missing the required query
    "search_orgs-p3": {"query": 42},  # wrong type
    "search_users-vs-search_orgs-s1": {"query": "ada", "limit": 10},  # undeclared parameter
}

# A well-formed call for each tool. Keyed by tool rather than shared, so the fixture reads
# as a plausible run rather than as one tool's arguments handed to another.
_VALID: dict[str, dict[str, Any]] = {
    "search_users": {"query": "ada"},
    "search_orgs": {"query": "acme"},
    "doStuff": {"params": {"mode": "full"}},
}


def _outcomes() -> tuple[CaseOutcome, ...]:
    by_name = {tool.name: tool for tool in SAMPLE_TOOLS}
    built: list[CaseOutcome] = []
    for case, picked in _plan():
        tool = by_name.get(picked or "")
        arguments = _ARGUMENTS.get(case.id, _VALID.get(picked or "", {})) if tool else {}
        built.append(
            CaseOutcome(
                case=case,
                selected=picked,
                arguments=arguments,
                arguments_check=check_arguments(tool, arguments) if tool else None,
                cached=True,
            )
        )
    return tuple(built)


@pytest.fixture
def sample_outcomes() -> tuple[CaseOutcome, ...]:
    return _outcomes()


@pytest.fixture
def sample_suite() -> CaseSuite:
    return CaseSuite(
        target="python server.py",
        tool_digest=tool_digest(SAMPLE_TOOLS),
        generated_with=SAMPLE_MODEL,
        cases=tuple(case for case, _ in _plan()),
    )


@pytest.fixture
def sample_eval() -> EvalResult:
    """A full run over `SAMPLE_TOOLS`, for the renderer tests and their golden file."""
    outcomes = _outcomes()
    return EvalResult(
        target="python server.py",
        server=ServerInfo(name="acme-directory", version="0.4.2"),
        model=SAMPLE_MODEL,
        tool_digest=tool_digest(SAMPLE_TOOLS),
        scores=score(outcomes),
        outcomes=outcomes,
        cached_count=len(outcomes),
    )


@pytest.fixture
def sample_tools() -> tuple[ToolSpec, ...]:
    return SAMPLE_TOOLS
