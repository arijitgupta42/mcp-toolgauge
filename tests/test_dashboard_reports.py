"""The dashboard's committed demo reports must stay valid `ci --json` output.

The dashboard ships two reports it renders on first paint, produced by scoring the two fixture
servers. They are real output, but they are committed rather than regenerated, so nothing
stops them drifting out of shape with the models if a field is renamed. This is not a golden
test -- `--history` stamps a live timestamp, so the bytes are not reproducible and a
`git diff` check would fail for reasons that are not bugs -- it is a shape check: every demo
report still validates as a `CiReport`, and still carries the parts the dashboard's three
views read (findings, a confusion matrix, a history series). If a model gains or loses a
field, this fails here rather than in a viewer's browser.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_toolgauge.model import CiReport

REPORTS = Path(__file__).resolve().parent.parent / "dashboard" / "public" / "reports"
DEMOS = ["goodserver", "badserver"]


def _load(name: str) -> CiReport:
    return CiReport.model_validate_json((REPORTS / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", DEMOS)
def test_demo_report_is_a_valid_ci_report(name: str) -> None:
    report = _load(name)
    assert 0 <= report.health.overall <= 100
    assert report.server.name


@pytest.mark.parametrize("name", DEMOS)
def test_demo_report_carries_a_history_for_the_history_view(name: str) -> None:
    report = _load(name)
    assert report.history is not None
    assert len(report.history) >= 2  # a trajectory needs at least two points to be a line
    for point in report.history:
        assert 0 <= point.health.overall <= 100


@pytest.mark.parametrize("name", DEMOS)
def test_demo_report_carries_an_eval_with_a_confusion_matrix(name: str) -> None:
    """Both fixtures have an eval suite, so both drive the Selection heatmap."""
    report = _load(name)
    assert report.eval is not None
    assert report.eval.scores.confusion  # non-empty: there is a matrix to draw


def test_the_two_demos_still_tell_the_good_vs_bad_story() -> None:
    """The whole point of the pair: one clean and high, one riddled and low. If a change
    closes that gap, the demo stops demonstrating anything, so it is asserted here."""
    good = _load("goodserver")
    bad = _load("badserver")
    assert good.health.overall >= 75
    assert bad.health.overall <= 45
    assert not (good.lint.findings or ())  # goodserver lints clean
    assert bad.lint.findings  # badserver does not
