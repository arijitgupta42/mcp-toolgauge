"""Shared fixtures.

The two fixture servers are real subprocesses, so anything that spawns them is marked
`integration` and can be deselected with `-m "not integration"` to keep the unit suite fast.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mcp_doctor.lint import LintContext, get_rule, lint
from mcp_doctor.model import InspectResult, LintResult, Problem, ServerInfo, ToolSpec

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
