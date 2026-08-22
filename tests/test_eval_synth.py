"""Case synthesis, driven by a scripted completer rather than a model.

The interesting behaviour is not "did it call the model" but "did it ask for the right
things and keep only the usable answers". Two properties in particular:

* the hard cases are aimed at the pairs that actually overlap, using the same measure the
  linter uses -- so `MCP014` and the sibling cases cannot drift apart
* a small model's sloppier habits (code fences, three-word non-answers, repeats) are
  absorbed here rather than ending up in a committed suite
"""

from __future__ import annotations

import json

import pytest

from mcp_doctor.eval.backend import Completion, ToolCall
from mcp_doctor.eval.synth import (
    SynthesisFailed,
    confusable_pairs,
    draft_cases,
)
from mcp_doctor.lint.rules.description import CONFUSABLE_SIMILARITY
from mcp_doctor.model import CaseKind, ToolSpec

TWINS = (
    ToolSpec(
        name="search_users",
        description="Searches the database and returns matching records for the given query.",
    ),
    ToolSpec(
        name="search_orgs",
        description="Searches the database and returns matching records for the query given.",
    ),
)

UNRELATED = ToolSpec(
    name="archive_ticket",
    description="Permanently archive a support ticket, removing it from the active queue.",
)


class Script:
    """Answers every request with the same payload, and remembers what it was asked."""

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    def __call__(self, messages: list[dict[str, str]]) -> tuple[str, Completion]:
        self.prompts.append(messages[-1]["content"])
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return text, Completion(call=ToolCall(), cost_usd=0.001)


FOUR = {
    "prompts": [
        "Who looks after billing at Acme?",
        "Find me the person who owns this account.",
        "I need contact details for their lead engineer.",
        "Track down whoever filed this last week.",
    ],
    "a": ["Who runs the platform team?", "Find the individual on call."],
    "b": ["Which company owns that domain?", "List the departments under engineering."],
}


class TestConfusablePairs:
    def test_near_identical_descriptions_pair_up(self) -> None:
        assert confusable_pairs(TWINS) == ((TWINS[0], TWINS[1]),)

    def test_unrelated_tools_do_not(self) -> None:
        assert confusable_pairs((TWINS[0], UNRELATED)) == ()

    def test_the_threshold_is_the_linters(self) -> None:
        """Imported, not restated. A pair the linter warns about is a pair that gets hard
        cases, and the two must not drift."""
        import mcp_doctor.eval.synth as synth

        assert synth.CONFUSABLE_SIMILARITY is CONFUSABLE_SIMILARITY

    def test_names_alone_can_make_a_pair(self) -> None:
        """`ticket` and `ticket2` share no prose worth measuring and are still the most
        confusable pair on the server."""
        thin = (
            ToolSpec(name="ticket", description="Creates a ticket in the support system."),
            ToolSpec(name="ticket2", description="Creates a ticket."),
        )

        assert confusable_pairs(thin) == ((thin[0], thin[1]),)

    def test_tools_with_no_description_are_not_paired_by_prose(self) -> None:
        blank = (
            ToolSpec(name="alpha_widget", description=None),
            ToolSpec(name="beta_gadget", description=None),
        )

        assert confusable_pairs(blank) == ()

    def test_the_list_is_capped(self) -> None:
        many = tuple(
            ToolSpec(name=f"search_thing{index}", description="Searches and returns records.")
            for index in range(10)
        )

        assert len(confusable_pairs(many, limit=3)) == 3

    def test_the_order_is_reproducible(self) -> None:
        tools = (*TWINS, UNRELATED)

        assert confusable_pairs(tools) == confusable_pairs(tools)


