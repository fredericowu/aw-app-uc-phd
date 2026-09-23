"""P0 prototype: chunk + embed `estudo_geral/*.md` into the workspace Postgres (pgvector).

Entrypoint: `python -m estudo_geral_extractor.index <ingest|query|bench|drop|stats>`.

This is the P0 card's prototype (`3e45bf3b-9510-81ff-aec2-fe76fd8f1e97`). It is
deliberately NOT wired into `uc_phd_app/` — no route, no MCP tool, no plugin
change. It writes to the REAL workspace Postgres in the app's real namespace,
with the real embedding model, so the numbers it reports are the baseline P1
gets to build on.

DISPOSABLE PROTOTYPE TABLE
--------------------------
The table is named with a `_proto` suffix and is not created by the app's
plugin. Workspace tables are NEVER auto-dropped (`src/apps/db_tables.py:12-22`),
so `python -m estudo_geral_extractor.index drop` is the only thing that removes
it. P1 creates its own `__chunks` table through `migrations/`; this one can go
at any time.

WHERE THIS HAS TO RUN
---------------------
Inside the **workspace container** (`aw-remote-host-workspace`). An agent runner
container is a different network namespace and cannot reach
`aw-remote-host-postgres:5432` — it fails with `Connection refused`. Run it as:

    podman exec aw-remote-host-workspace sh -c '...'

TABLE NAMING
------------
The app's table prefix is `app__aw-app-uc-phd__`, which contains hyphens, so an
unquoted identifier is a syntax error and `schema_translate_map` never rewrites
text SQL. Every statement here goes through `src.apps.db_tables.DbTables`, which
quotes and schema-qualifies via the `{table}` placeholder.

TYPE RESOLUTION
---------------
The `vector` extension lives in schema `public`; this app's tables live in
`workspace_aw`. `public.vector(768)` is spelled out rather than relying on
`search_path` being `"$user", public`.

EMBEDDINGS
----------
`nomic-ai/nomic-embed-text-v1.5` via `fastembed` (ONNX, no PyTorch), 768-dim,
task-prefix aware — deliberately identical to the `kb` app's own model
(`apps/kb/kb_app/kb_pg.py`) so the two indexes stay comparable.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

import yaml

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

APP_ID = "aw-app-uc-phd"
TABLE = "app__aw-app-uc-phd__chunks_proto"

VECTOR_DIM = 768
MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"

# 1500 chars is the `kb` app's own per-input embedding cap (`_EMBED_MAX_CHARS`).
# There it is a *truncation*; here it is the *chunk size*, so a 500 KB thesis
# keeps all of its text instead of losing everything after the first page.
CHUNK_CHARS = 1500
CHUNK_OVERLAP = 200

# Rows per INSERT statement. Each `DbTables.execute` call is its own
# transaction, so one row per call would mean ~6k transactions.
INSERT_BATCH = 100

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "estudo_geral"

_model = None


# --------------------------------------------------------------------------
# Embeddings
# --------------------------------------------------------------------------

def get_model():
    """Load the ONNX model. Raises loudly — `pip_requires` failures are silent
    in this runtime (`src/apps/runtime.py:1905-1916`), so "the script started"
    proves nothing; "the model loaded" is the only acceptance signal."""
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        # threads=4 measured on this host (12 cores, load average ~20 from the
        # rest of the workspace), 16 chunks of 1500 chars each:
        #   threads=1 -> 0.83/s   threads=2 -> 1.50/s
        #   threads=4 -> 2.14/s   threads=8 -> 1.25/s
        # More ONNX intra-op threads than the box has *spare* cores makes it
        # slower, not faster — 8 was 1.7x worse than 4 here.
        _model = TextEmbedding(MODEL_NAME, threads=int(os.environ.get("EG_EMBED_THREADS", "4")))
    return _model


def embed_docs(texts):
    """Embed for INDEXING — nomic is task-prefix aware and documents/queries
    live in different sub-spaces."""
    model = get_model()
    prefixed = ["search_document: " + t[:CHUNK_CHARS] for t in texts]
    return [[float(x) for x in v] for v in model.embed(prefixed, batch_size=8)]


def embed_query(text):
    model = get_model()
    vecs = list(model.embed(["search_query: " + text], batch_size=1))
    return [float(x) for x in vecs[0]]


def vec_literal(vec):
    """Serialise a float list to a pgvector literal: `[1.0,2.0,...]`."""
    return "[" + ",".join(f"{x:.8g}" for x in vec) + "]"


# --------------------------------------------------------------------------
# Documents -> chunks
# --------------------------------------------------------------------------

def split_front_matter(raw):
    """`---\\n<yaml>\\n---\\n\\n<body>` -> (dict, body). Returns ({}, raw) if absent."""
    if not raw.startswith("---\n"):
        return {}, raw
    end = raw.find("\n---\n", 4)
    if end == -1:
        return {}, raw
    front = yaml.safe_load(raw[4:end]) or {}
    return front, raw[end + len("\n---\n"):].lstrip("\n")


# `pypdf`'s extracted text carries stray control bytes from the source PDFs.
# A NUL is not merely ugly — Postgres `text` cannot hold one at all, and
# psycopg raises `DataError: PostgreSQL text fields cannot contain NUL (0x00)
# bytes` on insert. That surfaced 200 chunks into 10316/117599, i.e. after 13
# minutes of embedding, so it is stripped at the chunk boundary rather than
# left for the database to reject. The other C0 controls are dropped with it
# (they are noise in an embedding); the whitespace ones are left for `split()`
# below to collapse.
_CONTROL_CHARS = {c: None for c in range(0x20) if chr(c) not in " \t\n\r\v\f"}
_CONTROL_CHARS[0x7F] = None


def chunk_text(body):
    """Fixed-width character chunks with overlap, snapped to a whitespace
    boundary so a chunk never starts or ends mid-word."""
    body = " ".join(body.translate(_CONTROL_CHARS).split())
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
        # Snap the overlap window's start forward to a word boundary too —
        # `end - CHUNK_OVERLAP` lands mid-word otherwise, so every chunk after
        # the first would open with a fragment.
        nxt = max(end - CHUNK_OVERLAP, start + 1)
        space = body.find(" ", nxt)
        start = space + 1 if space != -1 and space < end else nxt
    return chunks


def load_documents():
    """Every `estudo_geral/*.md` -> (front_matter, body). Sorted for determinism."""
    docs = []
    for path in sorted(DOCS_DIR.glob("*.md")):
        front, body = split_front_matter(path.read_text(encoding="utf-8"))
        if not front.get("handle"):
            print(f"  ! {path.name}: no handle in front matter, skipped", flush=True)
            continue
        docs.append((path, front, body))
    return docs


# --------------------------------------------------------------------------
# Postgres (through the app-tables facade — never raw table names)
# --------------------------------------------------------------------------

def db():
    from src.apps.db_tables import DbTables
    return DbTables()


def qualified_table():
    """The facade's own prefix check + quoting + schema qualification, for the
    few statements `DbTables.execute` cannot carry (see `cmd_stats`). Still
    never hand-spelled: `app__aw-app-uc-phd__` has hyphens in it."""
    from src.apps.db_tables import DbTables, _validate
    _validate(APP_ID, TABLE)
    return DbTables()._qualified(TABLE)


def create_table():
    """`vector` is qualified `public.vector` on purpose (the extension lives in
    `public`, the table in `workspace_aw`)."""
    db().create(APP_ID, TABLE, f"""
        id          bigserial PRIMARY KEY,
        handle      text NOT NULL,
        title       text NOT NULL,
        source_url  text NOT NULL,
        doc_date    text,
        ord         integer NOT NULL,
        chunk_text  text NOT NULL,
        embedding   public.vector({VECTOR_DIM}) NOT NULL,
        UNIQUE (handle, ord)
    """)
    db().execute(APP_ID, TABLE, (
        "CREATE INDEX IF NOT EXISTS chunks_proto_embedding_hnsw "
        "ON {table} USING hnsw (embedding public.vector_cosine_ops)"
    ))
    db().execute(APP_ID, TABLE,
                 "CREATE INDEX IF NOT EXISTS chunks_proto_handle ON {table} (handle)")


def insert_batch(rows):
    """One multi-row INSERT. `rows` = list of (handle, title, url, date, ord, text, vec)."""
    values, params = [], {}
    for i, (handle, title, url, date, ord_, text, vec) in enumerate(rows):
        values.append(
            f"(:h{i}, :t{i}, :u{i}, :d{i}, :o{i}, :c{i}, CAST(:e{i} AS public.vector))")
        params |= {f"h{i}": handle, f"t{i}": title, f"u{i}": url, f"d{i}": date,
                   f"o{i}": ord_, f"c{i}": text, f"e{i}": vec_literal(vec)}
    sql = ("INSERT INTO {table} (handle, title, source_url, doc_date, ord, chunk_text, embedding) "
           "VALUES " + ", ".join(values) + " ON CONFLICT (handle, ord) DO NOTHING")
    db().execute(APP_ID, TABLE, sql, params)


def ingested_counts():
    """handle -> chunk count already in the table, so a re-run resumes instead
    of re-embedding an hour of work. `ON CONFLICT DO NOTHING` protects the
    *insert*; this protects the *embedding*, which is where the time goes."""
    rows = db().execute(APP_ID, TABLE,
                        "SELECT handle, count(*) FROM {table} GROUP BY handle")
    return {r[0]: r[1] for r in rows}


def search(text, k=5):
    """Returns (rows, embed_seconds, db_seconds)."""
    t0 = time.perf_counter()
    qvec = vec_literal(embed_query(text))
    t1 = time.perf_counter()
    rows = db().execute(APP_ID, TABLE, (
        "SELECT handle, title, source_url, ord, chunk_text, "
        "       embedding <=> CAST(:q AS public.vector) AS distance "
        "FROM {table} ORDER BY embedding <=> CAST(:q AS public.vector) LIMIT :k"
    ), {"q": qvec, "k": k})
    t2 = time.perf_counter()
    return rows, t1 - t0, t2 - t1


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_ingest(args):
    print(f"model: {MODEL_NAME} ({VECTOR_DIM}-dim)", flush=True)
    t_model = time.perf_counter()
    get_model()
    print(f"model loaded in {time.perf_counter() - t_model:.1f}s", flush=True)

    create_table()
    print(f"table ready: {TABLE}", flush=True)

    docs = load_documents()
    print(f"documents: {len(docs)}", flush=True)
    already = {} if args.reembed else ingested_counts()

    total_chunks = 0
    embedded_chunks = 0   # excludes resumed/skipped docs, so the rate is honest
    total_embed_s = 0.0
    total_db_s = 0.0
    per_doc = []
    t_all = time.perf_counter()

    for path, front, body in docs:
        chunks = chunk_text(body)
        handle = front["handle"]
        title = front.get("title") or handle
        url = front["source_url"]
        date = str(front.get("date") or "")
        if not chunks:
            print(f"  {handle}: 0 chunks (no body — full_text={front.get('full_text')})",
                  flush=True)
            per_doc.append({"handle": handle, "chunks": 0})
            continue
        if already.get(handle) == len(chunks):
            print(f"  {handle}: {len(chunks):5d} chunks already ingested, skipped", flush=True)
            total_chunks += len(chunks)
            per_doc.append({"handle": handle, "chunks": len(chunks), "skipped": True})
            continue

        t_doc = time.perf_counter()
        doc_embed_s = 0.0
        doc_db_s = 0.0
        for i in range(0, len(chunks), INSERT_BATCH):
            window = chunks[i:i + INSERT_BATCH]
            t0 = time.perf_counter()
            vecs = embed_docs(window)
            t1 = time.perf_counter()
            insert_batch([(handle, title, url, date, i + j, window[j], vecs[j])
                          for j in range(len(window))])
            t2 = time.perf_counter()
            doc_embed_s += t1 - t0
            doc_db_s += t2 - t1

        total_chunks += len(chunks)
        embedded_chunks += len(chunks)
        total_embed_s += doc_embed_s
        total_db_s += doc_db_s
        per_doc.append({"handle": handle, "chunks": len(chunks),
                        "embed_s": round(doc_embed_s, 2)})
        print(f"  {handle}: {len(chunks):5d} chunks  "
              f"embed {doc_embed_s:7.1f}s  insert {doc_db_s:5.1f}s  "
              f"({time.perf_counter() - t_doc:.1f}s total)", flush=True)

    wall = time.perf_counter() - t_all
    rate = embedded_chunks / total_embed_s if total_embed_s else 0
    print(f"\nINGEST DONE  chunks={total_chunks} (embedded this run: {embedded_chunks})  "
          f"wall={wall:.1f}s  embed={total_embed_s:.1f}s  insert={total_db_s:.1f}s  "
          f"rate={rate:.1f} chunks/s", flush=True)
    if args.report:
        Path(args.report).write_text(json.dumps({
            "chunks": total_chunks, "embedded_this_run": embedded_chunks,
            "documents": len(docs), "threads": os.environ.get("EG_EMBED_THREADS", "8"),
            "wall_s": round(wall, 2), "embed_s": round(total_embed_s, 2),
            "insert_s": round(total_db_s, 2),
            "embed_chunks_per_s": round(rate, 2), "per_doc": per_doc,
        }, indent=2, ensure_ascii=False), encoding="utf-8")


def cmd_query(args):
    rows, embed_s, db_s = search(args.text, args.k)
    print(f'query: "{args.text}"   embed={embed_s * 1000:.0f}ms  db={db_s * 1000:.0f}ms\n')
    for rank, r in enumerate(rows, 1):
        handle, title, url, ord_, chunk, dist = r
        snippet = " ".join(chunk.split())[:220]
        print(f"{rank}. [{dist:.4f}] {title}")
        print(f"   {handle}  chunk #{ord_}  {url}")
        print(f"   …{snippet}…\n")


def cmd_stats(args):
    rows = db().execute(APP_ID, TABLE, (
        "SELECT count(*) AS chunks, count(DISTINCT handle) AS docs, "
        "       pg_size_pretty(pg_total_relation_size('{table}'::regclass)) AS size "
        "FROM {table}"))
    print(f"chunks={rows[0][0]}  documents={rows[0][1]}  table_size={rows[0][2]}")

    # `DbTables.execute` commits and returns the connection to the pool before
    # a non-SELECT result can be read, and EXPLAIN is not a SELECT — so this
    # one goes through the facade's session instead, which also lets the
    # index-off comparison share a transaction with the SET LOCAL.
    from sqlalchemy import text
    tbl = qualified_table()
    knn = (f"SELECT handle FROM {tbl} "
           "ORDER BY embedding <=> CAST(:q AS public.vector) LIMIT 5")
    qvec = vec_literal(embed_query("computational creativity"))
    with db().session(APP_ID) as s:
        for label, prelude in (("index available", None),
                               ("index disabled (exact scan)",
                                "SET LOCAL enable_indexscan = off")):
            if prelude:
                s.execute(text(prelude))
            print(f"\nEXPLAIN ANALYZE — {label}:")
            for line in s.execute(text("EXPLAIN ANALYZE " + knn), {"q": qvec}):
                # The plan inlines the whole 768-float query vector, which is
                # ~9 KB per line and buries the node types being compared.
                row = line[0]
                print("  " + (row if len(row) <= 160 else row[:160] + " …"))
        s.rollback()


# Real questions about what these 18 DEI doctoral theses are actually about —
# mixed PT/EN on purpose, since the corpus is bilingual.
BENCH_QUERIES = [
    "computational creativity and evolutionary art",
    "audio-visual perception and cross-modal associations",
    "reinforcement learning for drug discovery",
    "deep learning for medical image segmentation",
    "aprendizagem automática aplicada à saúde",
    "energy efficiency in wireless sensor networks",
    "software architecture and microservices",
    "natural language processing for Portuguese",
    "robótica móvel e navegação autónoma",
    "cybersecurity intrusion detection",
    "human-computer interaction and user experience design",
    "optimisation algorithms and metaheuristics",
    "cloud computing resource allocation",
    "sistemas de informação e bases de dados",
    "computer vision object detection",
    "generative models and neural networks",
    "internet of things edge computing",
    "biomedical signal processing EEG",
    "recommender systems and collaborative filtering",
    "formal verification of concurrent systems",
]


def cmd_bench(args):
    # The host this runs on is shared with the rest of the workspace, so a
    # latency number without the load it was taken under is not reproducible.
    print(f"host load average (1/5/15m): "
          f"{'/'.join(f'{x:.1f}' for x in os.getloadavg())}  cores={os.cpu_count()}")
    rows = db().execute(APP_ID, TABLE,
                        "SELECT count(*), count(DISTINCT handle) FROM {table}")
    print(f"corpus: {rows[0][0]} chunks over {rows[0][1]} documents\n")
    get_model()
    reps = args.reps
    # Pre-embed once per query so the measurement is the *vector search*, not
    # the model. End-to-end (embed + search) is reported separately below.
    vectors = [vec_literal(embed_query(q)) for q in BENCH_QUERIES]

    # Warm the connection pool and the OS page cache — a first-call outlier
    # would otherwise dominate a 200-sample p95.
    for _ in range(3):
        db().execute(APP_ID, TABLE,
                     "SELECT 1 FROM {table} ORDER BY embedding <=> CAST(:q AS public.vector) LIMIT 5",
                     {"q": vectors[0]})

    db_ms, e2e_ms, embed_ms = [], [], []
    for _ in range(reps):
        for q, v in zip(BENCH_QUERIES, vectors):
            t0 = time.perf_counter()
            embed_query(q)
            t1 = time.perf_counter()
            db().execute(APP_ID, TABLE, (
                "SELECT handle, title, source_url, chunk_text, "
                "       embedding <=> CAST(:q AS public.vector) AS distance "
                "FROM {table} ORDER BY embedding <=> CAST(:q AS public.vector) LIMIT :k"
            ), {"q": v, "k": args.k})
            t2 = time.perf_counter()
            embed_ms.append((t1 - t0) * 1000)
            db_ms.append((t2 - t1) * 1000)
            e2e_ms.append((t2 - t0) * 1000)

    def pct(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(round(p / 100 * len(xs))) - 1 if p else 0)]

    for label, xs in (("vector search (db only)", db_ms),
                      ("query embedding", embed_ms),
                      ("end-to-end (embed + search)", e2e_ms)):
        print(f"{label:30s} n={len(xs):4d}  "
              f"min={min(xs):6.1f}  p50={statistics.median(xs):6.1f}  "
              f"p95={pct(xs, 95):6.1f}  p99={pct(xs, 99):6.1f}  max={max(xs):7.1f}  (ms)")


def cmd_drop(args):
    db().drop(APP_ID, TABLE)
    print(f"dropped {TABLE}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="estudo_geral_extractor.index")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="chunk + embed every estudo_geral/*.md")
    p.add_argument("--report", help="write a JSON summary here")
    p.add_argument("--reembed", action="store_true",
                   help="re-embed documents already in the table (default: resume)")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("query", help="one semantic query, top-k chunks")
    p.add_argument("text")
    p.add_argument("-k", type=int, default=5)
    p.set_defaults(func=cmd_query)

    p = sub.add_parser("bench", help="latency distribution over a fixed query set")
    p.add_argument("--reps", type=int, default=10)
    p.add_argument("-k", type=int, default=5)
    p.set_defaults(func=cmd_bench)

    p = sub.add_parser("stats", help="row counts + EXPLAIN ANALYZE of a KNN query")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("drop", help="drop the prototype table")
    p.set_defaults(func=cmd_drop)

    args = ap.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
