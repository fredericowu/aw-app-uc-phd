"""v1 HTTP surface for the collaboration graph (``uc_phd_app/collab.py``).

Ranked-table-first, deliberately: ``/collab/pairs`` and the person-anchored
``/collab/people/{slug}`` are the two shapes the design notes ask for — no
raw force-directed node-link endpoint exists, because 4,242 edges over 475
nodes drawn without an anchor is a hairball, not an answer.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import collab, db

router = APIRouter()


def _validate_kind(kind: str) -> None:
    if kind not in collab.KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {collab.KINDS}, got {kind!r}")


def _caveat_for(kind: str) -> str:
    return collab.CO_PROJECT_CAVEAT if kind == "co_project" else collab.CO_SUPERVISION_CAVEAT


@router.get("/collab/summary")
async def collab_summary() -> dict:
    """Weight-distribution headline: pair counts, how many sit below the
    default floor, and the heaviest edge per kind — the check the design
    notes ask for before picking an encoding, surfaced on screen."""
    return {
        **collab.summary(),
        "default_min_weight": collab.DEFAULT_MIN_WEIGHT,
        "caveats": {"co_project": collab.CO_PROJECT_CAVEAT, "co_supervision": collab.CO_SUPERVISION_CAVEAT},
    }


@router.get("/collab/pairs")
async def collab_pairs(
    kind: str = Query(default="co_project"),
    min_weight: int | None = Query(default=None, ge=1),
    sort: str = Query(default="weight", pattern="^(weight|normalized)$"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Ranked pairs table — the default way to look at this graph. Sorted by
    raw ``weight`` unless ``sort=normalized`` is requested (co_project only;
    co_supervision has no normalised column, see collab.py)."""
    _validate_kind(kind)
    floor = min_weight if min_weight is not None else collab.DEFAULT_MIN_WEIGHT[kind]
    pairs = [p for p in collab.enriched_pairs(kind) if p["weight"] >= floor]
    if sort == "normalized" and kind == "co_project":
        pairs.sort(key=lambda p: (-p["weight_normalized"], -p["weight"], p["person_a"]))
    else:
        pairs.sort(key=lambda p: (-p["weight"], p["person_a"], p["person_b"]))
    total = len(pairs)
    page = pairs[offset : offset + limit]
    return {
        "kind": kind,
        "min_weight": floor,
        "sort": sort,
        "total": total,
        "limit": limit,
        "offset": offset,
        "pairs": page,
        "caveat": _caveat_for(kind),
        "cross_group_caveat": collab.CROSS_GROUP_CAVEAT,
    }


def _escape_like(term: str) -> str:
    """``%``/``_``/``\\`` are wildcards in LIKE — same escaping as
    ``api/projects.py``'s project-title search, applied here to person
    names."""
    for ch in ("\\", "%", "_"):
        term = term.replace(ch, "\\" + ch)
    return f"%{term}%"


@router.get("/collab/people")
async def collab_people(
    q: str | None = Query(default=None, description="Free-text search over person names"),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """Anchor picker: search people by name, or list the busiest
    collaborators (by project count) when ``q`` is omitted."""
    term = (q or "").strip()
    params: dict = {"limit": limit}
    where = ""
    if term:
        where = "WHERE pe.name LIKE :like ESCAPE '\\'"
        params["like"] = _escape_like(term)
    rows = db.rows(
        f"""
        SELECT pe.slug, pe.name, COUNT(DISTINCT pp.project_id) AS project_count
        FROM people pe LEFT JOIN project_people pp ON pp.person_slug = pe.slug
        {where}
        GROUP BY pe.slug, pe.name
        ORDER BY project_count DESC, pe.name
        LIMIT :limit
        """,
        params,
    )
    return {"people": rows}


@router.get("/collab/people/{slug}")
async def collab_person_neighbours(
    slug: str,
    kind: str = Query(default="co_project"),
    min_weight: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """One person's collaboration neighbourhood — the anchored view the
    design notes ask for instead of drawing the whole 4,242-edge graph."""
    _validate_kind(kind)
    person = db.one("SELECT slug, name FROM people WHERE slug = :slug", {"slug": slug})
    if person is None:
        raise HTTPException(status_code=404, detail=f"no person {slug!r}")
    groups = collab.person_groups().get(slug, set())
    collaborators = collab.neighbours(slug, kind, min_weight)
    return {
        "person": {"slug": person["slug"], "name": person["name"], "groups": sorted(groups)},
        "kind": kind,
        "min_weight": min_weight,
        "total": len(collaborators),
        "collaborators": collaborators[:limit],
        "caveat": _caveat_for(kind),
        "cross_group_caveat": collab.CROSS_GROUP_CAVEAT,
    }
