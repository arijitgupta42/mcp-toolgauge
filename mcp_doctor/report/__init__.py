"""Renderers: one module per output shape, each a pure function of a result model."""

from mcp_doctor.report.inspect import render_inspect_json, render_inspect_table
from mcp_doctor.report.lint import render_lint_json, render_lint_table
from mcp_doctor.report.sarif import render_lint_sarif

__all__ = [
    "render_inspect_json",
    "render_inspect_table",
    "render_lint_json",
    "render_lint_sarif",
    "render_lint_table",
]
