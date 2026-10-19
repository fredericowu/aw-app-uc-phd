"""analysis/build_thesis_facts.py — the offline seed builder.

Runs against a throwaway copy of the fixture database, never the committed
seed: this is the one script in the repo that writes ``cisuc.sqlite3``, and a
test that pointed it at the real file would silently rewrite shipped data.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from analysis import build_thesis_facts as build_mod
from analysis import duplicate_theses as dup_mod
from analysis.name_match import Person
from tests.conftest import THESIS_MD

THESIS_NO_URL = THESIS_MD.replace(
    "source_url: https://estudogeral.uc.pt/handle/10316/000001\n", ""
)
THESIS_NO_SETS = THESIS_MD.replace(
    "oai_sets:\n- com_10316_255\n- col_10316_15519\n", ""
)


@pytest.fixture()
def corpus(tmp_path):
    """A one-thesis estudo_geral/ with the manifest that must agree with it."""
    directory = tmp_path / "estudo_geral"
    directory.mkdir()
    (directory / "10316-000001.md").write_text(THESIS_MD, encoding="utf-8")
    (directory / "manifest.json").write_text(
        json.dumps([{"handle": "10316/000001"}]), encoding="utf-8"
    )
    return directory


@pytest.fixture()
def aliases(tmp_path):
    """An EMPTY person_aliases.json, for the same reason ``corpus`` is a tmp
    directory and not the real ``estudo_geral/``: the committed
    ``data/person_aliases.json`` names real CISUC slugs, and the fixture
    ``people`` table does not have them — so pointing these tests at it would
    (correctly) fail validation on every one of them. A test that wants
    aliases writes its own, as ``test_an_alias_group_*`` below does."""
    path = tmp_path / "person_aliases.json"
    path.write_text(json.dumps({"pairs": []}), encoding="utf-8")
    return path


@pytest.fixture()
def full_names(tmp_path):
    """An EMPTY person_full_names.json, for exactly the reason ``aliases``
    above is empty: the committed ``data/person_full_names.json`` names real
    CISUC slugs and the fixture ``people`` table does not have them, so these
    tests would (correctly) fail its validation. A test that wants a reviewed
    full name writes its own, as tests/test_person_full_names.py does."""
    path = tmp_path / "person_full_names.json"
    path.write_text(json.dumps({"entries": []}), encoding="utf-8")
    return path


@pytest.fixture()
def externals(tmp_path):
    """An EMPTY external_people.json, for exactly the reason ``aliases`` and
    ``full_names`` above are empty — and here the collision is sharper: the
    committed ``data/external_people.json`` names real thesis mentions, and
    this ``corpus`` fixture is one synthetic thesis, so its validator would
    (correctly) refuse every entry. A test that wants an external identity
    writes its own, as tests/test_external_people.py does."""
    path = tmp_path / "external_people.json"
    path.write_text(json.dumps({"entries": []}), encoding="utf-8")
    return path


@pytest.fixture()
def multi_authors(tmp_path):
    """An EMPTY multi_thesis_authors.json, for exactly the reason the three
    fixtures above are empty, and here the refusal is the sharpest of the
    four: the committed ``data/multi_thesis_authors.json`` names a real CISUC
    slug AND two real thesis handles AND asserts the matcher resolves both of
    them, none of which is true of this one synthetic thesis — so its
    validator would (correctly) refuse the entry three times over. A test that
    wants an exemption writes its own, as ``test_a_reviewed_multi_thesis_*``
    below does."""
    path = tmp_path / "multi_thesis_authors.json"
    path.write_text(json.dumps({"entries": []}), encoding="utf-8")
    return path


@pytest.fixture()
def dup_theses(tmp_path):
    """An EMPTY duplicate_theses.json, for exactly the reason the four fixtures
    above are empty, and here the refusal would be the most consequential of
    the five: the committed ``data/duplicate_theses.json`` names two real
    Estudo Geral handles and requires BOTH to be in the corpus being built, so
    this one synthetic thesis would (correctly) refuse the entry — and if it
    somehow did not, the build under test would be dropping a thesis the test
    never asked it to.

    Empty is also the control these tests mostly want: with no reviewed
    duplicate, ``build()`` must behave exactly as it did before this
    instrument existed. The tests that want an exclusion write their own, as
    ``test_a_reviewed_duplicate_*`` below does."""
    path = tmp_path / "duplicate_theses.json"
    path.write_text(json.dumps({"entries": []}), encoding="utf-8")
    return path


def test_it_writes_the_three_tables_and_reports_what_it_wrote(corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses):
    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)

    assert report["theses"] == 1
    assert report["supervision_edges"] == 2
    assert report["distinct_names"] == 3
    assert report["tiers"]["exact"] == 1  # "Lovelace, Ada" -> ada
    assert report["tiers"]["unmatched"] == 2
    assert report["unresolved"] == ["Curie, Marie Sklodowska", "Nobody, At All"]

    conn = sqlite3.connect(fixture_db)
    conn.row_factory = sqlite3.Row
    thesis = conn.execute("SELECT * FROM theses").fetchone()
    assert thesis["handle"] == "10316/000001"
    assert thesis["slug"] == "10316-000001"
    assert thesis["year"] == "2024"
    assert thesis["full_text"] == 1
    assert thesis["abstract_en"] == "An abstract in English."
    assert [r["keyword"] for r in conn.execute("SELECT * FROM thesis_keywords ORDER BY ordinal")] == [
        "graphs",
        "graphs",
    ]
    conn.close()


def test_an_unmatched_name_is_preserved_as_a_row_with_a_null_slug(corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses):
    """The whole reason person_slug is nullable: dropping the 14 names nobody
    can resolve would be data loss dressed up as a clean join."""
    build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)

    conn = sqlite3.connect(fixture_db)
    conn.row_factory = sqlite3.Row
    rows = {r["name_raw"]: r for r in conn.execute("SELECT * FROM thesis_people")}
    conn.close()

    assert set(rows) == {"Lovelace, Ada", "Curie, Marie Sklodowska", "Nobody, At All"}
    assert rows["Lovelace, Ada"]["person_slug"] == "ada"
    assert rows["Lovelace, Ada"]["role"] == "author"
    assert rows["Curie, Marie Sklodowska"]["person_slug"] is None
    assert rows["Curie, Marie Sklodowska"]["match_status"] == "unmatched"
    assert rows["Curie, Marie Sklodowska"]["match_confidence"] == 0.0
    assert rows["Curie, Marie Sklodowska"]["match_note"]


def test_one_name_resolving_to_duplicate_people_rows_writes_both(corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses):
    """The João Bicker case: the PK has to carry person_slug or one of the two
    rows silently overwrites the other."""
    conn = sqlite3.connect(fixture_db)
    conn.execute("INSERT INTO people (slug, name) VALUES ('ada-1', 'Ada Lovelace')")
    conn.commit()
    conn.close()

    build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)

    conn = sqlite3.connect(fixture_db)
    slugs = [
        r[0]
        for r in conn.execute(
            "SELECT person_slug FROM thesis_people WHERE name_raw = 'Lovelace, Ada' ORDER BY 1"
        )
    ]
    conn.close()
    assert slugs == ["ada", "ada-1"]


def test_two_rows_a_review_calls_different_people_write_one_unresolved_row(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """The same two rows as the test above, with the one fact that changes what
    they mean: ``data/person_aliases.json`` says a human read both CISUC pages
    and these are two people (the real ``nuno-silva-1``/``nuno-silva-2``).

    Writing both rows then attributes one thesis mention to two unrelated
    humans — and every query that joins on ``person_slug``
    (``sql/partner_thesis_links.sql``, ``_person_group_shares``) counts it
    twice. One mention is one row, and with two real people fitting it, it is
    ambiguous and carries no slug.
    """
    conn = sqlite3.connect(fixture_db)
    conn.execute("INSERT INTO people (slug, name) VALUES ('ada-1', 'Ada Lovelace')")
    conn.commit()
    conn.close()
    aliases.write_text(
        json.dumps(
            {
                "pairs": [
                    {
                        "a": "ada",
                        "b": "ada-1",
                        "verdict": "distinct",
                        "canonical": None,
                        "evidence": "Different mailboxes at different domains.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)

    conn = sqlite3.connect(fixture_db)
    conn.row_factory = sqlite3.Row
    rows = list(
        conn.execute("SELECT * FROM thesis_people WHERE name_raw = 'Lovelace, Ada'")
    )
    conn.close()
    assert len(rows) == 1
    assert rows[0]["person_slug"] is None
    assert rows[0]["match_status"] == "ambiguous"


def test_rebuilding_replaces_rather_than_accumulates(corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses):
    """The tables are a pure function of the committed corpus. An upsert would
    leave a withdrawn thesis in the seed forever."""
    build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)
    (corpus / "10316-000001.md").unlink()
    (corpus / "manifest.json").write_text("[]", encoding="utf-8")

    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)

    assert report["theses"] == 0
    conn = sqlite3.connect(fixture_db)
    assert conn.execute("SELECT COUNT(*) FROM thesis_people").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM thesis_keywords").fetchone()[0] == 0
    conn.close()


def test_a_manifest_that_disagrees_with_the_files_is_a_hard_failure(corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses):
    """The glob is not the inventory. A half-failed download leaves a manifest
    entry with no .md, and trusting the glob would report a smaller corpus
    with no error at all."""
    (corpus / "manifest.json").write_text(
        json.dumps([{"handle": "10316/000001"}, {"handle": "10316/999999"}]), encoding="utf-8"
    )
    with pytest.raises(build_mod.ReconciliationError, match="10316/999999"):
        build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)


def test_an_unlisted_md_file_is_a_hard_failure_too(corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses):
    (corpus / "manifest.json").write_text("[]", encoding="utf-8")
    with pytest.raises(build_mod.ReconciliationError, match="unlisted"):
        build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)


def test_a_thesis_without_a_source_url_names_itself_when_it_fails(corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses):
    """source_url is NOT NULL in the schema; a bare sqlite3.IntegrityError
    would not say which thesis lost its provenance."""
    (corpus / "10316-000001.md").write_text(THESIS_NO_URL, encoding="utf-8")
    with pytest.raises(ValueError, match="10316/000001: no source_url"):
        build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)


def test_it_writes_every_oai_set_the_thesis_belongs_to(corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses):
    """Origin is many-to-many: the umbrella collection is stored next to the
    harvested community, raw, so a membership nobody planned for stays
    queryable without re-harvesting.

    The fixture thesis is listed under both ``com_10316_255`` (DEI) and
    ``col_10316_15519``, and the latter is now a harvested set in its own
    right ("UC" — the university-wide doctoral collection), so the per-set
    report counts this one thesis under *two* labels. That double count is
    the many-to-many the first paragraph describes, not a defect: the report
    answers "how many theses came from ISR", and a thesis cross-listed in
    two communities genuinely came from both."""
    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)
    assert report["thesis_sets"] == 2
    assert report["theses_per_harvest_set"] == {
        "DEI": 1,
        "INESCC": 0,
        "ISR": 0,
        "IT": 0,
        "UC": 1,
    }

    conn = sqlite3.connect(fixture_db)
    try:
        rows = conn.execute("SELECT handle, set_spec FROM thesis_sets ORDER BY set_spec").fetchall()
    finally:
        conn.close()
    assert rows == [("10316/000001", "col_10316_15519"), ("10316/000001", "com_10316_255")]


def test_a_rebuild_replaces_thesis_sets_rather_than_appending(corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses):
    """thesis_sets is in THESIS_TABLES, so the full-replace delete covers it —
    without that, a second run would hit the (handle, set_spec) primary key."""
    build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)
    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)
    assert report["thesis_sets"] == 2


def test_a_duplicated_set_spec_is_stored_once(corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses):
    """The primary key is (handle, set_spec); a header repeating a spec must
    not turn a provenance detail into an IntegrityError."""
    (corpus / "10316-000001.md").write_text(
        THESIS_MD.replace(
            "oai_sets:\n- com_10316_255\n", "oai_sets:\n- com_10316_255\n- com_10316_255\n"
        ),
        encoding="utf-8",
    )
    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)
    assert report["thesis_sets"] == 2


def test_a_thesis_without_oai_sets_names_itself_when_it_fails(corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses):
    """Same strictness as source_url, for the same reason: every OAI header
    carries set membership, so a front matter without it is a stale file —
    and writing zero rows would hide that from every grouping query."""
    (corpus / "10316-000001.md").write_text(THESIS_NO_SETS, encoding="utf-8")
    with pytest.raises(ValueError, match="10316/000001: no oai_sets"):
        build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)


def test_front_matter_without_delimiters_raises(tmp_path):
    directory = tmp_path / "estudo_geral"
    directory.mkdir()
    (directory / "broken.md").write_text("# No front matter here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no YAML front matter"):
        build_mod.load_front_matters(directory)


def test_load_cisuc_people_reads_the_people_table(fixture_db):
    conn = sqlite3.connect(fixture_db)
    try:
        assert Person("ada", "Ada Lovelace") in build_mod.load_cisuc_people(conn)
    finally:
        conn.close()


def test_the_cli_prints_its_report(corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses, capsys):
    assert build_mod.main(
        ["--db", str(fixture_db), "--estudo-geral", str(corpus),
         "--person-aliases", str(aliases),
         "--person-full-names", str(full_names),
         "--external-people", str(externals),
         "--multi-thesis-authors", str(multi_authors),
         "--duplicate-theses", str(dup_theses)]
    ) == 0
    assert json.loads(capsys.readouterr().out)["theses"] == 1


def test_the_committed_seed_holds_the_real_corpus():
    """The seed that actually ships. Asserts the measured shape of the real
    data — 2689 theses, 4568 supervisor rows, 4988 distinct names — so a
    rebuild that silently loses rows fails here rather than in the dashboard.

    The numbers were 181 / 242 / 283 while the harvest was DEI-only. They are
    what they are now because the harvest added ``col_10316_15519``, the
    university-wide "UC — Teses de Doutoramento" collection
    (``estudo_geral_extractor.oai.HARVEST_SETS``): 181 DEI theses plus 2556
    reached only through the UC umbrella, which is every doctoral thesis at
    Coimbra rather than every doctoral thesis at the department. All three
    figures are re-derived from a ``python -m analysis.build_thesis_facts``
    run against this file, not carried over from a report.

    The supervisor-row floor is a floor, not an equality, for the reason it
    was one at 242: it moves when ``person_aliases`` collapses two rows that
    are the same human (that is how 244 became 242 — "Araújo, Filipe"
    resolving to both ``filipe-araujo`` and ``filipius-1``), and a verdict
    like that is a feature landing, not a row silently lost. It moved again,
    4580 -> 4574, when four more such pairs were reviewed (joao-bicker,
    jcfgonc, cristina-costa, luis-rodrigues-3). The count of distinct
    supervision EDGES (``build()``'s ``supervision_edges``, 4570) is the
    figure aliasing cannot move, and it did not.

    4574 -> 4570 is the same floor moving for the mirror-image reason: the
    matcher now reads ``person_aliases``' reviewed ``distinct`` verdicts, so
    four supervisor mentions that were two rows under two different real
    people are one unresolved row each (``docs/thesis-attribution.md``,
    amendment 2026-10-19). ``supervision_edges`` is still 4570 — which is
    what says these were duplicate ROWS for one mention and not lost
    supervisions — and the floor is now equal to it, so the next collapse of
    either kind will fail here and want a number read off a rebuild.

    **2690 -> 2689, and 4570 -> 4568 (amendment 2026-10-19).** The first
    movement of these figures that is a thesis genuinely leaving the corpus
    rather than rows collapsing onto one person. ``10316/90536`` is one
    physical doctoral thesis that Estudo Geral deposited twice, reviewed
    against both OAI records and excluded by ``data/duplicate_theses.json``
    (``analysis/duplicate_theses.py``); the record that stays is
    ``10316/90537``. The deltas are the duplicate's own rows and nothing else,
    read off a rebuild and row-diffed against the previous seed: ``theses``
    -1, ``thesis_people`` -3 (its unmatched author plus its two ``exact``
    UC-directory supervisors), ``thesis_keywords`` -5, ``thesis_sets`` -4.

    ``supervision_edges`` moves this time, 4570 -> 4568, where aliasing could
    never move it — and that is the point: it is counted from the front
    matters, so a thesis leaving the corpus is exactly the kind of change it
    is supposed to register. The supervisor-row floor tracks it down to 4568
    for the same reason, so floor == edges still holds.

    ``distinct_names`` does NOT move, and that was checked rather than assumed:
    both of the dropped supervisor name strings ("Alcoforado, Joaquim Luís
    Medeiros", "Vieira, Cristina Maria Coimbra") appear on other theses (3 and
    8 respectively), and the dropped author "Moio, Isabel Sofia Fernandes" is
    still the author of the surviving 10316/90537. The author-name count the
    dashboard publishes as "Students" is unchanged at 2686 for that last
    reason."""
    conn = sqlite3.connect(f"file:{build_mod.DEFAULT_DB}?mode=ro", uri=True)
    try:
        assert conn.execute("SELECT COUNT(*) FROM theses").fetchone()[0] == 2689
        assert conn.execute(
            "SELECT COUNT(*) FROM thesis_people WHERE role = 'supervisor'"
        ).fetchone()[0] >= 4568
        assert conn.execute(
            "SELECT COUNT(DISTINCT name_raw) FROM thesis_people"
        ).fetchone()[0] == 4988
        # The invariant item #1 restored, re-checked at the new size: one
        # `people` row authors at most one thesis, so resolved or not, the
        # corpus has exactly one author row per thesis.
        assert conn.execute(
            "SELECT COUNT(*) FROM thesis_people WHERE role = 'author'"
        ).fetchone()[0] == 2689
        # Every thesis carries its provenance, and nothing lost its rights flag.
        assert conn.execute("SELECT COUNT(*) FROM theses WHERE source_url IS NULL").fetchone()[0] == 0
    finally:
        conn.close()


# --------------------------------------------------------------------------
# The author-uniqueness invariant — one people row, at most one authored PhD
# --------------------------------------------------------------------------

ADA = Person("ada", "Ada Lovelace")


def _author_row(handle, name_raw, slug, status="confident", confidence=0.8, ordinal=0):
    return (handle, name_raw, "author", slug, status, confidence, "matched", ordinal)


def test_the_set_equality_claimant_keeps_the_slug_and_the_subset_claim_is_demoted():
    """The pedro-martins shape, in miniature: two different real people whose
    names both fit one CISUC row. The one whose name IS the row keeps it."""
    rows = [
        _author_row("t1", "Lovelace, Ada", "ada", status="exact", confidence=1.0),
        _author_row("t2", "Lovelace, Ada Augusta Byron", "ada"),
    ]
    out, conflicts = build_mod.resolve_author_conflicts(rows, [ADA])

    assert out[0] == rows[0]
    demoted = out[1]
    assert demoted[build_mod.SLUG] is None
    assert demoted[build_mod.STATUS] == "ambiguous"
    assert demoted[build_mod.MATCH_CONFIDENCE] == 0.4
    assert "also claimed by thesis t1" in demoted[build_mod.NOTE]
    assert '"Lovelace, Ada" equals the CISUC row "Ada Lovelace" exactly' in demoted[build_mod.NOTE]

    assert conflicts == [
        {
            "person_slug": "ada",
            "person_name": "Ada Lovelace",
            "kept": {"handle": "t1", "name_raw": "Lovelace, Ada"},
            "demoted": [{"handle": "t2", "name_raw": "Lovelace, Ada Augusta Byron"}],
            "decision": "kept the one set-equality claim, demoted the rest",
        }
    ]


def test_with_no_set_equal_claimant_every_claimant_is_demoted():
    """Nothing separates two subset claims, so preferring either would be the
    same guess the matcher was just stopped from making."""
    rows = [
        _author_row("t1", "Lovelace, Ada Augusta", "ada"),
        _author_row("t2", "Lovelace, Ada Byron", "ada"),
    ]
    out, conflicts = build_mod.resolve_author_conflicts(rows, [ADA])

    assert [row[build_mod.SLUG] for row in out] == [None, None]
    assert all(row[build_mod.STATUS] == "ambiguous" for row in out)
    assert all("none of them equals the CISUC row" in row[build_mod.NOTE] for row in out)
    assert conflicts[0]["kept"] is None
    assert conflicts[0]["decision"] == "no single set-equality claim — demoted every claimant"
    assert len(conflicts[0]["demoted"]) == 2


def test_one_supervisor_across_many_theses_is_not_a_conflict():
    """The normal case, and the whole advisor view. Exempt on purpose."""
    rows = [
        ("t1", "Lovelace, Ada Augusta", "supervisor", "ada", "confident", 0.8, "matched", 0),
        ("t2", "Lovelace, Ada Byron", "supervisor", "ada", "confident", 0.8, "matched", 0),
    ]
    assert build_mod.resolve_author_conflicts(rows, [ADA]) == (rows, [])


def test_one_person_authoring_one_thesis_under_two_duplicate_rows_is_untouched():
    """``people`` holds grace/grace-1 for one human, so one author legitimately
    writes two rows. Two rows, one handle — not a conflict."""
    duplicates = [Person("grace", "Grace Hopper"), Person("grace-1", "Grace Hopper")]
    rows = [
        _author_row("t1", "Hopper, Grace", "grace"),
        _author_row("t1", "Hopper, Grace", "grace-1"),
    ]
    assert build_mod.resolve_author_conflicts(rows, duplicates) == (rows, [])


def test_a_demoted_claimant_collapses_to_a_single_null_slug_row():
    """It arrived as two rows (a duplicated ``people`` row); unresolved names
    are written as exactly one row, so that is what it leaves as."""
    duplicates = [Person("grace", "Grace Hopper"), Person("grace-1", "Grace Hopper")]
    rows = [
        _author_row("t1", "Hopper, Grace", "grace", status="exact", confidence=1.0),
        _author_row("t1", "Hopper, Grace", "grace-1", status="exact", confidence=1.0),
        _author_row("t2", "Hopper, Grace Brewster", "grace", ordinal=3),
        _author_row("t2", "Hopper, Grace Brewster", "grace-1", ordinal=3),
    ]
    out, conflicts = build_mod.resolve_author_conflicts(rows, duplicates)

    assert out[:2] == rows[:2]
    assert len(out) == 3
    assert out[2][build_mod.HANDLE] == "t2"
    assert out[2][build_mod.SLUG] is None
    assert out[2][build_mod.ORDINAL] == 3
    assert len(conflicts) == 2  # one per contested slug


def test_minimal_evidence_lists_the_two_token_matches_for_human_review():
    """Surname + first given name is the weakest evidence the matcher acts on,
    and no name-only rule can tell a right one from a wrong one."""
    people = [ADA, Person("alan", "Alan Mathison Turing")]
    rows = [
        _author_row("t1", "Lovelace, Ada Augusta", "ada"),
        _author_row("t2", "Turing, Alan Mathison", "alan"),
    ]
    assert build_mod.minimal_evidence_matches(rows, people) == [
        {
            "handle": "t1",
            "name_raw": "Lovelace, Ada Augusta",
            "person_slug": "ada",
            "person_name": "Ada Lovelace",
        }
    ]


def test_the_build_reports_the_conflict_and_writes_no_duplicate_resolved_author(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """End to end: a second thesis whose author's longer name also fits 'Ada
    Lovelace' must not merge the two into one student."""
    second = THESIS_MD.replace("10316/000001", "10316/000002").replace(
        "- Lovelace, Ada\n", "- Lovelace, Ada Augusta Byron\n"
    )
    (corpus / "10316-000002.md").write_text(second, encoding="utf-8")
    (corpus / "manifest.json").write_text(
        json.dumps([{"handle": "10316/000001"}, {"handle": "10316/000002"}]), encoding="utf-8"
    )

    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)
    assert [c["person_slug"] for c in report["author_conflicts"]] == ["ada"]
    assert report["author_conflicts"][0]["kept"]["handle"] == "10316/000001"

    conn = sqlite3.connect(fixture_db)
    try:
        assert conn.execute(
            "SELECT person_slug FROM thesis_people WHERE role = 'author' "
            "AND person_slug IS NOT NULL GROUP BY person_slug "
            "HAVING COUNT(DISTINCT handle) > 1"
        ).fetchall() == []
        assert conn.execute(
            "SELECT match_status FROM thesis_people WHERE handle = '10316/000002' "
            "AND role = 'author'"
        ).fetchone() == ("ambiguous",)
    finally:
        conn.close()


