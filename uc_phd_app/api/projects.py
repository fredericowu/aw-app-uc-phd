"""The v1 HTTP surface: CISUC projects, as JSON.

One endpoint per committed query in ``sql/``, plus the two things a static
presentation could never do — a filterable project list and a per-project
detail view that includes the raw ``project_fields_raw`` pairs.

Nothing here rewrites a query in Python. ``db.query("coverage")`` reads
``sql/coverage.sql``; if a number looks wrong, the file that produced it is
named in the endpoint's own docstring.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import db

router = APIRouter()

#: Ranking caveat surfaced with the top-projects payload so the UI cannot
#: render the table without it. Lifted from sql/top_projects_per_group.sql's
#: own header comment — total budget is a proxy for "size/relevance", not a
#: given, and the request never specified a metric.
TOP_PROJECTS_CAVEAT = (
    "Ranked by total budget (descending) — the request never specified a "
    "ranking metric, and total budget is the most objective proxy the data "
    "offers for a project's size. It is a proxy, not a measure of quality or "
    "impact. Only projects with both a parsed budget and a synopsis are "
    "eligible, and a project belonging to several groups can appear in more "
    "than one group's top 10."
)

#: Same honesty note for every per-group figure (sql/projects_per_group.sql,
#: sql/budget_by_group.sql): group membership is many-to-many, so the columns
#: sum to more than the 400 projects.
GROUP_MANY_TO_MANY_CAVEAT = (
    "A project can belong to more than one research group, so these counts "
    "sum to more than the total number of projects — each membership is "
    "counted under every group it belongs to."
)

#: Carried with the stacked coordinators payload — see sql/top_coordinators.sql
#: for the full counting rationale.
COORDINATOR_STACK_CAVEAT = (
    "Each segment is COUNT(DISTINCT project_id) of that coordinator's own "
    "coordinated projects in that group — a project belonging to more than "
    "one group is counted under every one of them, so a bar's segments can "
    "sum to more than its own project_count (same many-to-many rule as every "
    "other per-group figure in this app). Ranking and project_count are "
    "computed before that fan-out, and every coordinator is keyed by slug, "
    "not display name — the site has people who share a name under "
    "different profiles. A project with no listed research group is counted "
    "under 'UNGROUPED'."
)


@router.get("/coverage")
async def coverage() -> dict:
    """sql/coverage.sql — did we actually get everything?"""
    rows = db.query("coverage")
    return {"coverage": rows[0] if rows else {}}


@router.get("/groups")
async def groups() -> dict:
    """sql/projects_per_group.sql — projects per research group."""
    return {"groups": db.query("projects_per_group"), "caveat": GROUP_MANY_TO_MANY_CAVEAT}


@router.get("/groups/{code}/top-projects")
async def top_projects(code: str) -> dict:
    """sql/top_projects_per_group.sql, narrowed to one group.

    The query ranks every group in one pass (a window function partitioned by
    group), so the filter happens here rather than by editing the committed
    SQL into a parameterised variant — the file stays the one a reader can run
    by hand and get the whole table back.
    """
    all_rows = db.query("top_projects_per_group")
    wanted = [r for r in all_rows if r["code"] == code]
    if not wanted:
        raise HTTPException(status_code=404, detail=f"no top projects for group {code!r}")
    return {
        "code": code,
        "name": wanted[0]["name"],
        "projects": wanted,
        "caveat": TOP_PROJECTS_CAVEAT,
    }


@router.get("/top-projects")
async def top_projects_all() -> dict:
    """sql/top_projects_per_group.sql, every group at once.

    The UI shows all six groups side by side, and one request beats six.
    """
    by_group: dict[str, dict] = {}
    for row in db.query("top_projects_per_group"):
        entry = by_group.setdefault(
            row["code"], {"code": row["code"], "name": row["name"], "projects": []}
        )
        entry["projects"].append(row)
    return {"groups": list(by_group.values()), "caveat": TOP_PROJECTS_CAVEAT}


@router.get("/funding")
async def funding() -> dict:
    """sql/funding_breakdown.sql — top funders, long tail collapsed."""
    return {"funders": db.query("funding_breakdown")}


@router.get("/budget/by-group")
async def budget_by_group() -> dict:
    """sql/budget_by_group.sql."""
    return {"groups": db.query("budget_by_group"), "caveat": GROUP_MANY_TO_MANY_CAVEAT}


@router.get("/budget/by-year")
async def budget_by_year() -> dict:
    """sql/budget_by_year.sql."""
    return {"years": db.query("budget_by_year")}


@router.get("/timeline")
async def timeline() -> dict:
    """sql/start_date_timeline.sql — project starts per year."""
    return {"years": db.query("start_date_timeline")}


@router.get("/coordinators")
async def coordinators() -> dict:
    """sql/top_coordinators.sql, pivoted from long to wide.

    The query returns one row per (coordinator, group); the UI wants one
    row per coordinator with a value per group to feed a stacked bar, so the
    pivot happens here rather than in SQLite (no PIVOT) or in JS.
    """
    by_slug: dict[str, dict] = {}
    order: list[str] = []
    group_names: dict[str, str] = {}
    for row in db.query("top_coordinators"):
        slug = row["coordinator_slug"]
        entry = by_slug.get(slug)
        if entry is None:
            entry = {
                "coordinator_slug": slug,
                "coordinator": row["coordinator"],
                "project_count": row["project_count"],
            }
            by_slug[slug] = entry
            order.append(slug)
        entry[row["group_code"]] = row["group_project_count"]
        if row["group_name"]:
            group_names[row["group_code"]] = row["group_name"]
    return {
        "coordinators": [by_slug[slug] for slug in order],
        "group_names": group_names,
        "caveat": COORDINATOR_STACK_CAVEAT,
    }


_LIST_SQL = """
SELECT
    p.id,
    p.title,
    p.detail_url,
    p.scope,
    p.funding_raw,
    p.total_budget_amount,
    p.total_budget_currency,
    p.start_date,
    p.end_date,
    p.detail_fetched,
    (SELECT GROUP_CONCAT(pg.group_code, ',')
       FROM project_groups pg WHERE pg.project_id = p.id) AS group_codes
