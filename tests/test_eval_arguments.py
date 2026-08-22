"""The argument checker.

Four named failures, each of which maps to a different fix, so each gets tested on its own
and none of them is allowed to collect a false positive from the others.

The `anyOf` cases matter more than they look. Every Python MCP server spells an optional
parameter as `anyOf: [something, null]` and a literal as an enum branch, so a checker that
did not walk them would report a false problem on almost every well-written server -- which
is the worst possible failure mode for a tool whose whole pitch is telling people their
schemas are wrong.
"""

from __future__ import annotations

import pytest

from mcp_doctor.eval.arguments import check_arguments, describe
from mcp_doctor.model import ArgumentCheck, ToolSpec


def spec(properties: dict, required: list[str] | None = None, **extra) -> ToolSpec:
    schema: dict = {"type": "object", "properties": properties, **extra}
    if required is not None:
        schema["required"] = required
    return ToolSpec(name="search_users", description="Find people.", input_schema=schema)


STRING = spec({"query": {"type": "string"}}, ["query"])


class TestMissingRequired:
    def test_an_absent_required_parameter_is_reported(self) -> None:
        assert check_arguments(STRING, {}).missing_required == ("query",)

    def test_a_supplied_one_is_not(self) -> None:
        assert check_arguments(STRING, {"query": "ada"}).ok

    def test_an_optional_one_may_be_absent(self) -> None:
        tool = spec({"query": {"type": "string"}, "limit": {"type": "integer"}}, ["query"])

        assert check_arguments(tool, {"query": "ada"}).ok

    def test_explicit_null_counts_as_supplied(self) -> None:
        """The model answered the question. Whether null is a *good* answer is the
        schema's business, not this check's."""
        assert check_arguments(STRING, {"query": None}).missing_required == ()


class TestUnknown:
    def test_a_parameter_the_schema_never_declared_is_reported(self) -> None:
        assert check_arguments(STRING, {"query": "ada", "limit": 5}).unknown == ("limit",)

    def test_additional_properties_true_is_believed(self) -> None:
        """JSON Schema's default is permissive, but a schema that lists its properties is
        read as meaning those are the properties. An author who really accepts extras says
        so, and is believed."""
        tool = spec({"query": {"type": "string"}}, ["query"], additionalProperties=True)

        assert check_arguments(tool, {"query": "ada", "extra": 1}).ok

    def test_additional_properties_false_is_also_believed(self) -> None:
        tool = spec({"query": {"type": "string"}}, ["query"], additionalProperties=False)

        assert check_arguments(tool, {"query": "ada", "extra": 1}).unknown == ("extra",)

    def test_a_schema_with_no_properties_accuses_nobody(self) -> None:
        """A tool that declared nothing has no grounds to complain about anything."""
        tool = ToolSpec(name="run", description="Runs.", input_schema={"type": "object"})

        assert check_arguments(tool, {"anything": 1}).ok


class TestTypes:
    @pytest.mark.parametrize(
        ("declared", "value"),
        [
            ("string", "ada"),
            ("integer", 3),
            ("number", 3),
            ("number", 3.5),
            ("boolean", True),
            ("array", [1, 2]),
            ("object", {"a": 1}),
            ("null", None),
        ],
    )
    def test_matching_values_pass(self, declared: str, value: object) -> None:
        assert check_arguments(spec({"p": {"type": declared}}), {"p": value}).ok

    @pytest.mark.parametrize(
        ("declared", "value"),
        [
            ("string", 3),
            ("integer", "3"),
            ("integer", 3.5),
            ("number", "3"),
            ("boolean", "true"),
            ("array", {"a": 1}),
            ("object", [1]),
            ("null", 0),
        ],
    )
    def test_mismatched_values_are_reported(self, declared: str, value: object) -> None:
        assert check_arguments(spec({"p": {"type": declared}}), {"p": value}).wrong_type == ("p",)

    def test_a_bool_is_not_an_integer(self) -> None:
        """True is an int in Python and is not one in JSON Schema. Getting this wrong would
        silently accept `limit=true`."""
        assert check_arguments(spec({"p": {"type": "integer"}}), {"p": True}).wrong_type == ("p",)

    def test_a_bool_is_not_a_number(self) -> None:
        assert check_arguments(spec({"p": {"type": "number"}}), {"p": False}).wrong_type == ("p",)

    def test_a_type_list_accepts_any_of_them(self) -> None:
        tool = spec({"p": {"type": ["string", "null"]}})

        assert check_arguments(tool, {"p": "x"}).ok
        assert check_arguments(tool, {"p": None}).ok
        assert check_arguments(tool, {"p": 1}).wrong_type == ("p",)

    def test_a_parameter_with_no_declared_type_is_not_judged(self) -> None:
        assert check_arguments(spec({"p": {"title": "P"}}), {"p": object()}).ok