def test_rebuilding_over_a_seed_that_still_holds_a_false_merge_succeeds(corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses):
    """The ordering trap: schema.sql's author backstop is created by `build()`
    itself, so a rebuild has to clear the old rows BEFORE applying the schema
    or the fix could never be applied to the data it fixes.

    The seed this simulates is one from before the backstop existed at all, so
    the setup drops both of its forms — hence dropping the trigger as well as
    the index that preceded it."""
    conn = sqlite3.connect(fixture_db)
    try:
        conn.executescript(
            "DROP INDEX IF EXISTS idx_one_thesis_per_resolved_author;"
            "DROP TRIGGER IF EXISTS trg_one_thesis_per_resolved_author;"
            "INSERT INTO theses (handle, slug, title, source_url) VALUES"
            " ('old/1', 'old-1', 'Old One', 'https://example.test/1'),"
            " ('old/2', 'old-2', 'Old Two', 'https://example.test/2');"
            "INSERT INTO thesis_people VALUES"
            " ('old/1', 'Lovelace, Ada', 'author', 'ada', 'exact', 1.0, 'stale', 0),"
            " ('old/2', 'Lovelace, Ada Byron', 'author', 'ada', 'exact', 1.0, 'stale', 0);"
        )
        conn.commit()
    finally:
        conn.close()

    assert build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)["theses"] == 1


