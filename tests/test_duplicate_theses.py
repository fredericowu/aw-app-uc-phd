"""analysis/duplicate_theses.py — the reviewed exclusion, and its limits.

The thing under test is a file that **removes a thesis from every count this
repo publishes**, which makes its failure mode the sharpest of the four curated
files: the others get a match wrong, this one loses a thesis. Three properties
keep that safe, and each has a test below:

* **the key is a thesis handle and the claim is a PAIR.** An entry names the
  record that stays as well as the one that goes, so the claim is falsifiable
  and a lone deletion is not expressible. Nothing in the shape can carry person
  semantics — that is the line option C is on (``docs/thesis-attribution.md``),
  and the siblings all draw it;
* **it detects nothing.** The verdict rests on named fields that ``validate()``
  re-proves equal on every build, against the records themselves. There is no
  similarity rule here and there must never be one: in this corpus a false
  positive would silently delete a real thesis;
* **it goes stale loudly, in both directions.** The duplicate withdrawn
  upstream leaves an exclusion standing over nothing; the SURVIVOR withdrawn
  turns the entry from deduplicating a thesis into erasing one; the two records
  diverging in a field the evidence names means the reviewed verdict is no
  longer the one that was reached. Each breaks the build.

The end-to-end behaviour (the build-level exclusion, the empty-file control,
the ``theses`` trigger) lives in tests/test_build_thesis_facts.py, next to the
seam it changes. The committed ``data/duplicate_theses.json`` is checked
against the real seed at the bottom of this file.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from analysis import duplicate_theses as dup
from analysis.build_thesis_facts import DEFAULT_DB

ENTRY = {
    "duplicate_handle": "t1",
    "kept_handle": "t2",
    "identical_fields": ["authors", "date"],
    "source_url": "https://example.test/handle/t1",
    "evidence": "Two OAI records, one deposit: identical creator, date and abstracts.",
}

#: The corpus `validate()` judges against: the two records of the pair, with the
#: fields the entry above rests on identical and `title` deliberately NOT — a
#: duplicated deposit whose every field matched would be a different (and much
#: rarer) thing, and the committed entry's own pair differs in title.
CORPUS = {
    "t1": {"handle": "t1", "authors": ["Lovelace, Ada"], "date": "2018-01-09", "title": "Ada Lovelace"},
    "t2": {"handle": "t2", "authors": ["Lovelace, Ada"], "date": "2018-01-09", "title": "On Engines"},
}


def _write(tmp_path, *entries, **document):
    path = tmp_path / "duplicate_theses.json"
    path.write_text(json.dumps({"entries": list(entries), **document}), encoding="utf-8")
    return path


def test_a_well_formed_entry_loads(tmp_path):
    assert dup.load_entries(_write(tmp_path, ENTRY)) == [ENTRY]


def test_an_empty_file_loads_to_no_entries(tmp_path):
    """The default state of this instrument, and the one the build must treat as
    "change nothing" — an exclusion file is not a feature flag, and a repo with
    no reviewed duplicates must build exactly as it did before this existed."""
    assert dup.load_entries(_write(tmp_path)) == []
    assert dup.excluded_handles([]) == frozenset()


@pytest.mark.parametrize(
    "override, message",
    [
        ({"duplicate_handle": ""}, "must be a non-empty string"),
        ({"kept_handle": "  "}, "must be a non-empty string"),
        ({"source_url": "estudogeral.uc.pt/handle/t1"}, "is not a URL"),
        ({"evidence": "   "}, "evidence is required"),
        ({"identical_fields": "authors"}, "must be a non-empty list"),
        ({"identical_fields": []}, "must be a non-empty list"),
        ({"identical_fields": ["authors", ""]}, "must be a non-empty list"),
        ({"identical_fields": ["authors", "date", "authors"]}, "the same field twice"),
    ],
)
def test_the_shape_is_checked_rather_than_assumed(tmp_path, override, message):
    with pytest.raises(dup.DuplicateThesisError, match=message):
        dup.load_entries(_write(tmp_path, {**ENTRY, **override}))


def test_an_unknown_key_is_refused(tmp_path):
    """A typo'd key would otherwise be silently ignored — and the two most
    likely to be typo'd here are the two handles, where getting the pair
    backwards drops the record that should have stayed."""
    with pytest.raises(dup.DuplicateThesisError, match="unknown keys"):
        dup.load_entries(_write(tmp_path, {**ENTRY, "handle": "t1"}))


def test_a_note_is_optional_but_must_be_a_string(tmp_path):
    loaded = dup.load_entries(_write(tmp_path, {**ENTRY, "note": "t2 keeps the title"}))
    assert loaded[0]["note"] == "t2 keeps the title"
    with pytest.raises(dup.DuplicateThesisError, match="'note' must be a string"):
        dup.load_entries(_write(tmp_path, {**ENTRY, "note": 1}))


@pytest.mark.parametrize("fields", [["authors"], ["date"], ["abstract_pt", "abstract_en"]])
def test_an_entry_resting_on_less_than_authors_and_date_is_refused(tmp_path, fields):
    """The weak-entry door, kept shut in the module rather than in the file.
    Neither field alone is evidence of a duplicated DEPOSIT: one date is shared
    by every thesis defended that day, and one author by every graduate with two
    deposits — which is data/multi_thesis_authors.json's fact, and the exact
    opposite verdict to this file's."""
    with pytest.raises(dup.DuplicateThesisError, match="identical_fields' is missing"):
        dup.load_entries(_write(tmp_path, {**ENTRY, "identical_fields": fields}))


