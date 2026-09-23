"""analysis/build_bibliography.py — the offline bibliography builder.

Runs against a throwaway copy of the fixture database, never the committed
seed, for the same reason tests/test_build_thesis_facts.py does: this script
writes ``cisuc.sqlite3``, and a test pointed at the real file would silently
rewrite shipped data.

The fixture corpus is two theses that cite one work in common, written two
different ways — the smallest corpus that can tell "grouped correctly" apart
from "counted twice", which is the only thing this builder really has to get
right.
"""
from __future__ import annotations

import sqlite3

import pytest

from analysis import build_bibliography as build_mod

#: One reference both fixture theses carry, in visibly different wordings, and
#: a run of filler entries so the region clears the entry-shape density floor.
SHARED_A = (
    "Gamma, E., Helm, R., Johnson, R., & Vlissides, J. (1995). Design patterns: "
    "elements of reusable object-oriented software. Addison-Wesley, Reading MA."
)
SHARED_B = (
    "Gamma,   Erich,   Richard   Helm. 1995. “Design patterns: elements of reusable "
    "object-oriented software.” Addison Wesley Professional, Boston."
)
WITH_DOI_A = (
    "Carreira, J., H. Madeira, and J.G. Silva. 1998. “Xception: A Technique for the "
    "Evaluation of Depe ndability.” IEEE TSE 24 (2): 125–36. doi:10.1109/32.666826."
)
#: Same work as WITH_DOI_A, with a title no normalised key could reconcile —
#: only the DOI can group the two. Written in the same author-year shape as the
#: filler around it: a region is segmented by ONE winning style, so an entry in
#: a minority style inside it is absorbed into its neighbour rather than split
#: out. That is real parser behaviour (and part of why measured coverage is not
#: 100%), but it is not what this fixture is here to exercise.
WITH_DOI_B = (
    "Carreira, João, and Henrique Madeira. (1998). A totally different wording here "
    "that no title key could ever match. IEEE TSE, 24(2):125–136. doi: 10.1109/32.666826."
)


def _filler(prefix, n):
    return [
        f"{prefix}{i}, A. B. (20{i:02d}). A study of something measurable here. "
        f"Journal of Things, 4(2), 11-20."
        for i in range(n)
    ]


def _thesis_md(handle, entries):
    body = "\n".join(entries)
    return (
        f"---\nhandle: {handle}\ntitle: Fixture\nfull_text: true\n"
        f"source_url: https://estudogeral.uc.pt/handle/{handle}\n---\n\n"
        f"# Fixture\n\nprose\n\nReferences\n{body}\n"
    )


@pytest.fixture()
def corpus(tmp_path):
    """Two theses sharing one work (different wordings) and one DOI."""
    directory = tmp_path / "estudo_geral"
    directory.mkdir()
    (directory / "10316-000001.md").write_text(
        _thesis_md("10316/000001", [SHARED_A, WITH_DOI_A] + _filler("Alpha", 25)),
        encoding="utf-8",
    )
    (directory / "10316-000003.md").write_text(
        _thesis_md("10316/000003", [SHARED_B, WITH_DOI_B] + _filler("Beta", 25)),
        encoding="utf-8",
    )
    return directory


def test_it_writes_both_tables_and_reports_what_it_wrote(corpus, fixture_db):
    report = build_mod.build(fixture_db, corpus)

    assert report["coverage"]["parsed"] == 2
    # Two works are shared, so there are two fewer distinct works than
    # citations — the arithmetic that proves grouping happened at all.
    assert report["citations"] == report["references"] + 2
    assert report["cited_by_2_or_more"] == 2
    assert report["matcher_version"] == 1

    conn = sqlite3.connect(fixture_db)
    conn.row_factory = sqlite3.Row
    refs = conn.execute("SELECT * FROM bib_references ORDER BY cited_by DESC").fetchall()
    assert [r["cited_by"] for r in refs[:2]] == [2, 2]
    assert all(r["matcher_version"] == 1 for r in refs)
    assert conn.execute("SELECT COUNT(*) FROM thesis_references").fetchone()[0] == report["citations"]
    conn.close()


def test_a_work_cited_twice_in_different_wordings_is_one_row():
    """The whole feature in one assertion: the two Gamma strings share no
    byte-level run (one has collapsed whitespace and quotes, the other an
    ampersand and a different publisher) and still have to be one work."""
    works, _ = build_mod.group(
        {"10316-000001": [SHARED_A], "10316-000003": [SHARED_B]}
    )
    assert len(works) == 1
    assert works[0]["match_tier"] == "title"
    assert works[0]["handles"] == {"10316-000001", "10316-000003"}


def test_a_doi_beats_the_title_key_when_an_entry_carries_both():
    """DOI is the more precise of the two, so it claims the entry. The two
    WITH_DOI strings deliberately have irreconcilable titles — only the DOI
    can group them."""
    works, _ = build_mod.group(
        {"10316-000001": [WITH_DOI_A], "10316-000003": [WITH_DOI_B]}
    )
    assert len(works) == 1
    assert works[0]["match_tier"] == "doi"
    assert works[0]["doi"] == "10.1109/32.666826"
    assert len(works[0]["handles"]) == 2


