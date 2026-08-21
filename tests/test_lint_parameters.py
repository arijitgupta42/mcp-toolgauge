"""Parameter rules -- MCP020 to MCP025.

Two shapes turn up constantly in real servers and both are represented here: Pydantic's
auto-generated `title` on every field, which looks like documentation and is not, and its
`anyOf: [..., {"type": "null"}]` wrapping of every optional, which hides the real schema
one level down.
"""

from __future__ import annotations

from typing import Any


def schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or []}


def optional(inner: dict[str, Any], **top: Any) -> dict[str, Any]:
    """How Pydantic emits `X | None`: the real schema in an `anyOf`, everything else above."""
    return {"anyOf": [inner, {"type": "null"}], "default": None, **top}


class TestMCP020ParameterMissingDescription:
    def test_an_undocumented_parameter_is_flagged(self, tool, problems) -> None:
        found = problems("MCP020", tool(input_schema=schema({"q": {"type": "string"}})))

        assert found[0].parameter == "q"

    def test_an_auto_generated_title_is_not_documentation(self, tool, problems) -> None:
        """Pydantic gives every field a `title`. It is the field name with a capital
        letter, and counting it would make this rule fire on nothing."""
        assert problems(
            "MCP020", tool(input_schema=schema({"query": {"type": "string", "title": "Query"}}))
        )

    def test_a_described_parameter_is_left_alone(self, tool, problems) -> None:
        assert not problems(
            "MCP020",
            tool(input_schema=schema({"query": {"type": "string", "description": "Who to find."}})),
        )

    def test_a_description_above_an_anyOf_still_counts(self, tool, problems) -> None:
        assert not problems(
            "MCP020",
            tool(
                input_schema=schema(
                    {"org": optional({"type": "string"}, description="Restrict to one org.")}
                )
            ),
        )

    def test_a_tool_with_no_parameters_reports_nothing(self, tool, problems) -> None:
        assert not problems("MCP020", tool(input_schema={"type": "object"}))


class TestMCP021ParameterDescriptionRestatesName:
    def test_a_description_that_is_the_name_again_is_flagged(self, tool, problems) -> None:
        found = problems(
            "MCP021",
            tool(input_schema=schema({"limit": {"type": "integer", "description": "The limit."}})),
        )

        assert found[0].parameter == "limit"

    def test_a_description_that_adds_something_is_left_alone(self, tool, problems) -> None:
        assert not problems(
            "MCP021",
            tool(
                input_schema=schema(
                    {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of people to return. Caps at 100.",
                        }
                    }
                )
            ),
        )

    def test_a_missing_description_is_left_to_MCP020(self, tool, problems) -> None:
        assert not problems("MCP021", tool(input_schema=schema({"limit": {"type": "integer"}})))


class TestMCP022FreeStringWithEnumCandidates:
    def test_a_status_string_is_flagged(self, tool, problems) -> None:
        found = problems("MCP022", tool(input_schema=schema({"status": {"type": "string"}})))

        assert found[0].parameter == "status"

    def test_a_description_listing_values_is_flagged(self, tool, problems) -> None:
        assert problems(
            "MCP022",
            tool(
                input_schema=schema(
                    {"shape": {"type": "string", "description": "One of 'round' or 'square'."}}
                )
            ),
        )

    def test_an_enum_answers_the_question(self, tool, problems) -> None:
        assert not problems(
            "MCP022",
            tool(input_schema=schema({"status": {"type": "string", "enum": ["open", "closed"]}})),
        )

    def test_a_pattern_also_answers_it(self, tool, problems) -> None:
        assert not problems(
            "MCP022",
            tool(input_schema=schema({"mode": {"type": "string", "pattern": "^(fast|slow)$"}})),
        )

    def test_an_open_ended_string_is_left_alone(self, tool, problems) -> None:
        """A search query has no fixed set of valid values, and never will."""
        assert not problems("MCP022", tool(input_schema=schema({"query": {"type": "string"}})))

    def test_a_non_string_parameter_is_left_alone(self, tool, problems) -> None:
        assert not problems("MCP022", tool(input_schema=schema({"status": {"type": "integer"}})))


