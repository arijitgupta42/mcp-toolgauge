"""The text primitives every rule is built on.

Worth testing directly rather than only through the rules: a tokeniser that is subtly wrong
does not fail loudly, it produces confident, specific, incorrect advice. These are also the
functions whose behaviour the rule docs describe, so they are part of the promise.
"""

from __future__ import annotations

import pytest

from mcpcheckup.lint.text import (
    all_words,
    content_bag,
    content_words,
    identifier_tokens,
    is_subset_of_name,
    jaccard,
    meaningful_name_tokens,
    mentions,
    naming_style,
    singular,
    token_appears,
)


class TestIdentifierTokens:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("search_users", ("search", "users")),
            ("searchUsers", ("search", "users")),
            ("search-users", ("search", "users")),
            ("SearchUsers", ("search", "users")),
            ("ticket2", ("ticket", "2")),
            ("HTTPServer", ("http", "server")),
            ("getHTTPResponse", ("get", "http", "response")),
            ("run", ("run",)),
        ],
    )
    def test_names_split_into_words(self, name: str, expected: tuple[str, ...]) -> None:
        assert identifier_tokens(name) == expected


class TestNamingStyle:
    @pytest.mark.parametrize(
        ("name", "style"),
        [
            ("search_users", "snake_case"),
            ("searchUsers", "camelCase"),
            ("SearchUsers", "PascalCase"),
            ("search-users", "kebab-case"),
            ("SEARCH_USERS", "SCREAMING_SNAKE"),
            ("search", "flat"),
        ],
    )
    def test_conventions_are_recognised(self, name: str, style: str) -> None:
        assert naming_style(name) == style

    def test_a_single_lowercase_word_is_not_claimed_by_either_convention(self) -> None:
        """`search` is valid snake_case and valid camelCase. Calling it one of them would
        make MCP004 fire on almost every server in existence."""
        assert naming_style("search") == "flat"


class TestSingular:
    @pytest.mark.parametrize(
        ("word", "expected"),
        [
            ("users", "user"),
            ("orgs", "org"),
            ("organizations", "organization"),
            ("entries", "entry"),
            ("searches", "search"),
            ("user", "user"),
            ("address", "address"),
            ("status", "status"),
        ],
    )
    def test_plurals_fold_onto_their_singular(self, word: str, expected: str) -> None:
        assert singular(word) == expected

    def test_it_is_idempotent(self) -> None:
        for word in ("users", "entries", "searches", "status"):
            assert singular(singular(word)) == singular(word)


class TestWords:
    def test_all_words_keeps_stopwords(self) -> None:
        """Length checks count words, and a fragment made of stopwords is still a
        fragment."""
        assert len(all_words("Creates a ticket.")) == 3

    def test_content_words_drop_stopwords(self) -> None:
        assert content_words("Creates a ticket.") == ("create", "ticket")

    def test_content_words_keep_duplicates(self) -> None:
        assert content_words("Ticket ticket.") == ("ticket", "ticket")

    def test_no_text_yields_nothing(self) -> None:
        assert all_words(None) == ()
        assert content_words(None) == ()


class TestMeaningfulNameTokens:
    def test_verbs_are_stripped(self) -> None:
        """What is left is the subject a description has to justify."""
        assert meaningful_name_tokens("search_users") == ("user",)

    def test_generic_nouns_are_stripped_too(self) -> None:
        assert meaningful_name_tokens("get_data") == ()

    def test_real_subjects_survive(self) -> None:
        assert meaningful_name_tokens("create_support_ticket") == ("support", "ticket")

    def test_filler_and_digits_are_dropped(self) -> None:
        assert meaningful_name_tokens("delete_all_tickets2") == ("ticket",)


class TestJaccard:
    def test_identical_bags_score_one(self) -> None:
        bag = frozenset({"a", "b", "c"})

        assert jaccard(bag, bag) == 1.0

    def test_disjoint_bags_score_zero(self) -> None:
        assert jaccard(frozenset({"a"}), frozenset({"b"})) == 0.0

    def test_an_empty_bag_scores_zero_rather_than_dividing_by_zero(self) -> None:
        assert jaccard(frozenset(), frozenset({"a"})) == 0.0

    def test_it_is_symmetric(self) -> None:
        left, right = frozenset({"a", "b"}), frozenset({"b", "c", "d"})

        assert jaccard(left, right) == jaccard(right, left)

    def test_the_score_does_not_depend_on_any_other_tool(self) -> None:
        """The reason this metric was chosen over TF-IDF: a pair's score must not move
        when an unrelated tool is added to the server, or a finding appears in CI for a
        change the author did not make."""
        a = content_bag("Find people in the staff directory by name or email.")
        b = content_bag("Find teams in the staff directory by name or domain.")
        before = jaccard(a, b)
        # Adding a third description cannot enter into it: the function takes two bags.
        assert jaccard(a, b) == before

    def test_the_fixture_pair_scores_as_documented(self) -> None:
        """The number quoted in the MCP013 docs page and in its threshold comment."""
        a = content_bag(
            "Searches the database and returns matching records for the given query string."
        )
        b = content_bag(
            "Searches the database and returns matching records for the query string provided."
        )

        assert round(jaccard(a, b), 2) == 0.78


class TestTokenAppears:
    def test_an_exact_word_matches(self) -> None:
        assert token_appears("user", frozenset({"user"}))

    def test_a_prefix_matches_in_both_directions(self) -> None:
        assert token_appears("organization", frozenset({"organizations"}))
        assert token_appears("comments", frozenset({"comment"}))

    def test_short_tokens_require_an_exact_match(self) -> None:
        """Below four characters, prefix matching starts accepting coincidences."""
        assert not token_appears("org", frozenset({"organic"}))

    def test_an_unrelated_word_does_not_match(self) -> None:
        assert not token_appears("user", frozenset({"record", "database"}))


class TestIsSubsetOfName:
    def test_a_restatement_is_recognised(self) -> None:
        assert is_subset_of_name("Search.", "search")

    def test_stopwords_do_not_rescue_a_restatement(self) -> None:
        assert is_subset_of_name("Get the data.", "get_data")

    def test_new_information_is_recognised(self) -> None:
        assert not is_subset_of_name("Find people by email.", "search_users")

    def test_empty_text_is_not_a_restatement(self) -> None:
        """It is a missing description, which is a different and worse finding."""
        assert not is_subset_of_name(None, "search")


class TestMentions:
    def test_a_backticked_name_is_found(self) -> None:
        assert mentions("Use `search_users` instead.", "search_users")

    def test_a_spelled_out_name_is_found(self) -> None:
        assert mentions("Use search users instead.", "search_users")

    def test_an_unrelated_description_is_not_a_mention(self) -> None:
        assert not mentions("Find organizations by name.", "search_users")

    def test_no_text_is_not_a_mention(self) -> None:
        assert not mentions(None, "search_users")
