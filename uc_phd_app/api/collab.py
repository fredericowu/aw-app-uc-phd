"""v1 HTTP surface for the collaboration graph (``uc_phd_app/collab.py``).

Three shapes now, not two. ``/collab/graph`` exists because the thing the
earlier note rejected was one unfiltered draw — 4,242 edges over 470 nodes
with no anchor is a hairball — and not node-link drawing as such. The floor
is what makes it an answer: at the default of 4 shared projects it is 282
edges over 91 nodes, where individual hubs read as distinguishable circles
rather than a dense core (3 shared projects, 577/132, still looked like a
blob in a real screenshot — see ``collab.GRAPH_MIN_WEIGHT``). Floor 1 still
draws the hairball, on purpose, because seeing it is a better argument for
the floor than this paragraph.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import collab, db

router = APIRouter()


def _validate_kind(kind: str) -> None:
    if kind not in collab.KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {collab.KINDS}, got {kind!r}")


def _caveat_for(kind: str) -> str:
    """co_supervision's caveat is BUILT, not a constant: it quotes how many
    supervisor names, edges and pairs the identity step dropped, and those
    numbers move with the corpus. See ``collab.co_supervision_caveat``."""
    return collab.CO_PROJECT_CAVEAT if kind == "co_project" else collab.co_supervision_caveat()


def _without_shared_ids(pair: dict) -> dict:
    """``enriched_pairs`` is one internal shape with two deliberate exposure
    decisions. ``shared_ids`` exists for the graph, whose edges need to name
    what they stand for; the ranked table is a table of PEOPLE and a 50-row
    page of it would otherwise carry ~1,400 project ids nothing renders.
    ``/collab/people/{slug}`` needs no equivalent — ``collab.neighbours``
    builds its rows key by key rather than returning pairs verbatim, so it
    never had them."""
    return {k: v for k, v in pair.items() if k != "shared_ids"}


@router.get("/collab/summary")
async def collab_summary() -> dict:
    """Weight-distribution headline: pair counts, how many sit below the
    default floor, and the heaviest edge per kind — the check the design
    notes ask for before picking an encoding, surfaced on screen."""
    return {
        **collab.summary(),
        "default_min_weight": collab.DEFAULT_MIN_WEIGHT,
        "graph_min_weight": collab.GRAPH_MIN_WEIGHT,
        "caveats": {"co_project": collab.CO_PROJECT_CAVEAT, "co_supervision": collab.co_supervision_caveat()},
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
    page = [_without_shared_ids(p) for p in pairs[offset : offset + limit]]
    return {
        "kind": kind,
        "min_weight": floor,
        "sort": sort,
        "total": total,
        "limit": limit,
        "offset": offset,
        "pairs": page,
        "caveat": _caveat_for(kind),
        "excluded": collab.excluded_for(kind),
        "cross_group_caveat": collab.CROSS_GROUP_CAVEAT,
    }


@router.get("/collab/graph")
async def collab_graph(
    kind: str = Query(default="co_project"),
    min_weight: int | None = Query(default=None, ge=1),
) -> dict:
    """Node-aggregated, unpaginated graph for one kind at one floor — the
    shape a node-link rendering needs. Not paginated: at the default floor
    this is 91 nodes / 282 edges, well under 100 KB, and half a graph is
    not a smaller graph. ``source``/``target`` rather than
    ``person_a_slug``/``person_b_slug``: this is the one endpoint in the app
    that is graph-shaped, and source/target is the node-link vocabulary
    ``d3-force``'s ``forceLink`` expects by default.

    ``edge_count`` equals ``/collab/pairs``'s ``total`` for the same
    kind+floor by construction — both filter ``weight >= floor`` over
    ``enriched_pairs(kind)`` — pinned by a test rather than left to drift.

    This is the ONE endpoint that exposes ``shared_ids`` (which projects or
    theses an edge stands for), alongside a flat ``shared_labels``
    id -> title dictionary and the ``shared_noun`` to describe them with.
    Dictionary rather than titles inlined on every edge: the same id repeats
    across many edges (1,869 edge x project references over 266 distinct
    projects at the default floor), so inlining costs ~6x the bytes."""
    _validate_kind(kind)
    floor = min_weight if min_weight is not None else collab.GRAPH_MIN_WEIGHT[kind]
    result = collab.graph(kind, floor)
    return {
        **result,
        "caveat": _caveat_for(kind),
        "excluded": collab.excluded_for(kind),
        "degree_caveat": collab.DEGREE_CAVEAT,
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
        "excluded": collab.excluded_for(kind),
        "cross_group_caveat": collab.CROSS_GROUP_CAVEAT,
    }
