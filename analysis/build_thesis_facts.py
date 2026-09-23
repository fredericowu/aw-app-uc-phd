"""Build the thesis facts into the committed seed. Offline, by hand.

``python -m analysis.build_thesis_facts``

Reads ``estudo_geral/*.md`` (S1's committed front matter), reconciles it
against ``estudo_geral/manifest.json``, resolves every author and supervisor
name against the ``people`` table with ``analysis.name_match``, and writes
``theses`` / ``thesis_people`` / ``thesis_keywords`` into
``data/cisuc.sqlite3``.

Why the seed and not Postgres. Every join partner — people, project_people,
project_groups, project_partners — is already in this file, so structured
thesis facts anywhere else make every advisor or collaboration query a
cross-store join. The seed also ships for free (``uc_phd_app/seed.py``);
Postgres has no seed mechanism, and would need this rebuilt on every install.
Postgres keeps what genuinely needs it: the embeddings. If the corpus passes
~10k documents, or filtered search starts losing recall because over-fetching
``k`` no longer covers the SQLite filter, revisit that split.

Why offline. Same reason ``scraper/run.py`` is offline: this is a one-shot
whose output is reviewable in a diff. The app opens the database ``mode=ro``
and must never be the thing that writes it.

**This script does not freeze research groups.** It freezes *identity* —
name -> person. A person's group stays derived live from their project
history on every request (``uc_phd_app/theses.py``), because a group is a
live fact about a career, not a property of a thesis.
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

import yaml

from .name_match import AMBIGUOUS, CONFIDENT, EXACT, UNMATCHED, Person, match_name

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "scraper" / "schema.sql"
DEFAULT_DB = ROOT / "data" / "cisuc.sqlite3"
DEFAULT_ESTUDO_GERAL = ROOT / "estudo_geral"

ROLE_FIELDS = (("author", "authors"), ("supervisor", "supervisors"))
TIERS = (EXACT, CONFIDENT, AMBIGUOUS, UNMATCHED)


class ReconciliationError(RuntimeError):
    """The .md files and the manifest disagree about which theses exist."""


def load_front_matters(estudo_geral_dir: Path) -> list[dict]:
    """Every thesis's YAML front matter, body text skipped."""
    out = []
    for md_path in sorted(estudo_geral_dir.glob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        parts = text.split("---\n", 2)
        if len(parts) < 3:
            raise ValueError(f"{md_path}: no YAML front matter delimiters found")
        front_matter = yaml.safe_load(parts[1])
        front_matter["slug"] = md_path.stem
        out.append(front_matter)
    return out


def reconcile(front_matters: list[dict], manifest_path: Path) -> None:
    """The glob is not the inventory — ``manifest.json`` is.

    A download that half-failed leaves a manifest entry with no ``.md``, and
    the glob alone would report that as a smaller corpus with no error at all.
    Both directions are checked because both are real: a stray ``.md`` with no
    manifest row is just as wrong.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared = {row["handle"] for row in manifest}
    extracted = {fm["handle"] for fm in front_matters}
    if declared != extracted:
        raise ReconciliationError(
            f"manifest lists {len(declared)} theses, estudo_geral/*.md holds "
            f"{len(extracted)}; missing .md: {sorted(declared - extracted)}; "
            f"unlisted .md: {sorted(extracted - declared)}"
        )


def load_people(conn: sqlite3.Connection) -> list[Person]:
    return [Person(row[0], row[1]) for row in conn.execute("SELECT slug, name FROM people")]


def thesis_row(front_matter: dict) -> tuple:
    date = front_matter.get("date") or ""
    source_url = front_matter.get("source_url")
    if not source_url:
        # NOT NULL in the schema; failing here names the thesis, which a
        # bare IntegrityError from sqlite3 would not.
        raise ValueError(f"{front_matter['handle']}: no source_url — provenance is required")
    return (
        front_matter["handle"],
        front_matter["slug"],
        front_matter["title"],
        date or None,
        date[:4] or None,
        source_url,
        front_matter.get("rights"),
        1 if front_matter.get("full_text") else 0,
        front_matter.get("abstract_pt"),
        front_matter.get("abstract_en"),
    )


def people_rows(front_matter: dict, people: list[Person], cache: dict) -> list[tuple]:
    """``thesis_people`` rows for one thesis — one per resolved candidate, and
    exactly one carrying a NULL slug when nothing resolved."""
    rows = []
    for role, field in ROLE_FIELDS:
        for ordinal, name_raw in enumerate(front_matter.get(field) or []):
            if name_raw not in cache:
                cache[name_raw] = match_name(name_raw, people)
            result = cache[name_raw]
            slugs = [p.slug for p in result.people] if result.status in (EXACT, CONFIDENT) else [None]
            for slug in slugs:
                rows.append(
                    (
                        front_matter["handle"],
                        name_raw,
                        role,
                        slug,
                        result.status,
                        result.confidence,
                        result.note,
                        ordinal,
                    )
                )
    return rows


def keyword_rows(front_matter: dict) -> list[tuple]:
    return [
        (front_matter["handle"], keyword, ordinal)
        for ordinal, keyword in enumerate(front_matter.get("keywords") or [])
    ]


def build(db_path: Path, estudo_geral_dir: Path) -> dict:
    """Rebuild the three tables from scratch. Returns what it wrote."""
    front_matters = load_front_matters(estudo_geral_dir)
    reconcile(front_matters, estudo_geral_dir / "manifest.json")

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        people = load_people(conn)

        cache: dict = {}
        theses = [thesis_row(fm) for fm in front_matters]
        thesis_people: list[tuple] = []
        thesis_keywords: list[tuple] = []
        for fm in front_matters:
            thesis_people += people_rows(fm, people, cache)
            thesis_keywords += keyword_rows(fm)

        # Full replace, not upsert: the input is a committed directory, so the
        # tables are a pure function of it and a stale row from a thesis that
        # was withdrawn upstream would otherwise survive forever.
        conn.execute("DELETE FROM thesis_keywords")
        conn.execute("DELETE FROM thesis_people")
        conn.execute("DELETE FROM theses")
        conn.executemany("INSERT INTO theses VALUES (?,?,?,?,?,?,?,?,?,?)", theses)
        conn.executemany("INSERT INTO thesis_people VALUES (?,?,?,?,?,?,?,?)", thesis_people)
        conn.executemany("INSERT INTO thesis_keywords VALUES (?,?,?)", thesis_keywords)
        conn.commit()
    finally:
        conn.close()

    tiers = collections.Counter(m.status for m in cache.values())
    return {
        "theses": len(theses),
        "thesis_people_rows": len(thesis_people),
        "thesis_keywords": len(thesis_keywords),
        "supervision_edges": sum(
            1 for fm in front_matters for _ in (fm.get("supervisors") or [])
        ),
        "distinct_names": len(cache),
        "tiers": {tier: tiers.get(tier, 0) for tier in TIERS},
        "unresolved": sorted(
            name for name, m in cache.items() if m.status in (AMBIGUOUS, UNMATCHED)
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--estudo-geral", type=Path, default=DEFAULT_ESTUDO_GERAL)
    args = parser.parse_args(argv)

    report = build(args.db, args.estudo_geral)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
