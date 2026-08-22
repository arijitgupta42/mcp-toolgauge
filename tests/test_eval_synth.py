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

from mcp_doctor.eval.backend import BackendError, Completion, ToolCall
from mcp_doctor.eval.synth import (
    SynthesisFailed,
    _extract_json,
    confusable_pairs,
    draft_cases,
    looks_usable,
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

WITH_REQUIRED = ToolSpec(
    name="update_ticket_status",
    description="Move an existing support ticket to a new status.",
    input_schema={
        "type": "object",
        "properties": {
            "ticket_id": {
                "type": "string",
                "description": "Identifier of the ticket, e.g. 'tkt_4c8d'.",
            },
            "status": {"type": "string", "enum": ["open", "closed"]},
            "comment": {"type": "string", "description": "Optional note."},
        },
        "required": ["ticket_id", "status"],
    },
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

    def test_the_generator_is_told_to_supply_required_values(self) -> None:
        """Without this, a generator writes fluent requests that omit the identifier the
        tool needs -- "mark my ticket as resolved" for a tool requiring a ticket id. The
        model then declines, correctly, and the case records a miss that has nothing to do
        with the description under test."""
        script = Script(FOUR)
        draft_cases((WITH_REQUIRED,), script, per_tool=1, abstain=0)

        assert "required" in script.prompts[0]

    def test_required_parameters_are_shown_with_their_documentation(self) -> None:
        """A parameter description carrying `e.g. 'tkt_4c8d'` is the single most useful
        thing the generator can see -- it is how a prompt ends up quoting an identifier in
        a shape the tool actually accepts."""
        script = Script(FOUR)
        draft_cases((WITH_REQUIRED,), script, per_tool=1, abstain=0)

        assert "ticket_id -- Identifier of the ticket, e.g. 'tkt_4c8d'." in script.prompts[0]
        assert "optional parameters" in script.prompts[0]

    def test_abstain_prompts_are_not_told_to_supply_arguments(self) -> None:
        """An abstain case is supposed to be unanswerable, so the rule that makes positives
        answerable would be working against it."""
        script = Script(FOUR)
        draft_cases((WITH_REQUIRED,), script, per_tool=0, abstain=2)

        assert "cannot be answered by that tool" not in script.prompts[-1]

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

    def test_a_reply_with_no_json_says_what_came_back(self) -> None:
        with pytest.raises(SynthesisFailed, match="no JSON"):
            _extract_json("I would rather not.")

    def test_unparseable_json_says_so(self) -> None:
        with pytest.raises(SynthesisFailed, match="did not parse"):
            _extract_json('{"prompts": [oops}')

    def test_json_that_is_not_an_object_says_so(self) -> None:
        """A bare array is looked for only after an object, so this reports the precise
        complaint rather than "no JSON at all"."""
        with pytest.raises(SynthesisFailed, match="not an object"):
            _extract_json('["a", "b"]')

    def test_a_wrong_shaped_object_yields_no_cases_rather_than_bad_ones(self) -> None:
        with pytest.raises(SynthesisFailed, match="no usable cases"):
            draft_cases(TWINS[:1], Script({"questions": ["nope"]}), per_tool=1, abstain=0)

    def test_no_tools_means_no_suite(self) -> None:
        with pytest.raises(SynthesisFailed):
            draft_cases((), Script(FOUR))

    def test_raw_newlines_inside_strings_are_tolerated(self) -> None:
        """Small models emit these constantly and they are unambiguous to read."""
        payload = '{"prompts": ["Who owns\nthis account here?"]}'

        draft = draft_cases(TWINS[:1], Script(payload), per_tool=1, abstain=0)

        assert len(draft.cases) == 1

    def test_an_unterminated_string_is_still_a_failure(self) -> None:
        """Tolerance stops short of guessing. Broken is broken."""
        assert not looks_usable('{"prompts": ["never closed}')


class TestPartialFailure:
    """One unusable reply must not cost an eleven-call --init."""

    class Flaky:
        """Answers usably except for the tool named in `breaks`."""

        def __init__(self, breaks: str) -> None:
            self.breaks = breaks

        def __call__(self, messages: list[dict[str, str]]) -> tuple[str, Completion]:
            # Matched against the `name:` line _describe emits for the tool under
            # generation, not against the whole prompt -- the catalogue lists every tool,
            # so a bare name match would break every step rather than one.
            described = f"name: {self.breaks}" in messages[-1]["content"]
            body = "not json at all" if described else json.dumps(FOUR)
            return body, Completion(call=ToolCall(), cost_usd=0.001)

    def test_the_other_tools_still_get_cases(self) -> None:
        draft = draft_cases(TWINS, self.Flaky("search_orgs"), per_tool=2, abstain=0)

        assert {case.expected for case in draft.cases} == {"search_users"}

    def test_what_was_lost_is_named(self) -> None:
        draft = draft_cases(TWINS, self.Flaky("search_orgs"), per_tool=2, abstain=0)

        assert any("search_orgs" in label for label in draft.skipped)

    def test_a_skipped_step_still_counts_as_a_call(self) -> None:
        """It was paid for whether or not it was usable, so the count must include it.

        Three steps here: one positive request per tool, plus the pair. Two of them fail --
        search_orgs' own, and the pair, whose prompt describes both tools.
        """
        draft = draft_cases(TWINS, self.Flaky("search_orgs"), per_tool=1, abstain=0)

        assert draft.calls == 3
        assert len(draft.skipped) == 2
        assert draft.cases  # search_users survived

    def test_a_readable_reply_with_no_prompts_counts_as_skipped(self) -> None:
        """Silence here once cost badserver its abstain cases: the reply parsed, produced
        nothing, and reported success, so the suite shipped without them."""

        def wrong_key_for_abstains(
            messages: list[dict[str, str]],
        ) -> tuple[str, Completion]:
            asking_for_abstains = "none of these tools can satisfy" in messages[-1]["content"]
            body = {"questions": ["wrong key"]} if asking_for_abstains else FOUR
            return json.dumps(body), Completion(call=ToolCall())

        draft = draft_cases(TWINS[:1], wrong_key_for_abstains, per_tool=2, abstain=2)

        assert draft.cases  # the positives survived
        assert not [case for case in draft.cases if case.kind is CaseKind.ABSTAIN]
        assert any("nothing should answer" in label for label in draft.skipped)

    def test_a_reply_under_the_wrong_key_is_not_reusable_from_cache(self) -> None:
        """Parseable is not the same as usable. A tidy JSON object under the wrong key
        would otherwise be replayed forever and its step never retried."""
        assert not looks_usable('{"questions": ["wrong key"]}')
        assert not looks_usable('{"prompts": []}')
        assert looks_usable('{"prompts": ["a real prompt here"]}')
        assert looks_usable('{"a": ["one side"], "b": ["the other"]}')

    def test_everything_failing_is_still_an_error(self) -> None:
        with pytest.raises(SynthesisFailed, match="no usable cases"):
            draft_cases(TWINS, Script("not json at all"), per_tool=2, abstain=0)

    def test_a_backend_failure_is_not_swallowed(self) -> None:
        """A rate limit or a bad key is something the user can fix, so it stops the run
        rather than producing a suite full of holes."""

        def broken(messages: list[dict[str, str]]) -> tuple[str, Completion]:
            raise BackendError("Rate limited", retryable=True)

        with pytest.raises(BackendError):
            draft_cases(TWINS, broken, per_tool=1, abstain=0)


class TestCacheRejectsUnusableReplies:
    def test_a_recorded_but_unreadable_reply_is_not_served_back(self, tmp_path) -> None:
        """Otherwise one malformed answer is pinned forever and the affected tool is
        skipped on every future run, with no way to retry short of deleting the file."""
        from mcp_doctor.eval.cache import CachedCall, ResponseCache, cache_key
        from mcp_doctor.eval.runner import cached_text_completer

        cache = ResponseCache.load(tmp_path / "c.jsonl")
        messages = [{"role": "user", "content": "go"}]
        key = cache_key(model="m", messages=messages, tool_digest="d")
        cache.put(key, CachedCall(tool=None, arguments={"text": "not json"}), model="m")

        calls = {"n": 0}

        def fresh(**kwargs: object) -> tuple[str, Completion]:
            calls["n"] += 1
            return json.dumps(FOUR), Completion(call=ToolCall())

        import mcp_doctor.eval.backend as backend_module

        original = backend_module.complete_text
        backend_module.complete_text = fresh  # type: ignore[assignment]
        try:
            complete = cached_text_completer(
                model="m", cache=cache, tool_digest="d", accept=looks_usable
            )
            text, _ = complete(messages)
        finally:
            backend_module.complete_text = original  # type: ignore[assignment]

        assert calls["n"] == 1
        assert looks_usable(text)
