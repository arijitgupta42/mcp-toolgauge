"""The mcp-toolgauge command line.

Exit codes are part of the contract, because this is meant to run in CI:

    0  all good
    1  a threshold was missed -- lint's --fail-on, eval's --min-accuracy or --max-cost
    2  usage error -- we could not work out what to inspect, or the config or cases are wrong
    3  connection failure -- we knew what to inspect but could not reach it or the model
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.text import Text

from mcp_toolgauge import version as package_version
from mcp_toolgauge.connect import (
    DEFAULT_TIMEOUT_SECONDS,
    ConnectionFailed,
    TargetResolutionError,
    inspect_server_sync,
    resolve_target,
)
from mcp_toolgauge.eval import (
    DEFAULT_CASES_PER_TOOL,
    DEFAULT_MODEL,
    BackendError,
    BackendUnavailable,
    BudgetExceeded,
    CacheMiss,
    CaseFileError,
    ResponseCache,
    RunStats,
    SynthesisFailed,
    cache_path,
    cached_text_completer,
    credentials_present,
    default_cases_path,
    digest_warning,
    draft_cases,
    load_suite,
    looks_usable,
    run_suite,
    score,
    validate_against,
    write_suite,
)
from mcp_toolgauge.health import health_score
from mcp_toolgauge.history import HistoryError
from mcp_toolgauge.history import record as record_history
from mcp_toolgauge.lint import ConfigError, load_config
from mcp_toolgauge.lint import lint as run_lint
from mcp_toolgauge.model import (
    CaseSuite,
    CiReport,
    EvalResult,
    HealthPoint,
    InspectResult,
    Severity,
    tool_digest,
)
from mcp_toolgauge.report import (
    render_badge,
    render_ci_json,
    render_ci_markdown,
    render_ci_table,
    render_eval_json,
    render_eval_table,
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
        out().print(f"mcp-toolgauge {package_version()}")
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

    This is read-only: mcp-toolgauge lists the tools and disconnects. It never calls one.
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
        bool, typer.Option("--no-config", help="Ignore any mcp-toolgauge.toml on disk.")
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


# --------------------------------------------------------------------------------------
# eval
# --------------------------------------------------------------------------------------

ModelOption = Annotated[
    str, typer.Option("--model", help="Which model to ask. Any string LiteLLM understands.")
]
CasesOption = Annotated[
    Path | None,
    typer.Option("--cases", help="Case file to use, instead of the one beside the target."),
]
PaceOption = Annotated[
    float,
    typer.Option(
        "--pace",
        help="Seconds to wait between model calls. Raise it if a free tier rate-limits you.",
    ),
]


def _warn(console: Console, message: str) -> None:
    console.print(Text(f"warning: {message}", style="yellow"), soft_wrap=True)


def _init_cases(
    result: InspectResult,
    *,
    path: Path,
    model: str,
    digest: str,
    per_tool: int,
    pace: float,
    force: bool,
) -> None:
    """Generate a first-draft suite and write it, once.

    Deliberately loud about what happens next. A generated suite nobody reads is a
    benchmark of the generator's imagination, so the closing message asks for the edit
    rather than congratulating anyone on the file.
    """
    console = out()
    if not result.tools:
        err().print("[red]error:[/red] That server advertises no tools; there is nothing to test.")
        raise typer.Exit(EXIT_USAGE)

    cache = ResponseCache.load(cache_path(path))
    stats = RunStats()
    complete = cached_text_completer(
        model=model,
        cache=cache,
        tool_digest=digest,
        pace=pace,
        stats=stats,
        on_retry=lambda note: _warn(console, note),
        accept=looks_usable,
    )

    console.print(Text(f"Drafting cases with {model}...", style="dim"), soft_wrap=True)
    try:
        draft = draft_cases(
            result.tools,
            complete,
            per_tool=per_tool,
            on_step=lambda label: console.print(Text(f"  {label}", style="dim"), soft_wrap=True),
        )
    except (BackendUnavailable, BackendError, SynthesisFailed) as exc:
        err().print(f"[red]error:[/red] {exc}")
        raise typer.Exit(EXIT_USAGE) from exc

    suite = CaseSuite(
        target=result.target, tool_digest=digest, generated_with=model, cases=draft.cases
    )
    try:
        write_suite(path, suite, force=force)
    except CaseFileError as exc:
        err().print(f"[red]error:[/red] {exc}")
        raise typer.Exit(EXIT_USAGE) from exc

    for label in draft.skipped:
        _warn(
            console,
            f"The model's reply for '{label}' could not be read, so those cases are "
            "missing. Write them by hand, or run --init --force again to retry.",
        )

    tally = ", ".join(f"{count} {kind}" for kind, count in suite.counts.items() if count)
    spend = f"${draft.cost_usd:.4f}" if draft.cost_usd else "free"
    console.print()
    console.print(Text(f"Wrote {len(suite.cases)} cases to {path}", style="bold"), soft_wrap=True)
    console.print(Text(f"  {tally}   {spend}", style="dim"))
    console.print()
    console.print(
        Text(
            "Read them before you trust the score. Delete the prompts that do not sound "
            "like your users, rewrite the ones that gave the answer away, then commit the "
            "file.",
            style="dim",
        )
    )


@app.command()
def eval(
    target: TargetArgument,
    command: CommandOption = None,
    server: ServerOption = None,
    init: Annotated[
        bool, typer.Option("--init", help="Generate a first-draft case file and stop.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="With --init, overwrite an existing case file.")
    ] = False,
    cases_per_tool: Annotated[
        int, typer.Option("--cases-per-tool", help="With --init, prompts to draft per tool.")
    ] = DEFAULT_CASES_PER_TOOL,
    model: ModelOption = DEFAULT_MODEL,
    cases: CasesOption = None,
    offline: Annotated[
        bool, typer.Option("--offline", help="Answer only from the cache; never call a model.")
    ] = False,
    max_cost: Annotated[
        float | None,
        typer.Option("--max-cost", help="Stop once the run has cost this many dollars."),
    ] = None,
    min_accuracy: Annotated[
        float | None,
        typer.Option(
            "--min-accuracy",
            help="Exit 1 when selection accuracy falls below this, as a percentage.",
        ),
    ] = None,
    pace: PaceOption = 0.0,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit JSON instead of a table.")
    ] = False,
    timeout: TimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show every failing case and its prompt.")
    ] = False,
) -> None:
    """Measure whether a model actually picks the right tool.

    Puts the server's real tool definitions in front of a model at temperature 0 and counts
    where the traffic goes. Answers are cached, so a second run over an unchanged suite is
    free.

    Like inspect and lint, this never invokes one of your tools. It calls a model, reads
    your tool list, and leaves the server alone.
    """
    result = _fetch(target, command=command, server=server, timeout=timeout)
    digest = tool_digest(result.tools)
    path = cases if cases is not None else default_cases_path(_config_start(target))

    if init:
        _init_cases(
            result,
            path=path,
            model=model,
            digest=digest,
            per_tool=cases_per_tool,
            pace=pace,
            force=force,
        )
        return

    console = out()
    try:
        suite = load_suite(path)
        warnings = validate_against(suite, result.tools, path=path)
    except CaseFileError as exc:
        err().print(f"[red]error:[/red] {exc}")
        raise typer.Exit(EXIT_USAGE) from exc

    if not json_output:
        drift = digest_warning(suite, digest, path=path)
        for note in ((drift,) if drift else ()) + warnings:
            _warn(console, note)
        if not offline and not credentials_present(model):
            provider = model.split("/", 1)[0]
            _warn(
                console,
                f"No API key found in the environment for {provider}. If the run fails to "
                "authenticate, that is why.",
            )

    cache = ResponseCache.load(cache_path(path))
    try:
        run = run_suite(
            suite,
            result.tools,
            model=model,
            tool_digest=digest,
            cache=cache,
            server=result.server,
            offline=offline,
            max_cost=max_cost,
            pace=pace,
            on_retry=lambda note: _warn(console, note),
        )
    except (CacheMiss, BackendUnavailable) as exc:
        err().print(f"[red]error:[/red] {exc}")
        raise typer.Exit(EXIT_USAGE) from exc
    except BudgetExceeded as exc:
        err().print(f"[red]error:[/red] {exc}")
        raise typer.Exit(EXIT_THRESHOLD) from exc
    except BackendError as exc:
        err().print(f"[red]error:[/red] {exc}")
        raise typer.Exit(EXIT_CONNECTION) from exc

    report = EvalResult(
        target=result.target,
        server=result.server,
        model=model,
        tool_digest=digest,
        scores=score(run.outcomes),
        outcomes=run.outcomes,
        cached_count=run.stats.cached,
        called_count=run.stats.called,
        cost_usd=run.stats.cost_usd,
    )

    if json_output:
        print(render_eval_json(report))
    else:
        render_eval_table(report, console, verbose=verbose)

    if min_accuracy is not None and report.scores.selection.fraction * 100 < min_accuracy:
        raise typer.Exit(EXIT_THRESHOLD)


# --------------------------------------------------------------------------------------
# ci
# --------------------------------------------------------------------------------------


def _try_load_baseline(path: Path, console: Console) -> CiReport | None:
    """Read a prior `ci --json` file, for the vs-base deltas. Best-effort.

    A base branch that has never had a `ci` run yet has no baseline, and that must still
    produce a comment -- just without the delta column -- rather than failing the build. A
    file that is present but unreadable is treated the same way, with a louder warning.
    """
    if not path.is_file():
        _warn(console, f"No baseline at {path}; the comment will show no deltas.")
        return None
    try:
        return CiReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        _warn(console, f"Could not read the baseline at {path}, so no deltas: {exc}")
        return None


@app.command()
def ci(
    target: TargetArgument,
    command: CommandOption = None,
    server: ServerOption = None,
    model: ModelOption = DEFAULT_MODEL,
    cases: CasesOption = None,
    min_score: Annotated[
        float | None,
        typer.Option("--min-score", help="Exit 1 when the health score is below this."),
    ] = None,
    badge: Annotated[
        Path | None,
        typer.Option("--badge", help="Write a shields.io endpoint JSON to this path."),
    ] = None,
    markdown: Annotated[
        Path | None,
        typer.Option("--markdown", help="Write the PR-comment markdown here, or '-' for stdout."),
    ] = None,
    baseline: Annotated[
        Path | None,
        typer.Option("--baseline", help="A prior 'ci --json' file to show deltas against."),
    ] = None,
    history: Annotated[
        Path | None,
        typer.Option(
            "--history",
            help="Append this score to a history file (created if absent) for the dashboard.",
        ),
    ] = None,
    history_label: Annotated[
        str | None,
        typer.Option(
            "--history-label",
            help="Name this history point -- a commit sha or tag. With --history.",
        ),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit JSON instead of the scorecard.")
    ] = False,
    timeout: TimeoutOption = DEFAULT_TIMEOUT_SECONDS,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show the findings behind the lint score.")
    ] = False,
    config: Annotated[
        Path | None, typer.Option("--config", help="Use this config file instead of searching.")
    ] = None,
    no_config: Annotated[
        bool, typer.Option("--no-config", help="Ignore any mcp-toolgauge.toml on disk.")
    ] = False,
) -> None:
    """Score a server's health, gate it, and produce a badge and a PR comment.

    Combines lint and eval into one 0-100 number: `lint_score` from the findings, `eval_score`
    from selection accuracy, weighted equally. Eval is replayed from the committed cache and
    never calls a model, so a `ci` run is reproducible and free; a server with no eval suite
    is scored on lint alone.

    Like every other command, this is read-only: it lists your tools and leaves them alone.
    """
    start = _config_start(target)
    try:
        settings = load_config(explicit=config, start=start, enabled=not no_config)
    except ConfigError as exc:
        err().print(f"[red]error:[/red] {exc}")
        raise typer.Exit(EXIT_USAGE) from exc

    result = _fetch(target, command=command, server=server, timeout=timeout)
    lint_report = run_lint(result, severities=settings.severities)

    console = out()
    cases_path = cases if cases is not None else default_cases_path(start)
    # An explicit --cases means "use this file", so a missing one is an error, not a reason
    # to fall back to lint-only. The default path merely being absent is the common case, and
    # degrades quietly.
    evaluation = (
        _replay_eval(result, cases_path, model=model, json_output=json_output, console=console)
        if cases is not None or cases_path.is_file()
        else None
    )

    scores = evaluation.scores if evaluation is not None else None
    health = health_score(lint_report, scores)

    # Record before the gate, never after: a history that quietly skips the runs that failed
    # the threshold is not a history of the score, it is a history of the passing score, and
    # the whole point of the chart is to show the drop. A malformed existing file is a usage
    # error with a human fix, so it stops here rather than being appended over.
    series: tuple[HealthPoint, ...] | None = None
    if history is not None:
        try:
            updated, mismatch = record_history(
                history, target=result.target, health=health, label=history_label
            )
        except HistoryError as exc:
            err().print(f"[red]error:[/red] {exc}")
            raise typer.Exit(EXIT_USAGE) from exc
        series = updated.points
        if mismatch is not None and not json_output:
            _warn(console, mismatch)

    report = CiReport(
        target=result.target,
        server=result.server,
        health=health,
        lint=lint_report,
        eval=evaluation,
        history=series,
    )

    if json_output:
        print(render_ci_json(report))
    else:
        render_ci_table(report, console, verbose=verbose)

    if badge is not None:
        badge.write_text(render_badge(health) + "\n", encoding="utf-8")

    if markdown is not None:
        base = _try_load_baseline(baseline, console) if baseline is not None else None
        text = render_ci_markdown(report, baseline=base)
        if str(markdown) == "-":
            # typer.echo, not print: the comment carries a status emoji, and a bare print
            # crashes on a legacy Windows console's cp1252. echo writes it safely.
            typer.echo(text)
        else:
            markdown.write_text(text + "\n", encoding="utf-8")

    if min_score is not None and health.overall < min_score:
        raise typer.Exit(EXIT_THRESHOLD)


def _replay_eval(
    result: InspectResult,
    path: Path,
    *,
    model: str,
    json_output: bool,
    console: Console,
) -> EvalResult:
    """Replay a committed eval suite from its cache, offline. Never calls a model.

    Shares the eval command's failure mapping: a missing or mismatched case file is a usage
    error, and a cache with no answer for a case is the same -- in CI it means the committed
    cache and the checked-in cases have drifted apart.
    """
    digest = tool_digest(result.tools)
    try:
        suite = load_suite(path)
        warnings = validate_against(suite, result.tools, path=path)
    except CaseFileError as exc:
        err().print(f"[red]error:[/red] {exc}")
        raise typer.Exit(EXIT_USAGE) from exc

    if not json_output:
        drift = digest_warning(suite, digest, path=path)
        for note in ((drift,) if drift else ()) + warnings:
            _warn(console, note)

    cache = ResponseCache.load(cache_path(path))
    try:
        run = run_suite(
            suite,
            result.tools,
            model=model,
            tool_digest=digest,
            cache=cache,
            server=result.server,
            offline=True,
        )
    except (CacheMiss, BackendUnavailable) as exc:
        err().print(f"[red]error:[/red] {exc}")
        raise typer.Exit(EXIT_USAGE) from exc
    except BackendError as exc:
        err().print(f"[red]error:[/red] {exc}")
        raise typer.Exit(EXIT_CONNECTION) from exc

    return EvalResult(
        target=result.target,
        server=result.server,
        model=model,
        tool_digest=digest,
        scores=score(run.outcomes),
        outcomes=run.outcomes,
        cached_count=run.stats.cached,
        called_count=run.stats.called,
        cost_usd=run.stats.cost_usd,
    )
