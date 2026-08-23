"""The composite health score, and the CI report that carries it.

`lint` and `eval` each produce a number about one thing. `ci` produces the one number a
badge can show, and the whole design problem is doing that without letting the composite hide
what it is made of. So `HealthScore` keeps its two halves visible -- `lint_score` and
`eval_score` are stored beside `overall`, never just rolled into it -- and `eval_score` is
`None` rather than zero when no eval ran, because "we did not measure selection" and "the
model never picks the right tool" are opposite facts that must not share a rendering.

`CiReport` is self-describing for the same reason `LintResult` and `EvalResult` are: it holds
the full lint and eval results it was scored from, so a committed `ci --json` file can be
diffed against a later run -- which is exactly what the PR-comment renderer does -- without
needing the runs that produced either side.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from mcp_doctor.model.eval import EvalResult
from mcp_doctor.model.finding import LintResult
from mcp_doctor.model.tool import ServerInfo


class HealthScore(BaseModel):
    """The 0-100 headline, and the two halves it is made of.

    `eval_score` is `None` for a lint-only run. `errors` and `warnings` are the counts that
    drove `lint_score`, kept here so a consumer that only reads `.health` still knows why the
    number is what it is, and so the PR comment can show a findings delta without reaching
    back into the full lint result.
    """

    model_config = ConfigDict(frozen=True)

    overall: int
    lint_score: int
    eval_score: int | None = None
    errors: int = 0
    warnings: int = 0

    @property
    def is_lint_only(self) -> bool:
        return self.eval_score is None


class CiReport(BaseModel):
    """Everything one `mcp-doctor ci` run produced: both inputs and the score over them.

    The lint and eval results are carried whole rather than summarised, so this is the
    artifact a later run diffs against. `eval` is `None` exactly when the run was lint-only.
    """

    model_config = ConfigDict(frozen=True)

    target: str
    server: ServerInfo
    health: HealthScore
    lint: LintResult
    eval: EvalResult | None = None
