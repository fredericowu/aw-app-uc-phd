"""v1 HTTP surface for partner <-> thesis links.

Mirrors ``api/theses.py``'s shape: a thin wrapper around
``uc_phd_app/partner_links.py``, which owns the join and the caveat every
payload here carries.
"""
from __future__ import annotations

from fastapi import APIRouter

from .. import partner_links

router = APIRouter()


@router.get("/partners/theses")
async def partner_thesis_links() -> dict:
    """Every inferred partner -> thesis path (see partner_links.CAVEAT for
    why this is a path, not a bare partner/thesis pair) plus how much of
    Partners and Theses the link actually reaches."""
    return {
        "links": partner_links.list_links(),
        "coverage": partner_links.coverage(),
        "caveat": partner_links.CAVEAT,
    }