def test_a_rebuild_in_place_drops_the_index_the_trigger_replaced(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """The trap one step past the one above, and the reason schema.sql carries
    a DROP INDEX rather than just not creating one.

    Every statement in schema.sql is IF NOT EXISTS, and `build()` applies it
    over the seed file that already exists — so a seed built before the
    exemption landed would keep `idx_one_thesis_per_resolved_author` forever,
    and a reviewed multi-thesis author would fail at INSERT on an index no
    source file mentions any more. A gate-only fix passes every other test in
    this module and dies exactly here."""
    conn = sqlite3.connect(fixture_db)
    try:
        conn.executescript(
            "DROP TRIGGER IF EXISTS trg_one_thesis_per_resolved_author;"
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_one_thesis_per_resolved_author"
            " ON thesis_people(person_slug)"
            " WHERE role = 'author' AND person_slug IS NOT NULL;"
        )
        conn.commit()
    finally:
        conn.close()

    build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)

    conn = sqlite3.connect(fixture_db)
    try:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' "
            "AND name = 'idx_one_thesis_per_resolved_author'"
        ).fetchall() == []
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' "
            "AND name = 'trg_one_thesis_per_resolved_author'"
        ).fetchall() == [("trg_one_thesis_per_resolved_author",)]
    finally:
        conn.close()


