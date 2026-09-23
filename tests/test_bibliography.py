"""The bibliography query layer — uc_phd_app/bibliography.py.

Runs against the shared fixture database, never the real 23,316-row seed, for
the reason ``conftest`` gives: an assertion against the real corpus is a magic
number nobody can check, and it breaks whenever the matcher is rebuilt.

The fixture is built so the two things most worth protecting are visible in
it: a default floor that actually excludes rows (three of the five works sit
at cited_by = 1), and all three match tiers present at once, because the
tier is what a count means and a query that loses it is wrong in a way no
row count would reveal.
"""
from __future__ import annotations

import pytest

from uc_phd_app import bibliography


@pytest.fixture(autouse=True)
def _live(live_db):
    """Every test here reads the app's live-database path."""
    return live_db


def test_summary_reports_totals_and_the_distribution_behind_the_floor():
    summary = bibliography.summary()
    assert summary["references_total"] == 5
    assert summary["citations_total"] == 7
    # Two of the three theses cite something; the third has no references.
    assert summary["theses_with_references"] == 2
    assert summary["theses_total"] == 3
    assert summary["shared_references"] == 2
    assert summary["max_cited_by"] == 2
    assert summary["matcher_version"] == 1
    assert summary["default_min_cited_by"] == bibliography.DEFAULT_MIN_CITED_BY
    # The histogram is the argument for the floor, so it has to be served.
    assert summary["cited_by_histogram"] == {"1": 3, "2": 2}
    assert {t["match_tier"] for t in summary["match_tiers"]} == set(bibliography.TIERS)


def test_the_default_floor_excludes_singletons():
    """The whole point of DEFAULT_MIN_CITED_BY: in the real corpus 97% of
    works are cited exactly once, and ranking them is not a ranking."""
    default = bibliography.references()
    assert default["min_cited_by"] == 2
    assert default["total"] == 2
    assert {r["id"] for r in default["references"]} == {1, 2}


def test_floor_of_one_returns_the_whole_corpus():
    """A floor a caller cannot lift is a number they must trust rather than
    check, so min_cited_by=1 is offered and has to keep working."""
    assert bibliography.references(min_cited_by=1)["total"] == 5


def test_rows_are_ranked_by_citation_count_then_author():
    rows = bibliography.references(min_cited_by=1)["references"]
    assert [r["cited_by"] for r in rows] == sorted((r["cited_by"] for r in rows), reverse=True)
    # SQLite sorts NULL first, so the unmatched work with no author leads the
    # tie group; the rest are alphabetical. Pinned because "whatever order
    # SQLite returned" is not a stable ranking across rebuilds.
    tied = [r["first_author"] for r in rows if r["cited_by"] == 1]
    assert tied == [None, "Hopper", "Lovelace"]


def test_search_matches_the_display_string_and_the_doi():
    assert bibliography.references(min_cited_by=1, q="Xception")["total"] == 1
    assert bibliography.references(min_cited_by=1, q="10.1000/xyz123")["total"] == 1
    assert bibliography.references(min_cited_by=1, q="nothing here")["total"] == 0


def test_search_treats_like_wildcards_as_literal_characters():
    """A user searching for "%" means the character. Unescaped, "%" matches
    every row and the result set looks plausible but is wrong — the same trap
    tests/test_routes.py pins for the project-title search."""
    hits = bibliography.references(min_cited_by=1, q="%")
    assert hits["total"] == 1
    assert hits["references"][0]["id"] == 4


def test_a_blank_search_term_is_not_a_filter():
    """Whitespace typed into the box must not narrow to nothing."""
    assert bibliography.references(min_cited_by=1, q="   ")["total"] == 5
    assert bibliography.references(min_cited_by=1, q="   ")["q"] is None


def test_tier_filter_narrows_to_one_match_kind():
    assert bibliography.references(min_cited_by=1, tier="doi")["total"] == 2
    assert bibliography.references(min_cited_by=1, tier="title")["total"] == 2
    assert bibliography.references(min_cited_by=1, tier="unmatched")["total"] == 1


def test_paging_reports_the_unpaged_total():
    page = bibliography.references(min_cited_by=1, limit=2, offset=1)
    assert page["total"] == 5 and len(page["references"]) == 2
    assert page["limit"] == 2 and page["offset"] == 1


def test_every_listing_carries_both_caveats():
    result = bibliography.references()
    assert result["caveat"] == bibliography.BIBLIOGRAPHY_CAVEAT
    assert result["match_tier_caveat"] == bibliography.MATCH_TIER_CAVEAT


def test_citing_theses_carries_each_thesis_own_wording():
    """entry_raw is what makes the match checkable instead of asserted: two
    theses citing one work with visibly different strings is the evidence."""
    theses = bibliography.citing_theses(1)
    # Newest citing thesis first (ORDER BY year DESC): 2024 then 2023.
    assert [t["handle"] for t in theses] == ["10316/000001", "10316/000003"]
    assert len({t["entry_raw"] for t in theses}) == 2


def test_reference_detail_joins_the_citing_theses():
    detail = bibliography.reference(2)
    assert detail["cited_by"] == 2
    assert detail["doi"] is None
    assert len(detail["theses"]) == 2
    assert detail["caveat"] == bibliography.BIBLIOGRAPHY_CAVEAT


def test_reference_detail_is_none_for_an_unknown_id():
    assert bibliography.reference(4242) is None


def test_per_thesis_keeps_the_theses_that_contributed_nothing():
    """A thesis with no parseable bibliography is the finding, not a row to
    hide — LEFT JOIN, and the zero is reported."""
    result = bibliography.per_thesis()
    rows = {r["handle"]: r for r in result["theses"]}
    assert len(rows) == 3
    assert rows["10316/000002"]["reference_count"] == 0
    assert rows["10316/000001"]["reference_count"] == 4
    assert result["caveat"] == bibliography.COVERAGE_CAVEAT


def test_per_thesis_separates_a_stub_from_a_failed_parse():
    """full_text is what tells "no body text to parse" apart from "a body we
    could not parse", and COVERAGE_CAVEAT promises the reader it does."""
    rows = {r["handle"]: r for r in bibliography.per_thesis()["theses"]}
    assert rows["10316/000002"]["full_text"] == 0  # stub, nothing to parse
    assert rows["10316/000003"]["full_text"] == 1  # real body, real references


def test_the_caveats_state_the_measured_numbers_rather_than_hedging():
    """The repo's ethos is "measure honestly, caveat what's uncertain". A
    caveat that says "may be incomplete" without the figure is the failure
    mode this pins against."""
    assert "52.6%" in bibliography.BIBLIOGRAPHY_CAVEAT
    assert "133 of 181" in bibliography.BIBLIOGRAPHY_CAVEAT
    assert "97.0%" in bibliography.BIBLIOGRAPHY_CAVEAT
    assert "52.6%" in bibliography.MATCH_TIER_CAVEAT
