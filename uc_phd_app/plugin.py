"""Entrypoint referenced by aw-app.json's runtime.entrypoint
("uc_phd_app.plugin:UcPhdAppPlugin").

On activate, in this order:

1. **Seed the database into the app's data dir** (``seed.ensure_seeded()``).
   This must happen before any route can be called, and it must be safe to run
   concurrently — at ``AW_WORKSPACE_WORKERS>1`` every worker activates the app
   independently. ``seed.py`` explains how.
2. **Probe the pgvector store's state** (``store.VectorStore.probe_state()``)
   — ``ready`` / ``missing_extension`` / ``unavailable`` — and fire one
   ``ctx.notify`` if it isn't ``ready``, so a degraded search doesn't fail
   silently on a BYOD workspace that lacks the ``vector`` extension. Never
   ``CREATE EXTENSION`` here: that is a cluster-wide privileged side effect an
   app must not take just to enable its own feature (rejected in the S2
   design). Note the migration that creates this app's tables runs *after*
   ``activate()`` returns (see ``src/apps/runtime.py``'s ``_apply_migrations``
   docstring), so a brand-new install can observe ``unavailable`` for one
   instant here before self-correcting — every route re-probes per request,
   so nothing downstream is stuck on this snapshot.
3. **Register the backend sub-app** through the gated ``ctx.routes`` facade
   (capability ``routes:register``), mounted by the runtime at
   ``/api/apps/aw-app-uc-phd`` and on the app's own subdomain.
4. **Self-register the ``phd_knowledge_base`` MCP server** (S4) by writing
   ``mcp.json`` into the package dir — see ``mcp/self_register.py``. No new
   capability: the gateway discovers it by scanning the installed app dir,
   the same mechanism ``aw-app-whiteboard`` and ``aw-app-architecture`` use.

This app requests four permissions: ``routes:register``, ``fs:workspace-data``,
``net:outbound`` and ``db:own-tables`` — all **low risk**
(``src/apps/capabilities.py``). That is deliberate and load-bearing: the app
is distributed through the public catalog and IS signed (``aw-workspace-cli
apps --json`` reports ``"signed": true``), but the capability set stays free
of any high-risk entry regardless — ``filter_grants`` only refuses high-risk
caps for an *unsigned* app, so this app never needs to rely on that leniency.
Do not add ``ui:code``, ``containers:manage`` or ``mcp:register-gateway``
without a real reason to reconsider Tier-1 — see the S2 architecture card.

The scraper (``scraper/run.py``) and the Estudo Geral extractor
(``estudo_geral_extractor/run.py``) are not run from here — refreshing either
dataset is a manual CLI run. The vector index is refreshed by
``aw-workspace-cli uc-phd-index ingest`` (``commands/uc_phd_index.py``), also
never run from here: embedding ~5-6k chunks is minutes of work, which
``activate()`` — invoked on every worker, at boot — must never be on the hook
for.
"""
from __future__ import annotations

import logging
import os

from . import routes as routes_mod
from . import seed
from . import store
from .mcp import self_register as mcp_self_register

log = logging.getLogger("aw_apps.uc_phd")


class UcPhdAppPlugin:
    async def activate(self, ctx) -> None:
        result = seed.ensure_seeded()

        vector_store = store.VectorStore(ctx.db)
        state = vector_store.probe_state()
        log.info("aw-app-uc-phd: vector store state=%s reason=%s",
                  state["state"], state["reason"])
        if state["state"] != "ready":
            ctx.notify(
                f"UC PhD semantic search is degraded ({state['state']}): "
                f"{state['reason']}",
                level="warning", title="UC PhD Projects",
            )

        ctx.routes.register(routes_mod.build_routes(store=vector_store))

        # Discoverable by aw-mcp-gateway's app-scan — see mcp/self_register.py.
        port = int(os.environ.get("AW_PORT", "9030"))
        mcp_self_register.register_self(ctx.package_dir, port)

        log.info(
            "aw-app-uc-phd activated: database %s (%s), routes mounted",
            result.get("db"), result.get("action"),
        )

    async def deactivate(self) -> None:
        # Nothing to undo: no CLI installed, no container, and the data dir is
        # meant to outlive the app (that is the whole point of seeding into
        # it). The framework's journal reverse-replay unmounts the routes.
        log.info("aw-app-uc-phd deactivated")
