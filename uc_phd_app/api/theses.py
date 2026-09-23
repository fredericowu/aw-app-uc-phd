"""v1 HTTP surface for the S1 theses, joined to CISUC research groups.

Mirrors ``api/projects.py``'s shape: each route is a thin wrapper around
``uc_phd_app/theses.py``, which owns the join and the caveats.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db, theses

router = APIRouter()


@router.get("/theses")
async def list_theses() -> dict:
    """Every thesis: title, author, supervisor(s), year, resolved research
    group(s) (or none), whether full text was indexed, and the source URL.

    ``match_tiers`` reports how many distinct names the offline matcher
    resolved and how many it could not; ``attribution_tiers`` reports how
    many theses each of the two attribution signals agreed on — both
    surfaced next to the data rather than left for someone to discover by
    counting "(unattributed)" labels."""
    items = theses.list_theses()
    return {
        "theses": items,
        "caveat": theses.GROUP_CAVEAT,
        "attribution_note": theses.ATTRIBUTION_NOTE,
        "match_tiers": theses.match_tiers(),
        "attribution_tiers": theses.tier_breakdown(items),
    }


@router.get("/theses/groups")
async def theses_group_breakdown() -> dict:
    """Theses per research group, same many-to-many shape as
    ``/groups`` for projects — see ``theses.GROUP_CAVEAT``."""
    items = theses.list_theses()
    breakdown = theses.group_breakdown(items)
    group_rows = db.rows("SELECT code, name FROM research_groups ORDER BY code")
    groups = [
        {
            "code": row["code"],
            "name": row["name"],
            "thesis_count": breakdown["counts"].get(row["code"], 0),
        }
        for row in group_rows
    ]
    return {
        "groups": groups,
        "unattributed": breakdown["unattributed"],
        "total_theses": len(items),
        "caveat": theses.GROUP_CAVEAT,
    }


# ── detail (S5) ──────────────────────────────────────────────────────────
#
# Both routes below MUST stay declared after /theses/groups (a handle like
# "10316/117181" contains a slash, so {handle:path} is a greedy match that
# would otherwise swallow "groups" as a handle segment — see
# tests/test_routes.py's "ordering trap"), AND /body MUST stay declared
# BEFORE the plain {handle:path} route: {handle:path}'s regex is `.*`, so it
# greedily matches "<handle>/body" too and — being registered first — would
# swallow every body request as a detail request with a bogus handle.
# FastAPI matches routes in declaration order; verified empirically, not
# just by reading the docs.


@router.get("/theses/{handle:path}/body")
async def thesis_body(handle: str) -> dict:
    """The extracted document text, split out from the metadata route below
    because it can be uncompressed on the wire (the tunnel strips
    ``Content-Encoding``) and up to ~1.2 MB — the header must not block on
    it. ``body`` is ``null`` when the thesis exists but has no ``.md`` on
    disk (unindexed or embargoed-with-no-extraction), never a 404 — the
    thesis itself is real, only the body is absent."""
    thesis = theses.get_thesis(handle, with_body=False)
    if thesis is None:
        raise HTTPException(status_code=404, detail=f"no thesis with handle {handle!r}")
    body = theses.thesis_body(handle)
    return {
        "handle": handle,
        "full_text": thesis["full_text"],
        "body": body,
        "bytes": len(body.encode("utf-8")) if body is not None else 0,
    }


@router.get("/theses/{handle:path}")
async def thesis_detail(handle: str) -> dict:
    """One thesis's metadata + both abstracts — no body. Cheap on purpose:
    the extracted text can run past a megabyte, and this route backs the
    detail page's header, which must render before that much text has even
    been read off disk. See ``thesis_body`` above for the body itself."""
    thesis = theses.get_thesis(handle, with_body=False)
    if thesis is None:
        raise HTTPException(status_code=404, detail=f"no thesis with handle {handle!r}")
    return thesis
