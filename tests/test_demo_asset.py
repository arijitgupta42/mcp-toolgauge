"""The README demo SVG is committed, real output -- these keep it honest.

`scripts/render_demo.py` captures real mcpcheckup output into docs/assets/demo.svg. That
script connects to both fixture servers, so it runs by hand, not in CI (the same reason the
dashboard's demo reports are committed rather than regenerated). What CI *can* cheaply do is
shape-check the committed file: that it is a valid, animated SVG and that it still tells the
story the README promises. If a change moves the output enough that the demo no longer shows
the MCP013 error, the 88% confusion, or the 96-vs-28 gap, this fails and the demo gets
regenerated -- rather than the README quietly showing a stale screenshot.

Deliberately not a byte-for-byte golden: the point is the story is present, not that the
pixels never move.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parent.parent / "docs" / "assets" / "demo.svg"
SVG_NS = "http://www.w3.org/2000/svg"


@pytest.fixture(scope="module")
def svg_text() -> str:
    if not DEMO.is_file():
        pytest.fail(f"{DEMO} is missing; regenerate it with `uv run python scripts/render_demo.py`")
    return DEMO.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rendered_text(svg_text: str) -> str:
    """All text drawn in the SVG, as one whitespace-collapsed string.

    Rich emits each styled run as its own `<text>` element and every space as a
    non-breaking space, so a line like "Health  96 / 100" arrives as several elements.
    Collapsing all whitespace to single spaces stitches a line back into the phrase a
    reader sees, which is what the story assertions match against.
    """
    root = ET.fromstring(svg_text)
    parts = [el.text for el in root.iter(f"{{{SVG_NS}}}text") if el.text]
    return " ".join(" ".join(parts).split())


def test_is_valid_svg(svg_text: str) -> None:
    root = ET.fromstring(svg_text)  # raises on malformed XML
    assert root.tag == f"{{{SVG_NS}}}svg"


def test_three_scenes_animate_on_a_loop(svg_text: str) -> None:
    root = ET.fromstring(svg_text)
    animates = list(root.iter(f"{{{SVG_NS}}}animate"))
    assert len(animates) == 3, "expected exactly three cross-faded scenes"
    for a in animates:
        assert a.get("attributeName") == "opacity"
        assert a.get("repeatCount") == "indefinite", "the demo must loop"


def test_scene_styles_are_scoped(svg_text: str) -> None:
    # Each scene is exported with its own unique_id so the three <style> blocks don't collide
    # when combined into one document.
    for uid in ("scene-lint", "scene-eval", "scene-ci"):
        assert uid in svg_text, f"missing scene {uid!r}"


@pytest.mark.parametrize(
    "token",
    [
        "MCP013",  # scene 1: the near-duplicate-description error, the whole pitch
        "search_users",  # scene 2: the tool that steals the traffic
        "ticket2",  # scene 2: the tool it steals from
        "88%",  # scene 2: the money number
        "captures",  # scene 2: "... captures 88% of the prompts meant for ..."
        "Health",  # scene 3: the scorecard
        "96 / 100",  # scene 3: goodserver
        "28 / 100",  # scene 3: badserver
    ],
)
def test_story_is_present(rendered_text: str, token: str) -> None:
    assert token in rendered_text, f"the demo no longer shows {token!r}; regenerate it"


def test_stays_small_enough_to_embed(svg_text: str) -> None:
    # An inline README image people actually wait to load. Real output is ~50 KB; the ceiling
    # only catches a regression that balloons it (e.g. an accidental raster embed).
    assert len(svg_text.encode("utf-8")) < 200_000
