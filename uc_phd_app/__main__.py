"""Standalone entrypoint (ADR Decision 4) — run this app WITHOUT the
aw-workspace runtime, which is how the UI is developed and demoed:

    python -m uc_phd_app                  # binds 127.0.0.1:9482 (default)
    PORT=9483 python -m uc_phd_app

Mounts the SAME ``build_routes()`` sub-app at BOTH roots the runtime exposes
it on in integrated mode, because the frontend behaves differently at each and
only serving one of them hides a real bug:

* ``/api/apps/aw-app-uc-phd`` — the path mount, where ``base: './'`` in
  ``vite.config.js`` is what keeps the assets resolvable.
* ``/`` — stands in for the app's own subdomain
  (``aw-app-uc-phd.app.<workspace>``), which is the root the ``managed_app``
  window actually loads.

Serving the SPA at ``/`` from a plain ``StaticFiles`` mount instead would put
the page at a root whose ``/api/...`` paths answer 404, so the standalone mode
used to develop the UI would disagree with the mode users see.

The database is seeded the same way it is in integrated mode, so a fresh
checkout works with no setup. Point ``AW_APP_UC_PHD_DATA_DIR`` somewhere
scratch if you do not want to touch the real workspace data dir.

Auth: standalone has **no** ``IdentityGuard`` — that is aw-workspace runtime
machinery, not app code. Hence binding ``127.0.0.1`` by default.
"""
from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI

from . import paths, seed, store
from .routes import build_routes

SLUG = "aw-app-uc-phd"  # must match aw-app.json's "id"
DEFAULT_PORT = 9482  # must match aw-app.json's runtime.standalone.default_port

APP_ROOT = paths.PACKAGE_ROOT
UI_DIST = paths.ui_dist()


def build_standalone_app() -> FastAPI:
    seed.ensure_seeded()
    app = FastAPI(title="UC PhD Projects (standalone)")
    # No ctx outside the runtime, but the loader's cli_store() talks to
    # Postgres directly (same adapter the indexing CLI uses) — so search
    # still works standalone as long as this process also happens to sit
    # inside the aw-workspace checkout (`src.apps.db_tables` importable) AND
    # can reach Postgres. Neither is true for the common case — a plain
    # checkout of this repo, run for UI development, with none of
    # aw-workspace's own code anywhere nearby — so that failure is expected,
    # not a bug: search just reports "unavailable" like it would for any
    # other degraded store. Indexing (writes) stays a CLI-only job that must
    # run inside the workspace container regardless.
    try:
        from estudo_geral_extractor.pgvector_index import cli_store
        vector_store = cli_store()
    except ImportError:
        vector_store = store.VectorStore(None)
    # A fresh sub-app per mount: build_routes() is a factory, and the same
    # FastAPI instance must not be mounted twice.
    app.mount(f"/api/apps/{SLUG}", build_routes(store=vector_store))
    # Root LAST — this one carries the SPA's StaticFiles("/"), which matches
    # everything and would otherwise swallow the prefixed mount above.
    app.mount("/", build_routes(store=vector_store))
    return app


app = build_standalone_app()


def main() -> None:
    if not UI_DIST.is_dir():
        print(f"NOTE: {UI_DIST} not built yet — run `npm run build` in ui/ first "
              f"(API routes still work without it).")
    port = int(os.environ.get("PORT", str(DEFAULT_PORT)))
    host = os.environ.get("AW_APP_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
