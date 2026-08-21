"""The mcp-doctor command line.

Exit codes are part of the contract, because this is meant to run in CI:

    0  all good
    1  findings at or above --fail-on (and, later, a `ci` threshold failure)
    2  usage error -- we could not work out what to inspect, or the config is wrong
    3  connection failure -- we knew what to inspect but could not reach it
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.text import Text

from mcp_doctor import version as package_version
from mcp_doctor.connect import (
    DEFAULT_TIMEOUT_SECONDS,
    ConnectionFailed,
    TargetResolutionError,
    inspect_server_sync,
    resolve_target,
)
from mcp_doctor.lint import ConfigError, load_config
from mcp_doctor.lint import lint as run_lint
from mcp_doctor.model import InspectResult, Severity
from mcp_doctor.report import (
    render_inspect_json,
    render_inspect_table,
    render_lint_json,
    render_lint_sarif,
    render_lint_table,
)

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

TargetArgument = Annotated[
    str,
    typer.Argument(
        help=(
            "A directory containing the server (its .mcp.json is used if present), "
            "a .py server, a .json manifest, or an http(s) URL."
        ),
    ),
]
CommandOption = Annotated[
    str | None,
    typer.Option("--command", "-c", help="Command to start the server, overriding discovery."),
]
ServerOption = Annotated[
    str | None,
    typer.Option("--server", help="Which server to use, if the manifest declares several."),
]
TimeoutOption = Annotated[
    float, typer.Option("--timeout", help="Seconds to wait for the server.")
]


def out() -> Console:
    """A console built per call, not at import.

    Rich samples NO_COLOR (and terminal width) when a Console is constructed. Building
    these at module scope would freeze whatever the environment looked like at import,
    which is both wrong for embedders and untestable.
    """
    return Console()


def err() -> Console:
    return Console(stderr=True)


def _version_callback(requested: bool) -> None:
    if requested:
        out().print(f"mcp-doctor {package_version()}")
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


def _fetch(
    target: str,
    *,
    command: str | None,
    server: str | None,
    timeout: float,
) -> InspectResult:
    """Resolve a target and read its tool list, mapping both failures to their exit codes.

    Shared by every command that needs a server, so that "could not work out what you
    meant" and "could not reach it" stay distinguishable no matter which command you ran.
    """
    try:
        resolved = resolve_target(target, command=command, server=server)
    except TargetResolutionError as exc:
        err().print(f"[red]error:[/red] {exc}")
        raise typer.Exit(EXIT_USAGE) from exc

    try:
        return inspect_server_sync(resolved, timeout=timeout)
    except ConnectionFailed as exc:
        err().print(f"[red]error:[/red] {exc}")
        raise typer.Exit(EXIT_CONNECTION) from exc


@app.command()
def inspect(
    target: TargetArgument,
    command: CommandOption = None,
    server: ServerOption = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit JSON instead of a table.")
    ] = False,
    timeout: TimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show parameters, schemas, and instructions.")
    ] = False,
) -> None:
    """Connect to a server and print the tools it advertises.

    This is read-only: mcp-doctor lists the tools and disconnects. It never calls one.
    """
    result = _fetch(target, command=command, server=server, timeout=timeout)

    if json_output:
        # print(), not console.print(), so Rich never wraps or highlights the payload.
        print(render_inspect_json(result))
    else:
        render_inspect_table(result, out(), verbose=verbose)


def _config_start(target: str) -> Path:
    """Where config discovery begins: the target's directory, or the working directory."""
    path = Path(target)
    if path.is_dir():
        return path
    if path.is_file():
        return path.parent
    return Path.cwd()


@app.command()
def lint(
    target: TargetArgument,
    command: CommandOption = None,
    server: ServerOption = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit JSON instead of a table.")
    ] = False,
    sarif: Annotated[
        bool, typer.Option("--sarif", help="Emit SARIF 2.1.0, for code-scanning upload.")
    ] = False,
    fail_on: Annotated[
        Severity | None,
        typer.Option(
            "--fail-on",
            help="Exit 1 when a finding reaches this severity. 'off' never fails.",
        ),
    ] = None,
    timeout: TimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show info findings and every suggestion.")
    ] = False,
    config: Annotated[
        Path | None, typer.Option("--config", help="Use this config file instead of searching.")
    ] = None,
    no_config: Annotated[
        bool, typer.Option("--no-config", help="Ignore any mcp-doctor.toml on disk.")
    ] = False,
) -> None:
    """Check a server's tools for the things that stop them being selected.

    Every rule is deterministic and offline: no model is called and nothing is sent
    anywhere. Like `inspect`, this never invokes one of the server's tools.
    """
    if json_output and sarif:
        err().print("[red]error:[/red] --json and --sarif cannot be combined; pick one.")
        raise typer.Exit(EXIT_USAGE)

    try:
        settings = load_config(
            explicit=config, start=_config_start(target), enabled=not no_config
        )
    except ConfigError as exc:
        err().print(f"[red]error:[/red] {exc}")
        raise typer.Exit(EXIT_USAGE) from exc

    result = _fetch(target, command=command, server=server, timeout=timeout)
    report = run_lint(result, severities=settings.severities)

    if json_output:
        print(render_lint_json(report))
    elif sarif:
        print(render_lint_sarif(report, version=package_version()))
    else:
        console = out()
        if verbose and settings.source is not None:
            # Text, not a format string: a path is data, and console.print() would read
            # any bracket in it as Rich markup. soft_wrap keeps a long path on one line,
            # because a path broken across two lines cannot be copied.
            console.print(
                Text(f"config: {settings.describe_source()}", style="dim"), soft_wrap=True
            )
        render_lint_table(report, console, verbose=verbose)

    floor = fail_on if fail_on is not None else settings.fail_on
    if report.at_or_above(floor):
        raise typer.Exit(EXIT_THRESHOLD)
