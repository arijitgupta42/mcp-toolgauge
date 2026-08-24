"""The rule registry and the runner that drives it.

A rule is a function from a `LintContext` to some `Problem`s. It never constructs a
`Finding`, never reads configuration, and never decides its own severity -- the engine does
all three. That keeps a rule module to the thing it is actually good at, which is knowing
what bad looks like.

Rules are pure and offline by construction: the context they receive is data that has
already been fetched, and there is no client, no filesystem handle, and no clock anywhere
in this module. Lint runs on every pull request, so it has to be free and instant.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from mcp_toolgauge.lint.text import (
    content_bag,
    identifier_tokens,
    meaningful_name_tokens,
)
from mcp_toolgauge.model import (
    Finding,
    InspectResult,
    LintResult,
    Problem,
    ServerInfo,
    Severity,
    ToolAnnotations,
    ToolSpec,
)


@dataclass(frozen=True)
class LintTool:
    """A tool plus the text analysis every rule would otherwise redo.

    Tokenising ten descriptions is cheap; tokenising them once per rule per pairwise
    comparison is not, and the overlap rules are O(n^2).
    """

    index: int
    spec: ToolSpec
    name_tokens: tuple[str, ...]
    subject_tokens: tuple[str, ...]
    description_bag: frozenset[str]

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def description(self) -> str | None:
        return self.spec.description

    @property
    def annotations(self) -> ToolAnnotations | None:
        return self.spec.annotations

    @property
    def parameters(self) -> dict[str, Any]:
        return self.spec.parameters


@dataclass(frozen=True)
class LintContext:
    """Everything a rule is allowed to look at."""

    server: ServerInfo
    tools: tuple[LintTool, ...]

    @classmethod
    def build(cls, server: ServerInfo, specs: Iterable[ToolSpec]) -> LintContext:
        return cls(
            server=server,
            tools=tuple(
                LintTool(
                    index=index,
                    spec=spec,
                    name_tokens=identifier_tokens(spec.name),
                    subject_tokens=meaningful_name_tokens(spec.name),
                    description_bag=content_bag(spec.description),
                )
                for index, spec in enumerate(specs)
            ),
        )


RuleFunction = Callable[[LintContext], Iterable[Problem]]


@dataclass(frozen=True)
class Rule:
    """One check, its identity, and what it costs you to ignore."""

    id: str
    name: str
    summary: str
    severity: Severity
    check: RuleFunction

    @property
    def docs_path(self) -> str:
        """Where this rule's "why it matters" page lives, relative to the repo root."""
        return f"docs/rules/{self.id}.md"

    @property
    def help_uri(self) -> str:
        return f"https://github.com/arijitgupta42/mcp-toolgauge/blob/main/{self.docs_path}"


_REGISTRY: dict[str, Rule] = {}


def rule(
    rule_id: str,
    name: str,
    *,
    severity: Severity,
    summary: str,
) -> Callable[[RuleFunction], RuleFunction]:
    """Register a check under an `MCP0xx` ID.

    The function is returned unchanged, so a rule stays directly callable in a test without
    going through the engine.
    """

    def register(function: RuleFunction) -> RuleFunction:
        if rule_id in _REGISTRY:
            raise ValueError(f"Rule {rule_id} is already registered.")
        _REGISTRY[rule_id] = Rule(
            id=rule_id, name=name, summary=summary, severity=severity, check=function
        )
        return function

    return register


def all_rules() -> tuple[Rule, ...]:
    """Every registered rule, in ID order.

    Sorted rather than in registration order so that output, and anything golden-tested
    against it, does not depend on which module Python imported first.
    """
    return tuple(sorted(_REGISTRY.values(), key=lambda item: item.id))


def get_rule(rule_id: str) -> Rule | None:
    return _REGISTRY.get(rule_id)


def rule_ids() -> frozenset[str]:
    return frozenset(_REGISTRY)


@dataclass(frozen=True)
class _Ordering:
    """Sort key material, kept out of the sort lambda so the intent stays readable."""

    tool_index: dict[str, int] = field(default_factory=dict)

    def key(self, finding: Finding) -> tuple[int, str, str]:
        # Server-level findings sort first: they are about the whole surface, so they set
        # the context for everything under them.
        index = -1 if finding.tool is None else self.tool_index.get(finding.tool, 1 << 30)
        return (index, finding.rule, finding.parameter or "")


def run_rules(
    context: LintContext,
    *,
    severities: Mapping[str, Severity] | None = None,
) -> tuple[Finding, ...]:
    """Run every enabled rule and return its findings in a deterministic order.

    `severities` overrides a rule's default severity by ID; `Severity.OFF` disables the
    rule, and a disabled rule is not run at all rather than run and filtered, so turning a
    rule off is also how you make it stop costing you anything.
    """
    overrides = severities or {}
    findings: list[Finding] = []

    for registered in all_rules():
        severity = overrides.get(registered.id, registered.severity)
        if severity is Severity.OFF:
            continue
        for problem in registered.check(context):
            findings.append(
                Finding(
                    rule=registered.id,
                    severity=severity,
                    message=problem.message,
                    suggestion=problem.suggestion,
                    tool=problem.tool,
                    parameter=problem.parameter,
                    related=problem.related,
                )
            )

    ordering = _Ordering({tool.name: tool.index for tool in context.tools})
    findings.sort(key=ordering.key)
    return tuple(findings)


def lint(
    result: InspectResult,
    *,
    severities: Mapping[str, Severity] | None = None,
) -> LintResult:
    """Lint an already-fetched `InspectResult`. The whole public surface of the engine."""
    context = LintContext.build(result.server, result.tools)
    return LintResult(
        target=result.target,
        server=result.server,
        tool_count=len(result.tools),
        findings=run_rules(context, severities=severities),
    )
