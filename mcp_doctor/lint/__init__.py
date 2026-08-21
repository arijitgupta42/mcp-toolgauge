"""Static analysis of a server's tools. Deterministic, offline, and free.

Importing this package registers every rule -- see `mcp_doctor.lint.rules`.
"""

from mcp_doctor.lint import rules as rules  # imported for its rule-registration side effect
from mcp_doctor.lint.config import (
    CONFIG_FILENAME,
    ConfigError,
    LintConfig,
    find_config,
    load_config,
)
from mcp_doctor.lint.engine import (
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
