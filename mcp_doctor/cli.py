"""The mcp-doctor command line.

Exit codes are part of the contract, because this is meant to run in CI:

    0  all good
    1  threshold failure (arrives with `ci` in a later milestone)
    2  usage error -- we could not work out what to inspect
    3  connection failure -- we knew what to inspect but could not reach it
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Annotated

import typer
from rich.console import Console

from mcp_doctor.connect import (
    DEFAULT_TIMEOUT_SECONDS,
    ConnectionFailed,
    TargetResolutionError,
    inspect_server_sync,
    resolve_target,
)
from mcp_doctor.report import render_inspect_json, render_inspect_table

EXIT_OK = 0
EXIT_THRESHOLD = 1
EXIT_USAGE = 2
EXIT_CONNECTION = 3

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode=None,
    help="Audit MCP servers: find out why your tools don't get called.",
)

def out() -> Console:
    """A console built per call, not at import.

    Rich samples NO_COLOR (and terminal width) when a Console is constructed. Building
    these at module scope would freeze whatever the environment looked like at import,
    which is both wrong for embedders and untestable.
    """
    return Console()


def err() -> Console:
    return Console(stderr=True)


def _version() -> str:
    try:
        return package_version("mcp-doctor")
    except PackageNotFoundError:  # running from a source checkout without an install
        return "0.0.0+unknown"


def _version_callback(requested: bool) -> None:
    if requested:
        out().print(f"mcp-doctor {_version()}")
        raise typer.Exit(EXIT_OK)


@app.callback()
def main(
    show_version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Show the version."
        ),
    ] = False,
) -> None:
    """Audit MCP servers: find out why your tools don't get called."""


@app.command()
def inspect(
    target: Annotated[
        str,
        typer.Argument(
            help=(
                "A directory containing the server (its .mcp.json is used if present), "
                "a .py server, a .json manifest, or an http(s) URL."
            ),
        ),
    ],
    command: Annotated[
        str | None,
        typer.Option("--command", "-c", help="Command to start the server, overriding discovery."),
    ] = None,
    server: Annotated[
        str | None,
        typer.Option("--server", help="Which server to use, if the manifest declares several."),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit JSON instead of a table.")
    ] = False,
    timeout: Annotated[
        float, typer.Option("--timeout", help="Seconds to wait for the server.")
    ] = DEFAULT_TIMEOUT_SECONDS,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show parameters, schemas, and instructions.")
    ] = False,
) -> None:
    """Connect to a server and print the tools it advertises.

    This is read-only: mcp-doctor lists the tools and disconnects. It never calls one.
    """
    try:
        resolved = resolve_target(target, command=command, server=server)
    except TargetResolutionError as exc:
        err().print(f"[red]error:[/red] {exc}")
        raise typer.Exit(EXIT_USAGE) from exc

    try:
        result = inspect_server_sync(resolved, timeout=timeout)
    except ConnectionFailed as exc:
        err().print(f"[red]error:[/red] {exc}")
        raise typer.Exit(EXIT_CONNECTION) from exc

    if json_output:
        # print(), not console.print(), so Rich never wraps or highlights the payload.
        print(render_inspect_json(result))
    else:
        render_inspect_table(result, out(), verbose=verbose)