class TestDrafting:
    def test_every_tool_gets_positive_cases(self) -> None:
        draft = draft_cases(TWINS, Script(FOUR), per_tool=4, abstain=0)

        positives = [case for case in draft.cases if case.kind is CaseKind.POSITIVE]
        assert len(positives) == 8
        assert {case.expected for case in positives} == {"search_users", "search_orgs"}

    def test_overlapping_pairs_get_hard_cases_in_both_directions(self) -> None:
        draft = draft_cases(TWINS, Script(FOUR), per_tool=1, per_pair=2, abstain=0)

        siblings = [case for case in draft.cases if case.kind is CaseKind.SIBLING]
        assert {case.expected for case in siblings} == {"search_users", "search_orgs"}
        assert all(case.rival is not None for case in siblings)

    def test_abstain_cases_are_asked_for_once_for_the_server(self) -> None:
        script = Script(FOUR)
        draft = draft_cases(TWINS, script, per_tool=1, per_pair=1, abstain=3)

        abstains = [case for case in draft.cases if case.kind is CaseKind.ABSTAIN]
        assert len(abstains) == 3
        assert all(case.expected is None for case in abstains)

    def test_ids_are_stable_and_readable(self) -> None:
        draft = draft_cases(TWINS, Script(FOUR), per_tool=2, per_pair=1, abstain=1)
        ids = [case.id for case in draft.cases]

        assert "search_users-p1" in ids
        assert "search_users-vs-search_orgs-s1" in ids
        assert "abstain-1" in ids
        assert len(ids) == len(set(ids))

    def test_the_generator_is_told_to_paraphrase(self) -> None:
        """Otherwise the suite grades string matching rather than comprehension."""
        script = Script(FOUR)
        draft_cases(TWINS, Script(FOUR), per_tool=1, abstain=0)
        draft_cases(TWINS, script, per_tool=1, abstain=0)

        assert any("Paraphrase" in prompt for prompt in script.prompts)

    def test_the_generator_sees_the_other_tools(self) -> None:
        """A prompt that only one tool can answer cannot be written without knowing what
        the others are."""
        script = Script(FOUR)
        draft_cases(TWINS, script, per_tool=1, abstain=0)

        assert "search_orgs" in script.prompts[0]

    def test_cost_and_call_count_are_accumulated(self) -> None:
        draft = draft_cases(TWINS, Script(FOUR), per_tool=1, per_pair=1, abstain=1)

        assert draft.calls == 4  # two tools, one pair, one abstain request
        assert draft.cost_usd == pytest.approx(0.004)

    def test_progress_is_reported(self) -> None:
        steps: list[str] = []
        draft_cases(TWINS, Script(FOUR), per_tool=1, abstain=0, on_step=steps.append)

        assert any("search_users" in step for step in steps)


class TestSloppyModels:
    def test_a_fenced_reply_is_parsed(self) -> None:
        fenced = "```json\n" + json.dumps({"prompts": ["Who owns this account here?"]}) + "\n```"

        draft = draft_cases(TWINS[:1], Script(fenced), per_tool=1, abstain=0)

        assert len(draft.cases) == 1

    def test_chatter_around_the_json_is_tolerated(self) -> None:
        chatty = (
            'Sure! Here you go: {"prompts": ["Find the person who filed this"]} '
            "Hope that helps."
        )

        draft = draft_cases(TWINS[:1], Script(chatty), per_tool=1, abstain=0)

        assert draft.cases[0].prompt == "Find the person who filed this"

    def test_two_word_answers_are_dropped(self) -> None:
        """A label is not a prompt, and a suite padded with labels reports a number that
        means nothing."""
        payload = {"prompts": ["find user", "Who is the account manager for Acme?"]}

        draft = draft_cases(TWINS[:1], Script(payload), per_tool=4, abstain=0)

        assert len(draft.cases) == 1

    def test_repeats_are_collapsed(self) -> None:
        same = "Who is the account manager here?"
        draft = draft_cases(
            TWINS[:1], Script({"prompts": [same, same, same]}), per_tool=4, abstain=0
        )

        assert len(draft.cases) == 1

    def test_whitespace_is_normalised(self) -> None:
        payload = {"prompts": ["  Who   is\n the account\tmanager?  "]}

        draft = draft_cases(TWINS[:1], Script(payload), per_tool=1, abstain=0)

        assert draft.cases[0].prompt == "Who is the account manager?"

    def test_more_prompts_than_asked_for_are_capped(self) -> None:
        draft = draft_cases(TWINS[:1], Script(FOUR), per_tool=2, abstain=0)

        assert len(draft.cases) == 2

    def test_a_reply_with_no_json_is_an_error_that_shows_what_came_back(self) -> None:
        with pytest.raises(SynthesisFailed, match="no JSON"):
            draft_cases(TWINS[:1], Script("I would rather not."), per_tool=1, abstain=0)

    def test_unparseable_json_is_an_error(self) -> None:
        with pytest.raises(SynthesisFailed, match="did not parse"):
            draft_cases(TWINS[:1], Script('{"prompts": [oops}'), per_tool=1, abstain=0)

    def test_json_that_is_not_an_object_is_an_error(self) -> None:
        with pytest.raises(SynthesisFailed, match="not an object"):
            draft_cases(TWINS[:1], Script('["a", "b"]'), per_tool=1, abstain=0)

    def test_a_wrong_shaped_object_yields_no_cases_rather_than_bad_ones(self) -> None:
        with pytest.raises(SynthesisFailed, match="no usable cases"):
            draft_cases(TWINS[:1], Script({"questions": ["nope"]}), per_tool=1, abstain=0)

    def test_no_tools_means_no_suite(self) -> None:
        with pytest.raises(SynthesisFailed):
            draft_cases((), Script(FOUR))
