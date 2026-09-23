"""v1 HTTP surface for one person — the researcher/collaborator profile.

**What this page can and cannot be.** ``people`` is ``(slug TEXT PRIMARY KEY,
name TEXT)`` and nothing else (``scraper/schema.sql``) — no photo, no bio, no
email, no publication count. A profile here is therefore never *who someone
is*; it is only what they are **connected to** in this dataset: the projects
they were listed on, the theses they authored or supervised, the research
groups those projects touch, and the keywords attached to both. The payload
carries ``PROFILE_CAVEAT`` saying exactly that, the same way every other
endpoint in this app carries its own honesty note, so a frontend change cannot
quietly drop it.

**Why the SQL is inline rather than a committed ``sql/*.sql`` file.** Same
rule ``api/projects.py``'s ``_LIST_SQL``/``project_detail`` follow and state:
files under ``sql/`` are fixed-result analytical queries a reader can run by
hand and get the whole table back. Everything below is keyed on one caller-
supplied slug, so a committed file would either need a hardcoded slug or
return nothing useful on its own. Do not "promote" these into ``sql/`` — that
would break the property those files exist for.

**Collaborators are deliberately absent.** ``/collab/people/{slug}`` already
answers that, and ``collab.enriched_pairs()`` recomputes all 4,242 pairs in
Python on every call. The profile header must not block on that, so the
frontend fetches the neighbourhood separately — the same split
``api/theses.py`` uses for a thesis's body.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import collab, db, theses

router = APIRouter()

#: Carried with every profile payload. The feasibility finding this feature was
#: scoped around, stated on the page rather than left implicit.
PROFILE_CAVEAT = (
    "Everything here is derived from CISUC project listings and Estudo Geral. "
    "This app holds no biographical data about a person — the people table is "
    "a slug and a display name, nothing else — so a profile can only show what "
    "someone is connected to, never who they are."
)

#: Why a project count is COUNT(DISTINCT project_id) and not COUNT(*).
PROJECT_COUNT_CAVEAT = (
    "project_count counts DISTINCT projects, not project_people rows — that "
    "table's primary key is (project_id, person_slug, role), so one person can "
    "hold both the coordinator and researcher role on the same project and "
    "would otherwise be counted twice. Roles are listed per project instead. "
    "coordinated_count is the same distinct count narrowed to projects where "
    "this person is listed as coordinator."
)

#: Why some theses a person really worked on may not appear here.
THESIS_MATCH_CAVEAT = (
    "A thesis appears here only when the offline name matcher resolved its "
    "author/supervisor name to this person at the 'exact' or 'confident' tier "
    "(uc_phd_app/theses.py's RESOLVED_TIERS). An 'ambiguous' row carries a "
    "person slug too, and is deliberately excluded: more than one real person "
    "fits that name and picking either would be a guess. Authored and "
    "supervised are kept as separate lists and never summed."
)

#: Why the two keyword lists are not one list.
KEYWORDS_CAVEAT = (
    "Project keywords come from the CISUC project pages and thesis keywords "
    "from Estudo Geral front matter — two different vocabularies, from two "
    "different sources, kept separate and labelled rather than merged into a "
    "single word cloud that would imply they are comparable."
)

#: Why a person's name may not identify them.
DUPLICATE_NAME_CAVEAT = (
    "More than one CISUC profile carries this display name. They are separate "
    "slugs and this app has no evidence about whether they are the same human "
    "— nothing here merges them, and every figure on this page is keyed on "
    "slug, not name."
)

# ``thesis_people.match_status`` tiers that mean "this is a person". Built from
# theses.RESOLVED_TIERS rather than re-listing 'exact','confident' here — a
# fourth notion of what counts as resolved is exactly what that constant exists
# to prevent.
_TIER_PARAMS = {f"tier{i}": tier for i, tier in enumerate(theses.RESOLVED_TIERS)}
_TIER_PLACEHOLDERS = ", ".join(f":{name}" for name in _TIER_PARAMS)

# The person's own CISUC page URL is STORED, not derived: project_fields_raw
# carries the href the site published next to their name on every project they
# appear on (1,870 rows, 475 distinct — exactly one per person). Reading it
# means a person whose URL the site never published simply has none, instead of
# this app inventing a link by concatenating a slug onto a hardcoded host and
# sending the reader to a 404. Matched on the '/<slug>' suffix rather than
# LIKE, so a slug can carry no wildcard meaning.
_CISUC_URL_SQL = """
SELECT href
FROM project_fields_raw
WHERE href IS NOT NULL
  AND substr(href, length(href) - length(:slug)) = '/' || :slug
LIMIT 1
"""

_SIBLING_SLUGS_SQL = """
SELECT slug, name FROM people
WHERE name = (SELECT name FROM people WHERE slug = :slug) AND slug <> :slug
ORDER BY slug
"""

# One row per (project, role) — the grain project_people actually has. Folded
# into one entry per project below, which is what makes the distinct counting
# above true by construction rather than by a COUNT(DISTINCT ...) a later edit
# could quietly turn back into COUNT(*).
_PROJECTS_SQL = """
SELECT
    p.id,
    p.title,
    p.detail_url,
    p.start_date,
    p.end_date,
    p.total_budget_amount,
    p.total_budget_currency,
    pp.role,
    pp.ordinal,
    (SELECT GROUP_CONCAT(pg.group_code, ',')
       FROM project_groups pg WHERE pg.project_id = p.id) AS group_codes
