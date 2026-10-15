"""analysis/person_full_names.py — the curated full legal names, and the gate.

Three things are under test here, and they fail for different reasons:

* the **loader**, which must refuse a file it cannot act on rather than skip
  an entry. A skipped entry here is quieter than a skipped alias: the person
  simply goes back to unmatched and the build still reports success;
* the **display-coverage rule**, which is the only automatic check standing
  between a typo'd entry and a wrong human landing on somebody's thesis at
  the ``confident`` tier;
* the **gate** — ``name_match._fits_full`` must be unreachable for a person
  with no reviewed entry. That is not a detail of the design, it *is* the
  design: the same comparison run against an unreviewed display name is
  measured-rejected relaxation B, which produced ``"Cruz, Luís Alberto da
  Silva"`` -> ``Luís Silva``. ``test_the_same_shape_without_a_reviewed_entry_
  stays_unmatched`` replays exactly that false positive and asserts it does
  not happen.

The committed ``data/person_full_names.json`` is validated against the real
roster at the bottom, so a slug — or a display name — renamed upstream fails
here rather than at the next seed rebuild.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from analysis import build_thesis_facts as build_mod
from analysis import person_full_names
from analysis.name_match import CONFIDENT, EXACT, UNMATCHED, Person, match_name

#: The ``antonio-dourado`` shape, on the synthetic roster: CISUC publishes a
#: form that drops the real surname entirely.
ENTRY = {
    "slug": "ada",
    "full_name": "Ada Lovelace Byron",
    "evidence": "Her own published biography gives the full name verbatim.",
}


def _write(tmp_path, *entries):
    path = tmp_path / "person_full_names.json"
    path.write_text(json.dumps({"entries": list(entries)}), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# The loader — every refusal, because each one is a silent wrong answer
# --------------------------------------------------------------------------


def test_an_entry_naming_a_slug_that_does_not_exist_is_refused(tmp_path):
    """The upstream-rename case. Skipping it would un-match a person and
    report a successful build."""
    entries = person_full_names.load_entries(_write(tmp_path, {**ENTRY, "slug": "ada-9"}))
    with pytest.raises(person_full_names.FullNameError, match="no row in people carries the slug"):
        person_full_names.validate(entries, {"ada": "Ada Lovelace"})


def test_two_entries_for_one_slug_are_refused(tmp_path):
    """One person has one legal name. Two entries would make which one wins
    depend on the file's ordering."""
    entries = person_full_names.load_entries(
        _write(tmp_path, ENTRY, {**ENTRY, "full_name": "Ada Augusta Lovelace"})
    )
    with pytest.raises(person_full_names.FullNameError, match="already has a full name"):
        person_full_names.validate(entries, {"ada": "Ada Lovelace"})


def test_a_full_name_that_does_not_cover_the_display_name_is_refused(tmp_path):
    """THE safety check. CISUC publishes "Ada Lovelace"; an entry claiming her
    legal name is "Grace Brewster Hopper" is either a typo or a different
    human, and acting on it would land that human on Ada's theses."""
    entries = person_full_names.load_entries(
        _write(tmp_path, {**ENTRY, "full_name": "Grace Brewster Hopper"})
    )
    with pytest.raises(person_full_names.FullNameError, match="does not account for"):
        person_full_names.validate(entries, {"ada": "Ada Lovelace"})


def test_the_display_name_may_abbreviate_a_given_name_as_an_initial(tmp_path):
    """"F. Amilcar Cardoso" is CISUC's own convention, not a mismatch — the
    coverage check excuses an initial exactly where the matcher does."""
    entries = person_full_names.load_entries(
        _write(tmp_path, {**ENTRY, "slug": "cardoso", "full_name": "Fernando Amílcar Cardoso"})
    )
    person_full_names.validate(entries, {"cardoso": "F. Amilcar Cardoso"})


def test_coverage_is_checked_against_the_live_display_name_not_the_file(tmp_path):
    """A directory sync that renames the display name out from under a
    committed entry must break the build, not silently keep resolving."""
    entries = person_full_names.load_entries(_write(tmp_path, ENTRY))
    person_full_names.validate(entries, {"ada": "Ada Lovelace"})
    with pytest.raises(person_full_names.FullNameError, match="does not account for"):
        person_full_names.validate(entries, {"ada": "Augusta King"})


def test_an_entry_with_no_evidence_is_refused(tmp_path):
    with pytest.raises(person_full_names.FullNameError, match="evidence is required"):
        person_full_names.load_entries(_write(tmp_path, {**ENTRY, "evidence": "   "}))


@pytest.mark.parametrize("key", ["slug", "full_name"])
def test_a_blank_field_is_refused_before_any_slug_is_looked_up(tmp_path, key):
    with pytest.raises(person_full_names.FullNameError, match=f"{key!r} must be a non-empty string"):
        person_full_names.load_entries(_write(tmp_path, {**ENTRY, key: "   "}))


