"""The thesis corpus, read from the seed and joined to CISUC research groups.

Two halves that must stay apart, and did not before this module was rewritten.

**Identity is frozen.** "Which person is `Carvalho, Paulo Fernando Pereira
de`?" is answered once, offline, by ``analysis/name_match.py``, and committed
into ``thesis_people``. It used to be answered by re-parsing 18 YAML front
matters on every request against a hand-verified JSON file — fine at 18
theses, not at the 181 the corpus is growing to, and not once the advisor
view, the collaboration graph and the theme recommendation each need the same
join. Each of them now queries this one table instead of inventing a fourth
notion of who a person is.

**Groups stay live.** A matched person's research group is still re-derived
on every request from ``project_people`` / ``project_groups``, exactly as
before. That is deliberate and worth keeping verbatim: a group is a live fact
about a person's project history, not something to freeze into a thesis row.
Rebuilding the seed must never be what it takes for a new project to move
someone's group.

A name the matcher could not resolve is still a row here, carrying
``name_raw`` and its tier — never dropped, never guessed. 14 of today's 50
names are unmatched, all of them thesis authors or external co-supervisors;
``docs/thesis-attribution.md`` has the full record and the two deliberate
near-misses.
"""
from __future__ import annotations

from pathlib import Path

from . import db

#: Carried with the theses payload — the per-thesis group list is
#: many-to-many for the same reason projects are (see
#: ``api/projects.py:GROUP_MANY_TO_MANY_CAVEAT``), compounded by supervisors
#: whose own coordinator-role projects already span several groups. See
#: ``docs/thesis-attribution.md`` for the full explanation.
GROUP_CAVEAT = (
    "A thesis's research group(s) is the union of its matched author's and "
    "supervisors' own groups, so a thesis can show more than one group — "
    "these counts sum to more than 18. A name with no exact match is never "
    "guessed; see docs/thesis-attribution.md for the full record."
)

ATTRIBUTION_NOTE = (
    "Group attribution joins each thesis's author/supervisor names against "
    "the existing people/project_groups tables — Estudo Geral itself has no "
    "research-group field. The name -> person step is resolved once, offline, "
    "by a deterministic matcher (analysis/name_match.py) whose every decision "
    "carries a tier: exact, confident, ambiguous or unmatched. Ambiguous and "
    "unmatched names are shown as unattributed rather than resolved by "
    "guessing. Full record: docs/thesis-attribution.md."
)

#: Tiers that mean "this is a person". ``ambiguous`` is deliberately not one
#: of them: more than one real person fits, and picking either is the guess
#: this whole module exists to avoid.
RESOLVED_TIERS = ("exact", "confident")

_COORDINATOR_GROUPS_SQL = """
    SELECT DISTINCT pg.group_code
    FROM project_people pp JOIN project_groups pg ON pg.project_id = pp.project_id
    WHERE pp.person_slug = :slug AND pp.role = 'coordinator'
"""
_RESEARCHER_GROUPS_SQL = """
    SELECT DISTINCT pg.group_code
    FROM project_people pp JOIN project_groups pg ON pg.project_id = pp.project_id
    WHERE pp.person_slug = :slug AND pp.role = 'researcher'
"""


def _person_groups(slug: str, db_path: Path | None = None) -> set[str]:
    """A person's research group(s): their own coordinator-role projects if
    they have any (the strongest signal — see docs/thesis-attribution.md),
    else the groups of projects where they are listed as a researcher."""
    coordinator_groups = {
        r["group_code"] for r in db.rows(_COORDINATOR_GROUPS_SQL, {"slug": slug}, db_path)
    }
    if coordinator_groups:
        return coordinator_groups
    return {r["group_code"] for r in db.rows(_RESEARCHER_GROUPS_SQL, {"slug": slug}, db_path)}


def _resolve_person_rows(rows: list[dict], db_path: Path | None = None,
                          with_groups: bool = True) -> list[dict]:
    """Collapse the ``thesis_people`` rows for one (name, role) into the shape
    the dashboard renders.

    ``status`` stays "matched"/"unattributed" — the frontend's existing
    contract — and the finer ``match_status`` tier rides alongside it, so a
    later view can distinguish "nobody fits" from "two people fit" without
    this one changing.

    ``with_groups=False`` skips the per-person group lookup for callers that
    must not display a group anyway (``supervisors_for``, for the Fit screen —
    see its docstring). ``groups`` stays present and empty so the returned
    shape does not fork.
    """
    by_name: dict[str, dict] = {}
    slug_cache: dict[str, set[str]] = {}
    for row in rows:
        entry = by_name.get(row["name_raw"])
        if entry is None:
            resolved = row["match_status"] in RESOLVED_TIERS
            entry = by_name[row["name_raw"]] = {
                "name": row["name_raw"],
                "status": "matched" if resolved else "unattributed",
                "match_status": row["match_status"],
                "confidence": row["match_confidence"],
                "note": row["match_note"],
                "matched": [],
                "groups": [],
            }
        if entry["status"] != "matched" or row["person_slug"] is None:
            continue
        entry["matched"].append({"slug": row["person_slug"], "name": row["person_name"]})
        if not with_groups:
            continue
        slug = row["person_slug"]
        if slug not in slug_cache:
            slug_cache[slug] = _person_groups(slug, db_path)
        entry["groups"] = sorted(set(entry["groups"]) | slug_cache[slug])
    return list(by_name.values())


