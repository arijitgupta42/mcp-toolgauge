"""The scoring maths.

The most carefully tested file in the repo, because it is the one nobody re-derives by
hand. A linter that misses a rule produces a report that is merely incomplete; a scorer
that divides by the wrong denominator produces a number that is confidently wrong, and
somebody will put it in a README.

So the fixtures are small enough to count on your fingers, and the expected values are
written out as literals rather than computed -- a test that recomputes the thing it is
testing proves only that the code is consistent with itself.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mcpcheckup.eval.score import (
    NOTABLE_SHARE,
    confusion_matrix,
    describe_confusion,
    notable_confusions,
    per_tool_scores,
    score,
)
from mcpcheckup.model import (
    ArgumentCheck,
    CaseKind,
    CaseOutcome,
    ConfusionCell,
    EvalCase,
    EvalScores,
    Rate,
)

REPO_ROOT = Path(__file__).parent.parent
SCORE_SOURCE = REPO_ROOT / "mcpcheckup" / "eval" / "score.py"


def case(
    name: str, kind: CaseKind = CaseKind.POSITIVE, expected: str | None = "alpha"
) -> EvalCase:
    return EvalCase(id=name, kind=kind, expected=expected, prompt="do the thing")


def outcome(
    name: str,
    selected: str | None,
    *,
    kind: CaseKind = CaseKind.POSITIVE,
    expected: str | None = "alpha",
    arguments_ok: bool | None = None,
) -> CaseOutcome:
    """One outcome, stating only what the test is about.

    `arguments_ok` of None means no tool was called, which is the distinction the scorer
    has to keep: "not checked" is not "checked and fine".
    """
    check = None
    if arguments_ok is True:
        check = ArgumentCheck()
    elif arguments_ok is False:
        check = ArgumentCheck(missing_required=("query",))
    return CaseOutcome(
        case=case(name, kind, expected), selected=selected, arguments_check=check
    )


class TestCorrectness:
    def test_the_right_tool_is_correct(self) -> None:
        assert outcome("a", "alpha").correct

    def test_the_wrong_tool_is_not(self) -> None:
        assert not outcome("a", "beta").correct

    def test_calling_nothing_when_a_tool_was_wanted_is_not(self) -> None:
        assert not outcome("a", None).correct

    def test_calling_nothing_on_an_abstain_case_is_correct(self) -> None:
        assert outcome("a", None, kind=CaseKind.ABSTAIN, expected=None).correct

    def test_calling_anything_on_an_abstain_case_is_not(self) -> None:
        assert not outcome("a", "alpha", kind=CaseKind.ABSTAIN, expected=None).correct


class TestHeadline:
    """The headline is selection only. Abstains must not be able to move it."""

    def test_selection_covers_positives_and_siblings(self) -> None:
        scores = score(
            [
                outcome("p1", "alpha"),
                outcome("p2", "beta"),
                outcome("s1", "alpha", kind=CaseKind.SIBLING),
            ]
        )

        assert (scores.selection.correct, scores.selection.total) == (2, 3)

    def test_abstain_cases_are_excluded_from_the_headline(self) -> None:
        selection = [outcome("p1", "alpha"), outcome("p2", "beta")]
        alone = score(selection)
        with_abstains = score(
            [
                *selection,
                outcome("a1", None, kind=CaseKind.ABSTAIN, expected=None),
                outcome("a2", None, kind=CaseKind.ABSTAIN, expected=None),
            ]
        )

        assert alone.selection.fraction == with_abstains.selection.fraction == 0.5

    def test_positives_and_siblings_are_reported_apart(self) -> None:
        scores = score(
            [
                outcome("p1", "alpha"),
                outcome("p2", "alpha"),
                outcome("s1", "beta", kind=CaseKind.SIBLING),
                outcome("s2", "beta", kind=CaseKind.SIBLING),
            ]
        )

        assert (scores.positives.correct, scores.positives.total) == (2, 2)
        assert (scores.siblings.correct, scores.siblings.total) == (0, 2)

    def test_abstention_is_scored_on_its_own(self) -> None:
        scores = score(
            [
                outcome("a1", None, kind=CaseKind.ABSTAIN, expected=None),
                outcome("a2", "alpha", kind=CaseKind.ABSTAIN, expected=None),
            ]
        )

        assert (scores.abstention.correct, scores.abstention.total) == (1, 2)


class TestArgumentValidity:
    def test_counts_every_call_not_only_the_correct_ones(self) -> None:
        """A wrong tool filled in properly still says something about your schemas."""
        scores = score(
            [
                outcome("p1", "beta", arguments_ok=True),
                outcome("p2", "alpha", arguments_ok=False),
            ]
        )

        assert (scores.arguments.correct, scores.arguments.total) == (1, 2)

    def test_a_case_with_no_call_is_not_counted(self) -> None:
        scores = score([outcome("p1", None), outcome("p2", "alpha", arguments_ok=True)])

        assert scores.arguments.total == 1

    def test_argument_failures_do_not_touch_selection(self) -> None:
        scores = score([outcome("p1", "alpha", arguments_ok=False)])

        assert scores.selection.fraction == 1.0
        assert scores.arguments.fraction == 0.0


class TestPerTool:
    def test_each_expected_tool_gets_a_score(self) -> None:
        scores = per_tool_scores(
            [
                outcome("a", "alpha"),
                outcome("b", "beta", expected="beta"),
                outcome("c", "alpha", expected="beta"),
            ]
        )

        assert {item.tool: (item.correct, item.total) for item in scores} == {
            "alpha": (1, 1),
            "beta": (1, 2),
        }

    def test_worst_first(self) -> None:
        """The report exists to be acted on, so the tool at 33% leads."""
        scores = per_tool_scores(
            [
                outcome("a", "alpha"),
                outcome("b", "gamma", expected="beta"),
                outcome("c", "gamma", expected="beta"),
                outcome("d", "beta", expected="beta"),
            ]
        )

        assert [item.tool for item in scores] == ["beta", "alpha"]

    def test_ties_break_alphabetically_so_the_order_is_stable(self) -> None:
        scores = per_tool_scores(
            [outcome("a", "zulu", expected="zulu"), outcome("b", "alpha", expected="alpha")]
        )

        assert [item.tool for item in scores] == ["alpha", "zulu"]

    def test_abstain_cases_produce_no_row(self) -> None:
        assert per_tool_scores([outcome("a", None, kind=CaseKind.ABSTAIN, expected=None)]) == ()


class TestConfusionMatrix:
    def test_the_diagonal_is_present(self) -> None:
        cells = confusion_matrix([outcome("a", "alpha")])

        assert len(cells) == 1
        assert cells[0].is_diagonal
        assert cells[0].share == 1.0

    def test_shares_are_normalised_across_the_row(self) -> None:
        """A row must add to 1.0 whatever else is on the server -- that is what makes
        "62% of the prompts meant for X" a true sentence."""
        cells = confusion_matrix(
            [
                outcome("a", "beta", expected="alpha"),
                outcome("b", "beta", expected="alpha"),
                outcome("c", "beta", expected="alpha"),
                outcome("d", "alpha", expected="alpha"),
            ]
        )

        assert sum(cell.share for cell in cells) == pytest.approx(1.0)
        stolen = next(cell for cell in cells if cell.selected == "beta")
        assert stolen.share == 0.75

    def test_a_second_tool_does_not_move_the_first_ones_row(self) -> None:
        one = [outcome("a", "beta", expected="alpha"), outcome("b", "alpha")]
        shared = confusion_matrix([*one, outcome("c", "gamma", expected="gamma")])
        alone = confusion_matrix(one)

        assert {(c.expected, c.selected, c.share) for c in alone} <= {
            (c.expected, c.selected, c.share) for c in shared
        }

    def test_calling_nothing_gets_its_own_cell(self) -> None:
        cells = confusion_matrix([outcome("a", None)])

        assert cells[0].selected is None
        assert cells[0].count == 1

    def test_the_nothing_cell_sorts_last_among_equals(self) -> None:
        """Rows are biggest-first; None only breaks a tie, and None does not compare
        against a string, so this is ordering rather than luck."""
        cells = confusion_matrix(
            [outcome("a", None), outcome("b", "beta"), outcome("c", "gamma")]
        )

        assert [cell.selected for cell in cells] == ["beta", "gamma", None]

    def test_a_bigger_nothing_cell_still_leads_its_row(self) -> None:
        cells = confusion_matrix([outcome("a", None), outcome("b", None), outcome("c", "beta")])

        assert cells[0].selected is None

    def test_abstain_cases_have_no_row(self) -> None:
        assert confusion_matrix([outcome("a", "alpha", kind=CaseKind.ABSTAIN, expected=None)]) == ()

    def test_ordering_is_deterministic(self) -> None:
        outcomes = [outcome("a", "beta"), outcome("b", "gamma"), outcome("c", "alpha")]

        assert confusion_matrix(outcomes) == confusion_matrix(list(reversed(outcomes)))


class TestNotableConfusions:
    def steal(self, share: float, selected: str | None = "beta") -> ConfusionCell:
        return ConfusionCell(expected="alpha", selected=selected, count=1, share=share)

    def test_the_diagonal_is_never_notable(self) -> None:
        scores = EvalScores(
            confusion=(ConfusionCell(expected="alpha", selected="alpha", count=9, share=1.0),)
        )

        assert notable_confusions(scores) == ()

    def test_calling_nothing_is_not_a_confusion(self) -> None:
        """That is the headline number's job; this list is about tools taking traffic."""
        scores = EvalScores(confusion=(self.steal(0.9, selected=None),))

        assert notable_confusions(scores) == ()

    def test_a_single_stray_answer_is_below_the_bar(self) -> None:
        scores = EvalScores(confusion=(self.steal(NOTABLE_SHARE - 0.01),))

        assert notable_confusions(scores) == ()

    def test_the_bar_itself_counts(self) -> None:
        scores = EvalScores(confusion=(self.steal(NOTABLE_SHARE),))

        assert len(notable_confusions(scores)) == 1

    def test_biggest_share_first(self) -> None:
        scores = EvalScores(
            confusion=(
                ConfusionCell(expected="a", selected="x", count=1, share=0.3),
                ConfusionCell(expected="b", selected="y", count=1, share=0.9),
            )
        )

        assert [cell.selected for cell in notable_confusions(scores)] == ["y", "x"]

    def test_the_list_is_capped(self) -> None:
        scores = EvalScores(
            confusion=tuple(
                ConfusionCell(expected=f"t{index}", selected="x", count=1, share=0.5)
                for index in range(20)
            )
        )

        assert len(notable_confusions(scores, limit=3)) == 3

    def test_the_sentence_names_both_tools_and_the_share(self) -> None:
        cell = ConfusionCell(expected="search_orgs", selected="search_users", count=5, share=0.62)

        assert describe_confusion(cell) == (
            "`search_users` captures 62% of the prompts meant for `search_orgs`."
        )


