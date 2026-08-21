"""Naming rules -- MCP001 to MCP004.

Every rule gets a fixture that triggers it and one that does not. The negative half is the
half that matters: a rule with no negative fixture is a rule nobody has checked for false
positives, and a linter that cries wolf gets switched off.
"""

from __future__ import annotations

GOOD = "Find individual people in the staff directory by name, email, or employee ID."


class TestMCP001NearDuplicateNames:
    def test_a_trailing_digit_does_not_distinguish_two_tools(self, tool, problems) -> None:
        found = problems("MCP001", tool(name="ticket"), tool(name="ticket2"))

        assert len(found) == 1
        assert found[0].tool == "ticket"
        assert found[0].related == ("ticket2",)

    def test_convention_alone_does_not_distinguish_two_tools(self, tool, problems) -> None:
        assert problems("MCP001", tool(name="getUser"), tool(name="get_user"))

    def test_a_plural_does_not_distinguish_two_tools(self, tool, problems) -> None:
        assert problems("MCP001", tool(name="list_item"), tool(name="list_items"))

    def test_an_exact_duplicate_says_so(self, tool, problems) -> None:
        found = problems("MCP001", tool(name="ticket"), tool(name="ticket"))

        assert "both named" in found[0].message

    def test_genuinely_different_names_are_left_alone(self, tool, problems) -> None:
        assert not problems("MCP001", tool(name="search_users"), tool(name="search_orgs"))

    def test_a_single_tool_cannot_collide(self, tool, problems) -> None:
        assert not problems("MCP001", tool(name="ticket"))


class TestMCP002NonDescriptiveName:
    def test_a_bare_verb_says_nothing(self, tool, problems) -> None:
        assert problems("MCP002", tool(name="run"))

    def test_a_generic_verb_and_a_generic_noun_still_say_nothing(self, tool, problems) -> None:
        assert problems("MCP002", tool(name="get_data"))

    def test_camel_case_filler_is_caught_too(self, tool, problems) -> None:
        assert problems("MCP002", tool(name="doStuff"))

    def test_digits_do_not_rescue_a_generic_name(self, tool, problems) -> None:
        assert problems("MCP002", tool(name="handler2"))

    def test_the_same_verb_with_a_real_subject_is_fine(self, tool, problems) -> None:
        """`get` is generic; `get_user_profile` is not, because the nouns do the work."""
        assert not problems("MCP002", tool(name="get_user_profile"))

    def test_a_descriptive_name_is_left_alone(self, tool, problems) -> None:
        assert not problems("MCP002", tool(name="archive_ticket"))


class TestMCP003NameSubjectMissing:
    def test_a_description_that_never_names_the_subject_is_flagged(self, tool, problems) -> None:
        found = problems(
            "MCP003",
            tool(
                name="search_users",
                description="Searches the database and returns matching records.",
            ),
        )

        assert len(found) == 1
        assert "user" in found[0].message

    def test_a_synonym_in_the_description_is_enough(self, tool, problems) -> None:
        """The verb is stripped before checking, so "Find people" does not have to say
        "search" -- but it does have to say something about users."""
        assert not problems(
            "MCP003",
            tool(
                name="search_users",
                description="Find people in the directory. Use this when the user wants a person.",
            ),
        )

    def test_a_plural_matches_its_singular(self, tool, problems) -> None:
        assert not problems(
            "MCP003",
            tool(name="search_organizations", description="Find organizations by name or domain."),
        )

    def test_a_verb_only_name_has_no_subject_to_check(self, tool, problems) -> None:
        assert not problems("MCP003", tool(name="search", description="Search."))

    def test_a_missing_description_is_left_to_MCP010(self, tool, problems) -> None:
        assert not problems("MCP003", tool(name="search_users", description=None))


class TestMCP004MixedNamingConventions:
    def test_one_camel_case_name_among_snake_case_is_flagged(self, tool, problems) -> None:
        found = problems(
            "MCP004",
            tool(name="search_users"),
            tool(name="delete_all_tickets"),
            tool(name="doStuff"),
        )

        assert len(found) == 1
        assert found[0].tool is None, "this is a finding about the server, not one tool"
        assert found[0].related == ("doStuff",)

    def test_a_consistent_server_is_left_alone(self, tool, problems) -> None:
        assert not problems("MCP004", tool(name="search_users"), tool(name="archive_ticket"))

    def test_single_word_names_conform_to_everything(self, tool, problems) -> None:
        """`search` is valid snake_case and valid camelCase; calling that a mix would be
        wrong, and would fire on almost every server in existence."""
        assert not problems("MCP004", tool(name="search"), tool(name="search_users"))

    def test_kebab_case_among_snake_case_is_flagged(self, tool, problems) -> None:
        assert problems("MCP004", tool(name="search_users"), tool(name="archive-ticket"))