def test_the_committed_seed_resolves_no_slug_to_two_authored_theses():
    """The invariant, asserted on the file that actually ships — and on the
    only exception to it, which is reviewed rather than merely tolerated.

    A slug on two authored theses is either a false merge or a graduate whose
    MSc dissertation and doctoral thesis are both deposited here. The
    difference is not visible in ``thesis_people``, so this reads the seed's
    own ``multi_thesis_authors`` table: every such slug must have a reviewed
    entry covering *exactly* the theses it actually authors. An exemption
    somebody widened by hand fails here, and so does a real false merge."""
    conn = sqlite3.connect(f"file:{build_mod.DEFAULT_DB}?mode=ro", uri=True)
    try:
        multiple = {
            slug: set(handles.split(","))
            for slug, handles in conn.execute(
                "SELECT person_slug, GROUP_CONCAT(DISTINCT handle) FROM thesis_people "
                "WHERE role = 'author' AND person_slug IS NOT NULL GROUP BY person_slug "
                "HAVING COUNT(DISTINCT handle) > 1"
            )
        }
        reviewed: dict[str, set[str]] = {}
        for slug, handle in conn.execute(
            "SELECT person_slug, handle FROM multi_thesis_authors"
        ):
            reviewed.setdefault(slug, set()).add(handle)
        assert multiple == reviewed
    finally:
        conn.close()


