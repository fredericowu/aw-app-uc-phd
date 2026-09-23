"""v1 HTTP surface for the bibliography (``uc_phd_app/bibliography.py``).

Thin wrappers, same shape as ``api/collab.py``: the module below owns the
floor, the caveats and the SQL, and these routes own validation and paging.

Route ordering matters here for the same reason it does in ``api/theses.py``,
though less dangerously: ``/bibliography/theses`` is declared before
``/bibliography/{reference_id}``, and the path converter on the latter is
``int``, so "theses" could not be swallowed as an id even if the order were
wrong. Declared in the safe order anyway — the next route added here might not
be an int.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import bibliography

router = APIRouter()


@router.get("/bibliography/summary")
async def bibliography_summary() -> dict:
    """Headline counts, the cited-by distribution, and the match-tier split.

    The histogram is served rather than left in a design note because it is
    the entire argument for the default floor: 97% of these works are cited
    exactly once, and a reader who cannot see that has no way to know what the
    ranking is hiding."""
    return {
        **bibliography.summary(),
        "caveat": bibliography.BIBLIOGRAPHY_CAVEAT,
        "match_tier_caveat": bibliography.MATCH_TIER_CAVEAT,
    }


@router.get("/bibliography/theses")
async def bibliography_per_thesis() -> dict:
    """Per-thesis reference counts, zeros included — the coverage view.

    This is how a reader checks the caveat instead of taking it on trust: the
    theses contributing nothing are listed by name, with ``full_text``
    separating "no body text to parse" from "a body we failed to parse"."""
    return bibliography.per_thesis()


@router.get("/bibliography")
async def bibliography_references(
    min_cited_by: int | None = Query(default=None, ge=1),
    q: str | None = Query(default=None, description="Free-text over the reference string or DOI"),
    tier: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=bibliography.MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """The ranked reference table.

    Defaults to ``min_cited_by=2`` (``bibliography.DEFAULT_MIN_CITED_BY``).
    ``min_cited_by=1`` returns the full 23,316-row corpus, paged — offered
    deliberately, because a floor a caller cannot lift is a number they have
    to trust rather than check."""
    if tier is not None and tier not in bibliography.TIERS:
        raise HTTPException(
            status_code=400,
            detail=f"tier must be one of {bibliography.TIERS}, got {tier!r}",
        )
    floor = min_cited_by if min_cited_by is not None else bibliography.DEFAULT_MIN_CITED_BY
    return bibliography.references(min_cited_by=floor, q=q, tier=tier, limit=limit, offset=offset)


@router.get("/bibliography/{reference_id}")
async def bibliography_reference(reference_id: int) -> dict:
    """One work and every thesis that cites it, with each thesis's own
    wording of the citation. ``handle`` is the key the thesis detail view
    routes on, so the UI can link straight through."""
    result = bibliography.reference(reference_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"no reference with id {reference_id}")
    return result