def list_theses(db_path: Path | None = None) -> list[dict]:
    """Every thesis, with its author/supervisors resolved to a CISUC person
    (or flagged unattributed) and its research group(s) joined in live."""
    people_rows = db.rows(db.load_query("thesis_people"), (), db_path)
    by_handle: dict[str, dict[str, list[dict]]] = {}
    for row in people_rows:
        by_handle.setdefault(row["handle"], {}).setdefault(row["role"], []).append(row)

    theses = []
    for thesis in db.rows(db.load_query("theses"), (), db_path):
        roles = by_handle.get(thesis["handle"], {})
        authors = _resolve_person_rows(roles.get("author", []), db_path)
        supervisors = _resolve_person_rows(roles.get("supervisor", []), db_path)
        groups: set[str] = set()
        for resolved in (*authors, *supervisors):
            groups.update(resolved["groups"])
        theses.append(
            {
                "handle": thesis["handle"],
                "title": thesis["title"],
                "source_url": thesis["source_url"],
                "year": thesis["year"],
                "rights": thesis["rights"],
                "full_text": bool(thesis["full_text"]),
                "authors": authors,
                "supervisors": supervisors,
                "groups": sorted(groups),
                "attributed": bool(groups),
            }
        )
    return theses


def supervisors_for(handles: list[str], db_path: Path | None = None) -> dict[str, list[dict]]:
    """Supervisors only, keyed by thesis handle — what the Fit screen names
    next to each matched thesis.

    Reads the same committed ``sql/thesis_people.sql`` ``list_theses`` does and
    filters in Python. At 18 theses / 50 name rows the whole table is smaller
    than the round trip to fetch part of it, and it keeps one committed query
    as the single definition of a thesis-person edge rather than a second,
    subtly-different one.

    Two deliberate narrowings against ``list_theses``:

    * **``role == 'supervisor'`` only.** A project ``coordinator`` is never an
      orientador and this app does not blur the two; ``thesis_people`` has no
      coordinator role precisely so that conflation cannot be re-introduced by
      a query. Authors are irrelevant here — the screen answers "who could
      supervise this", not "who wrote it".
    * **No research groups.** ``_resolve_person_rows`` resolves them and this
      drops them: group attribution currently yields 3.72 of 6 groups per
      thesis with 5/18 tagged all six (S7), so showing a group on this screen
      would look authoritative and mean nothing. Cut from v1 by the PO; the
      cheapest way to honour that is not to carry the field at all.

    An unresolved name keeps its row, its ``name_raw`` and its
    ``match_status`` — never dropped, never guessed. That is what the LEFT
    JOIN in the committed query exists for.
    """
    wanted = set(handles)
    by_handle: dict[str, list[dict]] = {h: [] for h in wanted}
    rows = db.rows(db.load_query("thesis_people"), (), db_path)
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        if row["handle"] in wanted and row["role"] == "supervisor":
            grouped.setdefault(row["handle"], []).append(row)
    for handle, person_rows in grouped.items():
        by_handle[handle] = [
            {
                "name": person["name"],
                "status": person["status"],
                "match_status": person["match_status"],
                "matched": person["matched"],
            }
            for person in _resolve_person_rows(person_rows, db_path, with_groups=False)
        ]
    return by_handle


def match_tiers(db_path: Path | None = None) -> dict:
    """How many distinct names landed in each matcher tier.

    Reported rather than hidden: the unmatched count is the honest measure of
    how far the identity spine reaches, and it will grow as the corpus does.
    """
    rows = db.rows(db.load_query("thesis_match_tiers"), (), db_path)
    return {row["match_status"]: row["name_count"] for row in rows}


def group_breakdown(theses: list[dict]) -> dict:
    """Per-group thesis counts (many-to-many, see ``GROUP_CAVEAT``) plus how
    many theses resolved to no group at all."""
    counts: dict[str, int] = {}
    unattributed = 0
    for thesis in theses:
        if not thesis["groups"]:
            unattributed += 1
            continue
        for code in thesis["groups"]:
            counts[code] = counts.get(code, 0) + 1
    return {"counts": counts, "unattributed": unattributed}
