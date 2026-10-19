"""analysis/person_aliases.py — the curated "de x para", and what reads it.

Three things are under test here, and they fail for different reasons:

* the **loader**, which must refuse a file it cannot act on rather than skip
  an entry — a skipped entry silently un-merges a person and the build still
  reports success;
* the **matcher**, which must collapse an alias group to one identity *and*
  must still report a reviewed-``distinct`` pair as ambiguous. That second
  half is the one that matters: ``nuno-silva-1``/``nuno-silva-4`` satisfy
  every name-shaped condition the collapse looks at and are two different
  humans, so a rule that collapsed on name shape alone would merge them at
  the confident tier;
* the **detection pass**, which must find a new suspect pair and go quiet
  about one somebody has already ruled on, under EITHER verdict.

The committed ``data/person_aliases.json`` is validated against the real
roster at the bottom, so a slug renamed upstream fails here rather than at
the next seed rebuild.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from analysis import build_thesis_facts as build_mod
from analysis import person_aliases
from analysis.name_match import AMBIGUOUS, CONFIDENT, Person, match_name
from scraper.people import possible_duplicates

#: The ``simao-paredes``/``s-paredes`` shape: one human, two directory
#: entries, one of them abbreviated.
PAIR_SAME = {
    "a": "ada-1",
    "b": "ada",
    "verdict": "same",
    "canonical": "ada",
    "evidence": "Both CISUC pages publish the same ORCID.",
}

#: The ``nuno-silva-1``/``nuno-silva-4`` shape: token-compatible names, two
#: different people.
PAIR_DISTINCT = {
    "a": "grace",
    "b": "grace-1",
    "verdict": "distinct",
    "canonical": None,
    "evidence": "Different mailboxes at different domains, different groups.",
}


def _write(tmp_path, *pairs):
    path = tmp_path / "person_aliases.json"
    path.write_text(json.dumps({"pairs": list(pairs)}), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# The loader — every refusal, because each one is a silent wrong answer
# --------------------------------------------------------------------------


def test_a_verdict_naming_a_slug_that_does_not_exist_is_refused(tmp_path):
    """The upstream-rename case. Skipping it would un-merge a person and
    report a successful build, which is the one outcome worth failing for."""
    path = _write(tmp_path, {**PAIR_SAME, "a": "ada-9"})
    pairs = person_aliases.load_pairs(path)
    with pytest.raises(person_aliases.AliasError, match="no row in people carries the slug"):
        person_aliases.validate(pairs, {"ada", "ada-1"})


def test_a_self_alias_is_refused(tmp_path):
    path = _write(tmp_path, {**PAIR_SAME, "a": "ada", "b": "ada"})
    pairs = person_aliases.load_pairs(path)
    with pytest.raises(person_aliases.AliasError, match="alias of itself"):
        person_aliases.validate(pairs, {"ada"})


def test_a_chain_is_refused(tmp_path):
    """``a -> b -> c``. Resolution is one hop everywhere (the table's PK and
    every consumer's single lookup), so a chain would resolve one person to a
    slug that is itself not an identity."""
    path = _write(
        tmp_path,
        {**PAIR_SAME, "a": "ada-2", "b": "ada-1", "canonical": "ada-1"},
        {**PAIR_SAME, "a": "ada-1", "b": "ada", "canonical": "ada"},
    )
    pairs = person_aliases.load_pairs(path)
    with pytest.raises(person_aliases.AliasError, match="alias chain"):
        person_aliases.validate(pairs, {"ada", "ada-1", "ada-2"})


def test_a_chain_is_refused_whichever_order_the_file_lists_it_in(tmp_path):
    """The chain check runs after the whole file is read, so the file's own
    ordering cannot decide whether it fires."""
    path = _write(
        tmp_path,
        {**PAIR_SAME, "a": "ada-1", "b": "ada", "canonical": "ada"},
        {**PAIR_SAME, "a": "ada-2", "b": "ada-1", "canonical": "ada-1"},
    )
    pairs = person_aliases.load_pairs(path)
    with pytest.raises(person_aliases.AliasError, match="alias chain"):
        person_aliases.validate(pairs, {"ada", "ada-1", "ada-2"})


def test_one_slug_cannot_resolve_to_two_different_people(tmp_path):
    path = _write(
        tmp_path,
        {**PAIR_SAME, "a": "ada-1", "b": "ada", "canonical": "ada"},
        {**PAIR_SAME, "a": "ada-1", "b": "alan", "canonical": "alan"},
    )
    pairs = person_aliases.load_pairs(path)
    with pytest.raises(person_aliases.AliasError, match="already an alias of"):
        person_aliases.validate(pairs, {"ada", "ada-1", "alan"})


def test_the_same_pair_twice_is_refused(tmp_path):
    path = _write(tmp_path, PAIR_SAME, {**PAIR_SAME, "a": "ada", "b": "ada-1"})
    pairs = person_aliases.load_pairs(path)
    with pytest.raises(person_aliases.AliasError, match="already has a verdict"):
        person_aliases.validate(pairs, {"ada", "ada-1"})


def test_a_same_verdict_needs_a_canonical_from_the_pair(tmp_path):
    path = _write(tmp_path, {**PAIR_SAME, "canonical": "alan"})
    pairs = person_aliases.load_pairs(path)
    with pytest.raises(person_aliases.AliasError, match="must be one of the two slugs"):
        person_aliases.validate(pairs, {"ada", "ada-1", "alan"})


def test_a_distinct_verdict_must_not_carry_a_canonical(tmp_path):
    """Two different people have no canonical between them, and a file that
    said otherwise would be recording two contradictory decisions."""
    path = _write(tmp_path, {**PAIR_DISTINCT, "canonical": "grace"})
    pairs = person_aliases.load_pairs(path)
    with pytest.raises(person_aliases.AliasError, match="must carry canonical: null"):
        person_aliases.validate(pairs, {"grace", "grace-1"})


def test_a_verdict_with_no_evidence_is_refused(tmp_path):
    path = _write(tmp_path, {**PAIR_SAME, "evidence": "   "})
    with pytest.raises(person_aliases.AliasError, match="evidence is required"):
        person_aliases.load_pairs(path)


@pytest.mark.parametrize(
    "mutation, expected",
    [
        ({"verdict": "maybe"}, "is not one of"),
        ({"a": ""}, "must be a non-empty slug"),
    ],
)
def test_a_malformed_entry_is_refused_before_any_slug_is_looked_up(tmp_path, mutation, expected):
    path = _write(tmp_path, {**PAIR_SAME, **mutation})
    with pytest.raises(person_aliases.AliasError, match=expected):
        person_aliases.load_pairs(path)


def test_an_unknown_key_is_refused_rather_than_ignored(tmp_path):
    """A typo'd key is how a verdict ends up meaning something other than what
    whoever wrote it intended — ``cannonical`` would read as no canonical."""
    path = _write(tmp_path, {**PAIR_SAME, "cannonical": "ada"})
    with pytest.raises(person_aliases.AliasError, match="unknown keys"):
        person_aliases.load_pairs(path)


def test_a_file_without_a_pairs_list_is_refused(tmp_path):
    path = tmp_path / "person_aliases.json"
    path.write_text(json.dumps([PAIR_SAME]), encoding="utf-8")
    with pytest.raises(person_aliases.AliasError, match="expected an object with a 'pairs' list"):
        person_aliases.load_pairs(path)


# --------------------------------------------------------------------------
# What the loader produces
# --------------------------------------------------------------------------


def test_the_map_carries_only_the_same_verdicts_and_points_at_the_canonical(tmp_path):
    pairs = person_aliases.load_pairs(_write(tmp_path, PAIR_SAME, PAIR_DISTINCT))
    assert person_aliases.alias_map(pairs) == {"ada-1": "ada"}


def test_reviewed_pairs_covers_both_verdicts_sorted(tmp_path):
    """A ``distinct`` pair counts as reviewed — that is the whole point of
    recording one, so the detection pass stops reporting it."""
    pairs = person_aliases.load_pairs(_write(tmp_path, PAIR_SAME, PAIR_DISTINCT))
    assert person_aliases.reviewed_pairs(pairs) == {("ada", "ada-1"), ("grace", "grace-1")}


@pytest.fixture()
def aliased_db(fixture_db):
    """The fixture database with an ``ada-1`` row, so ``ada-1``/``ada`` is a
    pair the validator can accept — it refuses a slug with no ``people`` row,
    which is the behaviour the loader tests above assert."""
    conn = sqlite3.connect(fixture_db)
    try:
        conn.execute("INSERT INTO people (slug, name) VALUES ('ada-1', 'Ada A. Lovelace')")
        conn.commit()
    finally:
        conn.close()
    return fixture_db


def test_write_table_replaces_rather_than_accumulates(tmp_path, aliased_db):
    """The table is a pure function of the file, so a verdict somebody removed
    must not survive in the seed."""
    conn = sqlite3.connect(aliased_db)
    try:
        assert person_aliases.load_and_write(conn, _write(tmp_path, PAIR_SAME)) == {
            "pairs_reviewed": 1,
            "same": 1,
            "distinct": 0,
        }
        assert conn.execute("SELECT from_slug, to_slug FROM person_aliases").fetchall() == [
            ("ada-1", "ada")
        ]

        person_aliases.load_and_write(conn, _write(tmp_path, PAIR_DISTINCT))
        assert conn.execute("SELECT COUNT(*) FROM person_aliases").fetchone()[0] == 0
    finally:
        conn.close()


def test_the_evidence_travels_into_the_table(tmp_path, aliased_db):
    conn = sqlite3.connect(aliased_db)
    try:
        person_aliases.load_and_write(conn, _write(tmp_path, PAIR_SAME))
        assert conn.execute("SELECT evidence FROM person_aliases").fetchone()[0] == (
            PAIR_SAME["evidence"]
        )
    finally:
        conn.close()


def test_people_canonical_excludes_aliases_but_people_keeps_them(tmp_path, aliased_db):
    """Never destructive: the aliased row stays, because scraper/people.py
    re-serves both slugs on every sync and both CISUC pages are live."""
    conn = sqlite3.connect(aliased_db)
    try:
        person_aliases.load_and_write(conn, _write(tmp_path, PAIR_SAME))
        conn.commit()
        assert conn.execute("SELECT 1 FROM people WHERE slug = 'ada-1'").fetchone() == (1,)
        assert conn.execute("SELECT 1 FROM people_canonical WHERE slug = 'ada-1'").fetchone() is None
        assert conn.execute("SELECT 1 FROM people_canonical WHERE slug = 'ada'").fetchone() == (1,)
    finally:
        conn.close()


# --------------------------------------------------------------------------
# The matcher — collapse, and the collapse that must NOT happen
# --------------------------------------------------------------------------

#: Two CISUC rows for one human, as `load_cisuc_people` hands them to the matcher.
#: Different display names, so nothing here is the pre-existing byte-equal
#: duplicate rule.
JORGE = (
    Person("jorge-silva", "Jorge Sá Silva", None),
    Person("j-silva", "Jorge Miguel Sa Silva", "jorge-silva"),
)

#: Two different humans whose names are token-compatible, as the real
#: nuno-silva family is. No canonical on either.
NUNO = (
    Person("nuno-silva-1", "Nuno Silva", None),
    Person("nuno-silva-4", "Nuno Pedro de Jesus Silva", None),
)


def test_an_alias_group_collapses_to_one_confident_identity():
    result = match_name("Silva, Jorge Miguel Sá", list(JORGE))
    assert result.status == CONFIDENT
    assert {p.slug for p in result.people} == {"jorge-silva", "j-silva"}
    assert "person_aliases.json" in result.note
    assert "canonical jorge-silva" in result.note


def test_without_the_alias_the_same_two_rows_are_ambiguous():
    """The control: the collapse comes from the reviewed verdict, not from
    anything in the two names."""
    unreviewed = tuple(Person(p.slug, p.name) for p in JORGE)
    assert match_name("Silva, Jorge Miguel Sá", list(unreviewed)).status == AMBIGUOUS


def test_a_reviewed_distinct_pair_does_not_collapse():
    """THE safety test. These two names are subset-compatible and share a
    primary given name — every shape the collapse looks at — and they are two
    real people. A `distinct` verdict writes no alias row, so neither Person
    carries a canonical and the name stays ambiguous."""
    result = match_name("Silva, Nuno Pedro de Jesus", list(NUNO))
    assert result.status == AMBIGUOUS
    assert {p.slug for p in result.people} == {"nuno-silva-1", "nuno-silva-4"}


def test_a_third_unrelated_person_still_makes_the_name_ambiguous():
    """The collapse needs EVERY candidate to be one identity. A genuinely
    different person who also fits is not resolved away by the alias."""
    candidates = [*JORGE, Person("jorge-silva-9", "Jorge Silva", None)]
    assert match_name("Silva, Jorge Miguel Sá", candidates).status == AMBIGUOUS


def test_the_byte_equal_duplicate_note_is_unchanged_by_this():
    """joao-bicker's rule still reports itself as a scraped-source duplicate,
    not as a reviewed alias — two different situations, two different notes."""
    note = match_name(
        "Bicker, João", [Person("joao-bicker", "João Bicker"), Person("joao-bicker-1", "João Bicker")]
    ).note
    assert "duplicate in the scraped source" in note


def test_the_builder_writes_the_canonical_slug_once_not_both_rows(tmp_path, fixture_db):
    """Canonicalisation happens in ``people_rows``, which is what makes
    ``resolve_author_conflicts`` and ``idx_one_thesis_per_resolved_author``
    see one person instead of two slugs."""
    conn = sqlite3.connect(fixture_db)
    try:
        conn.execute("INSERT INTO people (slug, name) VALUES ('ada-1', 'Ada A. Lovelace')")
        conn.commit()
    finally:
        conn.close()

    corpus = tmp_path / "estudo_geral"
    corpus.mkdir()
    from tests.conftest import THESIS_MD

    (corpus / "10316-000001.md").write_text(THESIS_MD, encoding="utf-8")
    (corpus / "manifest.json").write_text(
        json.dumps([{"handle": "10316/000001"}]), encoding="utf-8"
    )
    aliases = _write(
        tmp_path,
        {
            "a": "ada-1",
            "b": "ada",
            "verdict": "same",
            "canonical": "ada",
            "evidence": "Same mailbox local part on both CISUC pages.",
        },
    )

    # An empty person_full_names.json, for the same reason ``aliases`` above
    # is written here rather than taken from data/: the committed file names
    # real CISUC slugs the fixture ``people`` table does not have.
    full_names = tmp_path / "person_full_names.json"
    full_names.write_text(json.dumps({"entries": []}), encoding="utf-8")

    # ...and an empty external_people.json, for the third time for the third
    # reason: its entries name real thesis mentions, not this fixture's.
    externals = tmp_path / "external_people.json"
    externals.write_text(json.dumps({"entries": []}), encoding="utf-8")
    multi_authors = tmp_path / "multi_thesis_authors.json"
    multi_authors.write_text(json.dumps({"entries": []}), encoding="utf-8")

    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors)
    assert report["person_aliases"] == {"pairs_reviewed": 1, "same": 1, "distinct": 0}

    conn = sqlite3.connect(fixture_db)
    try:
        assert [
            r[0]
            for r in conn.execute(
                "SELECT person_slug FROM thesis_people WHERE name_raw = 'Lovelace, Ada' ORDER BY 1"
            )
        ] == ["ada"]
    finally:
        conn.close()


def test_load_cisuc_people_fills_canonical_from_the_table(tmp_path, fixture_db):
    conn = sqlite3.connect(fixture_db)
    try:
        conn.execute("INSERT INTO people (slug, name) VALUES ('ada-1', 'Ada A. Lovelace')")
        person_aliases.load_and_write(conn, _write(tmp_path, PAIR_SAME))
        conn.commit()
        by_slug = {p.slug: p for p in build_mod.load_cisuc_people(conn)}
    finally:
        conn.close()
    assert by_slug["ada-1"].canonical == "ada"
    assert by_slug["ada"].canonical is None


# --------------------------------------------------------------------------
# Forward detection — suggest only, and quiet once reviewed
# --------------------------------------------------------------------------

#: Every known family's shape, plus two pairs that must NOT be flagged.
ROSTER = [
    ("jorge-silva", "Jorge Sá Silva"),
    ("j-silva", "Jorge Miguel Sa Silva"),
    ("nuno-silva-1", "Nuno Silva"),
    ("nuno-silva-4", "Nuno Pedro de Jesus Silva"),
    ("pedro-silva-3", "Pedro Silva"),
    ("filipe-araujo", "Filipe Araujo"),
    ("filipius-1", "Filipe Araujo"),
    ("alan", "Alan Turing"),
]


def _flagged(reviewed=None):
    return {(p["a"], p["b"]) for p in possible_duplicates(ROSTER, reviewed)}


def test_detection_finds_the_abbreviated_initial_shape():
    assert ("j-silva", "jorge-silva") in _flagged()


def test_detection_finds_a_byte_equal_duplicate_name():
    assert ("filipe-araujo", "filipius-1") in _flagged()


def test_detection_finds_the_nuno_shape_too_because_it_cannot_tell():
    """It flags the pair that turns out to be two people exactly as readily as
    the pair that turns out to be one. That is the honest behaviour, and the
    reason the output is a suggestion rather than a merge."""
    assert ("nuno-silva-1", "nuno-silva-4") in _flagged()


def test_detection_does_not_flag_a_different_primary_given_name():
    """"Pedro Silva" is a token subset of "Nuno Pedro de Jesus Silva" and is
    somebody else — the first given name is what separates them."""
    assert ("nuno-silva-4", "pedro-silva-3") not in _flagged()


def test_detection_does_not_flag_an_unrelated_surname():
    assert not any("alan" in pair for pair in _flagged())


def test_a_reviewed_same_pair_goes_quiet(tmp_path):
    reviewed = person_aliases.reviewed_pairs(
        person_aliases.load_pairs(
            _write(
                tmp_path,
                {
                    "a": "j-silva",
                    "b": "jorge-silva",
                    "verdict": "same",
                    "canonical": "jorge-silva",
                    "evidence": "Same mailbox local part at two UC departments.",
                },
            )
        )
    )
    assert ("j-silva", "jorge-silva") not in _flagged(reviewed)
    assert ("filipe-araujo", "filipius-1") in _flagged(reviewed)


def test_a_reviewed_distinct_pair_goes_quiet_as_well(tmp_path):
    """Without this, a pair a human has correctly ruled DIFFERENT PEOPLE would
    be re-reported on every sync forever, and the list would train its reader
    to stop reading it."""
    reviewed = person_aliases.reviewed_pairs(
        person_aliases.load_pairs(
            _write(
                tmp_path,
                {
                    "a": "nuno-silva-1",
                    "b": "nuno-silva-4",
                    "verdict": "distinct",
                    "canonical": None,
                    "evidence": "nsilva@criticalsoftware.com (AC) vs npsilva@dei.uc.pt (SSE).",
                },
            )
        )
    )
    assert ("nuno-silva-1", "nuno-silva-4") not in _flagged(reviewed)


def test_detection_reports_the_pair_sorted_with_its_names():
    by_a = {p["a"]: p for p in possible_duplicates(ROSTER)}

    araujo = by_a["filipe-araujo"]
    assert (araujo["b"], araujo["name_a"], araujo["name_b"]) == (
        "filipius-1",
        "Filipe Araujo",
        "Filipe Araujo",
    )
    # Flagged for a human to read, so the two display names ride along — and
    # whether they are byte-equal is the first thing that reader wants.
    assert araujo["same_display_name"] is True
    assert by_a["j-silva"]["same_display_name"] is False


# --------------------------------------------------------------------------
# The file that actually ships
# --------------------------------------------------------------------------


def test_the_committed_verdicts_validate_against_the_real_roster():
    """A slug renamed upstream fails HERE, not at the next seed rebuild."""
    conn = sqlite3.connect(f"file:{build_mod.DEFAULT_DB}?mode=ro", uri=True)
    try:
        slugs = {row[0] for row in conn.execute("SELECT slug FROM people")}
    finally:
        conn.close()
    pairs = person_aliases.load_pairs()
    person_aliases.validate(pairs, slugs)
    assert len(pairs) >= 11


def test_the_committed_seed_carries_the_alias_table_the_app_reads():
    """The app opens the database mode=ro, so the table and the view have to
    be in the SHIPPED seed — not only in scraper/schema.sql."""
    conn = sqlite3.connect(f"file:{build_mod.DEFAULT_DB}?mode=ro", uri=True)
    try:
        stored = dict(conn.execute("SELECT from_slug, to_slug FROM person_aliases"))
        assert stored == person_aliases.alias_map(person_aliases.load_pairs())
        assert conn.execute("SELECT COUNT(*) FROM people_canonical").fetchone()[0] == (
            conn.execute("SELECT COUNT(*) FROM people").fetchone()[0] - len(stored)
        )
    finally:
        conn.close()


def test_no_committed_thesis_row_points_at_an_aliased_slug():
    """The whole reason canonicalisation lives in ``people_rows``: every
    consumer downstream of the seed can then assume one person, one slug."""
    conn = sqlite3.connect(f"file:{build_mod.DEFAULT_DB}?mode=ro", uri=True)
    try:
        assert conn.execute(
            "SELECT DISTINCT person_slug FROM thesis_people "
            "WHERE person_slug IN (SELECT from_slug FROM person_aliases)"
        ).fetchall() == []
    finally:
        conn.close()
