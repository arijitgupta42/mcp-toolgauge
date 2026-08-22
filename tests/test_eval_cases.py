"""The case file: reading it, writing it, and refusing to lose somebody's edits.

Two behaviours here are invariants rather than features, and both get tested as such:
`--init` will not overwrite a file that exists, and a case naming a tool the server does not
have is a hard error rather than a skipped case. The first protects the work a human put
into the suite; the second protects the score from quietly measuring less than it claims.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mcp_doctor.eval.cases import (
    CASES_FILENAME,
    CaseFileError,
    default_cases_path,
    digest_warning,
    load_suite,
    validate_against,
    write_suite,
)
from mcp_doctor.model import CaseKind, CaseSuite, EvalCase, ToolSpec

TOOLS = (
    ToolSpec(name="search_users", description="Find people."),
    ToolSpec(name="search_orgs", description="Find organizations."),
)

CASES = (
    EvalCase(
        id="search_users-p1",
        kind=CaseKind.POSITIVE,
        expected="search_users",
        prompt="Who is Ada Lovelace?",
    ),
    EvalCase(
        id="search_orgs-vs-search_users-s1",
        kind=CaseKind.SIBLING,
        expected="search_orgs",
        rival="search_users",
        prompt="Which company owns the acme.test domain?",
        note="Kept because a real user asked this.",
    ),
    EvalCase(id="abstain-1", kind=CaseKind.ABSTAIN, prompt="What is the weather in Paris?"),
)


def suite(cases=CASES, digest: str = "abc123") -> CaseSuite:
    return CaseSuite(
        target="python server.py", tool_digest=digest, generated_with="m", cases=cases
    )


class TestCaseModel:
    def test_an_abstain_case_may_not_expect_a_tool(self) -> None:
        with pytest.raises(ValueError, match="abstain"):
            EvalCase(id="a", kind=CaseKind.ABSTAIN, expected="search_users", prompt="p")

    def test_a_positive_case_must_expect_one(self) -> None:
        with pytest.raises(ValueError, match="no expected tool"):
            EvalCase(id="a", kind=CaseKind.POSITIVE, prompt="p")

    def test_positives_and_siblings_are_selection_cases(self) -> None:
        assert EvalCase(id="a", kind=CaseKind.POSITIVE, expected="t", prompt="p").is_selection
        assert EvalCase(id="b", kind=CaseKind.SIBLING, expected="t", prompt="p").is_selection

    def test_an_abstain_case_is_not(self) -> None:
        assert not EvalCase(id="a", kind=CaseKind.ABSTAIN, prompt="p").is_selection

    def test_a_suite_counts_its_kinds(self) -> None:
        assert suite().counts == {
            CaseKind.POSITIVE: 1,
            CaseKind.SIBLING: 1,
            CaseKind.ABSTAIN: 1,
        }


class TestPaths:
    def test_cases_default_to_a_prefixed_name_beside_the_target(self, tmp_path: Path) -> None:
        """Prefixed, because a bare `cases.yaml` in somebody's repo root does not say who
        owns it or what it is for."""
        assert default_cases_path(tmp_path) == tmp_path / CASES_FILENAME
        assert CASES_FILENAME.startswith("mcp-doctor")


class TestRoundTrip:
    def test_what_is_written_can_be_read(self, tmp_path: Path) -> None:
        path = tmp_path / CASES_FILENAME
        write_suite(path, suite())

        assert load_suite(path) == suite()

    def test_the_file_explains_itself(self, tmp_path: Path) -> None:
        """It is meant to be edited by a human who has never read the docs."""
        path = tmp_path / CASES_FILENAME
        write_suite(path, suite())
        text = path.read_text(encoding="utf-8")

        assert text.startswith("#")
        for kind in ("positive", "sibling", "abstain"):
            assert kind in text
        assert "--force" in text

    def test_a_case_reads_top_to_bottom(self, tmp_path: Path) -> None:
        """id, then what it expects, then the prompt -- reading order, not model_dump
        order."""
        path = tmp_path / CASES_FILENAME
        write_suite(path, suite())
        first = yaml.safe_load(path.read_text(encoding="utf-8"))["cases"][0]

        assert list(first) == ["id", "kind", "expected", "prompt"]

    def test_an_abstain_case_carries_no_empty_expected(self, tmp_path: Path) -> None:
        """`expected: null` only invites somebody to fill it in."""
        path = tmp_path / CASES_FILENAME
        write_suite(path, suite())
        entries = yaml.safe_load(path.read_text(encoding="utf-8"))["cases"]

        assert "expected" not in entries[-1]

    def test_notes_survive_the_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / CASES_FILENAME
        write_suite(path, suite())

        assert load_suite(path).cases[1].note == "Kept because a real user asked this."

    def test_the_parent_directory_is_created(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / CASES_FILENAME
        write_suite(path, suite())

        assert path.is_file()


class TestOverwriteProtection:
    def test_an_existing_file_is_not_clobbered(self, tmp_path: Path) -> None:
        """The committed-artifact invariant, enforced structurally rather than by
        discipline."""
        path = tmp_path / CASES_FILENAME
        write_suite(path, suite())

        with pytest.raises(CaseFileError, match="already exists"):
            write_suite(path, suite())

    def test_the_refusal_says_how_to_proceed(self, tmp_path: Path) -> None:
        path = tmp_path / CASES_FILENAME
        write_suite(path, suite())

        with pytest.raises(CaseFileError) as caught:
            write_suite(path, suite())

        assert "--force" in str(caught.value)
        assert "--cases" in str(caught.value)

    def test_force_overwrites(self, tmp_path: Path) -> None:
        path = tmp_path / CASES_FILENAME
        write_suite(path, suite())
        write_suite(path, suite(cases=CASES[:1]), force=True)

        assert len(load_suite(path).cases) == 1


class TestLoadErrors:
    def test_a_missing_file_says_how_to_make_one(self, tmp_path: Path) -> None:
        with pytest.raises(CaseFileError) as caught:
            load_suite(tmp_path / CASES_FILENAME)

        assert "--init" in str(caught.value)

    def test_broken_yaml_names_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / CASES_FILENAME
        path.write_text("cases: [unclosed", encoding="utf-8")

        with pytest.raises(CaseFileError, match="not valid YAML"):
            load_suite(path)

    def test_a_document_that_is_not_a_mapping_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / CASES_FILENAME
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")

        with pytest.raises(CaseFileError, match="the document"):
            load_suite(path)

    def test_cases_must_be_a_list(self, tmp_path: Path) -> None:
        path = tmp_path / CASES_FILENAME
        path.write_text("cases: nope\n", encoding="utf-8")

        with pytest.raises(CaseFileError, match="'cases'"):
            load_suite(path)

    def test_an_unusable_case_is_named(self, tmp_path: Path) -> None:
        path = tmp_path / CASES_FILENAME
        path.write_text(
            "cases:\n  - id: bad-one\n    kind: abstain\n    expected: search_users\n"
            "    prompt: hello there\n",
            encoding="utf-8",
        )

        with pytest.raises(CaseFileError) as caught:
            load_suite(path)

        assert "bad-one" in str(caught.value)

    def test_an_unknown_kind_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / CASES_FILENAME
        path.write_text(
            "cases:\n  - id: x\n    kind: wishful\n    expected: t\n    prompt: hi there\n",
            encoding="utf-8",
        )

        with pytest.raises(CaseFileError, match="x"):
            load_suite(path)

    def test_duplicate_ids_are_rejected(self, tmp_path: Path) -> None:
        """Ids are how a failure gets reported. Two cases with one id is a report that
        points at the wrong prompt."""
        path = tmp_path / CASES_FILENAME
        path.write_text(
            "cases:\n"
            "  - {id: same, kind: abstain, prompt: one prompt here}\n"
            "  - {id: same, kind: abstain, prompt: another prompt here}\n",
            encoding="utf-8",
        )

        with pytest.raises(CaseFileError, match="duplicate case ids: same"):
            load_suite(path)

    def test_an_empty_document_loads_as_an_empty_suite(self, tmp_path: Path) -> None:
        path = tmp_path / CASES_FILENAME
        path.write_text("", encoding="utf-8")

        assert load_suite(path).cases == ()


class TestValidation:
    def test_a_matching_suite_passes(self, tmp_path: Path) -> None:
        assert validate_against(suite(), TOOLS, path=tmp_path / CASES_FILENAME) == ()

    def test_an_expected_tool_that_is_gone_is_fatal(self, tmp_path: Path) -> None:
        """The case cannot be run, so it is an error rather than a warning."""
        removed = (TOOLS[0],)

        with pytest.raises(CaseFileError) as caught:
            validate_against(suite(), removed, path=tmp_path / CASES_FILENAME)

        assert "search_orgs" in str(caught.value)
        assert "expected" in str(caught.value)

    def test_a_rival_that_is_gone_is_also_fatal(self, tmp_path: Path) -> None:
        cases = (
            EvalCase(
                id="s1",
                kind=CaseKind.SIBLING,
                expected="search_users",
                rival="deleted_tool",
                prompt="p",
            ),
        )

        with pytest.raises(CaseFileError, match="rival"):
            validate_against(suite(cases=cases), TOOLS, path=tmp_path / CASES_FILENAME)

    def test_an_empty_suite_is_fatal(self, tmp_path: Path) -> None:
        with pytest.raises(CaseFileError, match="no cases"):
            validate_against(suite(cases=()), TOOLS, path=tmp_path / CASES_FILENAME)

    def test_an_unmeasured_tool_is_a_warning(self, tmp_path: Path) -> None:
        """Not fatal -- somebody may have deleted its cases on purpose -- but the report
        must not imply it measured a tool it did not."""
        extra = (*TOOLS, ToolSpec(name="archive_ticket", description="Archive it."))

        warnings = validate_against(suite(), extra, path=tmp_path / CASES_FILENAME)

        assert any("archive_ticket" in note for note in warnings)

    def test_a_suite_with_no_abstains_is_a_warning(self, tmp_path: Path) -> None:
        warnings = validate_against(suite(cases=CASES[:2]), TOOLS, path=tmp_path / CASES_FILENAME)

        assert any("abstain" in note for note in warnings)


class TestDrift:
    def test_a_matching_digest_is_silent(self, tmp_path: Path) -> None:
        assert digest_warning(suite(digest="abc"), "abc", path=tmp_path / CASES_FILENAME) is None

    def test_a_changed_digest_warns_about_comparability(self, tmp_path: Path) -> None:
        note = digest_warning(suite(digest="abc"), "xyz", path=tmp_path / CASES_FILENAME)

        assert note is not None
        assert "not\ncomparable" in note or "not comparable" in note
        assert "abc" in note and "xyz" in note

    def test_a_suite_with_no_digest_does_not_warn(self, tmp_path: Path) -> None:
        """Hand-written suites are legitimate, and nagging them helps nobody."""
        assert digest_warning(suite(digest=""), "xyz", path=tmp_path / CASES_FILENAME) is None
