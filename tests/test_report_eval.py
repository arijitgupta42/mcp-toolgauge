"""The eval renderer, driven directly so colour and layout can actually be observed.

Same reasoning as the lint renderer's tests: `CliRunner` output is never a terminal, so a
colour assertion made through it passes whether or not the behaviour is correct. These
build their own `Console` and force a terminal where it matters.

The content tests are mostly about one thing -- that the sentence naming the two confused
tools survives every path through the renderer. It is the output the command exists to
produce, and a layout change that quietly dropped it would be the worst possible regression
to ship green.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest
from rich.console import Console

from mcpcheckup.model import (
    ArgumentCheck,
    CaseKind,
    CaseOutcome,
    EvalCase,
    EvalResult,
    EvalScores,
    ServerInfo,
    ToolScore,
)
from mcpcheckup.report import render_eval_json, render_eval_table

GOLDEN = Path(__file__).parent / "golden" / "eval_report.txt"
GOLDEN_VERBOSE = Path(__file__).parent / "golden" / "eval_report_verbose.txt"

ANSI = re.compile(r"\x1b\[[0-9;]*m")
COLOUR = re.compile(r"\x1b\[[0-9;]*?(?:3[0-7]|4[0-7]|9[0-7]|10[0-7]|38;|48;)[0-9;]*m")

MONEY_LINE = "search_users captures 83% of the prompts meant for search_orgs"


def render(
    result: EvalResult,
    *,
    width: int = 100,
    verbose: bool = False,
    force_terminal: bool = False,
) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, width=width, force_terminal=force_terminal)
    render_eval_table(result, console, verbose=verbose)
    return buffer.getvalue()


def empty(**overrides) -> EvalResult:
    return EvalResult(
        **{
            "target": "python server.py",
            "server": ServerInfo(name="acme"),
            "model": "m",
            "tool_digest": "abc",
            "scores": EvalScores(),
            **overrides,
        }
    )


def perfect() -> EvalResult:
    outcomes = tuple(
        CaseOutcome(
            case=EvalCase(
                id=f"c{index}", kind=CaseKind.POSITIVE, expected="search_users", prompt="p"
            ),
            selected="search_users",
            arguments_check=ArgumentCheck(),
        )
        for index in range(3)
    )
    from mcpcheckup.eval import score

    return empty(scores=score(outcomes), outcomes=outcomes, cached_count=3)


class TestGolden:
    def test_matches_the_golden_file(self, sample_eval: EvalResult) -> None:
        assert render(sample_eval) == GOLDEN.read_text(encoding="utf-8")

    def test_verbose_matches_its_golden_file(self, sample_eval: EvalResult) -> None:
        assert render(sample_eval, verbose=True) == GOLDEN_VERBOSE.read_text(encoding="utf-8")


class TestColour:
    def test_a_terminal_gets_colour(self, sample_eval: EvalResult) -> None:
        assert COLOUR.search(render(sample_eval, force_terminal=True))

    def test_no_color_removes_colour_on_a_terminal(
        self, sample_eval: EvalResult, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NO_COLOR", "1")

        assert not COLOUR.search(render(sample_eval, force_terminal=True))

    def test_a_pipe_gets_no_escapes_at_all(self, sample_eval: EvalResult) -> None:
        assert not ANSI.search(render(sample_eval))


class TestLayout:
    @pytest.mark.parametrize("width", [40, 60, 80, 120, 200])
    def test_no_line_exceeds_the_terminal_width(
        self, sample_eval: EvalResult, width: int
    ) -> None:
        for line in render(sample_eval, width=width).splitlines():
            assert len(line) <= width, repr(line)

    @pytest.mark.parametrize("width", [40, 60, 80, 120, 200])
    def test_output_is_ascii_at_any_width(self, sample_eval: EvalResult, width: int) -> None:
        """Windows consoles and CI logs mangle decorative glyphs, so we emit none."""
        assert render(sample_eval, width=width).isascii()

    def test_no_line_carries_trailing_whitespace(self, sample_eval: EvalResult) -> None:
        for line in render(sample_eval, verbose=True).splitlines():
            assert line == line.rstrip(), repr(line)

    @pytest.mark.parametrize("width", [40, 60, 200])
    def test_the_money_line_survives_every_width(
        self, sample_eval: EvalResult, width: int
    ) -> None:
        """It is the reason the command exists. Nothing about layout may lose it.

        Compared with whitespace collapsed, because a narrow terminal is allowed to wrap
        the sentence -- it is not allowed to drop it or cut it short.
        """
        collapsed = " ".join(render(sample_eval, width=width).split())

        assert MONEY_LINE in collapsed

    @pytest.mark.parametrize("width", [40, 60, 200])
    def test_the_traffic_table_never_overflows(
        self, sample_eval: EvalResult, width: int
    ) -> None:
        """Narrow terminals lose the "went instead to" column rather than wrapping it --
        a wrapped row destroys the alignment the table exists for."""
        rendered = render(sample_eval, width=width)

        assert all(len(line) <= width for line in rendered.splitlines())
        if width == 40:
            assert "went instead to" not in rendered

    def test_a_long_thief_list_is_truncated_rather_than_wrapped(self) -> None:
        """A table row spilling onto three lines stops the table being scannable."""
        from mcpcheckup.model import ConfusionCell

        scores = EvalScores(
            selection_correct=1,
            selection_total=9,
            positive_correct=1,
            positive_total=9,
            per_tool=(ToolScore(tool="victim", correct=1, total=9),),
            confusion=tuple(
                ConfusionCell(
                    expected="victim", selected=f"a_rather_long_tool_name_{i}", count=1, share=0.11
                )
                for i in range(8)
            ),
        )

        for line in render(empty(scores=scores), width=60).splitlines():
            assert len(line) <= 60


class TestContent:
    def test_the_headline_is_selection_accuracy(self, sample_eval: EvalResult) -> None:
        assert "Selection accuracy" in render(sample_eval)

    def test_positives_and_siblings_are_shown_apart(self, sample_eval: EvalResult) -> None:
        output = render(sample_eval)

        assert "positives" in output
        assert "siblings" in output

    def test_abstention_and_arguments_are_their_own_lines(self, sample_eval: EvalResult) -> None:
        output = render(sample_eval)

        assert "Abstention" in output
        assert "Argument validity" in output

    def test_the_worst_tool_leads_the_table(self, sample_eval: EvalResult) -> None:
        lines = render(sample_eval).splitlines()
        header = next(line for line in lines if line.startswith("tool"))
        first_row = lines[lines.index(header) + 1]

        assert first_row.startswith("search_orgs")

    def test_calling_nothing_is_named_rather_than_blank(self, sample_eval: EvalResult) -> None:
        assert "(nothing)" in render(sample_eval)

    def test_backticks_are_stripped(self, sample_eval: EvalResult) -> None:
        assert "`" not in render(sample_eval)

    def test_the_model_is_always_named(self, sample_eval: EvalResult) -> None:
        """A score without a model name is not a score."""
        assert sample_eval.model in render(sample_eval)

    def test_a_fully_cached_run_says_it_was_free(self, sample_eval: EvalResult) -> None:
        assert "free" in render(sample_eval)
        assert "from cache" in render(sample_eval)

    def test_failures_are_hidden_by_default(self, sample_eval: EvalResult) -> None:
        assert "failures" not in render(sample_eval)
        assert "-v to see them" in render(sample_eval)

    def test_verbose_shows_the_failing_prompt(self, sample_eval: EvalResult) -> None:
        """A failure nobody can reproduce is a failure nobody fixes."""
        output = render(sample_eval, verbose=True)

        assert "failures" in output
        assert "A user utterance for search_orgs-p2." in output

    def test_verbose_names_what_was_wanted_and_what_arrived(
        self, sample_eval: EvalResult
    ) -> None:
        assert "wanted search_orgs, got search_users" in render(sample_eval, verbose=True)

    def test_argument_problems_are_deduplicated(self, sample_eval: EvalResult) -> None:
        """A parameter that is hard to fill in is hard to fill in every time."""
        output = render(sample_eval, verbose=True)

        assert output.count("was called without required parameter query") == 1


class TestPerfectRun:
    def test_a_clean_run_says_so(self) -> None:
        assert "Every prompt reached the tool it was meant for." in render(perfect())

    def test_a_clean_run_offers_no_failures_to_look_at(self) -> None:
        assert "-v to see them" not in render(perfect())

    def test_a_clean_run_prints_no_confusion_sentences(self) -> None:
        assert "captures" not in render(perfect())


class TestDegenerate:
    def test_a_run_with_no_cases_says_so_rather_than_dividing_by_zero(self) -> None:
        assert "No cases ran." in render(empty())

    def test_an_unnamed_server_still_renders(self) -> None:
        assert "(unnamed server)" in render(empty(server=ServerInfo()))

    def test_the_split_is_suppressed_when_there_are_no_sibling_cases(self) -> None:
        """Otherwise it is the headline printed twice under a different name."""
        output = render(perfect())

        assert "Selection accuracy" in output
        assert "siblings" not in output


class TestJson:
    def test_the_payload_parses_and_has_sorted_keys(self, sample_eval: EvalResult) -> None:
        payload = json.loads(render_eval_json(sample_eval))

        assert list(payload) == sorted(payload)

    def test_the_model_and_digest_are_recorded(self, sample_eval: EvalResult) -> None:
        payload = json.loads(render_eval_json(sample_eval))

        assert payload["model"] == sample_eval.model
        assert payload["tool_digest"] == sample_eval.tool_digest

    def test_the_full_matrix_is_present_including_the_diagonal(
        self, sample_eval: EvalResult
    ) -> None:
        """The terminal narrows it to the mistakes; a JSON consumer gets the real thing."""
        cells = json.loads(render_eval_json(sample_eval))["scores"]["confusion"]

        assert any(cell["expected"] == cell.get("selected") for cell in cells)

    def test_a_cell_for_calling_nothing_omits_selected(self, sample_eval: EvalResult) -> None:
        """Nulls are dropped, and absent reads as None in every consumer that matters."""
        cells = json.loads(render_eval_json(sample_eval))["scores"]["confusion"]

        assert any("selected" not in cell for cell in cells)

    def test_every_outcome_carries_its_case(self, sample_eval: EvalResult) -> None:
        payload = json.loads(render_eval_json(sample_eval))

        assert all(outcome["case"]["id"] for outcome in payload["outcomes"])

    def test_output_is_stable_between_runs(self, sample_eval: EvalResult) -> None:
        assert render_eval_json(sample_eval) == render_eval_json(sample_eval)
