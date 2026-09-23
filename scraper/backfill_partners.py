"""One-shot: (re)populate project_partners from already-stored partners_raw.

`python -m scraper.run` parses partners at scrape time (see run.py's
upsert_success), but the 261/398 projects already in the committed snapshot
were scraped before project_partners existed. Their partners_raw is already
in the database, verbatim — so this is a pure offline pass, no network, no
re-scrape: it re-reads that column and (re)writes the parsed/classified
rows. Idempotent (replace-style writes), so a rerun after changing the
classify_partner() heuristic is exactly how to pick up the new rule.

    python -m scraper.backfill_partners [path/to/cisuc.sqlite3]
"""
import sys
from pathlib import Path

from . import db
from .parse import classify_partner, split_partners

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "cisuc.sqlite3"


def backfill(conn):
    """Returns the number of projects (re)written."""
    db.apply_schema(conn)
    rows = conn.execute(
        "SELECT id, partners_raw FROM projects "
        "WHERE partners_raw IS NOT NULL AND partners_raw != ''"
    ).fetchall()
    for row in rows:
        names = split_partners(row["partners_raw"])
        partners = [(name, classify_partner(name)) for name in names]
        db.replace_project_partners(conn, row["id"], partners)
    conn.commit()
    return len(rows)


def main():
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_PATH
    conn = db.connect(str(db_path))
    try:
        updated = backfill(conn)
    finally:
        conn.close()
    print(f"backfilled project_partners for {updated} projects ({db_path})")


if __name__ == "__main__":
    main()