def test_an_entry_whose_duplicate_is_its_own_survivor_is_refused(tmp_path):
    """An entry asserts a pair. One naming itself as the record that stays would
    drop the thesis and keep nothing — the one outcome this file exists to make
    impossible."""
    with pytest.raises(dup.DuplicateThesisError, match="an entry asserts a PAIR"):
        dup.load_entries(_write(tmp_path, {**ENTRY, "kept_handle": "t1"}))


def test_the_same_duplicate_listed_twice_is_refused(tmp_path):
    with pytest.raises(dup.DuplicateThesisError, match="already has an entry earlier"):
        dup.load_entries(_write(tmp_path, ENTRY, {**ENTRY, "kept_handle": "t3"}))


def test_a_handle_that_is_both_a_duplicate_and_a_survivor_is_refused(tmp_path):
    """No chains, no cycles. If t1 -> t2 and t2 -> t3, which thesis survives
    depends on which entry the build read first — and in the cycle case (t1 ->
    t2, t2 -> t1) both records are dropped and the thesis disappears. Collapse
    it by hand into entries that all point at the record that actually stays."""
    with pytest.raises(dup.DuplicateThesisError, match="both a duplicate_handle and a"):
        dup.load_entries(
            _write(
                tmp_path,
                ENTRY,
                {**ENTRY, "duplicate_handle": "t2", "kept_handle": "t3"},
            )
        )


def test_a_well_formed_entry_validates():
    dup.validate([ENTRY], CORPUS)


def test_an_entry_whose_duplicate_left_the_corpus_is_refused():
    """Estudo Geral withdrew or merged the record upstream. The exclusion now
    stands over nothing, and leaving it hides a real harvest change behind an
    editorial decision nobody re-read."""
    with pytest.raises(dup.DuplicateThesisError, match="'t1' is not in this corpus"):
        dup.validate([ENTRY], {"t2": CORPUS["t2"]})


def test_an_entry_whose_survivor_left_the_corpus_is_refused():
    """The dangerous direction, and why ``kept_handle`` is a required field at
    all: with the survivor gone the entry stops deduplicating a thesis and
    starts erasing one, and nothing downstream would say so."""
    with pytest.raises(dup.DuplicateThesisError, match="SURVIVING thesis 't2'"):
        dup.validate([ENTRY], {"t1": CORPUS["t1"]})


def test_an_entry_whose_fields_stopped_matching_is_refused():
    """What makes this a re-proven verdict rather than a remembered one. If the
    records diverge in a field the evidence names, 'one deposit, two records' is
    no longer the claim a human checked — whatever it has become."""
    corpus = {**CORPUS, "t2": {**CORPUS["t2"], "date": "2019-02-02"}}
    with pytest.raises(dup.DuplicateThesisError, match="'date' no longer matches"):
        dup.validate([ENTRY], corpus)


def test_an_entry_naming_a_field_neither_record_carries_is_refused():
    """Distinct from divergence: a re-extraction that renamed or dropped the
    field leaves two absent values comparing equal, which would pass a naive
    equality check while proving nothing at all."""
    entry = {**ENTRY, "identical_fields": ["authors", "date", "abstract_pt"]}
    with pytest.raises(dup.DuplicateThesisError, match="no longer carries 'abstract_pt'"):
        dup.validate([entry], CORPUS)


