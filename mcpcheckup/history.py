"""The score history file: a server's health over time, for the dashboard's third view.

`ci` produces one number per run. A number is a fact; a trajectory is a story -- "this
branch dropped the score from 88 to 81" is the thing a maintainer actually wants to see -- and
nothing in the tool accumulated one until this file. `mcpcheckup ci --history <path>` appends
one point per run to a JSON file you commit, exactly the way the eval cache is a committed
artifact, and the dashboard reads it back.

The split of responsibilities mirrors the rest of the codebase. The *shape* of a point lives
in `model/health.py` (`HealthPoint`), because it crosses into `CiReport` and the JSON. The
*arithmetic* -- capping the series, spotting a target mismatch -- is pure functions here that
take data and return data, testable without a filesystem. Only `load_history` and
`write_history` touch disk, and `record` is the one orchestration seam the CLI calls, taking
`now` as an argument so the clock enters in exactly one place.

Like the eval cache and the badge, writing a history file writes to *your* repo, never to the
MCP server under inspection -- invariant 5 holds.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from mcpcheckup.model import HealthPoint, HealthScore

# A committed file that grows without bound is a committed file people delete. At 500 points
# -- one per CI run, so on a busy repo a few months of history -- the file is around 60 KB,
# still pleasant in a diff and instant for a browser to parse. Past that the oldest points
# fall off the front, because a health trend is about where you are heading, not about the
# first week.
MAX_POINTS = 500


class HistoryError(Exception):
    """A history file exists but could not be read as one.

    Its own exception, mapped to a usage error by the CLI, because the fix is a human one:
    the file is not JSON, or not the shape this tool writes, and appending to it blindly
    would either crash later or silently corrupt a record someone is keeping.
    """


class ScoreHistory(BaseModel):
    """A whole history file: the target it tracks, and every point recorded for it.

    `target` is stored, not decorative. A history file sits beside one server, and appending
    goodserver's score onto the file tracking badserver would produce a chart that lies. The
    target is recorded so a mismatch is *noticed* and warned about rather than silently mixed
    in -- the same reasoning behind `CaseSuite.tool_digest`.
    """

    model_config = ConfigDict(frozen=True)

    target: str
    points: tuple[HealthPoint, ...] = ()


def load_history(path: Path) -> ScoreHistory | None:
    """Read a history file. `None` when it does not exist yet; raise on a malformed one.

    Absent is the common first run and must be quiet -- there is nothing wrong with not yet
    having a history. Present-but-unreadable is different: it is a file someone is keeping,
    and appending to it as though it were empty would throw their record away, so it stops
    the run with a message instead.
    """
    if not path.is_file():
        return None
    try:
        return ScoreHistory.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise HistoryError(
            f"Could not read the history file at {path}: {exc}. "
            "Point --history at a fresh path, or fix or delete that file."
        ) from exc


def write_history(path: Path, history: ScoreHistory) -> None:
    """Persist a history file, deterministically. Creates the parent directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = history.model_dump(mode="json", exclude_none=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def append_point(
    history: ScoreHistory, point: HealthPoint, *, limit: int = MAX_POINTS
) -> ScoreHistory:
    """Return a new history with `point` on the end, capped to `limit` newest points.

    Pure: it does not touch disk and does not mutate its argument, so the capping logic is
    testable on its own. Oldest points drop off the front, because the trend that matters is
    the recent one and an unbounded committed file is a liability.
    """
    combined = (*history.points, point)
    if len(combined) > limit:
        combined = combined[len(combined) - limit :]
    return ScoreHistory(target=history.target, points=combined)


def _now_iso(now: datetime | None) -> str:
    """Current UTC time to the second, as the ISO string a `HealthPoint` stores.

    Seconds precision, not microseconds: a history point is a build, and sub-second detail is
    noise in a chart and churn in a diff. `now` is threaded in so a test pins a real value.
    """
    moment = now if now is not None else datetime.now(UTC)
    return moment.astimezone(UTC).replace(microsecond=0).isoformat()


def record(
    path: Path,
    *,
    target: str,
    health: HealthScore,
    label: str | None = None,
    now: datetime | None = None,
) -> tuple[ScoreHistory, str | None]:
    """Append this run's score to the history at `path`, and return it with any warning.

    The one function the CLI calls. It loads what is there (or starts fresh), appends a point
    stamped with `now`, writes it back, and returns the updated series so the run can embed it
    in its `CiReport`. The second element is a target-mismatch warning or `None`: a mismatch
    is surfaced, not fatal, because someone repointing a history file at a renamed server is
    doing something reasonable and the tool should say so rather than refuse.
    """
    existing = load_history(path)
    warning: str | None = None
    if existing is None:
        existing = ScoreHistory(target=target, points=())
    elif existing.target != target:
        warning = (
            f"The history at {path} was tracking {existing.target!r}, but this run is "
            f"{target!r}. Appending anyway; point --history at a per-server path to keep "
            "their trends apart."
        )

    point = HealthPoint(recorded_at=_now_iso(now), label=label, health=health)
    updated = append_point(existing, point)
    write_history(path, updated)
    return updated, warning