class TestEnums:
    PRIORITY = spec({"priority": {"type": "string", "enum": ["low", "high"]}})

    def test_an_allowed_value_passes(self) -> None:
        assert check_arguments(self.PRIORITY, {"priority": "low"}).ok

    def test_a_value_outside_the_enum_is_reported(self) -> None:
        assert check_arguments(self.PRIORITY, {"priority": "urgent"}).bad_enum == ("priority",)

    def test_a_const_behaves_like_a_one_value_enum(self) -> None:
        tool = spec({"p": {"const": "only"}})

        assert check_arguments(tool, {"p": "only"}).ok
        assert check_arguments(tool, {"p": "other"}).bad_enum == ("p",)

    def test_an_empty_enum_is_not_a_constraint(self) -> None:
        assert check_arguments(spec({"p": {"enum": []}}), {"p": "x"}).ok


class TestUnions:
    """`str | None` and `Literal[...] | None`, which is what real servers emit."""

    OPTIONAL = spec({"p": {"anyOf": [{"type": "string"}, {"type": "null"}]}})
    OPTIONAL_LITERAL = spec(
        {"p": {"anyOf": [{"type": "string", "enum": ["open", "closed"]}, {"type": "null"}]}}
    )

    def test_either_branch_is_accepted(self) -> None:
        assert check_arguments(self.OPTIONAL, {"p": "x"}).ok
        assert check_arguments(self.OPTIONAL, {"p": None}).ok

    def test_neither_branch_is_rejected(self) -> None:
        assert check_arguments(self.OPTIONAL, {"p": 5}).wrong_type == ("p",)

    def test_an_optional_literal_accepts_its_values_and_null(self) -> None:
        assert check_arguments(self.OPTIONAL_LITERAL, {"p": "open"}).ok
        assert check_arguments(self.OPTIONAL_LITERAL, {"p": None}).ok

    def test_a_wrong_literal_reads_as_an_enum_problem_not_a_type_one(self) -> None:
        """"not one of the allowed values" is the true and useful complaint here. "wrong
        type" would send the author to fix something that is not broken."""
        assert check_arguments(self.OPTIONAL_LITERAL, {"p": "bogus"}).bad_enum == ("p",)

    def test_one_of_is_walked_like_any_of(self) -> None:
        tool = spec({"p": {"oneOf": [{"type": "integer"}, {"type": "null"}]}})

        assert check_arguments(tool, {"p": 1}).ok
        assert check_arguments(tool, {"p": "x"}).wrong_type == ("p",)

    def test_an_empty_branch_list_is_ignored(self) -> None:
        assert check_arguments(spec({"p": {"anyOf": []}}), {"p": 1}).ok


class TestNoOpinion:
    def test_a_ref_is_not_judged(self) -> None:
        """We do not resolve references, so we do not get to have views about them."""
        assert check_arguments(spec({"p": {"$ref": "#/$defs/Thing"}}), {"p": 1}).ok

    def test_a_deeply_nested_union_stops_rather_than_guesses(self) -> None:
        """Past the depth limit the checker gives up, which is the safe direction: a
        checker that invents problems is worse than one that misses them."""
        schema: dict = {"type": "string"}
        for _ in range(12):
            schema = {"anyOf": [schema]}

        assert check_arguments(spec({"p": schema}), {"p": 999}).ok

    def test_a_non_dict_subschema_is_skipped(self) -> None:
        assert check_arguments(spec({"p": "not a schema"}), {"p": 1}).ok


class TestReporting:
    def test_several_problems_are_reported_together(self) -> None:
        tool = spec(
            {"query": {"type": "string"}, "priority": {"enum": ["low"]}},
            ["query", "body"],
        )

        check = check_arguments(tool, {"query": 1, "priority": "high", "extra": True})

        # `query` was supplied, just with the wrong type -- it is not also missing.
        assert check.missing_required == ("body",)
        assert check.unknown == ("extra",)
        assert check.wrong_type == ("query",)
        assert check.bad_enum == ("priority",)
        assert not check.ok

    def test_names_are_sorted_so_a_report_does_not_reorder_itself(self) -> None:
        """Providers do not agree on key order, and a report that shuffles between runs is
        a report nobody diffs."""
        tool = spec({"a": {"type": "string"}}, [])

        assert check_arguments(tool, {"z": 1, "b": 2, "m": 3}).unknown == ("b", "m", "z")

    def test_a_clean_check_describes_nothing(self) -> None:
        assert describe(ArgumentCheck(), "search_users") == ()

    def test_each_problem_becomes_a_sentence_naming_the_tool(self) -> None:
        lines = describe(
            ArgumentCheck(
                missing_required=("query",),
                unknown=("extra",),
                wrong_type=("limit",),
                bad_enum=("priority",),
            ),
            "search_users",
        )

        assert len(lines) == 4
        assert all(line.startswith("search_users ") for line in lines)
        assert "required parameter query" in lines[0]

    def test_the_plural_agrees(self) -> None:
        one = describe(ArgumentCheck(unknown=("a",)), "t")[0]
        two = describe(ArgumentCheck(unknown=("a", "b")), "t")[0]

        assert "parameter a" in one
        assert "parameters a, b" in two