def test_the_comparison_is_on_parsed_values_not_on_text():
    """The front matters are YAML and the build compares what it parsed, so a
    list that is equal item by item is equal here — reformatting the source
    files must not fail the build, and a reordered author list must."""
    dup.validate([ENTRY], CORPUS)
    reordered = {
        **CORPUS,
        "t2": {**CORPUS["t2"], "authors": ["Lovelace, Ada", "Babbage, Charles"]},
    }
    with pytest.raises(dup.DuplicateThesisError, match="'authors' no longer matches"):
        dup.validate([ENTRY], reordered)


def test_excluded_handles_names_the_duplicate_and_never_the_survivor():
    """The one-line consequence of the pair shape: ``build()`` filters by this
    set, so a reversed entry would drop the wrong record — and the survivor must
    never appear here even though the entry mentions it."""
    assert dup.excluded_handles([ENTRY]) == frozenset({"t1"})


def test_write_table_writes_one_row_per_entry(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE duplicate_theses (duplicate_handle TEXT PRIMARY KEY, "
        "kept_handle TEXT NOT NULL, source_url TEXT NOT NULL, evidence TEXT NOT NULL)"
    )
    assert dup.write_table(conn, [ENTRY]) == 1
    assert conn.execute(
        "SELECT duplicate_handle, kept_handle FROM duplicate_theses"
    ).fetchall() == [("t1", "t2")]

    # Full replace, not upsert: an exclusion somebody REMOVED must not survive
    # in the seed, because a leftover row keeps the backstop trigger refusing a
    # thesis the file no longer excludes.
    assert dup.write_table(conn, []) == 0
    assert conn.execute("SELECT COUNT(*) FROM duplicate_theses").fetchone()[0] == 0


# --------------------------------------------------------------------------
# The committed file, against the data it actually ships with
# --------------------------------------------------------------------------


def test_the_committed_file_loads():
    """The file that actually ships, through the shape checks that actually
    guard it — so a hand-edit that breaks the envelope fails here rather than at
    somebody's next rebuild.

    The *staleness* half of the committed claim is deliberately NOT asserted
    here, and the reason is a property of this repo rather than an omission:
    ``validate()`` needs both records' front matters, and only 181 of the
    corpus's 2690 ``estudo_geral/*.md`` are tracked (the rest are untracked in
    the shared tree — see docs/design/uc-phd-duplicate-thesis-exclusion.md §0),
    so a test reading the real corpus directory passes here and fails on a clean
    CI checkout. The two tests below assert the same claim through the artefact
    that IS committed — the seed — and ``build()`` itself re-proves the field
    equality on every rebuild, which is the enforcement point that matters."""
    entries = dup.load_entries()
    assert [e["duplicate_handle"] for e in entries] == ["10316/90536"]
    assert [e["kept_handle"] for e in entries] == ["10316/90537"]
    assert set(entries[0]["identical_fields"]) == {
        "authors",
        "date",
        "abstract_pt",
        "abstract_en",
    }


def test_the_committed_seed_excludes_every_reviewed_duplicate_and_keeps_its_survivor():
    """The two halves of the claim, in the seed that ships: the duplicate is
    absent from ``theses`` (and from every table keyed on a handle, which is
    what the exclusion-before-derivation seam buys), and the survivor is
    present — because an exclusion that took the pair with it would show up here
    as both handles missing."""
    entries = dup.load_entries()
    conn = sqlite3.connect(f"file:{DEFAULT_DB}?mode=ro", uri=True)
    try:
        for entry in entries:
            duplicate, keeper = entry["duplicate_handle"], entry["kept_handle"]
            for table in ("theses", "thesis_people", "thesis_keywords", "thesis_sets"):
                assert conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE handle = ?", (duplicate,)
                ).fetchone()[0] == 0, f"{duplicate} still has {table} rows in the seed"
            assert conn.execute(
                "SELECT COUNT(*) FROM theses WHERE handle = ?", (keeper,)
            ).fetchone()[0] == 1, f"the surviving thesis {keeper} is missing from the seed"
    finally:
        conn.close()


def test_the_committed_seed_table_carries_exactly_the_committed_entries():
    """The table is a pure function of the file, so a seed rebuilt from an older
    version of either is caught here rather than by a reader wondering why a
    handle is missing with no row explaining it."""
    entries = dup.load_entries()
    conn = sqlite3.connect(f"file:{DEFAULT_DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT duplicate_handle, kept_handle, source_url, evidence "
            "FROM duplicate_theses ORDER BY duplicate_handle"
        ).fetchall()
    finally:
        conn.close()
    assert rows == sorted(
        (e["duplicate_handle"], e["kept_handle"], e["source_url"], e["evidence"])
        for e in entries
    )
