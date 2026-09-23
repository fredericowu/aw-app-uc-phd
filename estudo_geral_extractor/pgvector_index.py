"""Production pgvector loader for the Estudo Geral thesis corpus (S3).

Entrypoint: ``python -m estudo_geral_extractor.pgvector_index
<ingest|status|bench>``, wrapped by ``commands/uc_phd_index.py`` as
``aw-workspace-cli uc-phd-index``.

Lives here, not under ``uc_phd_app/`` — deliberate. ``uc_phd_app/`` is the one
package this repo's 100%-coverage gate measures (``pyproject.toml``), and its
own rationale already carves scraper/run.py and this package's own run.py out
of that gate: both are one-shot CLIs that talk to a live external resource for
minutes, untestable without either hitting the real thing from CI or building
a mock whose only reader is the mock itself. This loader is the same shape —
minutes of fastembed/ONNX CPU work against the real workspace Postgres — so it
lives where that reasoning already applies instead of asking the gate to bend
for a third time. ``uc_phd_app/store.py`` keeps the SQL and chunking/embedding
logic that DOES run on every request (routes), which is what stays covered.

Scope: indexes exactly the 18 theses committed under ``estudo_geral/*.md`` —
the 2024+ DEI doctoral corpus S1 already extracted. This loader does not
widen that set; it indexes whatever ``.md`` files exist in that directory,
nothing more. A future corpus expansion (more years, more departments) is a
later card's decision, not something this file does on its own.

Resumable, keyed on content, not count: each thesis's ``.md`` is hashed
(``md_sha256``) and compared against ``documents.md_sha256``; unchanged
theses are skipped. The P0 prototype (``estudo_geral_extractor/index.py``)
resumed by comparing chunk COUNTS, which silently misses a content edit that
doesn't change the chunk count — this compares the actual content hash.

WHERE THIS HAS TO RUN
----------------------
Inside the workspace container (``aw-remote-host-workspace``) — an agent
runner container is a different network namespace and cannot reach
``aw-remote-host-postgres:5432``. Same constraint as the P0 prototype.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

import yaml

from uc_phd_app import paths, store


def split_front_matter(raw):
    """`---\\n<yaml>\\n---\\n\\n<body>` -> (dict, body). Returns ({}, raw) if absent.

    Deliberately duplicated from the P0 prototype rather than imported from
    it: this loader supersedes ``estudo_geral_extractor/index.py``, which is
    another card's deliverable and is expected to be deleted when that card
    closes. Importing a nine-line pure helper across that boundary would make
    this CLI — and, through ``uc_phd_app/__main__.py``'s standalone
    ``cli_store()`` probe, the whole standalone app — fail at import time the
    moment the prototype goes away.
    """
    if not raw.startswith("---\n"):
        return {}, raw
    end = raw.find("\n---\n", 4)
    if end == -1:
        return {}, raw
    front = yaml.safe_load(raw[4:end]) or {}
    return front, raw[end + len("\n---\n"):].lstrip("\n")


class _CliDb:
    """Talks to ``src.apps.db_tables.DbTables`` directly, bound to this app's
    id — the same thing ``ctx.db`` does inside the request pipeline, minus
    the ``ctx`` that only exists there. Not a facade bypass: there is no
    facade to go through outside the app runtime, and every statement still
    runs through ``DbTables``'s own ``_validate`` prefix check. Only
    importable inside the aw-workspace checkout (see this file's own module
    docstring for why that keeps it out of ``uc_phd_app``)."""

    def __init__(self) -> None:
        from src.apps.db_tables import DbTables
        self._tables = DbTables()

    def execute(self, name: str, sql: str, params: dict | None = None):
        return self._tables.execute(store.APP_ID, name, sql, params)

    def execute_multi(self, sql: str, names: list[str], params: dict | None = None):
        return self._tables.execute_multi(store.APP_ID, sql, names, params)


def cli_store() -> store.VectorStore:
    return store.VectorStore(_CliDb())


def load_documents() -> list[tuple[Path, dict, str, str]]:
    """Every ``estudo_geral/*.md`` -> (path, front_matter, body, md_sha256).
    Sorted for deterministic run order."""
    docs = []
    for path in sorted(paths.estudo_geral_dir().glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        front, body = split_front_matter(raw)
        if not front.get("handle"):
            print(f"  ! {path.name}: no handle in front matter, skipped", flush=True)
            continue
        sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        docs.append((path, front, body, sha))
    return docs


def handle_to_slug(handle: str) -> str:
    return handle.replace("/", "-")


def cmd_ingest(args: argparse.Namespace) -> int:
    print(f"model: {store.MODEL_NAME} ({store.VECTOR_DIM}-dim)", flush=True)
    t_model = time.perf_counter()
    store.load_model()
    print(f"model loaded in {time.perf_counter() - t_model:.1f}s", flush=True)

    vs = cli_store()
    state = vs.probe_state()
    if state["state"] != "ready":
        print(f"ABORT: vector store not ready — {state['state']}: {state['reason']}",
              file=sys.stderr)
        return 1

    docs = load_documents()
    print(f"documents: {len(docs)} (estudo_geral/*.md — 2024+ DEI corpus, not widened)",
          flush=True)

    total_chunks = 0
    embedded_docs = 0
    abstract_backfills = 0
    per_doc = []
    t_all = time.perf_counter()

    for path, front, body, sha in docs:
        handle = front["handle"]
        if not args.reembed and not vs.needs_reindex(handle, sha):
            print(f"  {handle}: unchanged (md_sha256 + abstract vector), skipped",
                  flush=True)
            per_doc.append({"handle": handle, "skipped": True})
            continue

        # The cheap repair path, and the reason `needs_reindex` checks the
        # abstract vector as well as the hash. migrations/0002 adds
        # `abstract_embedding` as NULL to rows that are otherwise fully and
        # correctly indexed. Re-chunking and re-embedding 6609 chunks to fill
        # in 18 vectors would be minutes of ONNX work for nothing — so when
        # only the abstract vector is missing, write just that.
        if not args.reembed and vs.document_md_sha256(handle) == sha:
            vs.set_abstract_embedding(handle, store.embed_docs(
                [store.abstract_content(front)])[0])
            abstract_backfills += 1
            print(f"  {handle}: chunks unchanged, abstract vector backfilled", flush=True)
            per_doc.append({"handle": handle, "abstract_backfilled": True})
            continue

        content = store.document_content(front, body)
        chunks = store.chunk_text(content)
        if not chunks:
            print(f"  {handle}: 0 chunks (empty content)", flush=True)
            per_doc.append({"handle": handle, "chunks": 0})
            continue

        t_doc = time.perf_counter()
        written = vs.replace_document(
            handle=handle,
            slug=handle_to_slug(handle),
            title=front.get("title") or handle,
            year=(str(front.get("date") or "")[:4] or None),
            source_url=front["source_url"],
            full_text=bool(front.get("full_text")),
            md_sha256=sha,
            chunks=chunks,
        )
        # After the chunks, so a crash between the two leaves the document row
        # stamped with _PENDING_SHA and `needs_reindex` reprocesses it — the
        # same resume guarantee replace_document already relies on.
        vs.set_abstract_embedding(handle, store.embed_docs(
            [store.abstract_content(front)])[0])
        total_chunks += written
        embedded_docs += 1
        per_doc.append({"handle": handle, "chunks": written})
        print(f"  {handle}: {written:5d} chunks  ({time.perf_counter() - t_doc:.1f}s)",
              flush=True)

    wall = time.perf_counter() - t_all
    stats = vs.stats()
    coverage = vs.abstract_coverage()
    print(f"\nINGEST DONE  documents_reembedded={embedded_docs}/{len(docs)}  "
          f"abstract_vectors_backfilled={abstract_backfills}  "
          f"chunks_written_this_run={total_chunks}  wall={wall:.1f}s  "
          f"table_totals: documents={stats['documents']} chunks={stats['chunks']}  "
          f"matchable={coverage['matchable']}/{coverage['theses']}", flush=True)
    # The Fit screen ranks over abstract_embedding, so a thesis missing one is
    # invisible there however well-chunked it is. Named here rather than left
    # to be discovered as "no matches" on screen.
    if coverage["matchable"] < coverage["theses"]:
        print(f"WARNING: {coverage['theses'] - coverage['matchable']} thesis/theses "
              f"have no abstract_embedding and will not appear on the Fit screen",
              file=sys.stderr)

    if args.report:
        Path(args.report).write_text(json.dumps({
            "documents": len(docs), "documents_reembedded": embedded_docs,
            "abstract_vectors_backfilled": abstract_backfills,
            "chunks_written_this_run": total_chunks, "wall_s": round(wall, 2),
            "table_totals": stats, "abstract_coverage": coverage,
            "per_doc": per_doc,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    vs = cli_store()
    state = vs.probe_state()
    reason = f" ({state['reason']})" if state["reason"] else ""
    print(f"state: {state['state']}{reason}")
    if state["state"] == "ready":
        stats = vs.stats()
        coverage = vs.abstract_coverage()
        print(f"documents={stats['documents']}  chunks={stats['chunks']}  "
              f"matchable_on_fit={coverage['matchable']}/{coverage['theses']}")
        return 0
    return 1


# Real questions about the 18 DEI doctoral theses, mixed PT/EN since the
# corpus is bilingual — same set the P0 prototype benchmarked with.
BENCH_QUERIES = [
    "computational creativity and evolutionary art",
    "reinforcement learning for drug discovery",
    "deep learning for medical image segmentation",
    "aprendizagem automática aplicada à saúde",
    "energy efficiency in wireless sensor networks",
    "natural language processing for Portuguese",
    "robótica móvel e navegação autónoma",
    "cybersecurity intrusion detection",
    "human-computer interaction and user experience design",
    "cloud computing resource allocation",
    "computer vision object detection",
    "internet of things edge computing",
]


def cmd_bench(args: argparse.Namespace) -> int:
    store.load_model()
    vs = cli_store()
    state = vs.probe_state()
    if state["state"] != "ready":
        print(f"ABORT: vector store not ready — {state['state']}: {state['reason']}",
              file=sys.stderr)
        return 1

    # Warm the connection pool / OS page cache so a first-call outlier
    # doesn't dominate a small sample.
    vs.search(BENCH_QUERIES[0], args.k)

    e2e_ms = []
    for _ in range(args.reps):
        for q in BENCH_QUERIES:
            t0 = time.perf_counter()
            vs.search(q, args.k)
            e2e_ms.append((time.perf_counter() - t0) * 1000)

    def pct(xs: list[float], p: float) -> float:
        xs = sorted(xs)
        idx = min(len(xs) - 1, max(0, int(round(p / 100 * len(xs))) - 1))
        return xs[idx]

    stats = vs.stats()
    print(f"chunks={stats['chunks']}  documents={stats['documents']}  "
          f"n={len(e2e_ms)}  p50={statistics.median(e2e_ms):.1f}ms  "
          f"p95={pct(e2e_ms, 95):.1f}ms  p99={pct(e2e_ms, 99):.1f}ms  "
          f"max={max(e2e_ms):.1f}ms  (end-to-end: embed + db)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="estudo_geral_extractor.pgvector_index")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="chunk + embed every estudo_geral/*.md")
    p.add_argument("--report", help="write a JSON summary here")
    p.add_argument("--reembed", action="store_true",
                    help="re-embed documents even if md_sha256 is unchanged")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("status", help="vector store state + row counts")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("bench", help="latency distribution over a fixed query set")
    p.add_argument("--reps", type=int, default=10)
    p.add_argument("-k", type=int, default=5)
    p.set_defaults(func=cmd_bench)

    args = ap.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
