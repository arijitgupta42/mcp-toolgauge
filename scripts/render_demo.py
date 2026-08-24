"""Generate the animated terminal demo in the README (docs/assets/demo.svg).

This is a build tool, not part of the package. It drives mcpcheckup's *own* renderers with a
recording Rich console, so every frame is real output -- the exact colours and layout a user
sees -- captured through `Console.export_svg` rather than mocked up. Three scenes, cross-faded
on a loop:

    1. lint   -- the MCP013 near-duplicate error, the finding the whole product hangs on
    2. eval   -- the confusion matrix, and "search_users captures 88% of prompts meant for ticket2"
    3. ci     -- the payoff: goodserver 96, badserver 28, side by side

It connects to the two fixture servers, so it is slow and spawns subprocesses -- the reason it
lives here and runs by hand, not in CI. CI only shape-checks the committed SVG
(tests/test_demo_asset.py), the same way the dashboard's demo reports are checked rather than
regenerated.

Run it from the repo root after any change that moves the output:

    uv run python scripts/render_demo.py
"""

from __future__ import annotations

import re
from itertools import pairwise
from pathlib import Path

from rich.console import Console
from rich.terminal_theme import TerminalTheme

from mcpcheckup.cli import _fetch, _replay_eval
from mcpcheckup.eval.backend import DEFAULT_MODEL
from mcpcheckup.health import health_score
from mcpcheckup.lint import lint as run_lint
from mcpcheckup.model.eval import EvalResult
from mcpcheckup.model.finding import Severity
from mcpcheckup.model.health import CiReport
from mcpcheckup.report.ci import render_ci_table
from mcpcheckup.report.eval import render_eval_table
from mcpcheckup.report.lint import render_lint_table

REPO = Path(__file__).resolve().parent.parent
BADSERVER = str(REPO / "tests" / "fixtures" / "badserver")
GOODSERVER = str(REPO / "tests" / "fixtures" / "goodserver")
OUT = REPO / "docs" / "assets" / "demo.svg"

WIDTH = 88  # terminal columns; wide enough for the confusion table, narrow enough to embed
SCENE_SECONDS = 7.0
FADE_SECONDS = 0.5

# A calm dark terminal, close to GitHub's dark canvas so the frame reads as a terminal on
# both README themes. Foreground/background plus the 16 ANSI slots the renderers use.
THEME = TerminalTheme(
    (13, 17, 23),  # background  #0d1117
    (201, 209, 217),  # foreground #c9d1d9
    [
        (48, 54, 61),  # black
        (248, 81, 73),  # red      -- error findings
        (63, 185, 80),  # green    -- passing / good
        (210, 153, 34),  # yellow   -- warnings
        (88, 166, 255),  # blue
        (188, 140, 255),  # magenta
        (57, 197, 207),  # cyan     -- identifiers (the styled() colour)
        (139, 148, 158),  # white / dim
    ],
    [
        (110, 118, 129),
        (255, 123, 114),
        (86, 211, 100),
        (227, 179, 65),
        (121, 192, 255),
        (210, 168, 255),
        (86, 211, 207),
        (176, 185, 195),
    ],
)


def _console() -> Console:
    """A recording console fixed to the demo width, colour forced on regardless of env."""
    return Console(record=True, width=WIDTH, force_terminal=True, color_system="truecolor")


def _evaluate(target: str) -> EvalResult:
    """Replay a fixture's committed eval cache, quietly -- no warnings into the frame."""
    result = _fetch(target, command=None, server=None, timeout=30.0)
    cases = Path(target) / "mcpcheckup-cases.yaml"
    # A throwaway quiet console swallows the loader's drift/validation notes; the caller
    # renders the returned result into the recording console itself.
    return _replay_eval(
        result, cases, model=DEFAULT_MODEL, json_output=True, console=Console(quiet=True)
    )


def _scene_lint() -> str:
    """badserver lint, focused on the search_users tool so the MCP013 error is the whole frame."""
    result = _fetch(BADSERVER, command=None, server=None, timeout=30.0)
    report = run_lint(result)
    focused = report.model_copy(
        update={"findings": tuple(f for f in report.findings if f.tool == "search_users")}
    )
    console = _console()
    render_lint_table(focused, console)
    errors = report.counts()[Severity.ERROR]
    console.print(
        f"[dim]  one of 10 tools shown · {len(report.findings)} findings in all, "
        f"{errors} errors · run:[/dim] [cyan]mcpcheckup lint <server>[/cyan]"
    )
    return console.export_svg(title="mcpcheckup lint  —  why won't this tool get called?",
                              theme=THEME, unique_id="scene-lint")


def _scene_eval() -> str:
    """badserver eval replayed offline -- the confusion matrix and the steal lines."""
    console = _console()
    render_eval_table(_evaluate(BADSERVER), console)
    return console.export_svg(title="mcpcheckup eval  —  where does the traffic actually go?",
                              theme=THEME, unique_id="scene-eval")


