"""The two-pass matcher: CISUC first, UC unit directories only for the gap.

Every fence in ``analysis/build_thesis_facts.py::people_rows`` has a test
here, because each of them is a place where a plausible-looking change
silently resolves a name to the wrong human:

* pass 2 runs for a supervisor pass 1 could not resolve, and says so in the
  note;
* it does NOT run for an author of the same name (the Product Owner's fence:
  a doctoral student is not staff, and a staff directory's same-name
  professor is this corpus's worst failure mode);
* it does NOT run for a pass-1 ``ambiguous`` name, or for one pass 1
  resolved — the CISUC verdict stands, and the UC row that also fits is
  REPORTED instead;
* two units publishing one folded name do not collapse into one person,
  which is the ``name_match._one_folded_name`` tightening;
* one unit publishing one folded name twice still collapses, exactly as
  CISUC's own duplicates always have;
* a reviewed ``person_aliases`` verdict merges a CISUC slug with a UC one,
  which is the only sanctioned way a cross-source pair ever becomes one
  person;
* a ``confident`` match resting on a bare published name — surname plus first
  given, nothing else — is REFUSED unless a richer harvested form corroborates
  the thesis name, and the corroboration can only ever withhold that refusal,
  never create a match.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from analysis import build_thesis_facts as build_mod
from analysis.name_match import AMBIGUOUS, CONFIDENT, Person, match_name
from tests.conftest import THESIS_MD

# "Curie, Marie Sklodowska" is the fixture thesis's first supervisor and
# resolves to nobody in CISUC's fixture roster — the gap pass 2 exists for.
UC_CURIE = "Marie Sklodowska Curie"


# The same four EMPTY curated-file fixtures tests/test_build_thesis_facts.py
# defines, and empty for the same reason: the committed JSON names real CISUC
# slugs and real thesis mentions, and the fixture database has neither, so
# pointing these tests at it would (correctly) fail every validator. A test
# that wants a curated fact writes its own, as the alias test below does.
@pytest.fixture()
def corpus(tmp_path):
    directory = tmp_path / "estudo_geral"
    directory.mkdir()
    (directory / "10316-000001.md").write_text(THESIS_MD, encoding="utf-8")
    (directory / "manifest.json").write_text(
        json.dumps([{"handle": "10316/000001"}]), encoding="utf-8"
    )
    return directory


@pytest.fixture()
def aliases(tmp_path):
    path = tmp_path / "person_aliases.json"
    path.write_text(json.dumps({"pairs": []}), encoding="utf-8")
    return path


@pytest.fixture()
def full_names(tmp_path):
    path = tmp_path / "person_full_names.json"
    path.write_text(json.dumps({"entries": []}), encoding="utf-8")
    return path


@pytest.fixture()
def externals(tmp_path):
    path = tmp_path / "external_people.json"
    path.write_text(json.dumps({"entries": []}), encoding="utf-8")
    return path


@pytest.fixture()
def multi_authors(tmp_path):
    path = tmp_path / "multi_thesis_authors.json"
    path.write_text(json.dumps({"entries": []}), encoding="utf-8")
    return path


@pytest.fixture()
def dup_theses(tmp_path):
    """Empty, like the three above: the committed data/duplicate_theses.json
    names two real Estudo Geral handles and requires both in the corpus being
    built, which no fixture corpus here has."""
    path = tmp_path / "duplicate_theses.json"
    path.write_text(json.dumps({"entries": []}), encoding="utf-8")
    return path


def _add_uc_person(
    db,
    slug,
    name,
    source="feuc",
    unit="Faculdade de Economia (FEUC)",
    published=None,
):
    """``published`` is this unit's verbatim ``name_as_published``, which is
    the display name unless a test says otherwise — the real harvest keeps the
    two apart (one unit publishes a full name where another publishes a bare
    one) and the bare-floor guard reads exactly that difference."""
    conn = sqlite3.connect(db)
    conn.execute("INSERT OR IGNORE INTO people (slug, name) VALUES (?, ?)", (slug, name))
    conn.execute(
        "INSERT OR REPLACE INTO directory_listings (person_slug, source, unit_name, "
        "listing_url, person_url, name_as_published, role_as_published, fetched_at) "
        "VALUES (?, ?, ?, ?, NULL, ?, NULL, '2026-10-19T00:00:00+00:00')",
        (slug, source, unit, f"https://www.uc.pt/{source}/docentes/", published or name),
    )
    conn.commit()
    conn.close()


def _corpus_with_supervisor(tmp_path, supervisor):
    """A one-thesis corpus whose single supervisor is ``supervisor`` and whose
    author resolves in CISUC — so each bare-floor fence below states its own
    thesis-side name instead of bending the shared fixture's."""
    directory = tmp_path / "estudo_geral"
    directory.mkdir()
    (directory / "10316-000003.md").write_text(
        "---\n"
        "handle: 10316/000003\n"
        "title: Floor Evidence\n"
        "authors:\n- Lovelace, Ada\n"
        f"supervisors:\n- {supervisor}\n"
        "date: '2024-05-01'\n"
        "source_url: https://estudogeral.uc.pt/handle/10316/000003\n"
        "oai_sets:\n- com_10316_255\n"
        "---\n\n# Floor Evidence\n",
        encoding="utf-8",
    )
    (directory / "manifest.json").write_text(
        json.dumps([{"handle": "10316/000003"}]), encoding="utf-8"
    )
    return directory