def test_a_missing_field_names_what_is_missing(tmp_path):
    entry = {k: v for k, v in ENTRY.items() if k != "full_name"}
    with pytest.raises(person_full_names.FullNameError, match=r"missing \['full_name'\]"):
        person_full_names.load_entries(_write(tmp_path, entry))


def test_an_unknown_key_is_refused_rather_than_ignored(tmp_path):
    """A typo'd key is how an entry ends up meaning something other than what
    whoever wrote it intended — ``fullname`` would read as a missing one."""
    with pytest.raises(person_full_names.FullNameError, match="unknown keys"):
        person_full_names.load_entries(_write(tmp_path, {**ENTRY, "fullname": "Ada Lovelace Byron"}))


def test_a_file_without_an_entries_list_is_refused(tmp_path):
    path = tmp_path / "person_full_names.json"
    path.write_text(json.dumps([ENTRY]), encoding="utf-8")
    with pytest.raises(person_full_names.FullNameError, match="expected an object with an 'entries' list"):
        person_full_names.load_entries(path)


# --------------------------------------------------------------------------
# What the loader produces, and what the seed ends up holding
# --------------------------------------------------------------------------


def test_the_map_is_slug_to_full_name(tmp_path):
    entries = person_full_names.load_entries(_write(tmp_path, ENTRY))
    assert person_full_names.full_name_map(entries) == {"ada": "Ada Lovelace Byron"}


def test_write_table_replaces_rather_than_accumulates(tmp_path, fixture_db):
    """The table is a pure function of the file, so an entry somebody removed
    must not survive in the seed."""
    conn = sqlite3.connect(fixture_db)
    try:
        assert person_full_names.load_and_write(conn, _write(tmp_path, ENTRY)) == {"full_names": 1}
        assert conn.execute("SELECT slug, full_name FROM person_full_names").fetchall() == [
            ("ada", "Ada Lovelace Byron")
        ]

        person_full_names.load_and_write(conn, _write(tmp_path))
        assert conn.execute("SELECT COUNT(*) FROM person_full_names").fetchone()[0] == 0
    finally:
        conn.close()


def test_the_evidence_travels_into_the_table(tmp_path, fixture_db):
    conn = sqlite3.connect(fixture_db)
    try:
        person_full_names.load_and_write(conn, _write(tmp_path, ENTRY))
        assert conn.execute("SELECT evidence FROM person_full_names").fetchone()[0] == (
            ENTRY["evidence"]
        )
    finally:
        conn.close()


def test_load_people_fills_full_name_from_the_table(tmp_path, fixture_db):
    conn = sqlite3.connect(fixture_db)
    try:
        person_full_names.load_and_write(conn, _write(tmp_path, ENTRY))
        conn.commit()
        by_slug = {p.slug: p for p in build_mod.load_people(conn)}
    finally:
        conn.close()
    assert by_slug["ada"].full_name == "Ada Lovelace Byron"
    assert by_slug["alan"].full_name is None


# --------------------------------------------------------------------------
# The matcher — the new direction, and the gate that makes it safe
# --------------------------------------------------------------------------

#: The ``antonio-dourado`` shape: CISUC drops the trailing surname, so the
#: display name and the thesis name share no surname token at all.
DOURADO = Person("dourado", "António Dourado", None, "António Dourado Pereira Correia")

#: The ``penousal-machado`` shape: CISUC prints a later given name, and the
#: thesis names only the first.
PENOUSAL = Person("penousal", "Penousal Machado", None, "Fernando Jorge Penousal Martins Machado")


def test_a_dropped_surname_resolves_against_the_reviewed_full_name():
    result = match_name("Correia, António Dourado Pereira", [DOURADO])
    assert result.status == CONFIDENT
    assert [p.slug for p in result.people] == ["dourado"]
    assert "person_full_names.json" in result.note
    assert "António Dourado Pereira Correia" in result.note


def test_a_swapped_given_name_resolves_against_the_reviewed_full_name():
    """"Machado, Fernando" carries neither of the two tokens CISUC prints
    together — "Penousal" is his third given name."""
    result = match_name("Machado, Fernando", [PENOUSAL])
    assert result.status == CONFIDENT
    assert [p.slug for p in result.people] == ["penousal"]


def test_a_full_name_match_is_capped_at_confident_even_on_set_equality():
    """Token-set equality with a *reviewed declaration* is not the same claim
    as equality with what CISUC published, which is what ``exact`` means."""
    result = match_name("Correia, António Dourado Pereira", [DOURADO])
    assert result.status == CONFIDENT
    assert result.confidence == 0.8
    assert result.status != EXACT