def test_the_committed_seed_carries_the_backstop_as_a_trigger_not_a_stale_index():
    """The shipped file, not just the source: the seed is rebuilt in place over
    itself, so "schema.sql says so" is not evidence that the file a user
    installs agrees."""
    conn = sqlite3.connect(f"file:{build_mod.DEFAULT_DB}?mode=ro", uri=True)
    try:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE name = "
            "'idx_one_thesis_per_resolved_author'"
        ).fetchall() == []
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name = "
            "'trg_one_thesis_per_resolved_author'"
        ).fetchall() == [("trg_one_thesis_per_resolved_author",)]
    finally:
        conn.close()


# --------------------------------------------------------------------------
# The reviewed exception — one graduate, an MSc and a PhD, both deposited
#
# The João Campos case. Both of his claims carry the IDENTICAL raw name
# "Campos, João Rodrigues de", and both are token-set-equal to the CISUC row
# "João Rodrigues Campos", so the gate found two set-equality claimants, could
# prefer neither, and withdrew both. What makes the exemption safe is that it
# is a reviewed fact about one person, not a rule about identical strings —
# see analysis/multi_thesis_authors.py.
# --------------------------------------------------------------------------


def _two_theses(corpus, *handles, author="Lovelace, Ada"):
    """The ``corpus`` fixture's one thesis, re-filed under several handles with
    one author name — the shape a graduate's MSc and PhD have here."""
    (corpus / "10316-000001.md").unlink()
    for handle in handles:
        slug = handle.replace("/", "-")
        (corpus / f"{slug}.md").write_text(
            THESIS_MD.replace("10316/000001", handle).replace(
                "- Lovelace, Ada\n", f"- {author}\n"
            ),
            encoding="utf-8",
        )
    (corpus / "manifest.json").write_text(
        json.dumps([{"handle": handle} for handle in handles]), encoding="utf-8"
    )


