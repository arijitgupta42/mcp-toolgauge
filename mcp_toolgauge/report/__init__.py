"""Renderers: one module per output shape, each a pure function of a result model."""

from mcp_toolgauge.report.badge import render_badge
from mcp_toolgauge.report.ci import render_ci_json, render_ci_markdown, render_ci_table
from mcp_toolgauge.report.eval import render_eval_json, render_eval_table
from mcp_toolgauge.report.inspect import render_inspect_json, render_inspect_table
from mcp_toolgauge.report.lint import render_lint_json, render_lint_table
from mcp_toolgauge.report.sarif import render_lint_sarif
from mcp_toolgauge.report.style import print_wrapped, styled

__all__ = [
    "print_wrapped",
    "render_badge",
    "render_ci_json",
    "render_ci_markdown",
    "render_ci_table",
    "render_eval_json",
    "render_eval_table",
    "render_inspect_json",
    "render_inspect_table",
    "render_lint_json",
    "render_lint_sarif",
    "render_lint_table",
    "styled",
]
