"""Renderers: one module per output shape, each a pure function of a result model."""

from mcp_doctor.report.badge import render_badge
from mcp_doctor.report.ci import render_ci_json, render_ci_markdown, render_ci_table
from mcp_doctor.report.eval import render_eval_json, render_eval_table
from mcp_doctor.report.inspect import render_inspect_json, render_inspect_table
from mcp_doctor.report.lint import render_lint_json, render_lint_table
from mcp_doctor.report.sarif import render_lint_sarif
from mcp_doctor.report.style import print_wrapped, styled

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