def _rows(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    out = {(r["name_raw"], r["role"]): r for r in conn.execute("SELECT * FROM thesis_people")}
    conn.close()
    return out


def test_a_supervisor_pass_1_cannot_resolve_is_resolved_by_the_uc_pool(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    _add_uc_person(fixture_db, "uc--feuc--marie-sklodowska-curie", UC_CURIE)

    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)
    row = _rows(fixture_db)[("Curie, Marie Sklodowska", "supervisor")]

    assert row["person_slug"] == "uc--feuc--marie-sklodowska-curie"
    assert row["match_status"] == "exact"
    # The source rides in the note, so the row is auditable with no join at
    # all — the join to directory_listings stays the machine-readable form.
    assert row["match_note"].startswith("via UC directory feuc: ")
    # Pass 1's own report card does not move: it is the number every figure
    # this repo has published is comparable to.
    assert report["tiers"]["unmatched"] == 2
    assert report["uc_directory"]["tiers"]["exact"] == 1
    assert report["uc_directory"]["people"] == 1
    assert report["uc_directory"]["units"] == ["feuc"]


def test_an_author_with_the_same_name_is_never_consulted_against_the_uc_pool(
    tmp_path, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """The Product Owner's fence, and the seam the two caches exist for: one
    name in both roles must not read the supervisor pass's answer."""
    directory = tmp_path / "estudo_geral"
    directory.mkdir()
    (directory / "10316-000002.md").write_text(
        "---\n"
        "handle: 10316/000002\n"
        "title: Two Roles\n"
        "authors:\n- Curie, Marie Sklodowska\n"
        "supervisors:\n- Curie, Marie Sklodowska\n"
        "date: '2024-05-01'\n"
        "source_url: https://estudogeral.uc.pt/handle/10316/000002\n"
        "oai_sets:\n- com_10316_255\n"
        "---\n\n# Two Roles\n",
        encoding="utf-8",
    )
    (directory / "manifest.json").write_text(
        json.dumps([{"handle": "10316/000002"}]), encoding="utf-8"
    )
    _add_uc_person(fixture_db, "uc--feuc--marie-sklodowska-curie", UC_CURIE)

    build_mod.build(fixture_db, directory, aliases, full_names, externals, multi_authors, dup_theses)
    rows = _rows(fixture_db)

    assert rows[("Curie, Marie Sklodowska", "supervisor")]["person_slug"] == (
        "uc--feuc--marie-sklodowska-curie"
    )
    assert rows[("Curie, Marie Sklodowska", "author")]["person_slug"] is None
    assert rows[("Curie, Marie Sklodowska", "author")]["match_status"] == "unmatched"


def test_a_pass_1_ambiguous_name_is_not_consulted_against_the_uc_pool(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """Two CISUC rows already fit and no rule separates them. More candidates
    cannot resolve that — only widen it — so pass 2 never runs."""
    conn = sqlite3.connect(fixture_db)
    # Two genuinely different CISUC people who both fit "Nobody, At All" AND
    # both carry its primary given name, so the tie-break cannot separate
    # them either — which is what `ambiguous` is for.
    conn.execute("INSERT INTO people (slug, name) VALUES ('at-nobody', 'At Nobody')")
    conn.execute("INSERT INTO people (slug, name) VALUES ('at-all-nobody', 'At All Nobody')")
    conn.commit()
    conn.close()
    _add_uc_person(fixture_db, "uc--feuc--at-all-nobody-uc", "At All Nobody")

    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)
    row = _rows(fixture_db)[("Nobody, At All", "supervisor")]

    assert row["match_status"] == AMBIGUOUS
    assert row["person_slug"] is None
    assert "via UC directory" not in row["match_note"]
    assert "Nobody, At All" not in report["uc_directory"]["ambiguous_names"]


def test_a_pass_1_resolved_name_keeps_its_cisuc_verdict_and_is_reported(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """Source precedence, and it is not silent: the UC row that also fits
    appears in ``cross_directory_fits`` for a human to review."""
    _add_uc_person(fixture_db, "uc--fduc--ada-lovelace", "Ada Lovelace", source="fduc",
                   unit="Faculdade de Direito (FDUC)")

    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)
    row = _rows(fixture_db)[("Lovelace, Ada", "author")]

    assert row["person_slug"] == "ada"
    assert row["match_status"] == "exact"
    flagged = {entry["name_raw"]: entry for entry in report["cross_directory_fits"]}
    assert "Lovelace, Ada" in flagged
    assert flagged["Lovelace, Ada"]["cisuc"] == [["ada", "Ada Lovelace"]]
    assert flagged["Lovelace, Ada"]["uc_directory"] == [
        ["uc--fduc--ada-lovelace", "Ada Lovelace", "fduc"]
    ]


def test_one_folded_name_in_two_units_is_ambiguous_not_one_person(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """The ``_one_folded_name`` tightening. "João Silva" at FDUC and "João
    Silva" at FFUC is two people until a human says otherwise, so the name
    stays unresolved — and because a pass-2 ambiguity is reported rather than
    written, the row is untouched and the candidates are in the report."""
    _add_uc_person(fixture_db, "uc--fduc--marie-sklodowska-curie", UC_CURIE, source="fduc",
                   unit="Faculdade de Direito (FDUC)")
    _add_uc_person(fixture_db, "uc--ffuc--marie-sklodowska-curie", UC_CURIE, source="ffuc",
                   unit="Faculdade de Farmácia (FFUC)")

    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)
    row = _rows(fixture_db)[("Curie, Marie Sklodowska", "supervisor")]

    assert row["person_slug"] is None
    assert row["match_status"] == "unmatched"
    assert "via UC directory" not in row["match_note"]
    assert report["uc_directory"]["tiers"][AMBIGUOUS] == 1
    assert sorted(
        source for _slug, _name, source in
        report["uc_directory"]["ambiguous_names"]["Curie, Marie Sklodowska"]
    ) == ["fduc", "ffuc"]


def test_one_folded_name_twice_within_one_unit_still_collapses(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """A single directory listing one human twice is the ``joao-bicker``
    shape, and the tightening must not have broken it: one source, so the
    collapse still happens."""
    _add_uc_person(fixture_db, "uc--feuc--marie-sklodowska-curie", UC_CURIE)
    _add_uc_person(fixture_db, "uc--feuc--marie-sklodowska-curie-2", UC_CURIE)

    build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)
    conn = sqlite3.connect(fixture_db)
    rows = conn.execute(
        "SELECT person_slug, match_status FROM thesis_people "
        "WHERE name_raw = 'Curie, Marie Sklodowska' ORDER BY person_slug"
    ).fetchall()
    conn.close()

    assert [r[1] for r in rows] == [CONFIDENT, CONFIDENT]
    assert [r[0] for r in rows] == [
        "uc--feuc--marie-sklodowska-curie",
        "uc--feuc--marie-sklodowska-curie-2",
    ]


def test_a_reviewed_alias_merges_two_units_into_one_person(
    corpus, fixture_db, tmp_path, full_names, externals, multi_authors, dup_theses
):
    """The sanctioned cross-source merge, and the escape hatch the
    ``_one_folded_name`` tightening leaves open.

    Two units publish the same folded name, so the tightening refuses to
    collapse them on the name — see
    ``test_one_folded_name_in_two_units_is_ambiguous_not_one_person``. A human
    then reads both pages, rules them one human and records it with evidence
    in ``data/person_aliases.json``; ``_one_canonical`` honours that across
    sources with no further change, and the CANONICAL slug is what gets
    written.
    """
    _add_uc_person(fixture_db, "uc--fduc--marie-sklodowska-curie", UC_CURIE, source="fduc",
                   unit="Faculdade de Direito (FDUC)")
    _add_uc_person(fixture_db, "uc--ffuc--marie-sklodowska-curie", UC_CURIE, source="ffuc",
                   unit="Faculdade de Farmácia (FFUC)")
    aliases_path = tmp_path / "person_aliases.json"
    aliases_path.write_text(
        json.dumps(
            {
                "pairs": [
                    {
                        "a": "uc--ffuc--marie-sklodowska-curie",
                        "b": "uc--fduc--marie-sklodowska-curie",
                        "verdict": "same",
                        "canonical": "uc--fduc--marie-sklodowska-curie",
                        "evidence": "fixture: one human, cross-listed by two faculties",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    build_mod.build(fixture_db, corpus, aliases_path, full_names, externals, multi_authors, dup_theses)
    row = _rows(fixture_db)[("Curie, Marie Sklodowska", "supervisor")]

    assert row["person_slug"] == "uc--fduc--marie-sklodowska-curie"
    assert row["match_status"] == CONFIDENT
    assert row["match_note"].startswith("via UC directory fduc, ffuc: ")


def test_the_uc_pool_is_empty_on_a_seed_with_no_listings(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """Every number is byte-identical to the one-pool build when no unit has
    been harvested. This is the zero-regression guarantee held structurally
    rather than by review."""
    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)

    assert report["uc_directory"]["people"] == 0
    assert report["uc_directory"]["names_consulted"] == 0
    assert report["cross_directory_fits"] == []
    assert report["tiers"] == {"exact": 1, "confident": 0, "ambiguous": 0, "unmatched": 2}


def test_load_cisuc_people_excludes_the_uc_pool_and_vice_versa(fixture_db):
    _add_uc_person(fixture_db, "uc--feuc--marie-sklodowska-curie", UC_CURIE)
    conn = sqlite3.connect(fixture_db)
    try:
        cisuc = build_mod.load_cisuc_people(conn)
        uc = build_mod.load_uc_directory_people(conn)
    finally:
        conn.close()

    assert Person("ada", "Ada Lovelace") in cisuc
    assert all(not p.slug.startswith("uc--") for p in cisuc)
    assert [p.slug for p in uc] == ["uc--feuc--marie-sklodowska-curie"]
    # The default is what keeps every existing Person construction untouched.
    assert all(p.source == "cisuc" for p in cisuc)
    assert uc[0].source == "feuc"


def test_a_bare_published_name_does_not_resolve_a_richer_thesis_name(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """The card's failure, in miniature. "Marie Curie" is surname plus first
    given and nothing else, so it fits every "Curie, Marie …" alive — which is
    how "Luís Cruz" came to hold "Cruz, Luís Alberto da Silva". The row keeps
    its pass-1 ``unmatched`` verdict and the refusal is reported."""
    _add_uc_person(fixture_db, "uc--feuc--marie-curie", "Marie Curie")

    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)
    row = _rows(fixture_db)[("Curie, Marie Sklodowska", "supervisor")]

    assert row["person_slug"] is None
    assert row["match_status"] == "unmatched"
    assert "via UC directory" not in row["match_note"]
    # The matcher's own report card still says what the matcher concluded —
    # the demotion is a decision at the acceptance seam, not a doctored match.
    assert report["uc_directory"]["tiers"][CONFIDENT] == 1
    demotions = {entry["name_raw"]: entry for entry in report["uc_pool_bare_floor_demotions"]}
    assert demotions["Curie, Marie Sklodowska"]["candidates"] == [
        ["uc--feuc--marie-curie", "Marie Curie", "feuc"]
    ]
    assert demotions["Curie, Marie Sklodowska"]["uncorroborated"] == ["sklodowska"]
    assert demotions["Curie, Marie Sklodowska"]["rows"] == 1
    assert report["uc_pool_minimal_evidence"] == []


def test_a_second_listing_publishing_the_full_form_keeps_the_match(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """The rescue, and the reason the guard reads ``directory_listings``
    rather than ``people.name``: the pool flattens a human to one display
    name, but the unit that published the full form still has it. Pedro Góis's
    FEUC listing against his bare CES one, and Elísio Estanque's "Guerreiro"
    — both real, both would otherwise be lost."""
    _add_uc_person(fixture_db, "uc--feuc--marie-curie", "Marie Curie")
    _add_uc_person(
        fixture_db,
        "uc--feuc--marie-curie",
        "Marie Curie",
        source="ces",
        unit="Centro de Estudos Sociais (CES)",
        published="Curie, Marie Sklodowska",
    )

    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)
    row = _rows(fixture_db)[("Curie, Marie Sklodowska", "supervisor")]

    assert row["person_slug"] == "uc--feuc--marie-curie"
    assert row["match_status"] == CONFIDENT
    # The note names the corroborating listing, so the row is auditable
    # without joining back to directory_listings to find out why it survived.
    assert row["match_note"].startswith(
        'via UC directory ces, corroborated by ces\'s published form '
        '"Curie, Marie Sklodowska": '
    )
    assert report["uc_pool_bare_floor_demotions"] == []
    kept = report["uc_pool_minimal_evidence"]
    assert [(e["name_raw"], e["person_slug"], e["corroborated_by"]) for e in kept] == [
        (
            "Curie, Marie Sklodowska",
            "uc--feuc--marie-curie",
            ["ces", "Curie, Marie Sklodowska"],
        )
    ]


def test_a_bare_thesis_name_still_matches_a_bare_published_name_exactly(
    tmp_path, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """Set-equal rows are NOT demoted (design §1): a bare thesis mention
    carries no middle names to contradict, it is the evidence grade pass 1 has
    always accepted, and two bare candidates already come out ``ambiguous``.
    They become countable instead — in ``uc_pool_minimal_evidence``, where
    ``exact`` is what marks them as this shape rather than a rescue."""
    directory = _corpus_with_supervisor(tmp_path, "Curie, Marie")
    _add_uc_person(fixture_db, "uc--feuc--marie-curie", "Marie Curie")

    report = build_mod.build(fixture_db, directory, aliases, full_names, externals, multi_authors, dup_theses)
    row = _rows(fixture_db)[("Curie, Marie", "supervisor")]

    assert row["person_slug"] == "uc--feuc--marie-curie"
    assert row["match_status"] == "exact"
    # Not a rescue: the guard never looked at it, because set-equal is not the
    # strict-superset shape it refuses. The note carries no corroboration
    # clause for exactly that reason.
    assert row["match_note"].startswith("via UC directory feuc: ")
    assert report["uc_pool_bare_floor_demotions"] == []
    assert [(e["person_slug"], e["match_status"]) for e in report["uc_pool_minimal_evidence"]] == [
        ("uc--feuc--marie-curie", "exact")
    ]


def test_a_published_name_richer_than_the_floor_still_resolves_a_superset(
    tmp_path, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """The unchanged majority, and the boundary of the guard: "Marie
    Sklodowska Curie" carries a given name beyond surname-plus-first, so the
    thesis name agrees with evidence the candidate actually holds. This is the
    subset rule doing the work it was built for, and nothing here touches
    it."""
    directory = _corpus_with_supervisor(tmp_path, "Curie, Marie Salomea Sklodowska")
    _add_uc_person(fixture_db, "uc--feuc--marie-sklodowska-curie", UC_CURIE)

    report = build_mod.build(fixture_db, directory, aliases, full_names, externals, multi_authors, dup_theses)
    row = _rows(fixture_db)[("Curie, Marie Salomea Sklodowska", "supervisor")]

    assert row["person_slug"] == "uc--feuc--marie-sklodowska-curie"
    assert row["match_status"] == CONFIDENT
    assert row["match_note"].startswith("via UC directory feuc: ")
    assert report["uc_pool_bare_floor_demotions"] == []
    assert report["uc_pool_minimal_evidence"] == []


def test_corroboration_can_never_turn_a_rejected_candidate_into_a_match(
    tmp_path, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """The relaxation-B fence (design §1), and the reason this comparison is
    safe where B was not.

    B compared thesis names against published display names and **created**
    matches — "Cruz, Luís Alberto da Silva" -> "Luís Silva", a confidently
    wrong person. Here the richest possible corroboration is handed to a
    candidate ``_fits()`` rejects outright, and it buys nothing: the
    comparison runs only on candidates already accepted, and only to choose
    between confident and demoted. It can withhold a demotion. It can never
    make a match.
    """
    directory = _corpus_with_supervisor(tmp_path, "Cruz, Luís Alberto da Silva")
    _add_uc_person(
        fixture_db,
        "uc--fctuc-deec--luis-silva",
        "Luís Silva",
        published="Luís Alberto da Silva Cruz",
    )

    report = build_mod.build(fixture_db, directory, aliases, full_names, externals, multi_authors, dup_theses)
    row = _rows(fixture_db)[("Cruz, Luís Alberto da Silva", "supervisor")]

    assert row["person_slug"] is None
    assert row["match_status"] == "unmatched"
    assert report["uc_directory"]["tiers"]["unmatched"] == 1
    assert report["uc_pool_bare_floor_demotions"] == []
    assert report["uc_pool_minimal_evidence"] == []
    # And the same thing said at the unit the guard is made of: the listing
    # form does corroborate the name — the candidate is still not a fit.
    person = Person("uc--fctuc-deec--luis-silva", "Luís Silva", source="fctuc-deec")
    listings = {"uc--fctuc-deec--luis-silva": [("fctuc-deec", "Luís Alberto da Silva Cruz")]}
    assert build_mod.corroborating_form("Cruz, Luís Alberto da Silva", person, listings)
    assert match_name("Cruz, Luís Alberto da Silva", [person]).status == "unmatched"


def test_the_floor_is_one_definition_shared_with_the_author_side_net():
    """``minimal_evidence_matches`` and the pass-2 guard must read the same
    set. Two hand-copied definitions is how the next pool expansion
    reproduces this card — design §7."""
    assert build_mod.floor_tokens("Cruz, Luís Alberto da Silva") == {"cruz", "luis"}
    assert build_mod.floor_tokens("Góis, Pedro Miguel Pimenta") == {"gois", "pedro"}
    # Multi-token surname: the whole surname is the floor, not its last token.
    assert build_mod.floor_tokens("da Silva Cruz, Luís Alberto") == {"silva", "cruz", "luis"}
    # No given part at all separates nobody, and the floor says so.
    assert build_mod.floor_tokens("Curie") == {"curie"}


@pytest.mark.parametrize(
    "thesis_name, candidate, expected",
    [
        # The two false positives the rejected relaxations produced. Neither
        # pool may ever resolve them, and the UC pool is a bigger pool — so
        # they are re-checked here against a UC-sourced candidate too.
        ("Cruz, Luís Alberto da Silva", Person("uc--x--luis-silva", "Luís Silva", source="x"), None),
        ("Fonseca, José Carlos", Person("uc--x--carlos-fonseca", "Carlos M. Fonseca", source="x"), None),
    ],
)
def test_the_known_false_positives_stay_rejected_in_the_uc_pool(thesis_name, candidate, expected):
    assert match_name(thesis_name, [candidate]).status == "unmatched"
    assert expected is None
