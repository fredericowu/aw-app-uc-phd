"""Production pgvector store for the Estudo Geral thesis corpus (S3).

Two tables under the enforced ``app__aw-app-uc-phd__`` prefix (created by
``migrations/0001_create_documents_and_chunks.sql``, never here — this module
only reads/writes rows):

* ``documents`` — one row per thesis (``handle`` PK), carrying provenance
  (``source_url``), whether full text was indexed, and the embedding
  model/dim it was indexed with.
* ``chunks`` — the embedded pieces, ``UNIQUE(handle, ordinal)``.

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
``migrations/0001_create_documents_and_chunks.sql``'s header for why the rule
flips there.
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
