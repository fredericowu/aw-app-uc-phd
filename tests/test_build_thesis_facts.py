"""analysis/build_thesis_facts.py — the offline seed builder.

Runs against a throwaway copy of the fixture database, never the committed
seed: this is the one script in the repo that writes ``cisuc.sqlite3``, and a
test that pointed it at the real file would silently rewrite shipped data.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from analysis import build_thesis_facts as build_mod
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

def test_it_writes_the_three_tables_and_reports_what_it_wrote(corpus, fixture_db, aliases, full_names, externals):
    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals)

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


def test_an_unmatched_name_is_preserved_as_a_row_with_a_null_slug(corpus, fixture_db, aliases, full_names, externals):
    """The whole reason person_slug is nullable: dropping the 14 names nobody
    can resolve would be data loss dressed up as a clean join."""
    build_mod.build(fixture_db, corpus, aliases, full_names, externals)

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


def test_one_name_resolving_to_duplicate_people_rows_writes_both(corpus, fixture_db, aliases, full_names, externals):
    """The João Bicker case: the PK has to carry person_slug or one of the two
    rows silently overwrites the other."""
    conn = sqlite3.connect(fixture_db)
    conn.execute("INSERT INTO people (slug, name) VALUES ('ada-1', 'Ada Lovelace')")
    conn.commit()
    conn.close()

    build_mod.build(fixture_db, corpus, aliases, full_names, externals)

    conn = sqlite3.connect(fixture_db)
    slugs = [
        r[0]
        for r in conn.execute(
            "SELECT person_slug FROM thesis_people WHERE name_raw = 'Lovelace, Ada' ORDER BY 1"
        )
    ]
    conn.close()
    assert slugs == ["ada", "ada-1"]


def test_rebuilding_replaces_rather_than_accumulates(corpus, fixture_db, aliases, full_names, externals):
    """The tables are a pure function of the committed corpus. An upsert would
    leave a withdrawn thesis in the seed forever."""
    build_mod.build(fixture_db, corpus, aliases, full_names, externals)
    (corpus / "10316-000001.md").unlink()
    (corpus / "manifest.json").write_text("[]", encoding="utf-8")

    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals)

    assert report["theses"] == 0
    conn = sqlite3.connect(fixture_db)
    assert conn.execute("SELECT COUNT(*) FROM thesis_people").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM thesis_keywords").fetchone()[0] == 0
    conn.close()


def test_a_manifest_that_disagrees_with_the_files_is_a_hard_failure(corpus, fixture_db, aliases, full_names, externals):
    """The glob is not the inventory. A half-failed download leaves a manifest
    entry with no .md, and trusting the glob would report a smaller corpus
    with no error at all."""
    (corpus / "manifest.json").write_text(
        json.dumps([{"handle": "10316/000001"}, {"handle": "10316/999999"}]), encoding="utf-8"
    )
    with pytest.raises(build_mod.ReconciliationError, match="10316/999999"):
        build_mod.build(fixture_db, corpus, aliases, full_names, externals)


def test_an_unlisted_md_file_is_a_hard_failure_too(corpus, fixture_db, aliases, full_names, externals):
    (corpus / "manifest.json").write_text("[]", encoding="utf-8")
    with pytest.raises(build_mod.ReconciliationError, match="unlisted"):
        build_mod.build(fixture_db, corpus, aliases, full_names, externals)


def test_a_thesis_without_a_source_url_names_itself_when_it_fails(corpus, fixture_db, aliases, full_names, externals):
    """source_url is NOT NULL in the schema; a bare sqlite3.IntegrityError
    would not say which thesis lost its provenance."""
    (corpus / "10316-000001.md").write_text(THESIS_NO_URL, encoding="utf-8")
    with pytest.raises(ValueError, match="10316/000001: no source_url"):
        build_mod.build(fixture_db, corpus, aliases, full_names, externals)


def test_it_writes_every_oai_set_the_thesis_belongs_to(corpus, fixture_db, aliases, full_names, externals):
    """Origin is many-to-many: the umbrella collection is stored next to the
    harvested community, raw, so a membership nobody planned for stays
    queryable without re-harvesting."""
    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals)
    assert report["thesis_sets"] == 2
    assert report["theses_per_harvest_set"] == {"DEI": 1, "INESCC": 0, "ISR": 0, "IT": 0}

    conn = sqlite3.connect(fixture_db)
    try:
        rows = conn.execute("SELECT handle, set_spec FROM thesis_sets ORDER BY set_spec").fetchall()
    finally:
        conn.close()
    assert rows == [("10316/000001", "col_10316_15519"), ("10316/000001", "com_10316_255")]


def test_a_rebuild_replaces_thesis_sets_rather_than_appending(corpus, fixture_db, aliases, full_names, externals):
    """thesis_sets is in THESIS_TABLES, so the full-replace delete covers it —
    without that, a second run would hit the (handle, set_spec) primary key."""
    build_mod.build(fixture_db, corpus, aliases, full_names, externals)
    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals)
    assert report["thesis_sets"] == 2


def test_a_duplicated_set_spec_is_stored_once(corpus, fixture_db, aliases, full_names, externals):
    """The primary key is (handle, set_spec); a header repeating a spec must
    not turn a provenance detail into an IntegrityError."""
    (corpus / "10316-000001.md").write_text(
        THESIS_MD.replace(
            "oai_sets:\n- com_10316_255\n", "oai_sets:\n- com_10316_255\n- com_10316_255\n"
        ),
        encoding="utf-8",
    )
    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals)
    assert report["thesis_sets"] == 2


def test_a_thesis_without_oai_sets_names_itself_when_it_fails(corpus, fixture_db, aliases, full_names, externals):
    """Same strictness as source_url, for the same reason: every OAI header
    carries set membership, so a front matter without it is a stale file —
    and writing zero rows would hide that from every grouping query."""
    (corpus / "10316-000001.md").write_text(THESIS_NO_SETS, encoding="utf-8")
    with pytest.raises(ValueError, match="10316/000001: no oai_sets"):
        build_mod.build(fixture_db, corpus, aliases, full_names, externals)


def test_front_matter_without_delimiters_raises(tmp_path):
    directory = tmp_path / "estudo_geral"
    directory.mkdir()
    (directory / "broken.md").write_text("# No front matter here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no YAML front matter"):
        build_mod.load_front_matters(directory)


def test_load_people_reads_the_people_table(fixture_db):
    conn = sqlite3.connect(fixture_db)
    try:
        assert Person("ada", "Ada Lovelace") in build_mod.load_people(conn)
    finally:
        conn.close()


def test_the_cli_prints_its_report(corpus, fixture_db, aliases, full_names, externals, capsys):
    assert build_mod.main(
        ["--db", str(fixture_db), "--estudo-geral", str(corpus),
         "--person-aliases", str(aliases),
         "--person-full-names", str(full_names),
         "--external-people", str(externals)]
    ) == 0
    assert json.loads(capsys.readouterr().out)["theses"] == 1


def test_the_committed_seed_holds_the_real_corpus():
    """The seed that actually ships. Asserts the measured shape of the real
    data — 181 theses (widened from an original 18), 242 supervisor rows, 283
    distinct names — so a rebuild that silently loses rows fails here rather
    than in the dashboard.

    The supervisor-row floor was 244 until ``person_aliases`` landed. Two of
    those rows were the SAME supervisor twice: "Araújo, Filipe" resolved to
    both ``filipe-araujo`` and ``filipius-1``, which CISUC lists separately
    and a human has since ruled one person. Collapsing them is the feature,
    so the floor moved with it — the count of distinct supervision EDGES
    (``build()``'s ``supervision_edges``, 241) did not change at all."""
    conn = sqlite3.connect(f"file:{build_mod.DEFAULT_DB}?mode=ro", uri=True)
    try:
        assert conn.execute("SELECT COUNT(*) FROM theses").fetchone()[0] == 181
        assert conn.execute(
            "SELECT COUNT(*) FROM thesis_people WHERE role = 'supervisor'"
        ).fetchone()[0] >= 242
        assert conn.execute(
            "SELECT COUNT(DISTINCT name_raw) FROM thesis_people"
        ).fetchone()[0] == 283
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
    corpus, fixture_db, aliases, full_names, externals
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

    report = build_mod.build(fixture_db, corpus, aliases, full_names, externals)
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


def test_rebuilding_over_a_seed_that_still_holds_a_false_merge_succeeds(corpus, fixture_db, aliases, full_names, externals):
    """The ordering trap: schema.sql's UNIQUE index is created by `build()`
    itself, so a rebuild had to clear the old rows BEFORE applying the schema
    or the fix could never be applied to the data it fixes."""
    conn = sqlite3.connect(fixture_db)
    try:
        conn.executescript(
            "DROP INDEX IF EXISTS idx_one_thesis_per_resolved_author;"
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

    assert build_mod.build(fixture_db, corpus, aliases, full_names, externals)["theses"] == 1


def test_the_committed_seed_resolves_no_slug_to_two_authored_theses():
    """The invariant, asserted on the file that actually ships."""
    conn = sqlite3.connect(f"file:{build_mod.DEFAULT_DB}?mode=ro", uri=True)
    try:
        assert conn.execute(
            "SELECT person_slug FROM thesis_people WHERE role = 'author' "
            "AND person_slug IS NOT NULL GROUP BY person_slug "
            "HAVING COUNT(DISTINCT handle) > 1"
        ).fetchall() == []
    finally:
        conn.close()