def _exemption(path, slug, *handles):
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "slug": slug,
                        "handles": list(handles),
                        "source_url": "https://www.cisuc.uc.pt/en/people/ada",
                        "evidence": "Reviewed against both OAI records: a masterThesis "
                        "and a doctoralThesis by one graduate.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_a_reviewed_multi_thesis_author_keeps_the_slug_on_every_listed_thesis(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """D2's whole point. Without the entry both rows are ``ambiguous`` with a
    NULL slug (``test_with_several_set_equal_claimants_the_note_says_so``
    below is that same input); with it, both resolve."""
    _two_theses(corpus, "10316/000001", "10316/000002")
    _exemption(multi_authors, "ada", "10316/000001", "10316/000002")

    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)

    assert report["author_conflicts"] == []
    assert report["multi_thesis_authors"] == {"people": 1, "exempted_claims": 2}
    conn = sqlite3.connect(fixture_db)
    try:
        assert sorted(
            conn.execute(
                "SELECT handle, person_slug, match_status FROM thesis_people "
                "WHERE role = 'author'"
            )
        ) == [
            ("10316/000001", "ada", "exact"),
            ("10316/000002", "ada", "exact"),
        ]
    finally:
        conn.close()


def test_a_claim_the_reviewed_entry_does_not_list_is_still_demoted(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """The handle list is exhaustive, and that is what keeps this a fact about
    one person rather than a blanket licence on a slug: a third thesis the
    review never saw is, by that review, somebody else."""
    _two_theses(corpus, "10316/000001", "10316/000002", "10316/000003")
    _exemption(multi_authors, "ada", "10316/000001", "10316/000002")

    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)

    assert [c["person_slug"] for c in report["author_conflicts"]] == ["ada"]
    assert report["author_conflicts"][0]["demoted"] == [
        {"handle": "10316/000003", "name_raw": "Lovelace, Ada"}
    ]
    assert report["author_conflicts"][0]["decision"] == (
        "kept the 2 claims reviewed in data/multi_thesis_authors.json, demoted the rest"
    )

    conn = sqlite3.connect(fixture_db)
    try:
        rows = dict(
            conn.execute(
                "SELECT handle, person_slug FROM thesis_people WHERE role = 'author'"
            )
        )
        note = conn.execute(
            "SELECT match_note FROM thesis_people WHERE handle = '10316/000003' "
            "AND role = 'author'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert rows == {
        "10316/000001": "ada",
        "10316/000002": "ada",
        "10316/000003": None,
    }
    assert "data/multi_thesis_authors.json" in note
    assert "this claim is not among them" in note


def test_an_exemption_whose_claim_the_matcher_does_not_resolve_is_refused(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """The staleness guard, and the boundary that keeps this file off the
    matcher's side of the line: an entry may only prevent a withdrawal, never
    create a match. An author name that changed upstream breaks the build
    instead of leaving an exemption standing over nothing."""
    _two_theses(corpus, "10316/000001", "10316/000002")
    (corpus / "10316-000002.md").write_text(
        THESIS_MD.replace("10316/000001", "10316/000002").replace(
            "- Lovelace, Ada\n", "- Nobody, At All\n"
        ),
        encoding="utf-8",
    )
    _exemption(multi_authors, "ada", "10316/000001", "10316/000002")

    with pytest.raises(
        build_mod.multi_thesis_authors.MultiThesisAuthorError,
        match="does not resolve the author of thesis '10316/000002'",
    ):
        build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)


def test_an_exemption_naming_a_thesis_outside_the_corpus_is_refused(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """A thesis withdrawn upstream leaves an exemption over a handle that is
    gone — an unreviewed hole in the one-person-one-thesis check."""
    _exemption(multi_authors, "ada", "10316/000001", "10316/999999")
    with pytest.raises(
        build_mod.multi_thesis_authors.MultiThesisAuthorError,
        match="thesis '10316/999999' is not in this corpus",
    ):
        build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)


def test_with_several_set_equal_claimants_the_note_says_so(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """The lying note, fixed. This is the same input as the first test in this
    section with the exemption removed, and it used to print the no-keeper
    text "none of them equals the CISUC row exactly" when in fact BOTH do —
    which is what sent the original investigation of João Campos looking for a
    matcher bug that was not there."""
    _two_theses(corpus, "10316/000001", "10316/000002")

    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses)

    assert report["author_conflicts"][0]["kept"] is None
    conn = sqlite3.connect(fixture_db)
    try:
        notes = {
            handle: note
            for handle, note in conn.execute(
                "SELECT handle, match_note FROM thesis_people WHERE role = 'author'"
            )
        }
    finally:
        conn.close()
    for note in notes.values():
        assert "none of them equals the CISUC row" not in note
        assert '2 of which equal the CISUC row "Ada Lovelace" exactly' in note
        assert "data/multi_thesis_authors.json" in note


def test_an_exemption_listing_one_thesis_is_refused_as_a_no_op():
    """One claim on a slug is never a conflict, so a one-handle entry exempts
    nothing — it is a typo or the leftover of a thesis that went away, and a
    file of no-ops is a file nobody reads."""
    import json as _json
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        _json.dump(
            {
                "entries": [
                    {
                        "slug": "ada",
                        "handles": ["t1"],
                        "source_url": "https://example.test/ada",
                        "evidence": "reviewed",
                    }
                ]
            },
            handle,
        )
        path = handle.name
    with pytest.raises(
        build_mod.multi_thesis_authors.MultiThesisAuthorError, match="at least 2"
    ):
        build_mod.multi_thesis_authors.load_entries(Path(path))


def test_the_exemption_is_read_per_claim_not_per_slug():
    """``resolve_author_conflicts`` on its own, with no build around it: the
    exemption is keyed on (slug, handle), so listing one of two claims keeps
    that one and demotes the other."""
    rows = [
        _author_row("t1", "Lovelace, Ada", "ada", status="exact", confidence=1.0),
        _author_row("t2", "Lovelace, Ada", "ada", status="exact", confidence=1.0),
    ]
    out, conflicts = build_mod.resolve_author_conflicts(
        rows, [ADA], frozenset({("ada", "t1")})
    )

    assert out[0] == rows[0]
    assert out[1][build_mod.SLUG] is None
    assert conflicts[0]["demoted"] == [{"handle": "t2", "name_raw": "Lovelace, Ada"}]


def test_an_exemption_on_a_different_slug_changes_nothing():
    """The exemption is not a global switch. A reviewed entry for somebody
    else leaves this slug's conflict exactly as it was."""
    rows = [
        _author_row("t1", "Lovelace, Ada", "ada", status="exact", confidence=1.0),
        _author_row("t2", "Lovelace, Ada Augusta Byron", "ada"),
    ]
    without = build_mod.resolve_author_conflicts(rows, [ADA])
    with_other = build_mod.resolve_author_conflicts(
        rows, [ADA], frozenset({("grace", "t1"), ("grace", "t2")})
    )
    assert without == with_other