FROM projects p
WHERE (:group IS NULL OR EXISTS (
          SELECT 1 FROM project_groups pg
          WHERE pg.project_id = p.id AND pg.group_code = :group))
  AND (:q IS NULL OR p.title LIKE :like ESCAPE '\\')
ORDER BY p.title
LIMIT :limit OFFSET :offset
"""

_COUNT_SQL = """
SELECT COUNT(*) AS total
FROM projects p
WHERE (:group IS NULL OR EXISTS (
          SELECT 1 FROM project_groups pg
          WHERE pg.project_id = p.id AND pg.group_code = :group))
  AND (:q IS NULL OR p.title LIKE :like ESCAPE '\\')
"""


def _escape_like(term: str) -> str:
    """``%``/``_``/``\\`` are wildcards in LIKE — a user searching for "50%"
    means the characters, not "anything"."""
    for ch in ("\\", "%", "_"):
        term = term.replace(ch, "\\" + ch)
    return f"%{term}%"


@router.get("/projects")
async def list_projects(
    group: str | None = Query(default=None, description="Research group code, e.g. NCS"),
    q: str | None = Query(default=None, description="Free-text search over project titles"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Paged project list. Not from a ``sql/`` file — it is a live query
    shaped by the caller's filters, which is exactly what a committed
    fixed-result file is not for."""
    term = (q or "").strip() or None
    params = {
        "group": group,
        "q": term,
        "like": _escape_like(term) if term else "",
        "limit": limit,
        "offset": offset,
    }
    total = db.one(_COUNT_SQL, params)["total"]
    items = db.rows(_LIST_SQL, params)
    for item in items:
        codes = item.pop("group_codes", None)
        item["groups"] = sorted(codes.split(",")) if codes else []
    return {"total": total, "limit": limit, "offset": offset, "projects": items}


@router.get("/projects/{project_id}")
async def project_detail(project_id: int) -> dict:
    """Everything the site publishes about one project.

    Includes the ``project_fields_raw`` pairs verbatim, in document order —
    that table is the catch-all where any label the parser never got a typed
    column for (``Keywords`` being the known case) is the only record.
    """
    project = db.one("SELECT * FROM projects WHERE id = :id", {"id": project_id})
    if project is None:
        raise HTTPException(status_code=404, detail=f"no project {project_id}")

    project["groups"] = db.rows(
        """
        SELECT rg.code, rg.name
        FROM project_groups pg JOIN research_groups rg ON rg.code = pg.group_code
        WHERE pg.project_id = :id
        ORDER BY rg.code
        """,
        {"id": project_id},
    )
    project["people"] = db.rows(
        """
        SELECT pe.slug, pe.name, pp.role, pp.ordinal
        FROM project_people pp JOIN people pe ON pe.slug = pp.person_slug
        WHERE pp.project_id = :id
        ORDER BY CASE pp.role WHEN 'coordinator' THEN 0 ELSE 1 END, pp.ordinal
        """,
        {"id": project_id},
    )
    project["keywords"] = [
        r["keyword"]
        for r in db.rows(
            "SELECT keyword FROM project_keywords WHERE project_id = :id ORDER BY ordinal",
            {"id": project_id},
        )
    ]
    project["fields_raw"] = db.rows(
        """
        SELECT label, ordinal, value_text, href
        FROM project_fields_raw WHERE project_id = :id
        ORDER BY ordinal
        """,
        {"id": project_id},
    )
    return {"project": project}
