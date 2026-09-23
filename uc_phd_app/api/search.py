"""v1 HTTP surface for semantic search over the Estudo Geral thesis corpus
(S3). Every route is a thin wrapper around ``uc_phd_app/store.py``, which
owns the SQL and the degraded-state probe.

Degraded states never look like "no results" — a query against a store that
isn't ``ready`` answers a typed 503 with a machine-readable reason, never an
empty ``results: []``, which is indistinguishable from a real zero-match
search (PO decision, S3).
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from .. import store as store_mod

router = APIRouter()


def _store(request: Request) -> store_mod.VectorStore:
    return request.app.state.vector_store


def _degraded(state: dict) -> None:
    raise HTTPException(status_code=503, detail={
        "error": state["state"],
        "reason": state["reason"],
    })


@router.get("/search")
async def search(request: Request, q: str, k: int = 5) -> dict:
    """Semantic search. Every result carries ``handle`` + ``source_url``;
    the embargoed thesis's results carry ``full_text: false`` so a caller can
    mark them as abstract/metadata-only rather than presenting them as if
    the full text had been searched."""
    vs = _store(request)
    state = vs.probe_state()
    if state["state"] != "ready":
        _degraded(state)
    # fastembed/ONNX embedding is synchronous CPU work — on the event loop it
    # would stall this worker's whole loop for 50-150ms per query at
    # WORKERS=5. asyncio.to_thread moves it off; no test catches this.
    return await asyncio.to_thread(vs.search, q, k)


@router.get("/index/status")
async def index_status(request: Request) -> dict:
    """What actually proves the app can search — not "the app started".
    ``pip_requires`` failures are silent (``src/apps/runtime.py``), so the
    model may simply never have been installed; this route forces a real
    load attempt instead of trusting a lazy import that hasn't happened
    yet."""
    vs = _store(request)
    try:
        await asyncio.to_thread(store_mod.load_model)
        model_loaded, model_error = True, None
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        model_loaded, model_error = False, str(exc)

    state = vs.probe_state()
    payload = {
        "model_loaded": model_loaded,
        "model_error": model_error,
        "model_name": store_mod.MODEL_NAME,
        "vector_store": state,
        "latency": vs.latency_verdict(),
    }
    if state["state"] == "ready":
        payload["stats"] = vs.stats()
    return payload
