"""Budget rules -- MCP050 to MCP052.

These are the only rules about the tool list being *expensive* rather than unclear, so the
fixtures are sized in tokens against the rule's own thresholds rather than hand-written
prose. The thresholds are imported, so what a test asserts is "over the line fires, under it
does not" -- not a particular number that a later tuning would falsify.
"""

from __future__ import annotations

from mcp_doctor.lint.rules.budget import (
    SERVER_BUDGET,
    SINGLE_TOOL_LIMIT,
    TOOL_COUNT_LIMIT,
    _definition_tokens,
)
from mcp_doctor.model import ToolSpec


def sized_tool(name: str, tokens: int) -> ToolSpec:
    """A tool whose definition estimates roughly `tokens`, padded with repeated prose.

    Only the description is padded; the schema is left empty, so nothing but MCP050/051's
    own measurement reacts to the size.
    """
    return ToolSpec(name=name, description="word " * (tokens * 4 // 5 + 1))


class TestMCP050SingleToolTooLarge:
    def test_an_oversized_definition_is_flagged(self, problems) -> None:
        big = sized_tool("create_ticket", SINGLE_TOOL_LIMIT + 300)
        assert _definition_tokens(big) > SINGLE_TOOL_LIMIT  # the fixture really is over the line

        found = problems("MCP050", big)

        assert len(found) == 1
        assert found[0].tool == "create_ticket"
        assert found[0].parameter is None

    def test_a_normal_definition_is_left_alone(self, problems) -> None:
        small = sized_tool("create_ticket", SINGLE_TOOL_LIMIT - 300)
        assert _definition_tokens(small) < SINGLE_TOOL_LIMIT

        assert not problems("MCP050", small)

    def test_the_message_names_a_token_figure(self, problems) -> None:
        """An author cannot act on 'too large' without knowing how large."""
        found = problems("MCP050", sized_tool("t", SINGLE_TOOL_LIMIT + 300))

        assert "tokens" in found[0].message


class TestMCP051ServerBudget:
    def test_a_surface_over_budget_is_flagged_once(self, problems) -> None:
        # Five tools that together clear the budget; the finding is about the sum, not any
        # one of them, so there is exactly one and it is server-level.
        each = SERVER_BUDGET // 4
        tools = tuple(sized_tool(f"tool_{index}", each) for index in range(5))
        assert sum(_definition_tokens(spec) for spec in tools) > SERVER_BUDGET

        found = problems("MCP051", *tools)

        assert len(found) == 1
        assert found[0].tool is None

    def test_a_surface_under_budget_is_left_alone(self, problems) -> None:
        tools = tuple(sized_tool(f"tool_{index}", 100) for index in range(3))

        assert not problems("MCP051", *tools)

    def test_no_tools_at_all_is_not_a_finding(self, problems) -> None:
        assert not problems("MCP051")


class TestMCP052TooManyTools:
    def test_a_crowded_server_is_flagged_once(self, problems) -> None:
        tools = tuple(
            ToolSpec(name=f"tool_{index}", description="A perfectly clear tool.")
            for index in range(TOOL_COUNT_LIMIT + 1)
        )

        found = problems("MCP052", *tools)

        assert len(found) == 1
        assert found[0].tool is None
        assert str(TOOL_COUNT_LIMIT + 1) in found[0].message

    def test_a_server_at_the_limit_is_left_alone(self, problems) -> None:
        tools = tuple(
            ToolSpec(name=f"tool_{index}", description="A perfectly clear tool.")
            for index in range(TOOL_COUNT_LIMIT)
        )

        assert not problems("MCP052", *tools)
