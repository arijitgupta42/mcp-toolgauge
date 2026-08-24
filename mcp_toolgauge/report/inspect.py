"""Rendering an `InspectResult` for humans and for machines.

Quiet by default, detailed under `-v`, per the house style. Colour is Rich's business: it
honours `NO_COLOR` itself, so nothing here needs to check for it.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from mcp_toolgauge.model import InspectResult, ToolSpec, canonical_json

# Rich pads each column by one space per side; three gaps between four columns.
_COLUMN_PADDING = 8
_MIN_DESCRIPTION_WIDTH = 24


def render_inspect_json(result: InspectResult) -> str:
    """Deterministic JSON -- stable enough to diff between runs and to golden-test."""
    return canonical_json(result)


def _first_sentence(description: str | None, budget: int) -> Text:
    """The opening sentence, flattened to one line and trimmed to `budget` columns.

    We do the trimming rather than delegating to Rich's overflow handling, because Rich
    shrinks a too-wide table by squeezing whichever columns it likes -- which collapsed the
    tool-name column to a single letter. Sizing this column ourselves keeps the fixed
    columns intact at any terminal width.

    Output stays ASCII on purpose: this gets piped into CI logs and Windows consoles, where
    a decorative ellipsis character comes back as a replacement glyph.
    """
    if not description or not description.strip():
        return Text("(no description)", style="red")

    flattened = " ".join(description.split())
    head, separator, _ = flattened.partition(". ")
    sentence = head + "." if separator else head
    if len(sentence) > budget:
        sentence = sentence[: max(1, budget - 3)].rstrip() + "..."
    return Text(sentence)


def _hint_markers(tool: ToolSpec) -> Text:
    """Compress the annotation tri-states into something scannable.

    A dim dash means the server said nothing, which is not the same as saying 'no' -- that
    distinction is the whole basis of the annotation lint rules.
    """
    annotations = tool.annotations
    markers = Text()
    for index, (label, value) in enumerate(
        (
            ("read-only", annotations.read_only_hint if annotations else None),
            ("destructive", annotations.destructive_hint if annotations else None),
            ("idempotent", annotations.idempotent_hint if annotations else None),
        )
    ):
        if index:
            markers.append(" ")
        if value is True:
            markers.append(label[:1].upper(), style="cyan")
        elif value is False:
            markers.append(label[:1].lower(), style="dim")
        else:
            markers.append("-", style="dim")
    # Exactly as wide as the "R D I" header, which the column budget assumes.
    return markers


def _type_of(schema: Any) -> str:
    if not isinstance(schema, dict):
        return "?"
    if "type" in schema:
        return str(schema["type"])
    if "anyOf" in schema and isinstance(schema["anyOf"], list):
        parts = [_type_of(option) for option in schema["anyOf"] if option != {"type": "null"}]
        return " | ".join(dict.fromkeys(parts)) or "any"
    if "enum" in schema:
        return "enum"
    return "any"


def render_inspect_table(result: InspectResult, console: Console, *, verbose: bool = False) -> None:
    """Print the discovered server and its tools."""
    server = result.server
    heading = Text(server.name or "(unnamed server)", style="bold")
    if server.version:
        heading.append(f" {server.version}", style="dim")
    if server.protocol_version:
        heading.append(f"  protocol {server.protocol_version}", style="dim")
    console.print(heading)
    console.print(Text(result.target, style="dim"))

    if verbose and server.instructions:
        console.print()
        console.print(Text("instructions", style="bold dim"))
        console.print(Text(" ".join(server.instructions.split())))

    console.print()

    if not result.tools:
        console.print(Text("This server advertises no tools.", style="yellow"))
        return

    # Give the description whatever the fixed columns do not need. One line per tool is
    # what makes the default view scannable.
    name_width = max(len("tool"), *(len(tool.name) for tool in result.tools))
    fixed_width = name_width + len("params") + len("R D I") + _COLUMN_PADDING
    budget = max(_MIN_DESCRIPTION_WIDTH, console.width - fixed_width)

    # overflow="crop" rather than "ellipsis": if the arithmetic above is ever wrong on some
    # terminal, Rich trims silently instead of inserting a Unicode ellipsis that Windows
    # consoles render as a replacement glyph. We do our own "..." where we intend one.
    table = Table(box=None, pad_edge=False, header_style="bold dim")
    table.add_column("tool", no_wrap=True, overflow="crop")
    table.add_column("description", no_wrap=True, overflow="crop")
    table.add_column("params", no_wrap=True, justify="right", overflow="crop")
    table.add_column("R D I", no_wrap=True, overflow="crop")

    for tool in result.tools:
        table.add_row(
            Text(tool.name, style="bold"),
            _first_sentence(tool.description, budget),
            str(len(tool.parameters)),
            _hint_markers(tool),
        )

    console.print(table)

    if verbose:
        for tool in result.tools:
            console.print()
            console.print(Text(tool.name, style="bold"))
            if tool.description:
                console.print(Text(" ".join(tool.description.split())))
            required = set(tool.required_parameters)
            if not tool.parameters:
                console.print(Text("  (no parameters)", style="dim"))
            for name, schema in tool.parameters.items():
                flag = "*" if name in required else " "
                line = Text(f"  {flag}{name}", style="cyan")
                line.append(f": {_type_of(schema)}", style="dim")
                description = schema.get("description") if isinstance(schema, dict) else None
                if description:
                    line.append(f" - {' '.join(str(description).split())}")
                else:
                    line.append("  (undocumented)", style="red")
                console.print(line)
            if tool.output_schema:
                console.print(Text("  returns: declared output schema", style="dim"))

    console.print()
    # Build the whole sentence before styling it. Appending "tool" and "s" as separate
    # spans split the word across two escape sequences, so "10 tools" was not findable as
    # a substring in coloured output.
    count = len(result.tools)
    summary = f"{count} tool" if count == 1 else f"{count} tools"
    if not verbose:
        summary += "   -v for parameter detail"
    console.print(Text(summary, style="dim"))
