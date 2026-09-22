"""Connection, schema application, and upsert helpers.

Idempotency contract: every project write is `INSERT ... ON CONFLICT
(title_norm) DO UPDATE`, and every child-table write for a project first
deletes that project's existing rows in the child table, then re-inserts
the current set. Re-running the whole scraper therefore replaces a
project's data with its current parse rather than duplicating it.
"""
import re
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def normalize_title(title):
    return re.sub(r"\s+", " ", title.strip()).casefold()


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def apply_schema(conn):
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


def upsert_project(conn, fields):
    """fields: dict of column -> value, must include 'title' and 'first_seen_at'.

    Returns the project's id.
    """
    title_norm = normalize_title(fields["title"])
    columns = dict(fields)
    columns["title_norm"] = title_norm

    existing = conn.execute(
        "SELECT id FROM projects WHERE title_norm = ?", (title_norm,)
    ).fetchone()

    if existing is None:
        cols = list(columns.keys())
        placeholders = ", ".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO projects ({', '.join(cols)}) VALUES ({placeholders})",
            [columns[c] for c in cols],
        )
        return conn.execute(
            "SELECT id FROM projects WHERE title_norm = ?", (title_norm,)
        ).fetchone()["id"]
    else:
        project_id = existing["id"]
        update_cols = [c for c in columns if c != "first_seen_at"]
        set_clause = ", ".join(f"{c} = ?" for c in update_cols)
        conn.execute(
            f"UPDATE projects SET {set_clause} WHERE id = ?",
            [columns[c] for c in update_cols] + [project_id],
        )
        return project_id


def replace_fields_raw(conn, project_id, rows):
    """rows: list of (label, ordinal, value_text, href)."""
    conn.execute("DELETE FROM project_fields_raw WHERE project_id = ?", (project_id,))
    conn.executemany(
        "INSERT INTO project_fields_raw (project_id, label, ordinal, value_text, href) "
        "VALUES (?, ?, ?, ?, ?)",
        [(project_id, label, ordinal, value_text, href) for label, ordinal, value_text, href in rows],
    )


def upsert_research_group(conn, code, name):
    conn.execute(
        "INSERT INTO research_groups (code, name) VALUES (?, ?) "
        "ON CONFLICT(code) DO UPDATE SET name = excluded.name",
        (code, name),
    )


def replace_project_groups(conn, project_id, group_codes):
    conn.execute("DELETE FROM project_groups WHERE project_id = ?", (project_id,))
    conn.executemany(
        "INSERT INTO project_groups (project_id, group_code) VALUES (?, ?)",
        [(project_id, code) for code in group_codes],
    )


def upsert_person(conn, slug, name):
    conn.execute(
        "INSERT INTO people (slug, name) VALUES (?, ?) "
        "ON CONFLICT(slug) DO UPDATE SET name = excluded.name",
        (slug, name),
    )


def replace_project_people(conn, project_id, people_rows):
    """people_rows: list of (slug, role, ordinal)."""
    conn.execute("DELETE FROM project_people WHERE project_id = ?", (project_id,))
    conn.executemany(
        "INSERT INTO project_people (project_id, person_slug, role, ordinal) "
        "VALUES (?, ?, ?, ?)",
        [(project_id, slug, role, ordinal) for slug, role, ordinal in people_rows],
    )


def replace_project_keywords(conn, project_id, keywords):
    conn.execute("DELETE FROM project_keywords WHERE project_id = ?", (project_id,))
    conn.executemany(
        "INSERT INTO project_keywords (project_id, keyword, ordinal) VALUES (?, ?, ?)",
        [(project_id, kw, i) for i, kw in enumerate(keywords)],
    )


def start_scrape_run(conn, started_at):
    cur = conn.execute(
        "INSERT INTO scrape_runs (started_at) VALUES (?)", (started_at,)
    )
    return cur.lastrowid


def finish_scrape_run(conn, run_id, finished_at, site_total_data, listing_rows, detail_ok, detail_failed, notes):
    conn.execute(
        "UPDATE scrape_runs SET finished_at=?, site_total_data=?, listing_rows=?, "
        "detail_ok=?, detail_failed=?, notes=? WHERE id=?",
        (finished_at, site_total_data, listing_rows, detail_ok, detail_failed, notes, run_id),
    )


def create_scrape_target(conn, run_id, title, url):
    cur = conn.execute(
        "INSERT INTO scrape_targets (run_id, title, url, status) VALUES (?, ?, ?, 'pending')",
        (run_id, title, url),
    )
    return cur.lastrowid


def update_scrape_target(conn, target_id, status, http_status=None, error=None):
    conn.execute(
        "UPDATE scrape_targets SET status=?, http_status=?, error=? WHERE id=?",
        (status, http_status, error, target_id),
    )