class TestEmptyRun:
    def test_scoring_nothing_produces_zeroes_rather_than_an_error(self) -> None:
        scores = score([])

        assert scores.selection.total == 0
        assert scores.per_tool == ()
        assert scores.confusion == ()

    def test_an_empty_rate_is_zero_not_a_division_error(self) -> None:
        assert Rate(0, 0).fraction == 0.0
        assert Rate(0, 0).percent == 0

    def test_percent_rounds(self) -> None:
        assert Rate(1, 3).percent == 33
        assert Rate(2, 3).percent == 67


class TestPurity:
    """The module must stay callable with no world around it."""

    def test_score_is_a_pure_function_of_its_input(self, sample_outcomes) -> None:
        assert score(sample_outcomes) == score(sample_outcomes)

    def test_an_iterator_is_consumed_safely(self) -> None:
        """`score` is documented as taking an iterable, and it walks it more than once."""
        scores = score(iter([outcome("a", "alpha"), outcome("b", "beta")]))

        assert scores.selection.total == 2
        assert len(scores.per_tool) == 1

    def test_score_imports_nothing_that_touches_the_world(self) -> None:
        """The purity invariant, checked rather than trusted.

        Read off the import statements rather than grepped for out of the source text: a
        substring search would fail on a docstring that says the word "time", and pass on a
        filesystem call reached through an alias.
        """
        tree = ast.parse(SCORE_SOURCE.read_text(encoding="utf-8"))

        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        forbidden = {"os", "io", "time", "datetime", "pathlib", "random", "socket", "httpx"}
        assert not imported & forbidden, sorted(imported & forbidden)

    def test_score_reaches_no_module_that_does_io(self) -> None:
        """It may import our own models and the standard library's data structures, and
        nothing else -- in particular not `cache`, `backend`, or `cases`."""
        tree = ast.parse(SCORE_SOURCE.read_text(encoding="utf-8"))

        internal = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("mcpcheckup")
        }

        assert internal == {"mcpcheckup.model"}


class TestKnownFixture:
    """Every headline number from the shared fixture, written out by hand.

    If one of these moves, either the arithmetic changed or the fixture did, and both are
    worth stopping for.
    """

    def test_the_headline_numbers(self, sample_outcomes) -> None:
        scores = score(sample_outcomes)

        assert (scores.selection.correct, scores.selection.total) == (6, 14)
        assert (scores.positives.correct, scores.positives.total) == (5, 10)
        assert (scores.siblings.correct, scores.siblings.total) == (1, 4)
        assert (scores.abstention.correct, scores.abstention.total) == (1, 2)
        assert (scores.arguments.correct, scores.arguments.total) == (11, 14)

    def test_the_per_tool_table(self, sample_outcomes) -> None:
        scores = score(sample_outcomes)

        assert [(item.tool, item.correct, item.total) for item in scores.per_tool] == [
            ("search_orgs", 1, 6),
            ("doStuff", 1, 2),
            ("search_users", 4, 6),
        ]

    def test_the_money_line(self, sample_outcomes) -> None:
        cells = notable_confusions(score(sample_outcomes))

        assert describe_confusion(cells[0]) == (
            "`search_users` captures 83% of the prompts meant for `search_orgs`."
        )
