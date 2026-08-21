"""Parameter rules -- MCP020 to MCP025.

Selecting the right tool is only half of a successful call; the model then has to invent
arguments for it. Every one of these rules is about the same failure: the schema knows
something the model is being asked to guess.

A note on `title`. Servers built on Pydantic emit an auto-generated `title` for every field
-- `query` becomes `"Query"` -- which looks like documentation in a JSON dump and contains
no information whatsoever. Nothing in this module treats `title` as a description.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from mcp_doctor.lint.engine import LintContext, rule
from mcp_doctor.lint.text import (
    DATE_LIKE_NAMES,
    DATE_LIKE_SUFFIXES,
    EMAIL_LIKE_NAMES,
    ENUM_LIKE_NAMES,
    ENUMERATION_PATTERN,
    EXAMPLE_PATTERN,
    URL_LIKE_NAMES,
    identifier_tokens,
    is_subset_of_name,
)
from mcp_doctor.model import Problem, Severity

# Keywords that pin a value's syntax down well enough that a model can produce one.
_CONSTRAINTS = ("enum", "const", "pattern", "format")


def _branches(schema: Any) -> list[dict[str, Any]]:
    """The real alternatives in a subschema, with the `null` arm of an optional dropped.

    An optional Pydantic field arrives as `anyOf: [{...}, {"type": "null"}]`, with the
    description and any `format` sitting at the top level alongside the `anyOf`. Rules need
    to see through that, or every optional parameter looks untyped and undocumented.
    """
    if not isinstance(schema, dict):
        return []
    for key in ("anyOf", "oneOf"):
        options = schema.get(key)
        if isinstance(options, list):
            real = [
                option
                for option in options
                if isinstance(option, dict) and option.get("type") != "null"
            ]
            if real:
                return real
    return [schema]


def _anywhere(schema: dict[str, Any], *keys: str) -> bool:
    """Whether any of `keys` is set at the top level or in one of the branches."""
    if any(schema.get(key) is not None for key in keys):
        return True
    return any(any(branch.get(key) is not None for key in keys) for branch in _branches(schema))


def _description_of(schema: Any) -> str | None:
    if not isinstance(schema, dict):
        return None
    for candidate in (schema, *_branches(schema)):
        text = candidate.get("description")
        if isinstance(text, str) and text.strip():
            return text
    return None


def _is_string(schema: dict[str, Any]) -> bool:
    for branch in _branches(schema):
        declared = branch.get("type")
        if declared == "string" or (isinstance(declared, list) and "string" in declared):
            return True
    return False


def _named_parameters(tool: Any) -> Iterable[tuple[str, dict[str, Any]]]:
    """Parameters whose subschema is a dict. Servers in the wild emit surprising shapes."""
    for name, schema in tool.parameters.items():
        if isinstance(schema, dict):
            yield name, schema


@rule(
    "MCP020",
    "parameter-missing-description",
    severity=Severity.WARNING,
    summary="A parameter has no description.",
)
def parameter_missing_description(ctx: LintContext) -> Iterable[Problem]:
    for tool in ctx.tools:
        for name, schema in _named_parameters(tool):
            if _description_of(schema) is not None:
                continue
            yield Problem(
                message=f"`{tool.name}.{name}` has no description.",
                suggestion=(
                    f"Describe what `{name}` is for, what a valid value looks like, and "
                    "what happens when it is omitted. An auto-generated `title` is not a "
                    "description -- it is the parameter name with a capital letter."
                ),
                tool=tool.name,
                parameter=name,
            )


@rule(
    "MCP021",
    "parameter-description-restates-name",
    severity=Severity.INFO,
    summary="A parameter's description only repeats its name.",
)
def parameter_description_restates_name(ctx: LintContext) -> Iterable[Problem]:
    for tool in ctx.tools:
        for name, schema in _named_parameters(tool):
            description = _description_of(schema)
            if description is None or not is_subset_of_name(description, name):
                continue
            yield Problem(
                message=(
                    f"`{tool.name}.{name}`'s description ({' '.join(description.split())!r}) "
                    "only restates its name."
                ),
                suggestion=(
                    f"Say something `{name}` does not already say: the units, the accepted "
                    "range, where the value comes from, an example. \"The limit\" as the "
                    "description of `limit` costs tokens and teaches nothing."
                ),
                tool=tool.name,
                parameter=name,
            )


@rule(
    "MCP022",
    "free-string-with-enum-candidates",
    severity=Severity.WARNING,
    summary="A free-form string parameter looks like it has a fixed set of valid values.",
)
def free_string_with_enum_candidates(ctx: LintContext) -> Iterable[Problem]:
    """Fire on string parameters whose name, or whose own prose, implies a closed set.

    `status: str` is an invitation to hallucinate. `status: Literal["open", "closed"]`
    becomes an `enum` in the schema, and the model can then only send a value that works.
    """
    for tool in ctx.tools:
        for name, schema in _named_parameters(tool):
            if not _is_string(schema) or _anywhere(schema, *_CONSTRAINTS):
                continue
            description = _description_of(schema) or ""
            by_name = bool(set(identifier_tokens(name)) & ENUM_LIKE_NAMES)
            by_prose = bool(ENUMERATION_PATTERN.search(description))
            if not (by_name or by_prose):
                continue

            reason = (
                "its description lists the values it accepts"
                if by_prose and not by_name
                else f"`{name}` almost always has a fixed set of valid values"
            )
            yield Problem(
                message=(
                    f"`{tool.name}.{name}` is a free-form string, but {reason}."
                ),
                suggestion=(
                    f"Declare the allowed values as an `enum` on `{name}` -- in Python, "
                    "type the argument as `Literal[\"open\", \"closed\"]` and the schema "
                    "follows. A model given an open string will invent a plausible value "
                    "and the call fails at validation, which reads to the user as the "
                    "tool being broken."
                ),
                tool=tool.name,
                parameter=name,
            )


def _format_shape(name: str) -> str | None:
    """What well-known syntax a parameter name implies, if any."""
    tokens = set(identifier_tokens(name))
    if tokens & EMAIL_LIKE_NAMES:
        return "an email address"
    if tokens & URL_LIKE_NAMES:
        return "a URL"
    if tokens & DATE_LIKE_NAMES or name.lower().endswith(DATE_LIKE_SUFFIXES):
        return "a date or timestamp"
    return None


@rule(
    "MCP023",
    "unconstrained-well-known-format",
    severity=Severity.WARNING,
    summary="A date, email, or URL parameter declares no format or pattern.",
)
def unconstrained_well_known_format(ctx: LintContext) -> Iterable[Problem]:
    """Only the parameter *name* triggers this, never the description.

    Triggering on description text was tried and is a false-positive machine: a search
    tool whose `query` description mentions matching on an email address is not itself an
    email parameter.
    """
    for tool in ctx.tools:
        for name, schema in _named_parameters(tool):
            if not _is_string(schema) or _anywhere(schema, *_CONSTRAINTS):
                continue
            shape = _format_shape(name)
            if shape is None:
                continue
            yield Problem(
                message=(
                    f"`{tool.name}.{name}` looks like {shape} but the schema constrains "
                    "nothing."
                ),
                suggestion=(
                    f"Add a JSON Schema `format` (`date`, `date-time`, `email`, `uri`) or "
                    f"a `pattern` to `{name}`, and put a concrete example in its "
                    "description. Otherwise every model picks its own convention and half "
                    "of them are wrong -- this is where `2026-01-31` and `31/01/2026` and "
                    "`last Tuesday` all arrive at the same endpoint."
                ),
                tool=tool.name,
                parameter=name,
            )


@rule(
    "MCP024",
    "untyped-parameter",
    severity=Severity.WARNING,
    summary="A parameter has no declared type, or is an object with no declared shape.",
)
def untyped_parameter(ctx: LintContext) -> Iterable[Problem]:
    """Two shapes of the same defect: no type at all, and `object` with no properties."""
    for tool in ctx.tools:
        for name, schema in _named_parameters(tool):
            branches = _branches(schema)
            described = any(
                branch.get(key) is not None
                for branch in branches
                for key in ("type", "enum", "const", "$ref", "properties", "items")
            )
            if not described:
                detail = f"`{tool.name}.{name}` has no declared type."
            elif all(
                branch.get("type") == "object" and not isinstance(branch.get("properties"), dict)
                for branch in branches
            ):
                detail = (
                    f"`{tool.name}.{name}` is an object with no declared properties, so "
                    "its shape is anyone's guess."
                )
            else:
                continue

            yield Problem(
                message=detail,
                suggestion=(
                    f"Give `{name}` a concrete schema -- name its fields, or replace the "
                    "free-form object with the two or three arguments it actually carries. "
                    "An opaque bag is the one parameter shape a model cannot fill in "
                    "correctly by reading the schema, so it guesses from the description "
                    "instead, if there is one."
                ),
                tool=tool.name,
                parameter=name,
            )


def _has_example(tool: Any) -> bool:
    """Whether anything in this tool shows a model a concrete value.

    `default` deliberately does not count. A default is what happens when nobody says
    anything; it is not a worked example of what a good value looks like, and a parameter
    whose only guidance is `default: ""` has told the model nothing.
    """
    if EXAMPLE_PATTERN.search(tool.description or ""):
        return True
    for _, schema in _named_parameters(tool):
        if _anywhere(schema, "examples", "example"):
            return True
        if EXAMPLE_PATTERN.search(_description_of(schema) or ""):
            return True
    return False


@rule(
    "MCP025",
    "no-example-values",
    severity=Severity.INFO,
    summary="Nothing in the tool's schema shows an example value.",
)
def no_example_values(ctx: LintContext) -> Iterable[Problem]:
    for tool in ctx.tools:
        if not tool.parameters or _has_example(tool):
            continue
        yield Problem(
            message=f"Nothing in `{tool.name}`'s schema shows an example value.",
            suggestion=(
                "Put one concrete value in the description of the least obvious parameter "
                "-- \"e.g. 'usr_1a2b'\" -- or add JSON Schema `examples`. Identifiers and "
                "formatted strings are the ones that matter: a model can guess what a "
                "search query looks like, and cannot guess what your IDs look like."
            ),
            tool=tool.name,
        )
