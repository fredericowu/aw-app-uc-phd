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

import sqlite3

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
#:
#: This is the NO-EVIDENCE case and stays that way. An exact-name twin whose
#: identity nobody has ruled on is a different situation from an alias group,
#: which has evidence by construction — ``_ALIAS_GROUP_SQL`` members are
#: therefore excluded from ``name_siblings`` below, so a reviewed pair
#: graduates out of this caveat instead of carrying both at once.
DUPLICATE_NAME_CAVEAT = (
    "More than one CISUC profile carries this display name. They are separate "
    "slugs and this app has no evidence about whether they are the same human "
    "— nothing here merges them, and every figure on this page is keyed on "
    "slug, not name."
)

#: Said on the page of a person UC publishes but CISUC does not. Three things
#: a reader would otherwise have to infer from an empty page: who lists them,
#: that the empty CISUC sections below are CORRECT rather than broken, and the
#: live URL to check the identity against. A profile that looks broken reads
#: as a bug, which is this workspace's own house failure mode.
DIRECTORY_CAVEAT = (
    "This person is a University of Coimbra academic listed by {where}, not a "
    "member of CISUC. They reached this app through their unit's own staff "
    "directory (scraper/uc_directories/), which is why the CISUC sections on "
    "this page — projects, research groups, collaborators-via-projects — are "
    "empty: those are derived from CISUC project listings, this person "
    "appears on none, and showing no group is the correct answer rather than "
    "a gap. The theses below are real: a supervisor name on an Estudo Geral "
    "record resolved to this directory entry. Check it against the live "
    "listing linked above."
)

