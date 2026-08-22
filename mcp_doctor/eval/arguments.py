"""Checking the arguments a model passed against the schema it was given.

Pure, offline, and deliberately not a JSON Schema validator. A general validator is both
more and less than what is wanted here. More, because it will happily fail a call over a
`multipleOf` or a `$ref` that has nothing to do with whether the tool was usable. Less,
because its messages -- "'x' is not valid under any of the given schemas" -- are not
something a server author can act on.

So this checks the four things that actually go wrong when a model fills in a tool call,
and reports each one by parameter name:

* a required parameter the model did not supply
* a parameter the schema never declared, which is the model inventing one
* a value of the wrong JSON type
* a value outside the declared `enum`

Each maps to a different fix. "Missing required" usually means the description never said
where to get the value; "unknown" usually means a parameter name that reads like something
it is not; "bad enum" almost always means the allowed values were never written down.

`anyOf` and `oneOf` are walked because that is how every Python MCP server spells an
optional or literal parameter -- `str | None` becomes `anyOf: [string, null]`, and a
`Literal` becomes an enum branch. Nothing else in the vocabulary is interpreted, and an
unrecognised schema yields no opinion rather than a guess.
"""

from __future__ import annotations

from typing import Any

from mcp_doctor.model import ArgumentCheck, ToolSpec

# Reasons a value can be rejected. Strings rather than an enum: they are internal to this
# module and they name the `ArgumentCheck` field they are collected into.
_WRONG_TYPE = "wrong_type"
_BAD_ENUM = "bad_enum"

# Deep enough for the nested unions Pydantic generates, shallow enough that a self-
# referential schema cannot spin. Past the limit we stop having an opinion, which is the
# safe direction to fail in: a checker that invents problems is worse than one that misses
# them.
_MAX_DEPTH = 6

_BRANCH_KEYWORDS = ("anyOf", "oneOf")


def _is_type(value: Any, name: str) -> bool:
    """Whether `value` is the JSON type `name`.

    `bool` is checked before the numeric types throughout, because in Python `True` is an
    `int` and a schema that asked for an integer did not ask for a boolean.
    """
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    if name == "null":
        return value is None
    # A type keyword we do not know is a type we do not judge.
    return True


def _declared_types(schema: dict[str, Any]) -> tuple[str, ...]:
    """The `type` keyword as a tuple, whether it was written as a string or a list."""
    declared = schema.get("type")
    if isinstance(declared, str):
        return (declared,)
    if isinstance(declared, list):
        return tuple(item for item in declared if isinstance(item, str))
    return ()


def _reject(value: Any, schema: dict[str, Any], depth: int = 0) -> str | None:
    """Why `value` is not acceptable to `schema`, or None if it is.

    Returns one of the two reason constants so the caller can file the parameter under the
    right heading. A schema this module does not understand returns None: no opinion.
    """
    if depth > _MAX_DEPTH or not isinstance(schema, dict) or "$ref" in schema:
        return None

    for keyword in _BRANCH_KEYWORDS:
        branches = schema.get(keyword)
        if isinstance(branches, list) and branches:
            reasons = [
                _reject(value, branch, depth + 1)
                for branch in branches
                if isinstance(branch, dict)
            ]
            if not reasons or None in reasons:
                return None
            # A value rejected by every branch is reported as an enum problem if any branch
            # thought so. For the common `Literal[...] | None`, "not one of the allowed
            # values" is the true and useful complaint; "wrong type" is neither.
            return _BAD_ENUM if _BAD_ENUM in reasons else _WRONG_TYPE

    if "const" in schema and value != schema["const"]:
        return _BAD_ENUM

    allowed = schema.get("enum")
    if isinstance(allowed, list) and allowed and value not in allowed:
        return _BAD_ENUM

    declared = _declared_types(schema)
    if declared and not any(_is_type(value, name) for name in declared):
        return _WRONG_TYPE

    return None


def _accepts_extras(schema: dict[str, Any]) -> bool:
    """Whether the schema says arguments it never declared are welcome.

    JSON Schema's default for `additionalProperties` is "allowed", but applying that
    default here would mean never reporting a hallucinated parameter -- which is the single
    most interesting thing this checker can find. So the default is inverted: a schema that
    bothered to declare its properties is read as meaning those are the properties, and an
    author who really does accept extras can say `additionalProperties: true` and be
    believed.
    """
    extras = schema.get("additionalProperties")
    return extras is not False and extras is not None


def check_arguments(tool: ToolSpec, arguments: dict[str, Any]) -> ArgumentCheck:
    """Compare one tool call's arguments against the tool's declared input schema."""
    properties = tool.parameters
    missing = tuple(
        name for name in tool.required_parameters if name not in arguments
    )

    unknown: list[str] = []
    wrong_type: list[str] = []
    bad_enum: list[str] = []

    permissive = not properties or _accepts_extras(tool.input_schema)

    for name, value in arguments.items():
        if name not in properties:
            if not permissive:
                unknown.append(name)
            continue
        subschema = properties[name]
        if not isinstance(subschema, dict):
            # Declared, but with a subschema this module cannot read. "Undeclared" would be
            # the wrong complaint -- the author did declare it -- and there is nothing to
            # check the value against, so the honest answer is no opinion.
            continue
        reason = _reject(value, subschema)
        if reason == _WRONG_TYPE:
            wrong_type.append(name)
        elif reason == _BAD_ENUM:
            bad_enum.append(name)

    # Sorted rather than in call order: the model's key order is not stable between
    # providers, and a report that reorders itself between runs is a report nobody diffs.
    return ArgumentCheck(
        missing_required=tuple(sorted(missing)),
        unknown=tuple(sorted(unknown)),
        wrong_type=tuple(sorted(wrong_type)),
        bad_enum=tuple(sorted(bad_enum)),
    )


def describe(check: ArgumentCheck, tool: str) -> tuple[str, ...]:
    """The check as sentences, for a report. Empty when nothing was wrong."""
    lines: list[str] = []
    if check.missing_required:
        lines.append(f"{tool} was called without required {_names(check.missing_required)}")
    if check.unknown:
        lines.append(f"{tool} was called with undeclared {_names(check.unknown)}")
    if check.wrong_type:
        lines.append(f"{tool} was called with the wrong type for {_names(check.wrong_type)}")
    if check.bad_enum:
        lines.append(
            f"{tool} was called with a value outside the enum for {_names(check.bad_enum)}"
        )
    return tuple(lines)


def _names(names: tuple[str, ...]) -> str:
    label = "parameter" if len(names) == 1 else "parameters"
    return f"{label} {', '.join(names)}"
