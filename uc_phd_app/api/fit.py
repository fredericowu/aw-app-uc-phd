"""v1 HTTP surface for the Fit screen — match an editable interest profile
against the thesis corpus.

Three routes: read the profile, write the profile, run the match. The profile
lives in ``uc_phd_app/profile.py``; the ranking lives in
``uc_phd_app/store.py``. This module is the thin layer between them, the same
shape ``api/search.py`` has over the same store.

Degraded states never look like "no matches"
---------------------------------------------
Exactly S3's contract, and for a sharper reason here: a Fit query that returns
nothing is a *legitimate* answer (a profile can genuinely match badly), so an
empty ``results: []`` from a broken vector store would be indistinguishable
from a real result in a way it never quite is for search. Every non-``ready``
store state answers a typed 503 with a machine-readable reason instead.

What this route deliberately does NOT return
----------------------------------------------
**A percentage match score.** ``Search.jsx`` used to render ``1 - distance``
as "Match 67%" (before this decision existed — fixed to match it); wrong for
the same reason here: all 18 of these are computing PhDs, so every one of
them scores in a narrow band against any computing profile (measured: top-1
to top-5 spans 0.007 for the seeded profile). A 67%-vs-66% gap on screen
would read as precision that does not exist. The screen shows **rank out of
the matchable corpus**, **which interest matched**, and **the evidence
passage** — three things that are true at this corpus size. ``distance`` is
still in the payload for debugging; it is not for display as a score.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Body, HTTPException, Request

from .. import profile as profile_mod
from .. import store as store_mod
from .. import theses as theses_mod

router = APIRouter()

#: Default number of theses returned. The PO's acceptance floor is 5; 8 gives
#: a little room to scan without turning a matcher into a ranked leaderboard.
DEFAULT_K = 8
MAX_K = 18

#: The denominator the screen states alongside the live count. NOT derived
#: from this repo's data — the corpus here is the 18 theses S1 extracted, and
#: 181 is the DEI doctoral total measured by the corpus-widening card. Stated
#: so the screen can say what it did NOT search, which at 18/181 is most of
#: it. When the widening lands, the live count moves and this stays.
DEI_DOCTORAL_TOTAL = 181

CORPUS_NOTE = (
    "Matched against the {matchable} DEI doctoral theses extracted from Estudo "
    f"Geral (2024+), out of roughly {DEI_DOCTORAL_TOTAL} DEI doctoral theses "
    "overall. This is a matcher over what has been indexed, not a survey of "
    "the department."
)

#: Supervisors come from the ``thesis_people`` identity spine (role =
#: 'supervisor'), via the committed ``sql/thesis_people.sql`` — never from
#: re-parsing ``estudo_geral/*.md`` front matter, which would be a second,
#: conflicting notion of who a person is. ``theses.supervisors_for`` owns that
#: join; this module only renders what it returns.
SUPERVISOR_NOTE = (
    "Supervisors come from the thesis records themselves. A name the identity "
    "matcher could not resolve to a CISUC person is still shown, flagged as "
    "unresolved — never dropped and never guessed."
)


def _store(request: Request) -> store_mod.VectorStore:
    return request.app.state.vector_store


def _degraded(state: dict) -> None:
    raise HTTPException(status_code=503, detail={
        "error": state["state"],
        "reason": state["reason"],
    })


def _profile_payload() -> dict:
    data = profile_mod.load()
    return {
        "interests": data["interests"],
        # Shown on screen as context for the interests, never embedded — see
        # profile.py. The career narrative in here is precisely what drags an
        # averaged single-vector query off topic.
        "body": data["body"],
        "differs_from_seed": data["differs_from_seed"],
        "seed_interests": data["seed_interests"],
    }


@router.get("/profile")
async def get_profile() -> dict:
    """The live, editable profile, plus whether it has diverged from the
    committed baseline (so the screen can offer a reset)."""
    return _profile_payload()


@router.put("/profile")
async def put_profile(payload: dict = Body(...)) -> dict:
    """Replace the interest list (and optionally the prose body).

    Writes land via ``os.replace`` — at ``AW_WORKSPACE_WORKERS>1`` a save here
    races reads in every other worker, and a partially-written profile would
    either fail to parse or, worse, parse into a truncated interest list.
    """
    if "interests" not in payload:
        raise HTTPException(status_code=400, detail="'interests' is required")
    try:
        return profile_mod.save(payload["interests"], payload.get("body"))
    except profile_mod.ProfileError as exc:
        # A bad interest list is a user error with a fixable message, not a 500.
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/profile/reset")
async def reset_profile() -> dict:
    """Restore the committed baseline, discarding local edits."""
    profile_mod.reset_to_seed()
    return _profile_payload()


@router.get("/fit")
async def fit(request: Request, k: int = DEFAULT_K) -> dict:
    """Theses ranked against the live profile, fused max-over-interests.

    Every stage that is synchronous CPU work runs off the event loop. That
    matters more here than on ``/api/search``: this embeds ONE VECTOR PER
    INTEREST, so a 4-interest profile is 4x50-150ms of ONNX work, and on the
    loop it would stall the whole worker for most of a second per request.
    ``store.embed_facets`` caches on a hash of the interest text, so only the
    first request after an edit pays it.
    """
    k = max(1, min(k, MAX_K))
    vs = _store(request)
    state = vs.probe_state()
    if state["state"] != "ready":
        _degraded(state)
    try:
        data = profile_mod.load()
    except profile_mod.ProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await asyncio.to_thread(_match, vs, data, k)


def _match(vs: store_mod.VectorStore, data: dict, k: int) -> dict:
    """The blocking half of ``fit`` — embedding plus two queries."""
    import time

    interests = data["interests"]
    t0 = time.perf_counter()
    facets = store_mod.embed_facets(interests)
    embed_ms = round((time.perf_counter() - t0) * 1000, 1)

    matched = vs.match_theses(facets, k=k)
    coverage = matched["coverage"]
    # One pass over the committed thesis_people query for the whole result
    # set, not one lookup per thesis.
    supervisors = theses_mod.supervisors_for([r["handle"] for r in matched["results"]])
    for r in matched["results"]:
        # Which of his own interests pulled this thesis in — the evidence the
        # screen leads with, and the thing a fused score could not say.
        r["matched_interest"] = interests[r["facet_index"]]
        r["supervisors"] = supervisors.get(r["handle"], [])
    return {
        "results": matched["results"],
        "interests": interests,
        "profile_differs_from_seed": data["differs_from_seed"],
        "coverage": {
            **coverage,
            "dei_doctoral_total": DEI_DOCTORAL_TOTAL,
            # Theses that exist but carry no abstract vector rank nowhere and
            # would otherwise vanish without trace. At 18 that is visible; at
            # 181 it would not be.
            "unmatchable": coverage["theses"] - coverage["matchable"],
        },
        "corpus_note": CORPUS_NOTE.format(matchable=coverage["matchable"]),
        "supervisor_note": SUPERVISOR_NOTE,
        "embed_ms": embed_ms,
        "db_ms": matched["db_ms"],
        "evidence_ms": matched["evidence_ms"],
    }
