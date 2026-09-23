"""Tool implementations for the ``phd_knowledge_base`` MCP server (S4).

Every tool here is a thin wrapper around ``uc_phd_app/store.py`` and
``uc_phd_app/theses.py`` — the same functions the HTTP routes
(``api/search.py``, ``api/theses.py``) call. No SQL lives here; this module
only shapes and filters what those two already return.
"""
from __future__ import annotations

from .. import store as store_mod
from .. import theses as theses_mod


class ToolError(Exception):
    """Raised by a tool implementation. ``http_handler.py`` turns this into a
    JSON-RPC tool error (``isError: true``), never an empty result — the
    degraded-store contract ``api/search.py`` already enforces over HTTP
    (S3) applies here too: a caller must never be told "no results" when the
    real answer is "the index is down"."""


def search_phd_theses(store: store_mod.VectorStore, query: str, limit: int = 5,
                       year: str | None = None, author: str | None = None) -> dict:
    """Semantic search over the thesis corpus, filtered by ``year``/
    ``author`` after the fact — ``store.search`` has no such columns to
    filter on, so this widens the candidate window when a filter is given
    (otherwise a matching thesis ranked just past ``limit`` would never be
    seen) rather than reimplementing the SQL with extra WHERE clauses."""
    state = store.probe_state()
    if state["state"] != "ready":
        raise ToolError(f"{state['state']}: {state['reason']}")
    fetch_k = limit if not (year or author) else min(max(limit * 5, 25), 100)
    outcome = store.search(query, k=fetch_k)
    index = {t["handle"]: t for t in theses_mod.list_theses()}
    results = []
    for hit in outcome["results"]:
        meta = index.get(hit["handle"])
        if meta is None:
            continue
        if year and meta.get("year") != year:
            continue
        if author and not any(author.lower() in a["name"].lower() for a in meta["authors"]):
            continue
        results.append({**hit, "authors": [a["name"] for a in meta["authors"]]})
        if len(results) >= limit:
            break
    # Passed through with .get(), not indexed directly: this tool must not
    # assume store.search()'s exact response shape beyond "results" — it is
    # a thin wrapper, not a second copy of the contract store.py owns.
    payload = {"results": results}
    for key in ("relevance", "embed_ms", "db_ms"):
        if key in outcome:
            payload[key] = outcome[key]
    return payload


def get_phd_thesis(handle: str) -> dict:
    """Full metadata, both abstracts, extracted body and ``source_url`` for
    one thesis. Raises when ``handle`` does not exist — a 404 shaped as a
    tool error, not a null/empty payload a caller could mistake for "found,
    but blank"."""
    thesis = theses_mod.get_thesis(handle)
    if thesis is None:
        raise ToolError(f"no thesis with handle {handle!r}")
    return thesis


def list_phd_theses(year: str | None = None, group: str | None = None, limit: int = 50) -> dict:
    """The manifest, no embedding — cheap enumeration of the whole corpus,
    optionally narrowed by year or research group."""
    items = theses_mod.list_theses()
    if year:
        items = [t for t in items if t["year"] == year]
    if group:
        items = [t for t in items if group in t["groups"]]
    return {"theses": items[:limit], "total": len(items)}