def test_an_entry_with_no_derivable_key_stays_a_singleton():
    """Collapsing every unparseable entry into one key would manufacture the
    single most-cited row in the corpus out of nothing."""
    works, _ = build_mod.group({"10316-000001": ["Ibid.", "Op. cit."]})
    assert len(works) == 2
    assert {w["match_tier"] for w in works} == {"unmatched"}
    assert all(len(w["handles"]) == 1 for w in works)


def test_a_truncated_doi_does_not_group_two_unrelated_works():
    """A line-wrapped DOI is the worst possible match key: high confidence by
    construction, and wrong."""
    entries = {
        "10316-000001": ["Smith, J. (2001). One paper about things. Journal. doi:10.1016/j"],
        "10316-000003": ["Jones, K. (2009). A different paper entirely. Other. doi:10.1016/j"],
    }
    works, _ = build_mod.group(entries)
    assert len(works) == 2
    assert all(w["doi"] is None for w in works)


def test_the_longest_wording_becomes_the_display_string(corpus, fixture_db):
    build_mod.build(fixture_db, corpus)
    conn = sqlite3.connect(fixture_db)
    display = conn.execute(
        "SELECT display_string FROM bib_references WHERE cited_by = 2 AND doi IS NULL"
    ).fetchone()[0]
    conn.close()
    # Collapsed whitespace, no leading marker — the display form, not the raw.
    assert "   " not in display
    assert "Design patterns" in display


def test_thesis_references_keeps_each_thesis_own_wording(corpus, fixture_db):
    """entry_raw verbatim is what makes the match checkable rather than
    asserted — it is the evidence behind the count."""
    build_mod.build(fixture_db, corpus)
    conn = sqlite3.connect(fixture_db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT tr.entry_raw FROM thesis_references tr
        JOIN bib_references r ON r.id = tr.reference_id
        WHERE r.cited_by = 2 AND r.doi IS NULL
        """
    ).fetchall()
    conn.close()
    assert len({r["entry_raw"] for r in rows}) == 2


def test_rebuilding_replaces_rather_than_appends(corpus, fixture_db):
    """Full replace, not upsert: the input is a committed directory, so these
    tables are a pure function of it and a withdrawn thesis's rows must not
    survive forever."""
    first = build_mod.build(fixture_db, corpus)
    second = build_mod.build(fixture_db, corpus)
    assert first["references"] == second["references"]
    conn = sqlite3.connect(fixture_db)
    assert conn.execute("SELECT COUNT(*) FROM bib_references").fetchone()[0] == second["references"]
    conn.close()


def test_a_thesis_md_with_no_row_in_theses_is_named_not_a_bare_fk_error(tmp_path, fixture_db):
    directory = tmp_path / "estudo_geral"
    directory.mkdir()
    (directory / "10316-999999.md").write_text(
        _thesis_md("10316/999999", _filler("Gamma", 30)), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="build_thesis_facts"):
        build_mod.build(fixture_db, directory)


def test_coverage_separates_a_stub_from_a_body_it_could_not_parse(corpus, fixture_db):
    """full_text is reported, never used as a filter — filtering on it is the
    trap that would drop real theses from the corpus."""
    (corpus / "10316-000002.md").write_text(
        "---\nhandle: 10316/000002\ntitle: Stub\nfull_text: false\n"
        "source_url: https://estudogeral.uc.pt/handle/10316/000002\n---\n\n# Stub\n",
        encoding="utf-8",
    )
    report = build_mod.build(fixture_db, corpus)
    assert report["coverage"]["files"] == 3
    assert report["coverage"]["with_body_text"] == 2
    assert report["coverage"]["metadata_only_stubs"] == 1
    assert report["coverage"]["parsed"] == 2
    assert report["coverage"]["body_but_unparsed"] == 0


def test_tier2_recall_is_measured_against_the_doi_groups_every_run(corpus):
    """The number in the caveats is recomputed, not asserted from memory — a
    matcher change that costs recall has to show up in the build output."""
    per_thesis = build_mod.parse_corpus(corpus)
    measured = build_mod.measure_tier2_recall(per_thesis)
    # One shared DOI, whose two wordings have deliberately irreconcilable
    # titles — so tier 2 alone would have missed it, and says so.
    assert measured["shared_doi_groups"] == 1
    assert measured["title_key_agreed"] == 0
    assert measured["recall"] == 0.0


def test_tier2_recall_reports_none_rather_than_dividing_by_zero():
    assert build_mod.measure_tier2_recall({})["recall"] is None


def test_main_prints_the_report(corpus, fixture_db, capsys):
    assert build_mod.main(["--db", str(fixture_db), "--estudo-geral", str(corpus)]) == 0
    assert "tier2_recall" in capsys.readouterr().out
