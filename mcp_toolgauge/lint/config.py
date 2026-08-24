"""Reading `mcp-toolgauge.toml`.

The configuration surface is deliberately one thing: per-rule severity, where `"off"` is a
severity. There is no separate enable list, disable list, or select list, because every one
of those is a second way to say something the severity table already says, and a linter
with four overlapping ways to silence a rule is a linter nobody can predict.

Discovery walks up from the target, checking `mcp-toolgauge.toml` and then `pyproject.toml` at
each level, which is what every other Python tool does and therefore what people expect.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp_toolgauge.lint.engine import rule_ids
from mcp_toolgauge.model import Severity

CONFIG_FILENAME = "mcp-toolgauge.toml"
PYPROJECT_FILENAME = "pyproject.toml"
PYPROJECT_SECTION = "mcp-toolgauge"

# How deep to walk before giving up. A real project's config is never forty levels above
# the server, and an unbounded walk on a network path is a hang.
_MAX_ASCENT = 40


class ConfigError(Exception):
    """The configuration file was found but could not be used (exit code 2).

    Always names the file and the offending key: a config error people cannot locate is
    worse than no config support at all.
    """


@dataclass(frozen=True)
class LintConfig:
    """Resolved configuration for one lint run."""

    severities: dict[str, Severity] = field(default_factory=dict)
    fail_on: Severity = Severity.ERROR
    source: Path | None = None

    def describe_source(self) -> str:
        return str(self.source) if self.source is not None else "built-in defaults"


def _parse_severity(raw: Any, *, where: str, path: Path) -> Severity:
    if not isinstance(raw, str):
        raise ConfigError(f"{path}: {where} should be a string, got {type(raw).__name__}.")
    try:
        return Severity(raw.lower())
    except ValueError as exc:
        allowed = ", ".join(item.value for item in Severity)
        raise ConfigError(f"{path}: {where} is {raw!r}; expected one of {allowed}.") from exc


def _table(parent: dict[str, Any], key: str, *, path: Path) -> dict[str, Any]:
    value = parent.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: [{key}] should be a table, got {type(value).__name__}.")
    return value


def _build(section: dict[str, Any], path: Path) -> LintConfig:
    lint = _table(section, "lint", path=path)
    rules = _table(lint, "rules", path=path)

    known = rule_ids()
    severities: dict[str, Severity] = {}
    for rule_id, raw in rules.items():
        if rule_id not in known:
            # A silently ignored override is a rule somebody believes they turned off.
            nearest = sorted(known)
            raise ConfigError(
                f"{path}: [lint.rules] has no rule {rule_id!r}. "
                f"Known rules: {', '.join(nearest)}."
            )
        severities[rule_id] = _parse_severity(raw, where=f"[lint.rules] {rule_id}", path=path)

    fail_on = Severity.ERROR
    if "fail_on" in lint:
        fail_on = _parse_severity(lint["fail_on"], where="[lint] fail_on", path=path)

    return LintConfig(severities=severities, fail_on=fail_on, source=path)


def _read(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc


def load_config_file(path: Path) -> LintConfig:
    """Load one config file by path, whichever of the two layouts it uses."""
    document = _read(path)
    if path.name == PYPROJECT_FILENAME:
        tool = _table(document, "tool", path=path)
        section = _table(tool, PYPROJECT_SECTION, path=path)
    else:
        section = document
    return _build(section, path)


def find_config(start: Path) -> Path | None:
    """Walk up from `start` looking for a config file. Returns the first one found.

    A `pyproject.toml` only counts when it actually declares a `[tool.mcp-toolgauge]` section,
    so the walk does not stop at the first unrelated Python project it passes.
    """
    directory = start if start.is_dir() else start.parent
    try:
        directory = directory.resolve()
    except OSError:  # a path that no longer exists, on a disconnected drive, etc.
        return None

    for _, candidate in zip(range(_MAX_ASCENT), [directory, *directory.parents], strict=False):
        own = candidate / CONFIG_FILENAME
        if own.is_file():
            return own
        pyproject = candidate / PYPROJECT_FILENAME
        if pyproject.is_file():
            try:
                document = _read(pyproject)
            except ConfigError:
                # Someone else's malformed pyproject is not our error to report.
                continue
            tool = document.get("tool")
            if isinstance(tool, dict) and isinstance(tool.get(PYPROJECT_SECTION), dict):
                return pyproject
    return None


def load_config(
    *,
    explicit: Path | None = None,
    start: Path | None = None,
    enabled: bool = True,
) -> LintConfig:
    """Resolve configuration for a run.

    `explicit` is `--config` and must exist. `start` is where discovery begins, normally the
    directory of the target. `enabled=False` is `--no-config`, which skips discovery
    entirely so a CI run can be made independent of whatever is checked in.
    """
    if explicit is not None:
        if not explicit.is_file():
            raise ConfigError(f"No such config file: {explicit}")
        return load_config_file(explicit)
    if not enabled or start is None:
        return LintConfig()
    found = find_config(start)
    return load_config_file(found) if found is not None else LintConfig()
