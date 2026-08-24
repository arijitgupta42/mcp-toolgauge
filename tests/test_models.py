"""The shared vocabulary. Small surface, but everything downstream is built on it."""

from __future__ import annotations

import json

from mcpcheckup.model import InspectResult, ServerInfo, ToolAnnotations, ToolSpec, canonical_json


def _spec(**overrides) -> ToolSpec:
    defaults = {
        "name": "search_users",
        "description": "Find people.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"],
        },
    }
    return ToolSpec(**{**defaults, **overrides})


class TestToolSpec:
    def test_parameters_come_from_the_schema_properties(self) -> None:
        assert set(_spec().parameters) == {"query", "limit"}

    def test_required_parameters_are_reported(self) -> None:
        assert _spec().required_parameters == ("query",)

    def test_a_schema_without_properties_yields_no_parameters(self) -> None:
        assert _spec(input_schema={"type": "object"}).parameters == {}

    def test_a_malformed_properties_block_does_not_explode(self) -> None:
        # Servers in the wild emit surprising schemas; a linter must survive them.
        assert _spec(input_schema={"properties": "not-a-dict"}).parameters == {}

    def test_a_malformed_required_block_does_not_explode(self) -> None:
        assert _spec(input_schema={"required": "query"}).required_parameters == ()

    def test_specs_are_immutable(self) -> None:
        spec = _spec()
        try:
            spec.name = "changed"  # type: ignore[misc]
        except Exception as exc:
            assert "frozen" in str(exc).lower() or "immutable" in str(exc).lower()
        else:
            raise AssertionError("ToolSpec should be frozen")


class TestDescriptionNormalisation:
    """Python 3.13 dedents docstrings at compile time; 3.11 and 3.12 do not.

    Without normalising, the description text -- and so every length, similarity, and eval
    prompt built from it -- would depend on the server author's interpreter.
    """

    def test_indented_continuation_lines_are_dedented(self) -> None:
        raw = "Find people.\n\n    Use this for a person, not an org.\n    "

        assert _spec(description=raw).description == (
            "Find people.\n\nUse this for a person, not an org."
        )

    def test_an_already_dedented_description_is_unchanged(self) -> None:
        dedented = "Find people.\n\nUse this for a person, not an org."

        assert _spec(description=dedented).description == dedented

    def test_both_python_docstring_shapes_agree(self) -> None:
        """The 3.11/3.12 shape and the 3.13 shape must land on the same text."""
        pre_313 = "Find people.\n\n    Use this for a person.\n    "
        py_313 = "Find people.\n\nUse this for a person.\n"

        assert _spec(description=pre_313).description == _spec(description=py_313).description

    def test_an_empty_description_collapses_to_none(self) -> None:
        assert _spec(description="").description is None

    def test_a_whitespace_only_description_collapses_to_none(self) -> None:
        assert _spec(description="   \n  \n").description is None

    def test_titles_are_normalised_too(self) -> None:
        assert _spec(title="  Spaced  ").title == "Spaced"


class TestAnnotations:
    def test_unset_hints_stay_none(self) -> None:
        """None and False mean different things: 'said nothing' versus 'said no'."""
        annotations = ToolAnnotations(read_only_hint=True)

        assert annotations.read_only_hint is True
        assert annotations.destructive_hint is None

    def test_false_is_preserved_rather_than_collapsed(self) -> None:
        assert ToolAnnotations(destructive_hint=False).destructive_hint is False


class TestInspectResult:
    def test_tool_names_are_listed_in_order(self) -> None:
        result = InspectResult(
            target="python server.py",
            server=ServerInfo(name="s"),
            tools=(_spec(name="a"), _spec(name="b")),
        )

        assert result.tool_names == ("a", "b")


class TestCanonicalJson:
    def _result(self) -> InspectResult:
        return InspectResult(
            target="python server.py",
            server=ServerInfo(name="acme", version="1.0.0"),
            tools=(_spec(),),
        )

    def test_output_parses(self) -> None:
        assert json.loads(canonical_json(self._result()))["target"] == "python server.py"

    def test_keys_are_sorted(self) -> None:
        payload = json.loads(canonical_json(self._result()))
        assert list(payload) == sorted(payload)

    def test_the_same_input_always_produces_the_same_bytes(self) -> None:
        """The eval cache key will depend on this, so it has to be stable."""
        assert canonical_json(self._result()) == canonical_json(self._result())

    def test_key_order_in_the_source_does_not_change_the_output(self) -> None:
        first = ToolSpec(name="t", description="d", input_schema={"a": 1, "b": 2})
        second = ToolSpec(name="t", description="d", input_schema={"b": 2, "a": 1})

        assert canonical_json(first) == canonical_json(second)

    def test_unset_fields_are_omitted(self) -> None:
        payload = json.loads(canonical_json(_spec(description=None)))

        assert "description" not in payload

    def test_compact_mode_has_no_newlines(self) -> None:
        assert "\n" not in canonical_json(self._result(), indent=None)
