"""Partner <-> thesis links: the "empresas e entidades patrocinadoras" side
of Frederico's tri-partite vision, closed the honest way.

There is no partner<->thesis edge in any source. Every link here is
transitive — partner -> project (``project_partners``) -> person
(``project_people``) -> thesis (``thesis_people``) — riding the same
``person_slug`` the identity spine (commit bd0da89) already resolves theses'
authors/supervisors to. This module never asserts "this company funded this
thesis"; every row keeps both intermediate hops (the project, and the person)
so a caller can render "via <project>, through <role> <person>" — see
``CAVEAT``, which every payload using this module must carry verbatim.

**Not** the "funding entity" work from the CORDIS investigation
(card 3e45bf3b-9510-81d5-aee9-eaf0967af56a). That card asked whether a
specific company *paid for* a project — money flowing in — and was measured
at 10% coverage with inverted semantics (EU paying the company, not the
company funding the research), then explicitly CUT by the PO. This module
answers a different, unrelated question: which of the companies/institutions
CISUC already lists as ``project_partners`` happen to share a project with
someone who wrote or supervised a thesis. No new notion of "funder" is
introduced here — ``partner_type`` stays exactly the academic/industry
classification ``project_partners`` already carries (commit baaedb2).
"""
from __future__ import annotations

from pathlib import Path

from . import db

CAVEAT = (
    "Every link here is inferred, never observed: partner -> project "
    "(project_partners) -> person (project_people) -> thesis (thesis_people), "
    "joined on the same person_slug the identity spine resolves a thesis's "
    "authors/supervisors to. This is NOT \"this company funded this thesis\" "
    "— it is \"this company shares a project with someone who wrote or "
    "supervised this thesis\". Every row carries the project and the person "
    "as explicit intermediate hops, plus a confidence (the thesis-side name "
    "match's own tier) — the only uncertain step in the chain, since "
    "project_partners and project_people are both scraped facts, not "
    "name-matched guesses."
)


def list_links(db_path: Path | None = None) -> list[dict]:
    """Every partner -> thesis path, one row per (partner, project, person,
    thesis, thesis role) — see sql/partner_thesis_links.sql for the join."""
    return db.query("partner_thesis_links", db_path)


def coverage(db_path: Path | None = None) -> dict:
    """How much of Partners and Theses this link actually reaches — see
    sql/partner_thesis_coverage.sql."""
    rows = db.query("partner_thesis_coverage", db_path)
    return rows[0] if rows else {}
