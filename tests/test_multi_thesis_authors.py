"""analysis/multi_thesis_authors.py — the reviewed exception, and its limits.

The thing under test is the boundary that keeps a fourth curated file from
becoming the thing all three of its siblings are forbidden to be: option C,
the thesis-name -> person lookup the Product Owner rejected
(``docs/thesis-attribution.md``). This one sits closest to that line of the
four, because its value IS a list of thesis handles. Three properties keep it
on the right side, and each has a test below:

* **the key is a person**, and an entry says how many theses that person has
  in this corpus. The handles are the evidence for the count, they are
  exhaustive, and a claim outside them is demoted exactly as it is today;
* **it creates no match.** ``validate()`` refuses an entry whose claims the
  matcher does not already resolve on its own, which is what makes "prevents
  a withdrawal" structurally different from "produces a match";
* **it goes stale loudly.** A thesis withdrawn upstream, a slug renamed, a
  name re-extracted, or ``person_aliases`` making the named slug an alias —
  each breaks the build rather than leaving an exemption standing over
  nothing. An exemption is the one curated fact whose silent survival would
  switch off the one-person-one-thesis check.

The end-to-end behaviour (the João Campos fixture, the demotion of an
unlisted claim, the ``thesis_people`` trigger) lives in
tests/test_build_thesis_facts.py, next to the conflict pass it changes. The
committed ``data/multi_thesis_authors.json`` is validated against the real
seed at the bottom of this file.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from analysis import multi_thesis_authors as mta
from analysis.build_thesis_facts import DEFAULT_DB

ENTRY = {
    "slug": "ada",
    "handles": ["t1", "t2"],
    "source_url": "https://example.test/ada",
    "evidence": "Two OAI records, one masterThesis and one doctoralThesis.",
}
SLUGS = {"ada"}
HANDLES = {"t1", "t2", "t3"}
CLAIMS = {("ada", "t1"), ("ada", "t2")}


def _write(tmp_path, *entries, **document):
    path = tmp_path / "multi_thesis_authors.json"
    path.write_text(
        json.dumps({"entries": list(entries), **document}), encoding="utf-8"
    )
    return path


def test_a_well_formed_entry_loads(tmp_path):
    assert mta.load_entries(_write(tmp_path, ENTRY)) == [ENTRY]


@pytest.mark.parametrize(
    "override, message",
    [
        ({"slug": ""}, "must be a non-empty string"),
        ({"source_url": "cisuc.uc.pt/ada"}, "is not a URL"),
        ({"evidence": "   "}, "evidence is required"),
        ({"handles": "t1"}, "must be a list of non-empty strings"),
        ({"handles": ["t1", ""]}, "must be a list of non-empty strings"),
        ({"handles": ["t1", "t1"]}, "lists the same handle twice"),
        ({"handles": ["t1"]}, "at least 2"),
    ],
)
def test_the_shape_is_checked_rather_than_assumed(tmp_path, override, message):
    with pytest.raises(mta.MultiThesisAuthorError, match=message):
        mta.load_entries(_write(tmp_path, {**ENTRY, **override}))


def test_an_unknown_key_is_refused(tmp_path):
    """A typo'd key would otherwise be silently ignored — and the key most
    likely to be typo'd here is ``handles``, whose absence changes what the
    entry exempts."""
    with pytest.raises(mta.MultiThesisAuthorError, match="unknown keys"):
        mta.load_entries(_write(tmp_path, {**ENTRY, "handle": "t1"}))


def test_a_note_is_optional_but_must_be_a_string(tmp_path):
    assert mta.load_entries(_write(tmp_path, {**ENTRY, "note": "an MSc"}))[0]["note"] == "an MSc"
    with pytest.raises(mta.MultiThesisAuthorError, match="'note' must be a string"):
        mta.load_entries(_write(tmp_path, {**ENTRY, "note": 1}))


def test_a_well_formed_entry_validates():
    mta.validate([ENTRY], SLUGS, HANDLES, CLAIMS)


def test_an_entry_naming_a_slug_people_does_not_carry_is_refused():
    """A slug renamed upstream, or the non-canonical half of a reviewed alias
    pair — in both cases the exemption names a slug no ``thesis_people`` row
    will ever carry, so it exempts nothing and the collision check is off for
    whatever rows DO carry the canonical."""
    with pytest.raises(mta.MultiThesisAuthorError, match="canonical slug 'ada'"):
        mta.validate([ENTRY], set(), HANDLES, CLAIMS)


def test_an_entry_naming_a_thesis_outside_the_corpus_is_refused():
    with pytest.raises(mta.MultiThesisAuthorError, match="thesis 't2' is not in this corpus"):
        mta.validate([ENTRY], SLUGS, {"t1"}, CLAIMS)


def test_an_entry_whose_claim_the_matcher_does_not_resolve_is_refused():
    """THE boundary. This file may only prevent the withdrawal of a match the
    matcher made independently; it must never be the thing that creates one.
    An entry that has outlived that is an exemption nobody reviewed."""
    with pytest.raises(
        mta.MultiThesisAuthorError, match="does not resolve the author of thesis 't2'"
    ):
        mta.validate([ENTRY], SLUGS, HANDLES, {("ada", "t1")})


def test_two_entries_for_one_slug_are_refused():
    """One person has one list of theses. Two entries would make which one
    wins depend on the file's order."""
    with pytest.raises(mta.MultiThesisAuthorError, match="already has an entry earlier"):
        mta.validate([ENTRY, ENTRY], SLUGS, HANDLES, CLAIMS)


