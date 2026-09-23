"""v1 HTTP surface for the S1 theses, joined to CISUC research groups.

Mirrors ``api/projects.py``'s shape: each route is a thin wrapper around
``uc_phd_app/theses.py``, which owns the join and the caveats.
"""
from __future__ import annotations

from fastapi import APIRouter

from .. import db, theses

router = APIRouter()


@router.get("/theses")
async def list_theses() -> dict:
    """Every thesis: title, author, supervisor(s), year, resolved research
    group(s) (or none), whether full text was indexed, and the source URL."""
    return {
        "theses": theses.list_theses(),
        "caveat": theses.GROUP_CAVEAT,
        "attribution_note": theses.ATTRIBUTION_NOTE,
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
