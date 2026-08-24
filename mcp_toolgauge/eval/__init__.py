"""Measuring whether a model actually picks the right tool.

Where `lint` reads a server's tools and says what looks wrong, `eval` puts those same tools
in front of a real model and counts what happens. The two halves meet in one place: the
sibling pairs `synth` writes hard cases for are exactly the pairs `MCP013` and `MCP014`
complain about, so a lint warning and an eval failure are statements about the same defect
at two different levels of proof.

Four rules hold across the package, and each is enforced by something other than good
intentions:

* **Every model call goes through the cache**, so a second run of an unchanged suite is
  free. `runner` never touches `backend` except through `cache`, and a test asserts it.
* **Cases are a committed artifact.** `--init` refuses to overwrite without `--force`.
* **`score` is pure.** No network, no filesystem, no clock -- it takes outcomes and returns
  numbers, and it has the highest test coverage in the repo.
* **Nothing here invokes one of the server's tools.** `eval` calls a *model*; the server is
  read exactly as `inspect` reads it, and then left alone.
"""

from mcp_toolgauge.eval.arguments import check_arguments
from mcp_toolgauge.eval.backend import (
    DEFAULT_MODEL,
    BackendError,
    BackendUnavailable,
    Completion,
    ToolCall,
    build_messages,
    credentials_present,
    tool_definitions,
)
from mcp_toolgauge.eval.cache import (
    CACHE_DIRNAME,
    CACHE_FILENAME,
    CachedCall,
    CacheMiss,
    ResponseCache,
    cache_key,
    cache_path,
)
from mcp_toolgauge.eval.cases import (
    CASES_FILENAME,
    CaseFileError,
    default_cases_path,
    digest_warning,
    load_suite,
    validate_against,
    write_suite,
)
from mcp_toolgauge.eval.runner import (
    BudgetExceeded,
    RunResult,
    RunStats,
    cached_text_completer,
    run_suite,
)
from mcp_toolgauge.eval.score import (
    confusion_matrix,
    describe_confusion,
    notable_confusions,
    per_tool_scores,
    score,
)
from mcp_toolgauge.eval.synth import (
    DEFAULT_ABSTAIN_CASES,
    DEFAULT_CASES_PER_TOOL,
    DEFAULT_SIBLING_CASES,
    Draft,
    SynthesisFailed,
    confusable_pairs,
    draft_cases,
    looks_usable,
)

__all__ = [
    "CACHE_DIRNAME",
    "CACHE_FILENAME",
    "CASES_FILENAME",
    "DEFAULT_ABSTAIN_CASES",
    "DEFAULT_CASES_PER_TOOL",
    "DEFAULT_MODEL",
    "DEFAULT_SIBLING_CASES",
    "BackendError",
    "BackendUnavailable",
    "BudgetExceeded",
    "CacheMiss",
    "CachedCall",
    "CaseFileError",
    "Completion",
    "Draft",
    "ResponseCache",
    "RunResult",
    "RunStats",
    "SynthesisFailed",
    "ToolCall",
    "build_messages",
    "cache_key",
    "cache_path",
    "cached_text_completer",
    "check_arguments",
    "confusable_pairs",
    "confusion_matrix",
    "credentials_present",
    "default_cases_path",
    "describe_confusion",
    "digest_warning",
    "draft_cases",
    "load_suite",
    "looks_usable",
    "notable_confusions",
    "per_tool_scores",
    "run_suite",
    "score",
    "tool_definitions",
    "validate_against",
    "write_suite",
]