FROM project_people pp
JOIN projects p ON p.id = pp.project_id
WHERE pp.person_slug = :slug
ORDER BY p.start_date DESC, p.title, pp.role
"""

_THESES_SQL = f"""
SELECT tp.role, t.handle, t.title, t.year, t.full_text, t.source_url
FROM thesis_people tp
JOIN theses t ON t.handle = tp.handle
WHERE tp.person_slug = :slug AND tp.match_status IN ({_TIER_PLACEHOLDERS})
ORDER BY t.year DESC, t.title
"""

_PROJECT_KEYWORDS_SQL = """
SELECT k.keyword, COUNT(DISTINCT k.project_id) AS project_count
FROM project_keywords k
WHERE k.project_id IN (SELECT project_id FROM project_people WHERE person_slug = :slug)
GROUP BY k.keyword
ORDER BY project_count DESC, k.keyword
"""

_THESIS_KEYWORDS_SQL = f"""
SELECT k.keyword, COUNT(DISTINCT k.handle) AS thesis_count
FROM thesis_keywords k
WHERE k.handle IN (
    SELECT handle FROM thesis_people
    WHERE person_slug = :slug AND match_status IN ({_TIER_PLACEHOLDERS})
)
GROUP BY k.keyword
ORDER BY thesis_count DESC, k.keyword
"""


def _fold_projects(rows: list[dict]) -> list[dict]:
    """One entry per project, with every role this person holds on it.

    The (project_id, person_slug, role) primary key lets the same person be
    listed twice on one project — coordinator *and* researcher. Folding here
    is what makes ``project_count`` a distinct-project count; summing the raw
    rows instead is the documented trap (see ``collab.py`` and
    ``api/projects.py``'s own notes on it).
    """
    by_id: dict[int, dict] = {}
    for row in rows:
        entry = by_id.get(row["id"])
        if entry is None:
            codes = row["group_codes"]
            entry = by_id[row["id"]] = {
                "id": row["id"],
                "title": row["title"],
                "detail_url": row["detail_url"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "total_budget_amount": row["total_budget_amount"],
                "total_budget_currency": row["total_budget_currency"],
                "groups": sorted(codes.split(",")) if codes else [],
                "roles": [],
            }
        if row["role"] not in entry["roles"]:
            entry["roles"].append(row["role"])
    for entry in by_id.values():
        entry["roles"].sort()
    return list(by_id.values())


@router.get("/people/{slug}")
async def person_detail(slug: str) -> dict:
    """One person's profile: who they worked with is NOT here (see the module
    docstring — the frontend fetches ``/collab/people/{slug}`` separately), but
    everything else this dataset knows about them is.

    404s on an unknown slug, matching ``api/collab.py``'s person route.
    """
    person = db.one("SELECT slug, name FROM people WHERE slug = :slug", {"slug": slug})
    if person is None:
        raise HTTPException(status_code=404, detail=f"no person {slug!r}")

    url_row = db.one(_CISUC_URL_SQL, {"slug": slug})
    siblings = db.rows(_SIBLING_SLUGS_SQL, {"slug": slug})

    projects = _fold_projects(db.rows(_PROJECTS_SQL, {"slug": slug}))
    coordinated = [p for p in projects if "coordinator" in p["roles"]]

    tier_params = {"slug": slug, **_TIER_PARAMS}
    thesis_rows = db.rows(_THESES_SQL, tier_params)

    def _thesis(row: dict) -> dict:
        return {
            "handle": row["handle"],
            "title": row["title"],
            "year": row["year"],
            "full_text": bool(row["full_text"]),
            "source_url": row["source_url"],
        }

    return {
        "person": {
            "slug": person["slug"],
            "name": person["name"],
            # None, never a guessed URL, when the site published no href.
            "cisuc_url": url_row["href"] if url_row else None,
            # collab.person_groups() is already this app's "every group from
            # any project, any role" answer — reused rather than re-derived.
            # (theses.py's _person_groups asks a different, coordinator-first
            # question for a different purpose; the two are not interchangeable.)
            "groups": sorted(collab.person_groups().get(slug, set())),
            "name_siblings": siblings,
        },
        "projects": {
            "project_count": len(projects),
            "coordinated_count": len(coordinated),
            "items": projects,
            "caveat": PROJECT_COUNT_CAVEAT,
        },
        "theses": {
            # Two lists, never one number. Someone can be the author of one
            # thesis and the supervisor of nine; summing them would describe
            # neither.
            "authored": [_thesis(r) for r in thesis_rows if r["role"] == "author"],
            "supervised": [_thesis(r) for r in thesis_rows if r["role"] == "supervisor"],
            "caveat": THESIS_MATCH_CAVEAT,
        },
        "keywords": {
            "project": db.rows(_PROJECT_KEYWORDS_SQL, {"slug": slug}),
            "thesis": db.rows(_THESIS_KEYWORDS_SQL, tier_params),
            "caveat": KEYWORDS_CAVEAT,
        },
        "caveat": PROFILE_CAVEAT,
        "duplicate_name_caveat": DUPLICATE_NAME_CAVEAT if siblings else None,
    }
