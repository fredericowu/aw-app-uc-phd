"""uc_phd_app's mode-agnostic FastAPI sub-app (ADR Decision 2/6).

``build_routes()`` returns the SAME sub-app object used in both modes:

* **integrated** — ``plugin.py`` hands it to ``ctx.routes.register(...)``,
  which mounts it at ``/api/apps/aw-app-uc-phd`` behind the runtime's
  ``IdentityGuard``, and also at ``aw-app-uc-phd.app.<workspace domain>``.
  That subdomain is the one the ``managed_app`` window actually loads.
* **standalone** — ``__main__.py`` mounts it at the same prefix itself, with
  no ``IdentityGuard`` (``python -m uc_phd_app``).

Every path declared here is RELATIVE, so both modes expose the same shape.

ORDER MATTERS — the one gotcha in this file
-------------------------------------------
The SPA is served by ``StaticFiles(directory=ui/dist, html=True)`` mounted at
``/``, and a Starlette ``Mount("/")`` matches **everything**. Registering it
before the API routers does not 404 them, which would at least be obvious — it
silently answers ``GET /api/coverage`` with ``index.html``, so the frontend
gets HTML where it expected JSON and reports a parse error pointing nowhere
near the cause. The static mount therefore goes **last**, always, and
``tests/test_routes.py`` asserts it.

There is no WebSocket here. The template ships a ``/ws/echo`` reference
socket; this app has nothing to stream, and an unused socket is a maintenance
liability. If a later feature needs one, ``aw-app-template``'s handler is the
reference to copy back in — along with the ``aw-ws/1`` envelope rules and the
``aw_app_uc_phd`` domain prefix (the app id with ``-`` -> ``_``, mechanically).
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import db, paths, seed
from . import store as store_mod
from .api import fit as fit_api
from .api import projects as projects_api
from .api import search as search_api
from .api import theses as theses_api


def build_routes(store: store_mod.VectorStore | None = None) -> FastAPI:
    """Mode-agnostic factory — called once per mode.

    ``store`` is the pgvector store (``uc_phd_app/store.py``), built by
    ``plugin.py`` in integrated mode from ``ctx.db``. Standalone mode has no
    ``ctx`` and passes nothing, which falls back to a store with no DB
    access — every search/status route reports ``unavailable`` rather than
    reaching for Postgres.
    """
    app = FastAPI(title="UC PhD Projects")
    app.state.vector_store = store or store_mod.VectorStore(None)

    @app.get("/healthz")
    async def healthz() -> dict:
        """What QA and ``doctor`` actually poke: is the database there, does
        it have rows, and which snapshot did it come from — plus the
        semantic-search state, so a degraded pgvector store shows up here
        too instead of only surfacing at query time."""
        live = paths.live_db_path()
        payload = {
            "status": "ok",
            "db_path": str(live),
            "db_exists": live.is_file(),
            "seed": seed.seed_info(),
            "search": app.state.vector_store.probe_state(),
        }
        try:
            payload["row_counts"] = db.table_counts()
        except Exception as exc:  # database missing or unreadable
            payload["status"] = "degraded"
            payload["error"] = str(exc)
        return payload

    app.include_router(projects_api.router, prefix="/api", tags=["projects"])
    app.include_router(theses_api.router, prefix="/api", tags=["theses"])
    app.include_router(search_api.router, prefix="/api", tags=["search"])
    app.include_router(fit_api.router, prefix="/api", tags=["fit"])

    # LAST. See the module docstring.
    dist = paths.ui_dist()
    if dist.is_dir():
        # html=True: GET / -> index.html, and any unknown path falls back to
        # it too. The SPA routes on the hash, so it does not strictly need the
        # fallback, but it keeps a stale deep link harmless instead of a 404.
        app.mount("/", StaticFiles(directory=dist, html=True), name="ui")

    return app
