"""Annotation rules -- MCP040 to MCP042.

The tri-state is what these rules are about. `None` means the server said nothing and is a
finding; `False` means the server said no and is not. Every rule here gets a test for that
distinction specifically, because collapsing the two would make all three rules useless on
any server that had already thought about the question.
"""

from __future__ import annotations

from mcpcheckup.model import ToolAnnotations

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True)


class TestMCP040DestructiveWithoutHint:
    def test_a_delete_verb_in_the_name_is_enough(self, tool, problems) -> None:
        found = problems(
            "MCP040",
            tool(name="delete_all_tickets", description="Removes every ticket for an org."),
        )

        assert found[0].tool == "delete_all_tickets"

    def test_the_description_alone_can_trigger_it(self, tool, problems) -> None:
        assert problems(
            "MCP040",
            tool(
                name="reset_workspace",
                description="Clears the workspace. This cannot be undone by any user.",
            ),
        )

    def test_a_declared_hint_answers_the_question(self, tool, problems) -> None:
        assert not problems(
            "MCP040",
            tool(
                name="archive_ticket",
                description="Permanently archive.",
                annotations=DESTRUCTIVE,
            ),
        )

    def test_saying_no_is_different_from_saying_nothing(self, tool, problems) -> None:
        """A server that declared `destructiveHint: false` has done the thing we ask for,
        even though the answer is no."""
        assert not problems(
            "MCP040",
            tool(
                name="delete_draft",
                description="Discards an unsaved draft.",
                annotations=ToolAnnotations(destructive_hint=False),
            ),
        )

    def test_a_harmless_tool_is_left_alone(self, tool, problems) -> None:
        assert not problems("MCP040", tool(name="search_users"))


class TestMCP041ReadOnlyWithoutHint:
    def test_a_read_verb_in_the_name_is_enough(self, tool, problems) -> None:
        assert problems("MCP041", tool(name="search_users"))

    def test_a_description_that_opens_with_a_read_verb_is_enough(self, tool, problems) -> None:
        assert problems(
            "MCP041",
            tool(name="user_profile", description="Returns the full profile for one person."),
        )

    def test_a_declared_hint_answers_the_question(self, tool, problems) -> None:
        assert not problems("MCP041", tool(name="search_users", annotations=READ_ONLY))

    def test_saying_no_is_different_from_saying_nothing(self, tool, problems) -> None:
        assert not problems(
            "MCP041",
            tool(name="search_users", annotations=ToolAnnotations(read_only_hint=False)),
        )

    def test_a_writing_tool_is_not_asked_for_a_read_only_hint(self, tool, problems) -> None:
        assert not problems(
            "MCP041",
            tool(name="create_support_ticket", description="Open a new support ticket."),
        )

    def test_a_read_verb_later_in_the_name_does_not_count(self, tool, problems) -> None:
        """Only the opening verb. "returns the updated record" turns up in the description
        of plenty of writes."""
        assert not problems(
            "MCP041",
            tool(name="update_ticket_status", description="Move a ticket to a new status."),
        )


class TestMCP042MissingIdempotentHint:
    def test_a_writing_tool_with_no_hint_is_flagged(self, tool, problems) -> None:
        assert problems(
            "MCP042",
            tool(name="create_support_ticket", description="Open a new support ticket."),
        )

    def test_a_declared_hint_answers_the_question(self, tool, problems) -> None:
        assert not problems(
            "MCP042",
            tool(
                name="update_ticket_status",
                description="Move a ticket to a new status.",
                annotations=ToolAnnotations(idempotent_hint=True),
            ),
        )

    def test_reads_are_skipped_so_they_get_one_finding_rather_than_two(
        self, tool, problems
    ) -> None:
        """MCP041 is already the finding that changes a read tool's behaviour."""
        assert not problems("MCP042", tool(name="search_users"))
