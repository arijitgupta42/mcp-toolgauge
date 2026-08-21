"""Rule modules, one per family.

Importing this package is what registers the rules: each module's `@rule` decorators run at
import time and populate the registry in `lint.engine`. `mcp_doctor.lint.__init__` imports
this package for exactly that reason, so anything that can reach the engine has already
loaded every rule.

`__all__` names the modules so the imports read as the deliberate re-exports they are,
rather than as four unused imports.
"""

from mcp_doctor.lint.rules import annotations, description, naming, parameters

__all__ = ["annotations", "description", "naming", "parameters"]