def test_exempt_claims_is_keyed_on_the_pair_not_the_slug():
    """What ``resolve_author_conflicts`` reads. Keyed on (slug, handle) so a
    claim on an exempted slug for an unlisted thesis is still demoted."""
    assert mta.exempt_claims([ENTRY]) == frozenset({("ada", "t1"), ("ada", "t2")})
    assert mta.exempt_claims([]) == frozenset()


def test_write_table_writes_one_row_per_exempted_claim(tmp_path):
    """One row per claim rather than one per person: schema.sql's trigger
    tests membership of a (person_slug, handle) pair, and a JSON list in a
    column would make that a string search."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE multi_thesis_authors (person_slug TEXT, handle TEXT, "
        "source_url TEXT, evidence TEXT, PRIMARY KEY (person_slug, handle))"
    )
    assert mta.write_table(conn, [ENTRY]) == 2
    assert conn.execute(
        "SELECT person_slug, handle FROM multi_thesis_authors ORDER BY handle"
    ).fetchall() == [("ada", "t1"), ("ada", "t2")]

    # Full replace, not upsert: an exemption somebody REMOVED must not survive
    # in the seed, because a leftover row keeps the schema backstop off.
    assert mta.write_table(conn, []) == 0
    assert conn.execute("SELECT COUNT(*) FROM multi_thesis_authors").fetchone()[0] == 0


def test_the_committed_file_validates_against_the_real_seed():
    """The file that actually ships, against the data it actually ships with —
    so an entry made obsolete by a harvest, a directory sync or a matcher
    change fails here rather than at somebody's next rebuild."""
    entries = mta.load_entries()
    conn = sqlite3.connect(f"file:{DEFAULT_DB}?mode=ro", uri=True)
    try:
        canonical = {
            row[0]
            for row in conn.execute(
                "SELECT slug FROM people WHERE slug NOT IN "
                "(SELECT from_slug FROM person_aliases)"
            )
        }
        handles = {row[0] for row in conn.execute("SELECT handle FROM theses")}
        claims = {
            (row[0], row[1])
            for row in conn.execute(
                "SELECT person_slug, handle FROM thesis_people WHERE role = 'author' "
                "AND person_slug IS NOT NULL AND match_status IN ('exact', 'confident')"
            )
        }
    finally:
        conn.close()
    mta.validate(entries, canonical, handles, claims)
    assert entries, "the file is expected to carry at least the joao-campos entry"
