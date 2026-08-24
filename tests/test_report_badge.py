"""The shields.io endpoint badge.

The badge is a four-key JSON document, so it is asserted inline rather than against a golden
-- a golden file for four keys is harder to read than the dict it encodes. What matters is
that the shape is exactly what shields.io expects, the message is the score, and the colour
tracks the same bands `color_for` defines.
"""

from __future__ import annotations

import json

from mcp_toolgauge.model import HealthScore
from mcp_toolgauge.report import render_badge


def badge(overall: int, **extra: object) -> dict[str, object]:
    health = HealthScore(overall=overall, lint_score=overall, **extra)
    return json.loads(render_badge(health))


class TestBadge:
    def test_it_is_a_shields_endpoint_document(self) -> None:
        assert badge(96) == {
            "schemaVersion": 1,
            "label": "mcp-toolgauge",
            "message": "96",
            "color": "brightgreen",
        }

    def test_the_message_is_the_score(self) -> None:
        assert badge(28)["message"] == "28"

    def test_the_colour_tracks_the_bands(self) -> None:
        assert badge(96)["color"] == "brightgreen"
        assert badge(78)["color"] == "green"
        assert badge(28)["color"] == "red"

    def test_a_lint_only_score_still_renders(self) -> None:
        """eval_score is None on a lint-only run; the badge shows the number regardless."""
        assert badge(91, eval_score=None)["message"] == "91"

    def test_the_label_can_be_overridden(self) -> None:
        text = render_badge(HealthScore(overall=50, lint_score=50), label="health")

        assert json.loads(text)["label"] == "health"

    def test_the_keys_are_sorted_so_the_file_is_diffable(self) -> None:
        payload = json.loads(render_badge(HealthScore(overall=50, lint_score=50)))

        assert list(payload) == sorted(payload)
