"""Shared fixtures.

The two fixture servers are real subprocesses, so anything that spawns them is marked
`integration` and can be deselected with `-m "not integration"` to keep the unit suite fast.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

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
