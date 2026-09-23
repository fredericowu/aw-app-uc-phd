"""uc_phd_app/db.py — the read-only connection and the sql/ loader.

The loader is what keeps every figure traceable to a committed file, so its
failure modes are worth asserting directly rather than only through a route.
"""
from __future__ import annotations

import sqlite3

import pytest

from uc_phd_app import db, paths


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
        "fill_rates",
        "projects_per_group",
        "top_projects_per_group",
        "funding_breakdown",
        "budget_by_group",
        "budget_by_year",
        "start_date_timeline",
        "top_coordinators",
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
    assert counts["scrape_targets"] == 3
    assert set(counts) == {
        "projects", "project_fields_raw", "research_groups", "project_groups",
        "people", "project_people", "project_keywords", "scrape_runs",
        "scrape_targets",
    }