#: Said out loud whenever this profile is an aggregate of several CISUC
#: directory entries, because every figure on the page then counts something
#: the site itself splits in two — a reader comparing this project count
#: against one CISUC page would otherwise find it too high and be right to.
ALIAS_CAVEAT = (
    "CISUC's own People directory lists this person under {count} separate "
    "entries, which a human reviewed and recorded as one human in "
    "data/person_aliases.json (with the evidence). This profile is the union "
    "of all of them: projects, theses and keywords are aggregated across the "
    "group and de-duplicated, and {canonical} is the canonical slug every "
    "figure in this app is keyed on. Visiting either slug lands here."
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

# Every UC unit that lists this person, ordered so the primary listing is
# stable across rebuilds. Empty for a CISUC member, which is how the profile
# tells the two apart without a second column on `people`
# (scraper/schema.sql: directory_listings).
_DIRECTORY_SQL = """
SELECT source, unit_name, listing_url, person_url, name_as_published, role_as_published
FROM directory_listings
WHERE person_slug IN ({group})
ORDER BY source
"""

# The requested slug's canonical identity, or nothing when it already is one.
# One hop, never a loop: person_aliases.from_slug is a PRIMARY KEY and
# analysis/person_aliases.py refuses a chain (see its validate()).
_CANONICAL_SQL = "SELECT to_slug FROM person_aliases WHERE from_slug = :slug"

# Every ``people`` row CISUC publishes for this one human: the canonical row
# plus the reviewed aliases pointing at it. Ordered canonical-first so the
# group's head is the profile identity and the rest are the "also listed as".
_ALIAS_GROUP_SQL = """
SELECT p.slug, p.name, 1 AS is_canonical
FROM people p WHERE p.slug = :canonical
UNION ALL
SELECT p.slug, p.name, 0 AS is_canonical
FROM person_aliases a JOIN people p ON p.slug = a.from_slug
WHERE a.to_slug = :canonical
ORDER BY is_canonical DESC, slug
"""

# Exact-name twins, EXCLUDING this person's own alias group — a reviewed pair
# is no longer a "same name, no evidence" case, and showing it as both would
# tell a reader two contradictory things about one pair.
_SIBLING_SLUGS_SQL = """
SELECT slug, name FROM people
WHERE name = (SELECT name FROM people WHERE slug = :slug)
  AND slug NOT IN (SELECT from_slug FROM person_aliases WHERE to_slug = :canonical)
  AND slug <> :canonical
ORDER BY slug
"""

# ``person_slug IN (<the alias group>)`` everywhere a person is identified,
# rather than ``= :slug``. The group is one slug for the overwhelming majority
# of people, so this is the same query with one extra placeholder — but where
# CISUC split a human in two, it is the difference between a profile showing
# their 16 projects and a profile showing 0 of them under the other slug.
#
# The placeholder list is built from the group's SIZE, never from its contents
# (``_group_params`` below), so no slug is ever interpolated into SQL text.
#
# project_people and thesis_people are both keyed on person_slug, and a
# project/thesis reachable through two members of one group would appear
# twice — every count below is already DISTINCT on the project id / handle,
# and ``_fold_projects`` folds the project rows, so the de-duplication the
# group needs is the de-duplication these queries already did for roles.
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
FROM (SELECT DISTINCT project_id, role, ordinal FROM project_people
      WHERE person_slug IN ({group})) pp
JOIN projects p ON p.id = pp.project_id
ORDER BY p.start_date DESC, p.title, pp.role
"""

_THESES_SQL = """
SELECT DISTINCT tp.role, t.handle, t.title, t.year, t.full_text, t.source_url
FROM thesis_people tp
JOIN theses t ON t.handle = tp.handle
WHERE tp.person_slug IN ({group}) AND tp.match_status IN ({tiers})
ORDER BY t.year DESC, t.title
"""

_PROJECT_KEYWORDS_SQL = """
SELECT k.keyword, COUNT(DISTINCT k.project_id) AS project_count
FROM project_keywords k
WHERE k.project_id IN (
    SELECT project_id FROM project_people WHERE person_slug IN ({group})
)
GROUP BY k.keyword
ORDER BY project_count DESC, k.keyword
"""

_THESIS_KEYWORDS_SQL = """
SELECT k.keyword, COUNT(DISTINCT k.handle) AS thesis_count
FROM thesis_keywords k
WHERE k.handle IN (
    SELECT handle FROM thesis_people
    WHERE person_slug IN ({group}) AND match_status IN ({tiers})
)
GROUP BY k.keyword
ORDER BY thesis_count DESC, k.keyword
"""


def _group_params(slugs: list[str]) -> tuple[str, dict]:
    """``("(:g0, :g1)", {"g0": ..., "g1": ...})`` for an IN list.

    Bound parameters, generated from the group's length — a slug is caller
    input (it arrives in the URL path) and never becomes SQL text, so the
    ``:slug``-everywhere property the rest of this module has is kept even
    though the arity is now variable.
    """
    names = [f"g{i}" for i in range(len(slugs))]
    return ", ".join(f":{name}" for name in names), dict(zip(names, slugs))


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

    **A requested slug is resolved to its alias group first.** Where CISUC's
    own directory lists one human twice, asking for either slug returns the
    one canonical profile, aggregated over every entry in the group — not a
    404, and not two half-empty pages, one of which carries all the projects
    and the other all the ORCID. ``ALIAS_CAVEAT`` says so on the page: these
    figures deliberately do not match any single CISUC page.
    """
    if db.one("SELECT slug FROM people WHERE slug = :slug", {"slug": slug}) is None:
        raise HTTPException(status_code=404, detail=f"no person {slug!r}")

    alias_row = db.one(_CANONICAL_SQL, {"slug": slug})
    canonical = alias_row["to_slug"] if alias_row else slug
    group = db.rows(_ALIAS_GROUP_SQL, {"canonical": canonical})
    group_slugs = [row["slug"] for row in group]
    placeholders, group_params = _group_params(group_slugs)

    # The canonical row IS the profile identity — requesting an alias slug
    # renders the person CISUC's richer entry describes, by that entry's name.
    person = next(row for row in group if row["is_canonical"])
    aliases = [{"slug": row["slug"], "name": row["name"]} for row in group if not row["is_canonical"]]

    # Any group member's published href, canonical first: the person has one
    # CISUC page per entry, and the canonical entry is the one to send a
    # reader to. Still never a reconstructed URL — if the site published no
    # href for any of them, there is no link.
    url_row = next(
        (row for row in (db.one(_CISUC_URL_SQL, {"slug": s}) for s in group_slugs) if row),
        None,
    )
    siblings = db.rows(_SIBLING_SLUGS_SQL, {"slug": canonical, "canonical": canonical})
    person_groups = collab.person_groups()
    # A seed built before the harvest existed has no table; every person in it
    # is a CISUC person, which is the correct answer rather than a 500. Same
    # call theses.directory_listings() makes.
    try:
        listings = db.rows(_DIRECTORY_SQL.format(group=placeholders), group_params)
    except sqlite3.OperationalError:
        listings = []

    projects = _fold_projects(
        db.rows(_PROJECTS_SQL.format(group=placeholders), group_params)
    )
    coordinated = [p for p in projects if "coordinator" in p["roles"]]

    tier_params = {**group_params, **_TIER_PARAMS}
    thesis_rows = db.rows(
        _THESES_SQL.format(group=placeholders, tiers=_TIER_PLACEHOLDERS), tier_params
    )

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
            # Unioned over the group: a human whose project history CISUC split
            # across two entries belongs to the groups of both.
            "groups": sorted(set().union(*(person_groups.get(s, set()) for s in group_slugs))),
            "name_siblings": siblings,
            # Which UC unit directory publishes this person, or [] for a
            # CISUC member — the payload shape for an existing profile is
            # therefore unchanged except for one empty list.
            "directory": listings,
            # The other CISUC directory entries for this same human. Empty for
            # almost everyone; never None, so the frontend can read .length.
            "aliases": aliases,
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
            "project": db.rows(_PROJECT_KEYWORDS_SQL.format(group=placeholders), group_params),
            "thesis": db.rows(
                _THESIS_KEYWORDS_SQL.format(group=placeholders, tiers=_TIER_PLACEHOLDERS),
                tier_params,
            ),
            "caveat": KEYWORDS_CAVEAT,
        },
        "caveat": PROFILE_CAVEAT,
        "duplicate_name_caveat": DUPLICATE_NAME_CAVEAT if siblings else None,
        "alias_caveat": (
            ALIAS_CAVEAT.format(count=len(group_slugs), canonical=canonical) if aliases else None
        ),
        "directory_caveat": (
            DIRECTORY_CAVEAT.format(where=" and ".join(r["unit_name"] for r in listings))
            if listings
            else None
        ),
    }
