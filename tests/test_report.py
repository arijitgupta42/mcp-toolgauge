"""The renderer, driven directly so colour behaviour can actually be observed.

Going through the CLI is not enough here: `CliRunner` output is never a terminal, so Rich
disables colour regardless and a NO_COLOR assertion there passes whether or not NO_COLOR is
honoured. These tests force a terminal so the check means something.
"""

from __future__ import annotations

import io
import re

import pytest
from rich.console import Console

from mcp_toolgauge.model import InspectResult, ServerInfo, ToolAnnotations, ToolSpec
from mcp_toolgauge.report import render_inspect_table

ANSI = re.compile(r"\x1b\[[0-9;]*m")

# Colour specifically -- foreground/background SGR codes, not attributes like bold (1) or
# dim (2). NO_COLOR governs colour; Rich keeps text attributes, which the spec allows.
COLOUR = re.compile(r"\x1b\[[0-9;]*?(?:3[0-7]|4[0-7]|9[0-7]|10[0-7]|38;|48;)[0-9;]*m")


def _result(*tools: ToolSpec) -> InspectResult:
    return InspectResult(
        target="python server.py",
        server=ServerInfo(name="acme", version="1.0.0", instructions="Do the thing."),
        tools=tools or (ToolSpec(name="search_users", description="Find people."),),
    )


def _render(
    *tools: ToolSpec,
    width: int = 100,
    verbose: bool = False,
    force_terminal: bool = False,
) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, width=width, force_terminal=force_terminal)
    render_inspect_table(_result(*tools), console, verbose=verbose)
    return buffer.getvalue()


# A tool that actually exercises a coloured style: a declared hint renders cyan, and a
# missing description renders red. Without one of these the output is only bold and dim.
COLOURFUL = ToolSpec(
    name="archive_ticket",
    description=None,
    annotations=ToolAnnotations(read_only_hint=True),
)


class TestColour:
    def test_a_terminal_gets_colour(self) -> None:
        assert COLOUR.search(_render(COLOURFUL, force_terminal=True))

    def test_no_color_removes_colour_on_a_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_COLOR", "1")

        # Bold and dim survive -- NO_COLOR governs colour, not text attributes.
        assert not COLOUR.search(_render(COLOURFUL, force_terminal=True))

    def test_a_pipe_gets_no_escapes_at_all(self) -> None:
        assert not ANSI.search(_render())


class TestLayout:
    @pytest.mark.parametrize("width", [40, 60, 80, 120, 200])
    def test_no_line_exceeds_the_terminal_width(self, width: int) -> None:
        for line in _render(width=width).splitlines():
            assert len(line) <= width

    @pytest.mark.parametrize("width", [40, 60, 80, 120, 200])
    def test_output_is_ascii_at_any_width(self, width: int) -> None:
        assert _render(width=width).isascii()

    def test_the_tool_name_is_never_truncated_away(self) -> None:
        """A collapsed name column was a real regression; the name is the one thing we owe."""
        assert "search_users" in _render(width=40)


class TestContent:
    def test_a_missing_description_is_flagged(self) -> None:
        buffer = io.StringIO()
        render_inspect_table(
            _result(ToolSpec(name="run", description=None)), Console(file=buffer, width=100)
        )

        assert "(no description)" in buffer.getvalue()

    def test_only_the_first_sentence_is_shown(self) -> None:
        buffer = io.StringIO()
        render_inspect_table(
            _result(ToolSpec(name="t", description="First one. Second one.")),
            Console(file=buffer, width=120),
        )

        output = buffer.getvalue()
        assert "First one." in output
        assert "Second one" not in output

    def test_hint_markers_distinguish_unset_from_false(self) -> None:
        buffer = io.StringIO()
        render_inspect_table(
            _result(
                ToolSpec(name="declared", annotations=ToolAnnotations(read_only_hint=False)),
                ToolSpec(name="silent"),
            ),
            Console(file=buffer, width=120),
        )

        lines = {
            line.split()[0]: line for line in buffer.getvalue().splitlines() if line.strip()
        }
        assert "r" in lines["declared"].split()[-3:]
        assert lines["silent"].rstrip().endswith("- - -")

    def test_instructions_appear_only_when_verbose(self) -> None:
        assert "Do the thing." not in _render()
        assert "Do the thing." in _render(verbose=True)
