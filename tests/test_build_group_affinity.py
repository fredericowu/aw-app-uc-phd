"""analysis/build_group_affinity.py — the offline content-signal builder.

Runs against a throwaway copy of the fixture database, never the committed
seed, for the same reason tests/test_build_thesis_facts.py does: this is one
of only two scripts in the repo that writes ``cisuc.sqlite3``.

The fixture's theses carry almost no text, so the *scores* here are near
meaningless and are never asserted as numbers. What is asserted is everything
around them that would silently corrupt an attribution: which corpus the IDF
is measured over, that a title alone does not earn a group, that zero-scoring
pairs are absent rather than stored, and that the ranking is stable.
"""
from __future__ import annotations

import sqlite3

import pytest

from analysis import build_group_affinity as build_mod


@pytest.fixture()
def built(fixture_db):
    """Build against the fixture DB, after giving two of its theses text that
    actually overlaps the fixture projects' vocabulary.

    The shared fixture's abstracts ("Abstract A.") share no term with its
    projects ("Alpha solves A."), so every cosine would be 0 and this whole
    file would be asserting against an empty table. Done here rather than in
    conftest because the exact strings are this file's business — several
    other tests assert those abstracts verbatim.
    """
    conn = sqlite3.connect(fixture_db)
    conn.execute(
        "UPDATE theses SET abstract_en = 'Networks and security in alpha systems.'"
        " WHERE handle = '10316/000001'"
    )
    conn.execute(
        "UPDATE theses SET abstract_en = 'Beta security analysis.'"
        " WHERE handle = '10316/000003'"
    )
    conn.commit()
    conn.close()

    report = build_mod.build(fixture_db)
    conn = sqlite3.connect(fixture_db)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        'SELECT handle, group_code, score, "rank" FROM thesis_group_affinity'
        ' ORDER BY handle, "rank"'
    )]
    conn.close()
    return report, rows


# ── tokenizing ─────────────────────────────────────────────────────────────


def test_accents_are_folded_so_one_term_is_not_two():
    """The same domain term is written both ways across the two corpora, and a
    split vocabulary would halve the evidence for exactly the words that
    separate the groups."""
    assert build_mod.tokenize("Optimização Inteligência") == build_mod.tokenize(
        "optimizacao inteligencia"
    )


def test_short_tokens_stop_words_and_punctuation_are_dropped():
    assert build_mod.tokenize("The AI and network-security systems, of 2024") == [
        "network",
        "security",
        "systems",
        "2024",
    ]


def test_tokenizing_nothing_is_an_empty_bag_not_a_crash():
    assert build_mod.tokenize(None) == []
    assert build_mod.tokenize("") == []


# ── the documents ──────────────────────────────────────────────────────────


def test_a_thesis_with_only_a_title_carries_no_content_signal(fixture_db):
    """Four or five title tokens will still rank six groups, confidently and
    meaninglessly. Requirement #4 on the card: nothing is guessed."""
    conn = sqlite3.connect(fixture_db)
    docs = build_mod.thesis_documents(conn)
    conn.close()
    # Thesis A has keywords and both abstracts; B, D and E have a title only.
    assert docs["10316/000001"]
    assert docs["10316/000002"] == []
    assert docs["10316/000004"] == []


def test_keywords_outweigh_a_title_which_outweighs_prose(fixture_db):
    """The field weights are the one tuning knob here — assert them rather
    than leaving them to be changed by accident."""
    conn = sqlite3.connect(fixture_db)
    conn.execute(
        "UPDATE theses SET title = 'zebra', abstract_en = 'walrus', abstract_pt = NULL"
        " WHERE handle = '10316/000001'"
    )
    conn.execute("DELETE FROM thesis_keywords")
    conn.execute(
        "INSERT INTO thesis_keywords (handle, keyword, ordinal)"
        " VALUES ('10316/000001', 'narwhal', 0)"
    )
    docs = build_mod.thesis_documents(conn)
    conn.close()
    bag = docs["10316/000001"]
    assert bag.count("narwhal") == 3
    assert bag.count("zebra") == 2
    assert bag.count("walrus") == 1


def test_a_group_document_is_every_one_of_its_projects_concatenated(fixture_db):
    """Alpha is in both groups, Beta in NCS only — so Alpha's tokens appear in
    both bags, the same many-to-many the rest of the app keeps honest."""
    conn = sqlite3.connect(fixture_db)
    groups = build_mod.group_documents(conn, build_mod.project_documents(conn))
    conn.close()
    assert "alpha" in groups["AC"]
    assert "alpha" in groups["NCS"]
    assert "beta" in groups["NCS"]
    assert "beta" not in groups["AC"]


