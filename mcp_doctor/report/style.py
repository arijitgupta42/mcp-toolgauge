"""Layout primitives shared by the terminal renderers.

Both `lint` and `eval` print the same shape of thing: a labelled line, wrapped to the
terminal, with identifiers picked out. Doing that twice would mean two implementations of
backtick handling and two answers to what a wrapped continuation line is indented to, which
is exactly the kind of duplication that drifts until two reports look like they came from
different programs.

Layout is done by hand rather than with a Rich table, for the reasons `report/lint.py`
records: a table pads every cell to the column width, which leaves trailing whitespace on
wrapped lines and a full-width blank line between groups. `Text.wrap` gives the same
wrapping with styles intact and nothing after the last visible character.
"""

from __future__ import annotations

from rich.console import Console
from rich.text import Text


def styled(text: str) -> Text:
    """Render `backticked` spans in colour, and drop the backticks.

    Messages are written with backticks around identifiers so they read correctly in a
    plain pipe, in JSON, and in a SARIF viewer. In a terminal we can do better than
    punctuation. An odd number of backticks means the text is not ours to reformat, so it
    falls through unchanged rather than eating the rest of the line.
    """
    parts = text.split("`")
    if len(parts) % 2 == 0:
        return Text(text)
    rendered = Text()
    for index, part in enumerate(parts):
        rendered.append(part, style="cyan" if index % 2 else "")
    return rendered


def print_wrapped(
    console: Console,
    body: Text,
    *,
    first: Text | None,
    width: int,
    indent: int,
) -> None:
    """Print `body` wrapped to `width`, with `first` in front of line one.

    Continuation lines are indented to `indent`, the same column the first line's text
    starts at, so a wrapped message stays visually attached to whatever labelled it.
    """
    continuation = " " * indent
    for index, line in enumerate(body.wrap(console, width)):
        row = first.copy() if index == 0 and first is not None else Text(continuation)
        row.append_text(line)
        # Wrapping keeps the space the line broke on. Trailing whitespace is noise in a CI
        # log and a diff, so it does not survive to the terminal.
        row.rstrip()
        console.print(row)