class TestMCP023UnconstrainedWellKnownFormat:
    def test_a_date_shaped_name_with_no_constraint_is_flagged(self, tool, problems) -> None:
        found = problems("MCP023", tool(input_schema=schema({"when": {"type": "string"}})))

        assert found[0].parameter == "when"
        assert "date" in found[0].message

    def test_a_rails_style_suffix_is_recognised(self, tool, problems) -> None:
        assert problems("MCP023", tool(input_schema=schema({"created_at": {"type": "string"}})))

    def test_an_email_name_is_recognised(self, tool, problems) -> None:
        assert problems("MCP023", tool(input_schema=schema({"email": {"type": "string"}})))

    def test_a_declared_format_answers_it(self, tool, problems) -> None:
        assert not problems(
            "MCP023",
            tool(input_schema=schema({"since": optional({"type": "string"}, format="date")})),
        )

    def test_the_description_never_triggers_it(self, tool, problems) -> None:
        """A search tool whose `query` mentions matching on an email address is not itself
        an email parameter. Triggering on description text fires on well-written servers."""
        assert not problems(
            "MCP023",
            tool(
                input_schema=schema(
                    {
                        "query": {
                            "type": "string",
                            "description": "Name or email address to match on.",
                        }
                    }
                )
            ),
        )


class TestMCP024UntypedParameter:
    def test_a_parameter_with_no_type_is_flagged(self, tool, problems) -> None:
        found = problems("MCP024", tool(input_schema=schema({"params": {"title": "Params"}})))

        assert "no declared type" in found[0].message

    def test_a_shapeless_object_is_flagged(self, tool, problems) -> None:
        found = problems(
            "MCP024",
            tool(
                input_schema=schema(
                    {"payload": {"type": "object", "additionalProperties": True}}
                )
            ),
        )

        assert "no declared properties" in found[0].message

    def test_a_shapeless_object_inside_an_optional_is_flagged(self, tool, problems) -> None:
        assert problems(
            "MCP024",
            tool(input_schema=schema({"opts": optional({"type": "object"})})),
        )

    def test_an_object_with_properties_is_fine(self, tool, problems) -> None:
        assert not problems(
            "MCP024",
            tool(
                input_schema=schema(
                    {"options": {"type": "object", "properties": {"dry_run": {"type": "boolean"}}}}
                )
            ),
        )

    def test_an_ordinary_typed_parameter_is_fine(self, tool, problems) -> None:
        assert not problems("MCP024", tool(input_schema=schema({"query": {"type": "string"}})))

    def test_an_enum_without_a_type_is_still_a_shape(self, tool, problems) -> None:
        assert not problems(
            "MCP024", tool(input_schema=schema({"status": {"enum": ["open", "closed"]}}))
        )


class TestMCP025NoExampleValues:
    def test_a_tool_with_no_examples_anywhere_is_flagged(self, tool, problems) -> None:
        found = problems(
            "MCP025",
            tool(
                input_schema=schema(
                    {"user_id": {"type": "string", "description": "The person's identifier."}}
                )
            ),
        )

        assert found[0].tool == "search_users"
        assert found[0].parameter is None, "this is about the tool's schema as a whole"

    def test_an_e_g_in_a_description_is_enough(self, tool, problems) -> None:
        assert not problems(
            "MCP025",
            tool(
                input_schema=schema(
                    {
                        "user_id": {
                            "type": "string",
                            "description": "Stable identifier, e.g. 'usr_1a2b'.",
                        }
                    }
                )
            ),
        )

    def test_a_schema_examples_keyword_is_enough(self, tool, problems) -> None:
        assert not problems(
            "MCP025",
            tool(input_schema=schema({"user_id": {"type": "string", "examples": ["usr_1a2b"]}})),
        )

    def test_a_default_is_not_an_example(self, tool, problems) -> None:
        """A default is what happens when nobody says anything. It does not show a model
        what a good value looks like."""
        assert problems(
            "MCP025",
            tool(input_schema=schema({"limit": {"type": "integer", "default": 20}})),
        )

    def test_a_tool_with_no_parameters_has_nothing_to_exemplify(self, tool, problems) -> None:
        assert not problems("MCP025", tool(input_schema={"type": "object"}))
