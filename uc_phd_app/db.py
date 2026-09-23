"""Read-only access to the live SQLite database, and the ``sql/`` loader.

Every figure this app serves traces back to a committed ``.sql`` file. That is
the single best property this repo has, and it survives the move into an app
only if the queries keep living in ``sql/`` — so nothing here re-expresses a
query as a Python string literal. ``load_query()`` reads the file; the route
returns its rows.

Connections are opened per request, read-only (``mode=ro``), and closed. The
app never writes to this database — refreshing the data is
``python -m scraper.run``, a CLI run, by design (no ``net:outbound``).
"""
from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path

from . import paths


class DatabaseUnavailable(RuntimeError):
    """The live database file is missing or unreadable."""


@lru_cache(maxsize=None)
def load_query(name: str) -> str:
    """Read ``sql/<name>.sql``. Cached — these files do not change at runtime.

    ``name`` is validated rather than trusted: every caller in this app passes
    a literal, but a path separator slipping through would turn a typo into a
    file read outside ``sql/``.
    """
    if not name.replace("_", "").isalnum():
        raise ValueError(f"not a query name: {name!r}")
    path = paths.sql_dir() / f"{name}.sql"
    if not path.is_file():
        raise FileNotFoundError(f"no such query: sql/{name}.sql")
    return path.read_text(encoding="utf-8")


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """A fresh read-only connection with ``sqlite3.Row`` rows."""
    path = db_path or paths.live_db_path()
    if not path.is_file():
        raise DatabaseUnavailable(f"database not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def rows(sql: str, params: tuple | dict = (), db_path: Path | None = None) -> list[dict]:
    """Run ``sql`` and return its rows as plain dicts."""
    conn = connect(db_path)
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def query(name: str, db_path: Path | None = None) -> list[dict]:
    """Run the committed ``sql/<name>.sql`` and return its rows."""
    return rows(load_query(name), (), db_path)


def one(sql: str, params: tuple | dict = (), db_path: Path | None = None) -> dict | None:
    """First row of ``sql``, or None."""
    result = rows(sql, params, db_path)
    return result[0] if result else None


def table_counts(db_path: Path | None = None) -> dict:
    """Row counts for the tables ``/healthz`` reports on."""
    names = (
        "projects", "project_fields_raw", "research_groups", "project_groups",
        "people", "project_people", "project_keywords", "project_partners",
        "theses", "thesis_people", "thesis_keywords",
        "bib_references", "thesis_references",
        "scrape_runs", "scrape_targets",
    )
    conn = connect(db_path)
    try:
        counts = {}
        for name in names:
            counts[name] = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        return counts
    finally:
        conn.close()
