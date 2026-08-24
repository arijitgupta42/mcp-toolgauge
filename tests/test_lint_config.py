"""Reading `mcp-toolgauge.toml`.

Config discovery walks up from the target, so most of these tests are about *which* file
wins. The error cases matter as much as the happy path: a config error people cannot
locate is worse than no config support at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_toolgauge.lint import ConfigError, find_config, load_config
from mcp_toolgauge.model import Severity

OWN = """
[lint]
fail_on = "warning"

[lint.rules]
MCP025 = "off"
MCP041 = "error"
"""

IN_PYPROJECT = """
[project]
name = "someone-elses-project"

[tool.mcp-toolgauge.lint.rules]
MCP013 = "warning"
"""

UNRELATED_PYPROJECT = """
[project]
name = "someone-elses-project"

[tool.ruff]
line-length = 100
"""


def write(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


class TestDiscovery:
    def test_a_config_beside_the_target_is_found(self, tmp_path: Path) -> None:
        write(tmp_path, "mcp-toolgauge.toml", OWN)

        assert find_config(tmp_path) == tmp_path / "mcp-toolgauge.toml"

    def test_discovery_walks_up_from_the_target(self, tmp_path: Path) -> None:
        write(tmp_path, "mcp-toolgauge.toml", OWN)
        nested = tmp_path / "servers" / "directory"
        nested.mkdir(parents=True)

        assert find_config(nested) == tmp_path / "mcp-toolgauge.toml"

    def test_a_file_target_searches_from_its_directory(self, tmp_path: Path) -> None:
        write(tmp_path, "mcp-toolgauge.toml", OWN)
        server = write(tmp_path, "server.py", "")

        assert find_config(server) == tmp_path / "mcp-toolgauge.toml"

    def test_pyproject_is_used_when_it_declares_a_section(self, tmp_path: Path) -> None:
        write(tmp_path, "pyproject.toml", IN_PYPROJECT)

        assert find_config(tmp_path) == tmp_path / "pyproject.toml"

    def test_an_unrelated_pyproject_does_not_stop_the_walk(self, tmp_path: Path) -> None:
        """Otherwise the first Python project between the server and the config wins, and
        the config is silently ignored."""
        write(tmp_path, "mcp-toolgauge.toml", OWN)
        nested = tmp_path / "packages" / "server"
        write(nested, "pyproject.toml", UNRELATED_PYPROJECT)

        assert find_config(nested) == tmp_path / "mcp-toolgauge.toml"

    def test_our_own_file_wins_over_pyproject_in_the_same_directory(self, tmp_path: Path) -> None:
        write(tmp_path, "mcp-toolgauge.toml", OWN)
        write(tmp_path, "pyproject.toml", IN_PYPROJECT)

        assert find_config(tmp_path) == tmp_path / "mcp-toolgauge.toml"

    def test_nothing_found_is_not_an_error(self, tmp_path: Path) -> None:
        nested = tmp_path / "empty"
        nested.mkdir()

        # Nothing to assert about the return value -- a parent of tmp_path could in
        # principle hold a config -- but it must not raise.
        find_config(nested)


class TestLoading:
    def test_severities_are_read(self, tmp_path: Path) -> None:
        write(tmp_path, "mcp-toolgauge.toml", OWN)

        settings = load_config(start=tmp_path)

        assert settings.severities == {"MCP025": Severity.OFF, "MCP041": Severity.ERROR}

    def test_fail_on_is_read(self, tmp_path: Path) -> None:
        write(tmp_path, "mcp-toolgauge.toml", OWN)

        assert load_config(start=tmp_path).fail_on is Severity.WARNING

    def test_fail_on_defaults_to_error(self, tmp_path: Path) -> None:
        write(tmp_path, "mcp-toolgauge.toml", "[lint.rules]\nMCP025 = 'off'\n")

        assert load_config(start=tmp_path).fail_on is Severity.ERROR

    def test_the_pyproject_layout_is_read(self, tmp_path: Path) -> None:
        write(tmp_path, "pyproject.toml", IN_PYPROJECT)

        assert load_config(start=tmp_path).severities == {"MCP013": Severity.WARNING}

    def test_an_explicit_path_skips_discovery(self, tmp_path: Path) -> None:
        chosen = write(tmp_path / "elsewhere", "custom.toml", OWN)
        write(tmp_path, "mcp-toolgauge.toml", "[lint]\nfail_on = 'info'\n")

        assert load_config(explicit=chosen, start=tmp_path).fail_on is Severity.WARNING

    def test_no_config_ignores_what_is_on_disk(self, tmp_path: Path) -> None:
        write(tmp_path, "mcp-toolgauge.toml", OWN)

        settings = load_config(start=tmp_path, enabled=False)

        assert settings.severities == {}
        assert settings.source is None

    def test_the_source_is_reported(self, tmp_path: Path) -> None:
        path = write(tmp_path, "mcp-toolgauge.toml", OWN)

        assert load_config(start=tmp_path).source == path


class TestErrors:
    def test_an_unknown_rule_id_is_an_error(self, tmp_path: Path) -> None:
        """A silently ignored override is a rule somebody believes they turned off."""
        write(tmp_path, "mcp-toolgauge.toml", "[lint.rules]\nMCP999 = 'off'\n")

        with pytest.raises(ConfigError, match="MCP999"):
            load_config(start=tmp_path)

    def test_an_unknown_severity_is_an_error(self, tmp_path: Path) -> None:
        write(tmp_path, "mcp-toolgauge.toml", "[lint.rules]\nMCP013 = 'critical'\n")

        with pytest.raises(ConfigError, match="critical"):
            load_config(start=tmp_path)

    def test_a_non_string_severity_is_an_error(self, tmp_path: Path) -> None:
        write(tmp_path, "mcp-toolgauge.toml", "[lint.rules]\nMCP013 = 3\n")

        with pytest.raises(ConfigError, match="MCP013"):
            load_config(start=tmp_path)

    def test_malformed_toml_names_the_file(self, tmp_path: Path) -> None:
        path = write(tmp_path, "mcp-toolgauge.toml", "[lint\nbroken")

        with pytest.raises(ConfigError, match=path.name):
            load_config(start=tmp_path)

    def test_a_missing_explicit_config_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="No such config file"):
            load_config(explicit=tmp_path / "nope.toml", start=tmp_path)

    def test_a_wrong_shaped_lint_section_is_an_error(self, tmp_path: Path) -> None:
        write(tmp_path, "mcp-toolgauge.toml", "lint = 'yes please'\n")

        with pytest.raises(ConfigError, match="table"):
            load_config(start=tmp_path)
