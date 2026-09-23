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


def test_it_writes_the_three_tables_and_reports_what_it_wrote(corpus, fixture_db):
    report = build_mod.build(fixture_db, corpus)

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


def test_an_unmatched_name_is_preserved_as_a_row_with_a_null_slug(corpus, fixture_db):
    """The whole reason person_slug is nullable: dropping the 14 names nobody
    can resolve would be data loss dressed up as a clean join."""
    build_mod.build(fixture_db, corpus)

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


def test_one_name_resolving_to_duplicate_people_rows_writes_both(corpus, fixture_db):
    """The João Bicker case: the PK has to carry person_slug or one of the two
    rows silently overwrites the other."""
    conn = sqlite3.connect(fixture_db)
    conn.execute("INSERT INTO people (slug, name) VALUES ('ada-1', 'Ada Lovelace')")
    conn.commit()
    conn.close()

    build_mod.build(fixture_db, corpus)

    conn = sqlite3.connect(fixture_db)
    slugs = [
        r[0]
        for r in conn.execute(
            "SELECT person_slug FROM thesis_people WHERE name_raw = 'Lovelace, Ada' ORDER BY 1"
        )
    ]
    conn.close()
    assert slugs == ["ada", "ada-1"]


def test_rebuilding_replaces_rather_than_accumulates(corpus, fixture_db):
    """The tables are a pure function of the committed corpus. An upsert would
    leave a withdrawn thesis in the seed forever."""
    build_mod.build(fixture_db, corpus)
    (corpus / "10316-000001.md").unlink()
    (corpus / "manifest.json").write_text("[]", encoding="utf-8")

    report = build_mod.build(fixture_db, corpus)

    assert report["theses"] == 0
    conn = sqlite3.connect(fixture_db)
    assert conn.execute("SELECT COUNT(*) FROM thesis_people").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM thesis_keywords").fetchone()[0] == 0
    conn.close()


def test_a_manifest_that_disagrees_with_the_files_is_a_hard_failure(corpus, fixture_db):
    """The glob is not the inventory. A half-failed download leaves a manifest
    entry with no .md, and trusting the glob would report a smaller corpus
    with no error at all."""
    (corpus / "manifest.json").write_text(
        json.dumps([{"handle": "10316/000001"}, {"handle": "10316/999999"}]), encoding="utf-8"
    )
    with pytest.raises(build_mod.ReconciliationError, match="10316/999999"):
        build_mod.build(fixture_db, corpus)


def test_an_unlisted_md_file_is_a_hard_failure_too(corpus, fixture_db):
    (corpus / "manifest.json").write_text("[]", encoding="utf-8")
    with pytest.raises(build_mod.ReconciliationError, match="unlisted"):
        build_mod.build(fixture_db, corpus)


def test_a_thesis_without_a_source_url_names_itself_when_it_fails(corpus, fixture_db):
    """source_url is NOT NULL in the schema; a bare sqlite3.IntegrityError
    would not say which thesis lost its provenance."""
    (corpus / "10316-000001.md").write_text(THESIS_NO_URL, encoding="utf-8")
    with pytest.raises(ValueError, match="10316/000001: no source_url"):
        build_mod.build(fixture_db, corpus)


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


def test_the_cli_prints_its_report(corpus, fixture_db, capsys):
    assert build_mod.main(["--db", str(fixture_db), "--estudo-geral", str(corpus)]) == 0
    assert json.loads(capsys.readouterr().out)["theses"] == 1


def test_the_committed_seed_holds_the_real_corpus():
    """The seed that actually ships. Asserts the measured shape of the real
    data — 18 theses, 40 supervision edges, 50 distinct names — so a rebuild
    that silently loses rows fails here rather than in the dashboard."""
    conn = sqlite3.connect(f"file:{build_mod.DEFAULT_DB}?mode=ro", uri=True)
    try:
        assert conn.execute("SELECT COUNT(*) FROM theses").fetchone()[0] == 18
        assert conn.execute(
            "SELECT COUNT(*) FROM thesis_people WHERE role = 'supervisor'"
        ).fetchone()[0] >= 40
        assert conn.execute(
            "SELECT COUNT(DISTINCT name_raw) FROM thesis_people"
        ).fetchone()[0] == 50
        # Every thesis carries its provenance, and nothing lost its rights flag.
        assert conn.execute("SELECT COUNT(*) FROM theses WHERE source_url IS NULL").fetchone()[0] == 0
    finally:
        conn.close()
