"""Static analysis of a server's tools. Deterministic, offline, and free.

Importing this package registers every rule -- see `mcp_toolgauge.lint.rules`.
"""

from mcp_toolgauge.lint import rules as rules  # imported for its rule-registration side effect
from mcp_toolgauge.lint.config import (
    CONFIG_FILENAME,
    ConfigError,
    LintConfig,
    find_config,
    load_config,
)
from mcp_toolgauge.lint.engine import (
    LintContext,
    LintTool,
    Rule,
    all_rules,
    get_rule,
    lint,
    rule,
    rule_ids,
    run_rules,
)

__all__ = [
    "CONFIG_FILENAME",
    "ConfigError",
    "LintConfig",
    "LintContext",
    "LintTool",
    "Rule",
    "all_rules",
    "find_config",
    "get_rule",
    "lint",
    "load_config",
    "rule",
    "rule_ids",
    "run_rules",
]
