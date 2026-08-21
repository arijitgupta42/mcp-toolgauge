"""mcp-doctor -- lint, evaluate, and CI-gate MCP servers."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version

__all__ = ["version"]


def version() -> str:
    """The installed version, or a marker when running from an uninstalled checkout."""
    try:
        return _package_version("mcp-doctor")
    except PackageNotFoundError:
        return "0.0.0+unknown"