def test_the_trigger_refuses_a_second_resolved_author_row_for_an_unreviewed_slug(
    fixture_db,
):
    """The backstop, at the strength the UNIQUE index had: a re-merge is
    impossible to COMMIT even when the build pass is bypassed entirely. This
    inserts straight into the table, as a hand-written migration or a future
    pipeline that skipped ``resolve_author_conflicts`` would."""
    conn = sqlite3.connect(fixture_db)
    try:
        conn.executescript(
            "INSERT INTO theses (handle, slug, title, source_url) VALUES"
            " ('t/1', 't-1', 'One', 'https://example.test/1'),"
            " ('t/2', 't-2', 'Two', 'https://example.test/2');"
            "INSERT INTO thesis_people VALUES"
            " ('t/1', 'Lovelace, Ada', 'author', 'ada', 'exact', 1.0, 'ok', 0);"
        )
        with pytest.raises(sqlite3.IntegrityError, match="one person authors at most one"):
            conn.execute(
                "INSERT INTO thesis_people VALUES "
                "('t/2', 'Lovelace, Ada Byron', 'author', 'ada', 'exact', 1.0, 'ok', 0)"
            )

        # Reviewed, and now the same insert is allowed — the trigger reads the
        # table rather than hard-coding the invariant.
        conn.execute(
            "INSERT INTO multi_thesis_authors VALUES "
            "('ada', 't/1', 'https://example.test/ada', 'reviewed'), "
            "('ada', 't/2', 'https://example.test/ada', 'reviewed')"
        )
        conn.execute(
            "INSERT INTO thesis_people VALUES "
            "('t/2', 'Lovelace, Ada Byron', 'author', 'ada', 'exact', 1.0, 'ok', 0)"
        )

        # Still refused on the SAME thesis, which the index also refused: two
        # author names on one thesis resolving to one person is a double-counted
        # student, not a multi-thesis author.
        with pytest.raises(sqlite3.IntegrityError, match="one person authors at most one"):
            conn.execute(
                "INSERT INTO thesis_people VALUES "
                "('t/2', 'Lovelace, Ada A.', 'author', 'ada', 'exact', 1.0, 'ok', 0)"
            )

        # And supervisors are exempt, exactly as the partial index was.
        conn.execute(
            "INSERT INTO thesis_people VALUES "
            "('t/1', 'Hopper, Grace', 'supervisor', 'grace', 'exact', 1.0, 'ok', 0), "
            "('t/2', 'Hopper, Grace', 'supervisor', 'grace', 'exact', 1.0, 'ok', 0)"
        )
    finally:
        conn.close()


# --------------------------------------------------------------------------
# The reviewed duplicate exclusion — one physical thesis, two deposited records
#
# The seam, and the whole argument for it: the exclusion applies to the
# front-matter list AFTER reconcile() has seen the full corpus and BEFORE any
# row is derived from it, so every thesis-keyed table is free of the handle by
# construction rather than by four separate filters. These tests assert that
# construction, not four filters — see analysis/duplicate_theses.py.
# --------------------------------------------------------------------------


