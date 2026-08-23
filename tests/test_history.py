"""The score-history file: loading, appending, the cap, and the target mismatch.

The arithmetic here is pure -- `append_point` and the cap do not touch disk -- so it is
tested directly on hand-built histories, the way `eval/score.py` is. The one thing that
must survive a real round-trip through the filesystem and back is the shape, because that
file is committed and read by a browser; the canonical-json test is the guard against the
`exclude_none` trap that bit `ConfusionCell.selected` in Session 4.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mcp_doctor.history import (
    MAX_POINTS,
    HistoryError,
    ScoreHistory,
    append_point,
    load_history,
    record,
    write_history,
)
from mcp_doctor.model import CiReport, HealthPoint, HealthScore, LintResult, ServerInfo

LINT_ONLY = HealthScore(overall=97, lint_score=97, eval_score=None, errors=0, warnings=1)
COMPOSITE = HealthScore(overall=96, lint_score=100, eval_score=92, errors=0, warnings=0)
WHEN = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)


def point(overall: int, at: str, label: str | None = None) -> HealthPoint:
    return HealthPoint(
        recorded_at=at,
        label=label,
        health=HealthScore(overall=overall, lint_score=overall, errors=0, warnings=0),
    )


class TestLoad:
    def test_a_missing_file_is_none_not_an_error(self, tmp_path: Path) -> None:
        assert load_history(tmp_path / "absent.json") is None

    def test_a_valid_file_round_trips(self, tmp_path: Path) -> None:
        out = tmp_path / "h.json"
        original = ScoreHistory(target="t", points=(point(50, "2026-01-01T00:00:00+00:00"),))
        write_history(out, original)

        assert load_history(out) == original

    def test_a_malformed_file_raises_history_error(self, tmp_path: Path) -> None:
        out = tmp_path / "h.json"
        out.write_text("{ not json", encoding="utf-8")

        with pytest.raises(HistoryError):
            load_history(out)

    def test_a_wrong_shape_file_raises_history_error(self, tmp_path: Path) -> None:
        out = tmp_path / "h.json"
        out.write_text('{"target": "t", "points": [{"nope": 1}]}', encoding="utf-8")

        with pytest.raises(HistoryError):
            load_history(out)


class TestAppend:
    def test_it_adds_to_the_end_without_mutating(self) -> None:
        history = ScoreHistory(target="t", points=(point(50, "a"),))
        result = append_point(history, point(60, "b"))

        assert [p.recorded_at for p in result.points] == ["a", "b"]
        # The original is untouched -- append_point is pure.
        assert len(history.points) == 1

    def test_it_caps_at_the_limit_dropping_oldest(self) -> None:
        history = ScoreHistory(target="t")
        for i in range(MAX_POINTS + 5):
            history = append_point(history, point(50, str(i)))

        recorded = [p.recorded_at for p in history.points]
        assert len(recorded) == MAX_POINTS
        # The five oldest fell off the front; the newest is still there.
        assert recorded[0] == "5"
        assert recorded[-1] == str(MAX_POINTS + 4)

    def test_a_custom_limit_is_honoured(self) -> None:
        history = ScoreHistory(target="t")
        for i in range(10):
            history = append_point(history, point(50, str(i)), limit=3)

        assert [p.recorded_at for p in history.points] == ["7", "8", "9"]


class TestRecord:
    def test_it_creates_stamps_and_returns_the_series(self, tmp_path: Path) -> None:
        out = tmp_path / "h.json"
        history, warning = record(out, target="t", health=COMPOSITE, label="v1", now=WHEN)

        assert warning is None
        assert len(history.points) == 1
        stored = history.points[0]
        assert stored.label == "v1"
        assert stored.recorded_at == "2026-08-23T12:00:00+00:00"
        assert stored.health == COMPOSITE
        # And it is on disk, not just returned.
        assert load_history(out) == history

    def test_it_appends_on_a_second_call(self, tmp_path: Path) -> None:
        out = tmp_path / "h.json"
        record(out, target="t", health=LINT_ONLY, now=WHEN)
        history, _ = record(out, target="t", health=COMPOSITE, now=WHEN)

        assert [p.health.overall for p in history.points] == [97, 96]

    def test_a_target_mismatch_warns_but_still_appends(self, tmp_path: Path) -> None:
        out = tmp_path / "h.json"
        record(out, target="server-a", health=COMPOSITE, now=WHEN)
        history, warning = record(out, target="server-b", health=COMPOSITE, now=WHEN)

        assert warning is not None
        assert "server-a" in warning and "server-b" in warning
        # Appended anyway -- a mismatch is surfaced, not fatal.
        assert len(history.points) == 2

    def test_seconds_precision_drops_microseconds(self, tmp_path: Path) -> None:
        out = tmp_path / "h.json"
        messy = datetime(2026, 8, 23, 12, 0, 0, 123456, tzinfo=UTC)
        history, _ = record(out, target="t", health=COMPOSITE, now=messy)

        assert history.points[0].recorded_at == "2026-08-23T12:00:00+00:00"


class TestCanonicalRoundTrip:
    def test_a_history_bearing_report_survives_canonical_json(self, tmp_path: Path) -> None:
        """The exclude_none trap: a report with history must read back as itself.

        `HealthScore.eval_score` is None on a lint-only point, and canonical_json drops
        nulls; without a default on the field the point would fail to re-validate on the way
        back in -- exactly the ConfusionCell.selected bug from Session 4, one field over.
        """
        report = CiReport(
            target="t",
            server=ServerInfo(name="acme", version="1.0.0"),
            health=COMPOSITE,
            lint=LintResult(target="t", server=ServerInfo(name="acme"), tool_count=2),
            history=(
                HealthPoint(recorded_at="2026-08-23T12:00:00+00:00", health=LINT_ONLY),
                HealthPoint(
                    recorded_at="2026-08-23T13:00:00+00:00", label="v2", health=COMPOSITE
                ),
            ),
        )

        from mcp_doctor.model import canonical_json

        restored = CiReport.model_validate_json(canonical_json(report))
        assert restored == report
