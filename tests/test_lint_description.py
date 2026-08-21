"""Description rules -- MCP010 to MCP015.

The interesting tests here are the boundary between MCP013 and MCP014. Overlap between
sibling tools is normal, so the two rules have to disagree about a middling pair: MCP013
should stay quiet, and MCP014 should ask for guidance.
"""

from __future__ import annotations

# The two carelessly-written siblings from the badserver fixture. Jaccard 0.78, which is
# over both thresholds.
COPY_PASTE_A = "Searches the database and returns matching records for the given query string."
COPY_PASTE_B = "Searches the database and returns matching records for the query string provided."

# Genuinely similar tools, written independently. Jaccard 0.60: confusable, but nobody
# would call these near-identical.
SIBLING_A = "Open a new support ticket for a customer and return the created ticket record."
SIBLING_B = "Open a new incident ticket for an engineer and return the created incident record."

DISTINCT = "Permanently archive a ticket, removing it from the active queue for good."


class TestMCP010MissingDescription:
    def test_no_description_is_an_error(self, tool, problems) -> None:
        assert problems("MCP010", tool(description=None))

    def test_a_blank_description_is_the_same_defect(self, tool, problems) -> None:
        """`ToolSpec` folds "" to None on ingest, so a rule never has to test for both."""
        assert problems("MCP010", tool(description="   \n  "))

    def test_a_real_description_is_left_alone(self, tool, problems) -> None:
        assert not problems("MCP010", tool())


class TestMCP011DescriptionTooShort:
    def test_a_one_word_description_is_a_fragment(self, tool, problems) -> None:
        found = problems("MCP011", tool(name="search", description="Search."))

        assert "1 word" in found[0].message

    def test_a_three_word_description_is_a_fragment(self, tool, problems) -> None:
        assert problems("MCP011", tool(description="Creates a ticket."))

    def test_an_unpunctuated_description_is_not_a_sentence(self, tool, problems) -> None:
        found = problems(
            "MCP011", tool(description="Finds people in the staff directory by name")
        )

        assert "not a complete sentence" in found[0].message

    def test_a_full_sentence_is_left_alone(self, tool, problems) -> None:
        assert not problems("MCP011", tool())

    def test_a_missing_description_is_left_to_MCP010(self, tool, problems) -> None:
        assert not problems("MCP011", tool(description=None))


class TestMCP012DescriptionRestatesName:
    def test_a_description_that_is_the_name_again_is_flagged(self, tool, problems) -> None:
        assert problems("MCP012", tool(name="search", description="Search."))

    def test_stopwords_do_not_rescue_a_restatement(self, tool, problems) -> None:
        assert problems("MCP012", tool(name="get_data", description="Get the data."))

    def test_a_description_that_adds_something_is_left_alone(self, tool, problems) -> None:
        assert not problems(
            "MCP012", tool(name="get_ticket", description="Fetch one ticket by ID.")
        )

    def test_a_missing_description_is_left_to_MCP010(self, tool, problems) -> None:
        assert not problems("MCP012", tool(name="search", description=None))


class TestMCP013OverlappingDescriptions:
    def test_near_copy_paste_siblings_are_an_error(self, tool, problems) -> None:
        found = problems(
            "MCP013",
            tool(name="search_users", description=COPY_PASTE_A),
            tool(name="search_orgs", description=COPY_PASTE_B),
        )

        assert len(found) == 1, "one finding per pair, not one per tool"
        assert found[0].tool == "search_users"
        assert found[0].related == ("search_orgs",)

    def test_the_message_quotes_the_percentage(self, tool, problems) -> None:
        """The number is the point: it is what an author can argue with, rather than
        disable."""
        found = problems(
            "MCP013",
            tool(name="search_users", description=COPY_PASTE_A),
            tool(name="search_orgs", description=COPY_PASTE_B),
        )

        assert "78%" in found[0].message

    def test_merely_similar_siblings_are_not_an_error(self, tool, problems) -> None:
        """0.60 similarity. Confusable, and MCP014's business -- not near-identical."""
        assert not problems(
            "MCP013",
            tool(name="create_support_ticket", description=SIBLING_A),
            tool(name="create_incident_ticket", description=SIBLING_B),
        )

    def test_distinct_descriptions_are_left_alone(self, tool, problems) -> None:
        assert not problems(
            "MCP013",
            tool(name="search_users", description=COPY_PASTE_A),
            tool(name="archive_ticket", description=DISTINCT),
        )

    def test_stubs_are_not_compared(self, tool, problems) -> None:
        """Two three-word descriptions collide trivially. MCP011 already reports them, and
        saying it twice would bury the pairs that matter."""
        assert not problems(
            "MCP013",
            tool(name="ticket", description="Creates a ticket."),
            tool(name="ticket2", description="Creates a ticket."),
        )


class TestMCP014NoDisambiguationGuidance:
    def test_confusable_siblings_with_no_guidance_are_both_flagged(self, tool, problems) -> None:
        found = problems(
            "MCP014",
            tool(name="create_support_ticket", description=SIBLING_A),
            tool(name="create_incident_ticket", description=SIBLING_B),
        )

        assert {problem.tool for problem in found} == {
            "create_support_ticket",
            "create_incident_ticket",
        }

    def test_naming_the_sibling_is_enough(self, tool, problems) -> None:
        assert not problems(
            "MCP014",
            tool(
                name="create_support_ticket",
                description=f"{SIBLING_A} For an engineer, use create_incident_ticket.",
            ),
            tool(
                name="create_incident_ticket",
                description=f"{SIBLING_B} For a customer, use create_support_ticket.",
            ),
        )

    def test_steering_language_alone_is_enough(self, tool, problems) -> None:
        """Deliberately generous: reward the author who wrote guidance, whatever the
        phrasing."""
        found = problems(
            "MCP014",
            tool(
                name="create_support_ticket",
                description=f"{SIBLING_A} Use this only when the reporter is a customer.",
            ),
            tool(name="create_incident_ticket", description=SIBLING_B),
        )

        assert {problem.tool for problem in found} == {"create_incident_ticket"}

    def test_unrelated_tools_are_not_asked_to_disambiguate(self, tool, problems) -> None:
        assert not problems(
            "MCP014",
            tool(name="search_users", description=COPY_PASTE_A),
            tool(name="archive_ticket", description=DISTINCT),
        )


class TestMCP015PlaceholderText:
    def test_a_todo_in_a_description_is_an_error(self, tool, problems) -> None:
        assert problems("MCP015", tool(description="TODO: document this properly."))

    def test_lorem_ipsum_is_caught(self, tool, problems) -> None:
        assert problems("MCP015", tool(description="Lorem ipsum dolor sit amet, consectetur."))

    def test_a_placeholder_in_a_parameter_is_caught(self, tool, problems) -> None:
        found = problems(
            "MCP015",
            tool(
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "FIXME"}},
                }
            ),
        )

        assert found[0].parameter == "query"

    def test_a_real_description_is_left_alone(self, tool, problems) -> None:
        assert not problems("MCP015", tool())

    def test_a_word_merely_containing_a_marker_is_not_a_placeholder(self, tool, problems) -> None:
        """Word boundaries matter: "wiping" is not "WIP"."""
        assert not problems("MCP015", tool(description="Find people by wiping the search cache."))