def test_every_research_group_gets_a_document_even_with_no_projects(fixture_db):
    """A group that vanished from the ranking because it happened to have no
    projects would look like a group nothing is about."""
    conn = sqlite3.connect(fixture_db)
    conn.execute("INSERT INTO research_groups (code, name) VALUES ('IS', 'Information Systems')")
    groups = build_mod.group_documents(conn, build_mod.project_documents(conn))
    conn.close()
    assert groups["IS"] == []


# ── the arithmetic ─────────────────────────────────────────────────────────


def test_idf_ranks_a_rare_term_above_a_ubiquitous_one():
    idf = build_mod.inverse_document_frequency(
        [["common", "rare"], ["common"], ["common"], ["common"]]
    )
    assert idf["rare"] > idf["common"]


def test_a_vector_is_l2_normalised_so_the_dot_product_is_the_cosine():
    idf = build_mod.inverse_document_frequency([["alpha", "beta"], ["alpha"]])
    vector = build_mod.tfidf_vector(["alpha", "beta", "beta"], idf)
    assert sum(w * w for w in vector.values()) == pytest.approx(1.0)
    assert build_mod.cosine(vector, vector) == pytest.approx(1.0)


def test_an_empty_bag_is_an_empty_vector_not_a_division_by_zero():
    assert build_mod.tfidf_vector([], {"alpha": 1.0}) == {}
    # And a bag whose every term is outside the vocabulary is the same state.
    assert build_mod.tfidf_vector(["unseen"], {"alpha": 1.0}) == {}


def test_cosine_of_documents_sharing_nothing_is_zero():
    idf = build_mod.inverse_document_frequency([["alpha"], ["beta"]])
    left = build_mod.tfidf_vector(["alpha"], idf)
    right = build_mod.tfidf_vector(["beta"], idf)
    assert build_mod.cosine(left, right) == 0.0
    assert build_mod.cosine(right, left) == 0.0


# ── the rows it writes ─────────────────────────────────────────────────────


def test_zero_scoring_pairs_are_absent_rather_than_stored_as_zero(built):
    """"No rows for this handle" is how the reader tells a thesis with no
    usable text from one scored low — a stored six-way tie at 0.0 would let
    an argmax invent a group out of nothing."""
    _report, rows = built
    assert rows
    assert all(row["score"] > 0 for row in rows)
    assert {row["handle"] for row in rows} == {"10316/000001", "10316/000003"}


def test_ranks_are_dense_and_ordered_best_first(built):
    _report, rows = built
    by_handle: dict[str, list[dict]] = {}
    for row in rows:
        by_handle.setdefault(row["handle"], []).append(row)
    for handle_rows in by_handle.values():
        assert [r["rank"] for r in handle_rows] == list(range(1, len(handle_rows) + 1))
        scores = [r["score"] for r in handle_rows]
        assert scores == sorted(scores, reverse=True)


def test_the_report_names_the_theses_it_could_not_score(built):
    """Not a warning buried in a log: the handles are in the report, because
    a corpus quietly losing its content signal is exactly the regression this
    builder would otherwise hide."""
    report, _rows = built
    assert report["theses"] == 5
    assert report["theses_scored"] == 2
    assert report["theses_without_content"] == [
        "10316/000002",
        "10316/000004",
        "10316/000005",
    ]


def test_rebuilding_replaces_rather_than_accumulates(fixture_db):
    """The table is a pure function of the seed. A thesis withdrawn upstream
    must not leave its affinity behind — same reason build_thesis_facts.py
    does a full replace."""
    build_mod.build(fixture_db)
    conn = sqlite3.connect(fixture_db)
    before = conn.execute("SELECT COUNT(*) FROM thesis_group_affinity").fetchone()[0]
    conn.close()

    build_mod.build(fixture_db)
    conn = sqlite3.connect(fixture_db)
    assert conn.execute("SELECT COUNT(*) FROM thesis_group_affinity").fetchone()[0] == before
    conn.close()


def test_margins_are_reported_and_empty_when_nothing_ranks_twice():
    assert build_mod.margins([]) == {}
    assert build_mod.margins([("h", "AC", 0.5, 1)]) == {}
    rows = [("h", "AC", 1.0, 1), ("h", "NCS", 0.5, 2)]
    assert build_mod.margins(rows) == {"p10": 0.5, "p50": 0.5, "p90": 0.5}


def test_main_writes_the_table_and_prints_its_report(fixture_db, capsys):
    """The CLI wiring. Run against the untouched fixture, whose theses share
    no vocabulary with its projects at all — so this also pins down that a
    corpus that scores nothing is a clean exit 0 with an honest report, not a
    crash and not a silent success."""
    import json

    assert build_mod.main(["--db", str(fixture_db)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["theses"] == 5
    assert report["groups"] == 2
    assert report["affinity_rows"] == 0
    assert report["theses_scored"] == 0