def test_the_same_shape_without_a_reviewed_entry_stays_unmatched():
    """THE gate, and the reason this design is not measured-rejected
    relaxation B. "Luís Silva" is a token subset of "Cruz, Luís Alberto da
    Silva" sharing the primary given name — exactly the shape that produced a
    confidently wrong person when ``_fits()`` was relaxed to accept it. With
    no reviewed full name on the row, the mirror direction never runs."""
    unreviewed = Person("luis-silva", "Luís Silva")
    assert match_name("Cruz, Luís Alberto da Silva", [unreviewed]).status == UNMATCHED


def test_a_reviewed_full_name_still_has_to_cover_every_thesis_token():
    """The mirror of ``_fits()``'s rule 2. Sharing a surname and some given
    names with a reviewed full name is not being that person."""
    assert match_name("Correia, António Maria", [DOURADO]).status == UNMATCHED


def test_the_display_name_gets_the_first_say():
    """A person whose display name fits is matched on the display name, and
    the note says so — the reviewed full name is a fallback, not an override.
    This is what keeps the nine theses already resolving to penousal-machado
    from changing their note or their tier."""
    result = match_name("Machado, Fernando Jorge Penousal Martins", [PENOUSAL])
    assert result.status == CONFIDENT
    assert "person_full_names.json" not in result.note


def test_a_second_candidate_makes_it_ambiguous_rather_than_tie_broken():
    """A reviewed full name buys weak thesis forms a match ("Machado,
    Fernando" is two tokens), so the collision guard has to keep working: a
    real second Fernando Machado must surface, not be resolved away."""
    other = Person("fernando-machado", "Fernando Machado")
    result = match_name("Machado, Fernando", [PENOUSAL, other])
    assert result.status == "ambiguous"
    assert sorted(p.slug for p in result.people) == ["fernando-machado", "penousal"]


def test_an_empty_name_matches_nobody_however_many_full_names_are_reviewed():
    """No surname token means no rule 1 on either side, and a blank name must
    never sweep up every reviewed person by having nothing to contradict."""
    assert match_name("", [DOURADO, PENOUSAL]).status == UNMATCHED


def test_a_full_name_claim_is_not_a_set_equality_claim_for_the_conflict_pass():
    """``resolve_author_conflicts`` picks the keeper by token-set equality
    against ``people.name``, deliberately — the DISPLAY name. A claim that
    only reached its slug through a reviewed full name is the *weaker* kind of
    evidence, so it must never win a conflict against a claimant whose name
    equals what CISUC publishes."""
    people = [Person("dourado", "António Dourado", None, "António Dourado Pereira Correia")]
    rows = [
        ("h1", "Correia, António Dourado Pereira", "author", "dourado", CONFIDENT, 0.8, "", 0),
        ("h2", "Dourado, António", "author", "dourado", EXACT, 1.0, "", 0),
    ]
    kept, conflicts = build_mod.resolve_author_conflicts(rows, people)
    assert len(conflicts) == 1
    assert conflicts[0]["kept"] == {"handle": "h2", "name_raw": "Dourado, António"}
    assert [r[3] for r in kept if r[0] == "h1"] == [None]


# --------------------------------------------------------------------------
# The file that actually ships
# --------------------------------------------------------------------------


def test_the_committed_entries_validate_against_the_real_roster():
    """A slug OR a display name renamed upstream fails HERE, not at the next
    seed rebuild."""
    conn = sqlite3.connect(f"file:{build_mod.DEFAULT_DB}?mode=ro", uri=True)
    try:
        names = dict(conn.execute("SELECT slug, name FROM people"))
    finally:
        conn.close()
    entries = person_full_names.load_entries()
    person_full_names.validate(entries, names)
    assert len(entries) >= 4


def test_the_committed_seed_carries_the_full_name_table_the_build_reads():
    """The build opens the shipped seed, so the table has to be in it — not
    only in scraper/schema.sql."""
    conn = sqlite3.connect(f"file:{build_mod.DEFAULT_DB}?mode=ro", uri=True)
    try:
        stored = dict(conn.execute("SELECT slug, full_name FROM person_full_names"))
    finally:
        conn.close()
    assert stored == person_full_names.full_name_map(person_full_names.load_entries())


def test_every_committed_full_name_actually_recovers_something():
    """An entry that matches no thesis name is not wrong, but it is unreviewed
    curation debt accumulating in a file whose whole value is that every line
    was checked. This fails loudly so the next person has to decide."""
    conn = sqlite3.connect(f"file:{build_mod.DEFAULT_DB}?mode=ro", uri=True)
    try:
        resolved = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT person_slug FROM thesis_people WHERE person_slug IS NOT NULL"
            )
        }
    finally:
        conn.close()
    unused = sorted(set(person_full_names.full_name_map(person_full_names.load_entries())) - resolved)
    assert not unused, f"reviewed full names that resolve no thesis name: {unused}"
