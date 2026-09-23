"""uc_phd_app/db.py — the read-only connection and the sql/ loader.

The loader is what keeps every figure traceable to a committed file, so its
failure modes are worth asserting directly rather than only through a route.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from uc_phd_app import db, paths

SCHEMA = Path(__file__).resolve().parent.parent / "scraper" / "schema.sql"


@pytest.fixture(autouse=True)
def clear_query_cache():
    db.load_query.cache_clear()
    yield
    db.load_query.cache_clear()


def test_every_committed_query_the_api_serves_exists_and_runs(fixture_db):
    """If someone renames a file in sql/, this fails here rather than as a
    500 from one endpoint nobody happened to open."""
    for name in (
        "coverage",
        "projects_per_group",
        "top_projects_per_group",
        "funding_breakdown",
        "budget_by_group",
        "budget_by_year",
        "start_date_timeline",
        "top_coordinators",
        "partners_breakdown",
        "partners_by_type",
        "partners_coverage",
    ):
        assert db.query(name, db_path=fixture_db) is not None


def test_load_query_reads_the_committed_file_not_a_python_literal():
    sql = db.load_query("coverage")
    assert sql == (paths.sql_dir() / "coverage.sql").read_text(encoding="utf-8")


def test_load_query_rejects_a_name_that_is_not_a_bare_query_name():
    for bad in ("../secrets", "a/b", "foo.sql", "x-y"):
        with pytest.raises(ValueError):
            db.load_query(bad)


def test_load_query_raises_for_a_query_that_does_not_exist():
    with pytest.raises(FileNotFoundError):
        db.load_query("no_such_query")


def test_connect_refuses_a_missing_database():
    with pytest.raises(db.DatabaseUnavailable):
        db.connect(paths.data_dir() / "absent.sqlite3")


def test_connections_are_read_only(fixture_db):
    conn = db.connect(fixture_db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM projects")
    finally:
        conn.close()


def test_rows_and_one_return_plain_dicts(fixture_db):
    rows = db.rows("SELECT id, title FROM projects ORDER BY id", db_path=fixture_db)
    assert rows[0] == {"id": 1, "title": "Alpha Project"}
    assert db.one("SELECT id FROM projects WHERE id = :i", {"i": 2}, fixture_db) == {"id": 2}
    assert db.one("SELECT id FROM projects WHERE id = 999", (), fixture_db) is None


def test_table_counts_covers_every_table_healthz_reports(fixture_db):
    counts = db.table_counts(fixture_db)
    assert counts["projects"] == 3
    assert counts["project_groups"] == 3
    assert counts["project_partners"] == 2
    assert counts["scrape_targets"] == 3
    assert set(counts) == {
        "projects", "project_fields_raw", "research_groups", "project_groups",
        "people", "project_people", "project_keywords", "project_partners",
        "scrape_runs", "scrape_targets",
    }


def test_funding_breakdown_collapses_fct_spelling_variants_but_not_joint_funders(tmp_path):
    """The live bug sql/funding_breakdown.sql was fixed for: FCT split across
    6+ spellings undercounted it in the Funding chart. Values naming FCT
    alongside a genuinely distinct co-funder must stay separate — merging
    those would misrepresent a joint arrangement as FCT-only."""
    db_path = tmp_path / "funding.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    fct_spellings = [
        "FCT",
        "FCT - Fundação para a Ciência e Tecnologia",
        "Fundação para a Ciência e a Tecnologia",
        "Portuguese Science Foundation",
        "FCT: PTDC/EIA-EIA/102185/2008",
    ]
    distinct_funders = ["FCT/CAPES", "FCT and DAAD", "PT Inovação"]
    conn.executemany(
        "INSERT INTO projects (id, title, title_norm, funding_raw, detail_fetched, first_seen_at) "
        "VALUES (?, ?, ?, ?, 1, '2026-01-01T00:00:00+00:00')",
        [
            (i, f"Project {i}", f"project {i}", funding)
            for i, funding in enumerate(fct_spellings + distinct_funders, start=1)
        ],
    )
    conn.commit()
    conn.close()

    breakdown = {r["funder"]: r["project_count"] for r in db.query("funding_breakdown", db_path=db_path)}
    assert breakdown["FCT"] == len(fct_spellings)
    assert breakdown["FCT/CAPES"] == 1
    assert breakdown["FCT and DAAD"] == 1
    assert breakdown["PT Inovação"] == 1
