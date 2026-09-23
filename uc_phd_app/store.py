"""Production pgvector store for the Estudo Geral thesis corpus (S3).

Two tables under the enforced ``app__aw-app-uc-phd__`` prefix (created by
``migrations/0001_create_documents_and_chunks.sql``, never here — this module
only reads/writes rows):

* ``documents`` — one row per thesis (``handle`` PK), carrying provenance
  (``source_url``), whether full text was indexed, the embedding model/dim it
  was indexed with, and (``migrations/0002``) ``abstract_embedding``: ONE
  vector for the whole thesis, over title + abstracts.
* ``chunks`` — the embedded pieces, ``UNIQUE(handle, ordinal)``.

Two rankings, deliberately not one
-----------------------------------
``search()`` ranks **chunks** and backs ``/api/search``. ``match_theses()``
ranks **theses** and backs the Fit screen. They are separate because chunk
ranking cannot answer "the 5 theses closest to this profile": the corpus is
6609 chunks across 18 theses (858 down to 8, top 3 holding 29.6%), so no ``k``
over chunks guarantees 5 distinct theses and a long thesis gets ~100x more
chances than a short one. Evidence passages on the Fit screen still come from
``chunks`` — the ranking is balanced, the quoted text is still real.

Same embedding model as the ``kb`` app (``apps/kb/kb_app/kb_pg.py``) and the
P0 prototype (``estudo_geral_extractor/index.py``): ``nomic-embed-text-v1.5``
via ``fastembed`` (ONNX, no PyTorch), 768-dim, task-prefix aware.

Two callers, one set of SQL
----------------------------
``VectorStore`` is driven by anything that duck-types ``ctx.db``'s
``execute``/``execute_multi`` — which is exactly two things:

* The FastAPI routes (integrated mode) — ``plugin.py`` builds a
  ``VectorStore(ctx.db)`` at ``activate()`` and hands it to
  ``routes.build_routes(store=...)``.
* ``estudo_geral_extractor/pgvector_index.py`` (the out-of-process loader,
  run as ``python -m estudo_geral_extractor.pgvector_index`` /
  ``aw-workspace-cli uc-phd-index``) has no ``ctx`` — a CLI process is not
  inside the app's request pipeline — so it builds a ``VectorStore`` over its
  own small adapter that talks to ``src.apps.db_tables.DbTables`` directly,
  the same way the P0 prototype and every other app's CLI-side Postgres
  access already does. That adapter deliberately does NOT live in this
  module: ``src.apps.db_tables`` is only importable inside the aw-workspace
  checkout, never in this repo's own CI, and this file sits inside
  ``uc_phd_app`` — the one package this repo's 100%-coverage gate actually
  measures (``pyproject.toml``). The loader, like ``scraper/run.py`` and
  ``estudo_geral_extractor/run.py`` before it, is a one-shot CLI touching a
  live Postgres and a 520 MB ONNX model — untestable in CI for the same
  reason those two are, which is exactly why the repo keeps that class of
  code in a sibling package outside the gate instead of lowering the gate.
  This module only owns the SQL and the chunking/embedding logic that DOES
  run on every request, which is what stays coverable at 100%. This is not a
  facade bypass either way: there is no facade to go through outside the app
  runtime, and the SQL — the only thing that actually matters for Decision 8
  (the ``app__<slug>__`` prefix enforcement) — is identical, because both
  paths run it through ``_validate``.

Schema-qualification rule (the sharp edge in this file)
---------------------------------------------------------
Every query here runs through ``ctx.db``/``DbTables``, whose engine's default
``search_path`` includes ``public`` (nothing in this app's request path ever
overrides it — only ``src/apps/migrations.py`` does that, and only for its
own migration transaction). So a bare ``<=>`` is correct in every query
below. Do NOT copy that into a ``.sql`` migration file — see
``migrations/0001_create_documents_and_chunks.sql``'s header (and 0002's) for
why the rule flips there.

The one thing that *is* spelled ``public.`` here is the ``CAST(... AS
public.vector)`` on every query parameter, and that is not an exception to the
rule above — it is a cast of a bound string literal, which has to name the
type explicitly whatever ``search_path`` says. The operators (``<=>``) and
opclasses stay bare.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from . import paths

log = logging.getLogger("aw_apps.uc_phd.store")

APP_ID = "aw-app-uc-phd"
DOCUMENTS_TABLE = "app__aw-app-uc-phd__documents"
CHUNKS_TABLE = "app__aw-app-uc-phd__chunks"

VECTOR_DIM = 768
MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"

# Matches the P0 prototype and kb_pg.py's own chunk size (kb's own
# per-input embedding cap, reused here as the chunk size — see
# estudo_geral_extractor/index.py's module docstring for the reasoning).
CHUNK_CHARS = 1500
CHUNK_OVERLAP = 200

# Rows per INSERT statement — one multi-row INSERT instead of one
# transaction per chunk (~5-6k chunks across the 18-thesis corpus).
INSERT_BATCH = 100

# ``DbTables.execute`` opens its own ``engine.begin()`` per call — there is no
# multi-statement transaction across the upsert/delete/insert sequence below.
# A crash between them must never leave `documents.md_sha256` matching the
# real content while `chunks` is short or empty, or the loader's own resume
# check (`document_md_sha256(handle) == sha`) would treat that partial write
# as done and skip it forever. No real sha256 hexdigest is 64 lowercase hex
# chars *and* equal to this — see `replace_document`.
_PENDING_SHA = "pending-reembed"

_model = None


# --------------------------------------------------------------------------
# Embeddings — lazy singleton, loaded on first real use so importing this
# module (e.g. for routes.py) never pays the ONNX load cost.
# --------------------------------------------------------------------------

def model_loaded() -> bool:
    """Whether the ONNX model has actually been loaded into this process —
    the real acceptance signal (`pip_requires` failures are silent)."""
    return _model is not None


def load_model() -> None:
    """Force the model to load now, raising on failure instead of deferring
    to the first query. Used by ``/api/index/status`` and the loader CLI,
    where "did it load" is the whole point of the check.

    ``FASTEMBED_CACHE_PATH`` defaults to ``/tmp`` (see kb_pg.py, the other
    app using this same model) — a re-download of the ~520 MB model on every
    container restart. Pointed at this app's own durable data dir instead,
    same as every other on-disk state this app keeps."""
    global _model
    if _model is None:
        os.environ.setdefault("FASTEMBED_CACHE_PATH", str(paths.fastembed_cache_dir()))
        from fastembed import TextEmbedding
        _model = TextEmbedding(MODEL_NAME)


def _get_model():
    load_model()
    return _model


def embed_docs(texts: list[str]) -> list[list[float]]:
    model = _get_model()
    prefixed = ["search_document: " + t[:CHUNK_CHARS] for t in texts]
    return [[float(x) for x in v] for v in model.embed(prefixed, batch_size=8)]


def embed_query(text: str) -> list[float]:
    """Synchronous CPU work — callers on the event loop must keep this off
    it (``asyncio.to_thread`` or a plain ``def`` route), see routes.py."""
    model = _get_model()
    vecs = list(model.embed(["search_query: " + text], batch_size=1))
    return [float(x) for x in vecs[0]]


def vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8g}" for x in vec) + "]"


# -- facet embedding cache (Fit screen) -------------------------------------
# Embedding is 50-150ms of synchronous ONNX CPU work PER FACET, and the Fit
# screen sends every interest as its own query — so an uncached request pays
# that N times over. The profile only changes when someone edits it, so the
# vectors are cached keyed on a hash of the interest text itself.
#
# Keyed on content, not on mtime or a "profile version": at
# AW_WORKSPACE_WORKERS>1 each worker has its own copy of this dict and no
# cross-process invalidation channel, so an edit saved by worker A must
# invalidate worker B's cache without B being told anything. A content hash
# does that for free — B re-reads the (small) file per request, hashes it, and
# simply misses the cache. An mtime or a counter would not survive that.
_facet_cache: dict[str, list[list[float]]] = {}

#: A handful of distinct profiles is all a single-user app ever sees; the cap
#: only exists so a pathological edit loop cannot grow this without bound.
_FACET_CACHE_MAX = 8


def facet_cache_key(interests: list[str]) -> str:
    """Content hash of an interest list — the cache key, and the only thing
    that decides whether a cached vector set is still valid."""
    import hashlib

    joined = "\x00".join(interests)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def embed_facets(interests: list[str]) -> list[list[float]]:
    """One query vector per interest line, cached on the interest text.

    Synchronous CPU work on a miss — callers on the event loop must keep this
    off it (``asyncio.to_thread``), same as ``embed_query``.
    """
    key = facet_cache_key(interests)
    cached = _facet_cache.get(key)
    if cached is not None:
        return cached
    vecs = [embed_query(text) for text in interests]
    if len(_facet_cache) >= _FACET_CACHE_MAX:
        _facet_cache.pop(next(iter(_facet_cache)))
    _facet_cache[key] = vecs
    return vecs


# --------------------------------------------------------------------------
# Chunking — pure functions, unit-tested without Postgres or the model.
# --------------------------------------------------------------------------

def chunk_text(body: str) -> list[str]:
    """Fixed-width character chunks with overlap, snapped to a whitespace
    boundary so a chunk never starts or ends mid-word."""
    body = body.replace("\x00", "")  # Postgres text columns reject NUL bytes outright
    body = " ".join(body.split())
    if not body:
        return []
    chunks = []
    start = 0
    n = len(body)
    while start < n:
        end = min(start + CHUNK_CHARS, n)
        if end < n:
            cut = body.rfind(" ", start + CHUNK_CHARS // 2, end)
            if cut != -1:
                end = cut
        piece = body[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        nxt = max(end - CHUNK_OVERLAP, start + 1)
        space = body.find(" ", nxt)
        start = space + 1 if space != -1 and space < end else nxt
    return chunks


def document_content(front_matter: dict, body: str) -> str:
    """What gets chunked + embedded for one thesis.

    Every thesis has a title and PT/EN abstracts regardless of ``full_text``
    — the embargoed thesis (``full_text: false``) is metadata-only, so its
    content is exactly title + abstracts, which is still real, substantial
    text to search over. A ``full_text`` thesis gets the extracted body on
    top of that, not instead of it.
    """
    parts = [front_matter.get("title") or ""]
    for key in ("abstract_en", "abstract_pt"):
        value = front_matter.get(key)
        if value:
            parts.append(value)
    if front_matter.get("full_text") and body.strip():
        parts.append(body)
    return "\n\n".join(p for p in parts if p)


def abstract_content(front_matter: dict) -> str:
    """What the per-thesis ``abstract_embedding`` is built from: title +
    ``abstract_en`` + ``abstract_pt``, never the body.

    Deliberately the same for every thesis, embargoed or not. ``documents``
    holds one row per thesis and one vector per row, so the vectors have to be
    comparable — folding the full body in for the 17 non-embargoed theses and
    not the 18th would make its distance mean something different from
    everyone else's, which is exactly the imbalance per-thesis ranking exists
    to remove. Truncated to ``CHUNK_CHARS`` by ``embed_docs`` like every other
    embedding in this module.
    """
    parts = [front_matter.get("title") or ""]
    for key in ("abstract_en", "abstract_pt"):
        value = front_matter.get(key)
        if value:
            parts.append(value)
    return "\n\n".join(p for p in parts if p)


# --------------------------------------------------------------------------
# VectorStore — the one place every query lives.
# --------------------------------------------------------------------------

class VectorStore:
    """``db`` is anything duck-typing ``ctx.db``'s ``execute``/
    ``execute_multi`` (or ``None`` in standalone mode, where there is no
    Postgres access at all — every method degrades to "unavailable")."""

    def __init__(self, db: Any | None) -> None:
        self._db = db

    # -- state -------------------------------------------------------

    def probe_state(self) -> dict:
        """One of ``ready`` / ``missing_extension`` / ``unavailable``, with
        a human reason — the three states S3's degraded-search contract is
        built on. Never raises."""
        if self._db is None:
            return {"state": "unavailable",
                    "reason": "standalone mode: no vector store wired"}
        try:
            ext = self._db.execute(
                DOCUMENTS_TABLE,
                "SELECT 1 FROM pg_extension WHERE extname = 'vector'",
            )
        except Exception as exc:  # noqa: BLE001 - degraded state, not a crash
            return {"state": "unavailable", "reason": f"database unreachable: {exc}"}
        if not ext:
            return {"state": "missing_extension",
                    "reason": "the 'vector' extension is not installed on this Postgres"}
        try:
            present = self._db.execute(
                DOCUMENTS_TABLE,
                "SELECT to_regclass('{table}') IS NOT NULL",
            )
        except Exception as exc:  # noqa: BLE001
            return {"state": "unavailable", "reason": f"table probe failed: {exc}"}
        if not present or not present[0][0]:
            return {"state": "unavailable",
                    "reason": f"{CHUNKS_TABLE} does not exist (migration may have failed)"}
        return {"state": "ready", "reason": None}

    def stats(self) -> dict:
        rows = self._db.execute(
            CHUNKS_TABLE,
            "SELECT count(*) FROM {table}",
        )
        chunk_count = rows[0][0] if rows else 0
        docs = self._db.execute(
            DOCUMENTS_TABLE,
            "SELECT count(*) FROM {table}",
        )
        doc_count = docs[0][0] if docs else 0
        return {"documents": doc_count, "chunks": chunk_count}

    # -- indexing (loader-side) ---------------------------------------

    def document_md_sha256(self, handle: str) -> str | None:
        rows = self._db.execute(
            DOCUMENTS_TABLE,
            "SELECT md_sha256 FROM {table} WHERE handle = :h",
            {"h": handle},
        )
        return rows[0][0] if rows else None

    def replace_document(self, *, handle: str, slug: str, title: str, year: str | None,
                          source_url: str, full_text: bool, md_sha256: str,
                          chunks: list[str]) -> int:
        """Upserts the document row and replaces every chunk for ``handle``
        with freshly-embedded ones. Deleting first (rather than relying on
        ``ON CONFLICT`` alone) is what keeps a re-run idempotent when the
        new chunk count is smaller than the old one — stale tail chunks
        would otherwise survive forever. Returns the chunk count written.

        The document row is upserted with ``_PENDING_SHA`` — not the real
        ``md_sha256`` — until every chunk batch below has committed; only
        then is it stamped with the real hash. If embedding/inserting raises
        partway (a batch failure, the process getting killed), the row is
        left with a hash that can never match a real thesis's content, so
        the next ``ingest`` run's ``document_md_sha256(handle) == sha`` check
        sees a mismatch and reprocesses the document from scratch — instead
        of silently treating a document with 0 or a truncated set of chunks
        as already done forever (see ``_PENDING_SHA``'s docstring)."""
        self._db.execute(
            DOCUMENTS_TABLE,
            "INSERT INTO {table} "
            "  (handle, slug, title, year, source_url, full_text, md_sha256, "
            "   embed_model, embed_dim, indexed_at) "
            "VALUES (:handle, :slug, :title, :year, :source_url, :full_text, "
            "        :md_sha256, :embed_model, :embed_dim, now()) "
            "ON CONFLICT (handle) DO UPDATE SET "
            "  slug = EXCLUDED.slug, title = EXCLUDED.title, year = EXCLUDED.year, "
            "  source_url = EXCLUDED.source_url, full_text = EXCLUDED.full_text, "
            "  md_sha256 = EXCLUDED.md_sha256, embed_model = EXCLUDED.embed_model, "
            "  embed_dim = EXCLUDED.embed_dim, indexed_at = now()",
            {"handle": handle, "slug": slug, "title": title, "year": year,
             "source_url": source_url, "full_text": full_text, "md_sha256": _PENDING_SHA,
             "embed_model": MODEL_NAME, "embed_dim": VECTOR_DIM},
        )
        self._db.execute(
            CHUNKS_TABLE,
            "DELETE FROM {table} WHERE handle = :h",
            {"h": handle},
        )
        written = 0
        for i in range(0, len(chunks), INSERT_BATCH):
            window = chunks[i:i + INSERT_BATCH]
            vecs = embed_docs(window)
            self._insert_chunk_batch(handle, i, window, vecs)
            written += len(window)
        self._db.execute(
            DOCUMENTS_TABLE,
            "UPDATE {table} SET md_sha256 = :sha WHERE handle = :h",
            {"sha": md_sha256, "h": handle},
        )
        return written

    def _insert_chunk_batch(self, handle: str, start_ordinal: int,
                             texts: list[str], vecs: list[list[float]]) -> None:
        values, params = [], {"h": handle}
        for i, (text, vec) in enumerate(zip(texts, vecs)):
            values.append(f"(:h, :o{i}, :c{i}, CAST(:e{i} AS public.vector))")
            params |= {f"o{i}": start_ordinal + i, f"c{i}": text, f"e{i}": vec_literal(vec)}
        sql = ("INSERT INTO {table} (handle, ordinal, chunk_text, embedding) "
               "VALUES " + ", ".join(values) +
               " ON CONFLICT (handle, ordinal) DO UPDATE SET "
               "chunk_text = EXCLUDED.chunk_text, embedding = EXCLUDED.embedding")
        self._db.execute(CHUNKS_TABLE, sql, params)

    # -- per-thesis abstract embedding (loader-side) --------------------

    def needs_reindex(self, handle: str, sha: str) -> bool:
        """Whether ``ingest`` must (re)process this thesis.

        THE TRAP THIS EXISTS TO CLOSE. The loader used to resume on
        ``document_md_sha256(handle) == sha`` alone. ``migrations/0002`` adds
        ``abstract_embedding`` as a NULL column to a table whose 18 rows are
        already indexed, so every sha still matched, every thesis was skipped,
        every abstract_embedding stayed NULL — and the Fit screen answered
        "no theses matched", which is indistinguishable from a profile with
        genuinely no hits. Nothing would have logged an error.

        So "already done" now means BOTH: content unchanged *and* the
        per-thesis vector actually present.
        """
        rows = self._db.execute(
            DOCUMENTS_TABLE,
            "SELECT md_sha256, abstract_embedding IS NOT NULL FROM {table} "
            "WHERE handle = :h",
            {"h": handle},
        )
        if not rows:
            return True
        stored_sha, has_abstract = rows[0][0], bool(rows[0][1])
        return stored_sha != sha or not has_abstract

    def set_abstract_embedding(self, handle: str, vec: list[float]) -> None:
        """Write the one-vector-per-thesis embedding.

        Separate from ``replace_document`` on purpose: this must be reachable
        for a thesis whose chunks are already correct and whose content has
        not changed — the backfill case ``migrations/0002`` creates — without
        re-embedding 858 chunks to get one vector.
        """
        self._db.execute(
            DOCUMENTS_TABLE,
            "UPDATE {table} SET abstract_embedding = CAST(:e AS public.vector) "
            "WHERE handle = :h",
            {"e": vec_literal(vec), "h": handle},
        )

    def abstract_coverage(self) -> dict:
        """``{theses, matchable}`` — how many theses exist against how many
        carry an ``abstract_embedding``.

        The Fit screen states both. A thesis with no abstract gets a NULL
        vector and silently vanishes from every ranking; at 18 that is
        visible, at 181 it would not be, so the gap is reported rather than
        left for someone to notice.
        """
        rows = self._db.execute(
            DOCUMENTS_TABLE,
            "SELECT count(*), count(abstract_embedding) FROM {table}",
        )
        total, embedded = (rows[0][0], rows[0][1]) if rows else (0, 0)
        return {"theses": int(total), "matchable": int(embedded)}

    # -- thesis matching (Fit screen) ----------------------------------

    def match_theses(self, facet_vectors: list[list[float]], k: int = 5) -> dict:
        """Rank THESES against a list of interest vectors, fused by MAX
        similarity (= MIN cosine distance) over facets.

        Max, not mean. Averaging the facets back into one vector is exactly
        the failure the facet split exists to undo — it lands the query
        near-equidistant from the whole corpus (measured: top1-top5 spread
        0.022 for the averaged paragraph against 0.081 for a single facet, and
        it pushes the privacy/security-architecture thesis out of the top 10
        of 18 for a profile that names secure software architecture twice).
        Max also keeps "which interest matched" meaningful, which is the
        evidence the screen is built on — a fused score cannot say that.

        Every per-facet distance comes back and the winner is picked here
        rather than in SQL: 18 rows makes the transfer free, and a CASE ladder
        over N facets in SQL would have to be generated anyway.

        Returns ``{results, coverage, embed_ms, db_ms}``. ``results`` carry
        ``rank`` (1-based, out of ``coverage['matchable']``), the winning
        ``facet_index``, and an evidence ``snippet`` — never a percentage
        score; see ``api/fit.py``.
        """
        if not facet_vectors:  # pragma: no cover - callers validate first
            raise ValueError("match_theses needs at least one facet vector")
        t0 = time.perf_counter()
        params: dict[str, Any] = {"k": k}
        dist_cols = []
        for i, vec in enumerate(facet_vectors):
            params[f"f{i}"] = vec_literal(vec)
            dist_cols.append(f"abstract_embedding <=> CAST(:f{i} AS public.vector) AS d{i}")
        # LEAST over the per-facet distances IS the max-similarity fusion.
        least = "LEAST(" + ", ".join(f"d{i}" for i in range(len(facet_vectors))) + ")"
        rows = self._db.execute(
            DOCUMENTS_TABLE,
            "SELECT handle, title, source_url, full_text, "
            + ", ".join(f"d{i}" for i in range(len(facet_vectors)))
            + " FROM (SELECT handle, title, source_url, full_text, "
            + ", ".join(dist_cols)
            + " FROM {table} WHERE abstract_embedding IS NOT NULL) t "
            f"ORDER BY {least} LIMIT :k",
            params,
        )
        results = []
        for rank, row in enumerate(rows, start=1):
            dists = [float(x) for x in row[4:]]
            best = min(range(len(dists)), key=lambda i: dists[i])
            results.append({
                "rank": rank,
                "handle": row[0],
                "title": row[1],
                "source_url": row[2],
                "full_text": bool(row[3]),
                "facet_index": best,
                "distance": dists[best],
                "facet_distances": dists,
            })
        t1 = time.perf_counter()
        self._attach_evidence(results, facet_vectors)
        t2 = time.perf_counter()
        return {
            "results": results,
            "coverage": self.abstract_coverage(),
            "db_ms": round((t1 - t0) * 1000, 1),
            "evidence_ms": round((t2 - t1) * 1000, 1),
        }

    def _attach_evidence(self, results: list[dict], facet_vectors: list[list[float]]) -> None:
        """Best real passage per matched thesis, against the facet that won it.

        The ranking is deliberately abstract-only, so without this the screen
        would quote an abstract back at a user who has already read it. The
        passage comes from ``chunks`` — the actual indexed text — so the
        balanced ranking keeps real evidence under it.

        One query, not one per thesis: a VALUES list of (handle, winning
        vector) pairs joined LATERAL against the chunks table, which uses the
        existing ``_handle_idx``.
        """
        if not results:
            return
        params: dict[str, Any] = {}
        pairs = []
        for i, r in enumerate(results):
            params[f"h{i}"] = r["handle"]
            params[f"q{i}"] = vec_literal(facet_vectors[r["facet_index"]])
            pairs.append(f"(CAST(:h{i} AS text), CAST(:q{i} AS public.vector))")
        rows = self._db.execute(
            CHUNKS_TABLE,
            "SELECT w.handle, c.ordinal, c.chunk_text "
            "FROM (VALUES " + ", ".join(pairs) + ") AS w(handle, qv) "
            "CROSS JOIN LATERAL ("
            "  SELECT ordinal, chunk_text FROM {table} "
            "  WHERE handle = w.handle ORDER BY embedding <=> w.qv LIMIT 1"
            ") c",
            params,
        )
        by_handle = {r[0]: (r[1], r[2]) for r in rows}
        for r in results:
            found = by_handle.get(r["handle"])
            # A thesis with an abstract embedding but no chunks is possible
            # (a failed/partial ingest); it keeps its rank and simply shows no
            # passage rather than disappearing from the list.
            r["ordinal"] = found[0] if found else None
            r["snippet"] = " ".join(found[1].split())[:400] if found else None

    # -- search (route-side) -------------------------------------------

    def search(self, query_text: str, k: int = 5) -> dict:
        """Returns ``{results, embed_ms, db_ms}``. Every result carries
        ``handle`` + ``source_url`` (S3 acceptance criterion #3) and
        ``full_text`` so a caller can mark abstract-only (embargoed) hits."""
        t0 = time.perf_counter()
        qvec = vec_literal(embed_query(query_text))
        t1 = time.perf_counter()
        rows = self._db.execute_multi(
            "SELECT c.handle, d.title, d.source_url, d.full_text, c.ordinal, "
            "       c.chunk_text, c.embedding <=> CAST(:q AS public.vector) AS distance "
            f"FROM {{table:{CHUNKS_TABLE}}} c "
            f"JOIN {{table:{DOCUMENTS_TABLE}}} d ON d.handle = c.handle "
            "ORDER BY c.embedding <=> CAST(:q AS public.vector) LIMIT :k",
            [CHUNKS_TABLE, DOCUMENTS_TABLE],
            {"q": qvec, "k": k},
        )
        t2 = time.perf_counter()
        results = [
            {
                "handle": r[0],
                "title": r[1],
                "source_url": r[2],
                "full_text": bool(r[3]),
                "ordinal": r[4],
                "snippet": " ".join(r[5].split())[:300],
                "distance": float(r[6]),
            }
            for r in rows
        ]
        return {
            "results": results,
            "embed_ms": round((t1 - t0) * 1000, 1),
            "db_ms": round((t2 - t1) * 1000, 1),
        }