def _ci_report(target: str) -> CiReport:
    result = _fetch(target, command=None, server=None, timeout=30.0)
    lint_report = run_lint(result)
    evaluation = _evaluate(target)
    return CiReport(
        target=result.target,
        server=result.server,
        health=health_score(lint_report, evaluation.scores),
        lint=lint_report,
        eval=evaluation,
    )


def _scene_ci() -> str:
    """Both servers scored, side by side: the 96-vs-28 payoff."""
    console = _console()
    console.print("[bold]$ mcpcheckup ci goodserver[/bold]")
    render_ci_table(_ci_report(GOODSERVER), console)
    console.print()
    console.print("[bold]$ mcpcheckup ci badserver[/bold]")
    render_ci_table(_ci_report(BADSERVER), console)
    return console.export_svg(title="mcpcheckup ci  —  one score you can gate a build on",
                              theme=THEME, unique_id="scene-ci")


_SVG_OPEN = re.compile(r"<svg[^>]*\bviewBox=\"0 0 (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)\"[^>]*>")


def _dims(svg: str) -> tuple[float, float]:
    m = _SVG_OPEN.search(svg)
    if not m:
        raise ValueError("could not read viewBox from an exported scene")
    return float(m.group(1)), float(m.group(2))


def _inner(svg: str) -> str:
    """The content between the outer <svg> tags -- everything but the root element itself."""
    start = svg.index(">", svg.index("<svg")) + 1
    end = svg.rindex("</svg>")
    return svg[start:end]


def _keyframes(index: int, total: int) -> tuple[str, str]:
    """Opacity keyTimes/values for scene `index`, cross-fading on a seamless loop.

    Each scene owns a window [index*S, (index+1)*S] and holds opacity 1 across it, fading over
    FADE seconds at each edge. The loop point (t=0 == t=total) is a genuine cross-fade: the
    last scene fades out into it and scene 0 fades in out of it, so there is no flash. Built as
    an explicit piecewise list with strictly increasing times -- no dedup, no t=0 collision.
    """
    total_s = total * SCENE_SECONDS
    f = FADE_SECONDS
    ws, we = index * SCENE_SECONDS, (index + 1) * SCENE_SECONDS

    if index == 0:
        # Already on at t=0 (the wrap fade-in landed here); fade out, stay off, fade back in.
        points = [(0.0, 1.0), (we - f, 1.0), (we, 0.0), (total_s - f, 0.0), (total_s, 1.0)]
    elif we >= total_s:
        # Last scene: its fade-out ends exactly at the loop point.
        points = [(0.0, 0.0), (ws, 0.0), (ws + f, 1.0), (total_s - f, 1.0), (total_s, 0.0)]
    else:
        # A middle scene: off, fade in at its window, hold, fade out, off.
        points = [(0.0, 0.0), (ws, 0.0), (ws + f, 1.0), (we - f, 1.0), (we, 0.0), (total_s, 0.0)]

    times = [t for t, _ in points]
    if any(b <= a for a, b in pairwise(times)):  # guard the invariant SMIL requires
        raise ValueError(f"non-increasing keyTimes for scene {index}: {times}")
    key_times = ";".join(f"{t / total_s:.4f}" for t, _ in points)
    values = ";".join(f"{v:.0f}" for _, v in points)
    return key_times, values


def compose(scenes: list[str]) -> str:
    total = len(scenes)
    dims = [_dims(s) for s in scenes]
    width = max(w for w, _ in dims)
    height = max(h for _, h in dims)
    total_s = total * SCENE_SECONDS

    groups = []
    for i, (svg, (w, h)) in enumerate(zip(scenes, dims, strict=True)):
        key_times, values = _keyframes(i, total)
        # Anchor every scene at the top-left: a terminal window's title bar stays put and its
        # content grows downward, so a shorter frame should leave space at the bottom, not
        # float in the middle. Widths are equal, so this only matters vertically.
        nested = (
            f'<svg width="{w:.0f}" height="{h:.0f}" '
            f'viewBox="0 0 {w:.0f} {h:.0f}">{_inner(svg)}</svg>'
        )
        groups.append(
            f'<g opacity="{1 if i == 0 else 0}">'
            f'<animate attributeName="opacity" dur="{total_s:.0f}s" '
            f'repeatCount="indefinite" calcMode="linear" '
            f'keyTimes="{key_times}" values="{values}"/>'
            f"{nested}</g>"
        )

    body = "".join(groups)
    # A full-frame background in the terminal's own colour, so the area a shorter scene
    # doesn't cover reads as terminal padding rather than a transparent hole onto the README.
    bg = f'<rect width="{width:.0f}" height="{height:.0f}" rx="8" fill="rgb(13,17,23)"/>'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}">\n'
        f"<title>mcpcheckup: lint, eval, and CI-gate an MCP server</title>\n"
        f"{bg}\n{body}\n</svg>\n"
    )


def main() -> None:
    print("Rendering scenes (this connects to both fixture servers)...")
    scenes = [_scene_lint(), _scene_eval(), _scene_ci()]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(compose(scenes), encoding="utf-8")
    size_kb = OUT.stat().st_size / 1024
    print(f"Wrote {OUT.relative_to(REPO)} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