def _exclusion(path, duplicate, keeper, fields=("authors", "date")):
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "duplicate_handle": duplicate,
                        "kept_handle": keeper,
                        "identical_fields": list(fields),
                        "source_url": f"https://estudogeral.uc.pt/handle/{duplicate}",
                        "evidence": "Reviewed against both OAI records: one deposit, "
                        "two handles, identical creator/date/abstracts.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_a_reviewed_duplicate_is_absent_from_every_thesis_keyed_table(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """What the seam buys. One filter, applied before any derivation, and all
    four tables come out consistent — there is no table left to forget, and so
    no orphan row pointing at a handle that is not in ``theses``."""
    _two_theses(corpus, "10316/000001", "10316/000002")
    _exclusion(dup_theses, "10316/000001", "10316/000002")

    report = build_mod.build(
        fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses
    )

    assert report["theses"] == 1
    assert report["duplicate_theses"] == {"entries": 1, "excluded_handles": 1}
    # Derived from the FILTERED list, which is why it is not 4: two theses with
    # two supervisors each, one of them dropped before the count.
    assert report["supervision_edges"] == 2

    conn = sqlite3.connect(fixture_db)
    try:
        for table in ("theses", "thesis_people", "thesis_keywords", "thesis_sets"):
            assert conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE handle = '10316/000001'"
            ).fetchone()[0] == 0, f"the excluded handle still has {table} rows"
        assert conn.execute(
            "SELECT COUNT(*) FROM theses WHERE handle = '10316/000002'"
        ).fetchone()[0] == 1, "the surviving thesis must still be written"
        # The reason the handle is gone is queryable, not only readable in git.
        assert conn.execute(
            "SELECT duplicate_handle, kept_handle FROM duplicate_theses"
        ).fetchall() == [("10316/000001", "10316/000002")]
    finally:
        conn.close()


def test_an_empty_exclusion_file_writes_both_records(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """The control, and the thing that says this instrument is additive: the
    same corpus with nothing reviewed builds exactly as it did before the file
    existed. If this ever fails, something started excluding on its own — which
    is the one behaviour the Product Owner ruled out."""
    _two_theses(corpus, "10316/000001", "10316/000002")

    report = build_mod.build(
        fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses
    )

    assert report["theses"] == 2
    assert report["duplicate_theses"] == {"entries": 0, "excluded_handles": 0}
    conn = sqlite3.connect(fixture_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM theses").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM duplicate_theses").fetchone()[0] == 0
    finally:
        conn.close()


def test_the_exclusion_is_validated_against_the_unfiltered_corpus(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """Order, asserted rather than assumed. ``validate()`` compares the
    duplicate's front matter with the survivor's, so it has to run while the
    duplicate is still in the list — a filter applied first would leave the
    verdict permanently unprovable and the check permanently passing."""
    _two_theses(corpus, "10316/000001", "10316/000002")
    # The two records disagree in a field the entry's evidence rests on.
    text = (corpus / "10316-000001.md").read_text(encoding="utf-8")
    (corpus / "10316-000001.md").write_text(
        text.replace("date: '2024-05-01'", "date: '2019-02-02'"), encoding="utf-8"
    )
    _exclusion(dup_theses, "10316/000001", "10316/000002")

    with pytest.raises(dup_mod.DuplicateThesisError, match="'date' no longer matches"):
        build_mod.build(
            fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses
        )


def test_an_exclusion_naming_a_thesis_outside_the_corpus_is_refused(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """A reviewed duplicate that went away upstream. The build stops rather
    than leaving an exclusion standing over nothing — which would hide a real
    harvest change behind an editorial decision nobody re-read."""
    _exclusion(dup_theses, "10316/000999", "10316/000001")

    with pytest.raises(dup_mod.DuplicateThesisError, match="'10316/000999' is not in this corpus"):
        build_mod.build(
            fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses
        )


def test_an_exclusion_whose_survivor_left_the_corpus_is_refused(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """The dangerous direction: with the survivor gone the entry would erase
    the thesis instead of deduplicating it, and no count downstream would say
    so. The build has to be the thing that notices."""
    _exclusion(dup_theses, "10316/000001", "10316/000999")

    with pytest.raises(dup_mod.DuplicateThesisError, match="SURVIVING thesis '10316/000999'"):
        build_mod.build(
            fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses
        )


def test_rebuilding_over_a_seed_that_still_holds_an_excluded_thesis_succeeds(
    corpus, fixture_db, aliases, full_names, externals, multi_authors, dup_theses
):
    """The ordering trap this trigger has and the author one does not: the seed
    being rebuilt may itself still carry the row the exclusion now forbids.
    ``THESIS_TABLES`` is swept before ``schema.sql`` is applied, so the stale
    row is gone before the trigger can see it — the same reason the sweep moved
    ahead of ``executescript`` for the author index."""
    _two_theses(corpus, "10316/000001", "10316/000002")
    build_mod.build(
        fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses
    )

    _exclusion(dup_theses, "10316/000001", "10316/000002")
    report = build_mod.build(
        fixture_db, corpus, aliases, full_names, externals, multi_authors, dup_theses
    )
    assert report["theses"] == 1


def test_the_trigger_refuses_an_excluded_handle_entering_theses(fixture_db):
    """The backstop, at the strength the build filter has: a reviewed-out
    record is impossible to COMMIT even when ``build()`` is bypassed entirely.
    This inserts straight into the table, as a hand-written migration or a
    future pipeline that skipped the filter would."""
    conn = sqlite3.connect(fixture_db)
    try:
        conn.executescript(
            "INSERT INTO theses (handle, slug, title, source_url) VALUES"
            " ('t/2', 't-2', 'The real one', 'https://example.test/2');"
            "INSERT INTO duplicate_theses VALUES"
            " ('t/1', 't/2', 'https://example.test/1', 'one deposit, two records');"
        )
        with pytest.raises(sqlite3.IntegrityError, match="reviewed duplicate record"):
            conn.execute(
                "INSERT INTO theses (handle, slug, title, source_url) "
                "VALUES ('t/1', 't-1', 'The duplicate', 'https://example.test/1')"
            )

        # Nothing else is touched: an unrelated thesis still inserts, and so
        # does the SURVIVOR of a reviewed pair — the trigger keys on the
        # duplicate handle, never on the entry.
        conn.execute(
            "INSERT INTO theses (handle, slug, title, source_url) "
            "VALUES ('t/3', 't-3', 'Unrelated', 'https://example.test/3')"
        )
    finally:
        conn.close()


def test_the_committed_seed_carries_the_duplicate_backstop_as_a_trigger(fixture_db):
    """The trigger ships in ``schema.sql``, so every seed built by this script
    carries it — including the committed one. Asserted against a freshly
    applied schema rather than against the seed's text, because the seed is a
    binary and a grep over it is not a test."""
    conn = sqlite3.connect(fixture_db)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' "
            "AND name = 'trg_no_excluded_thesis'"
        ).fetchone()[0] == 1
    finally:
        conn.close()
