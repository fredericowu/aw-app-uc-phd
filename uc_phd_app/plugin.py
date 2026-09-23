"""Entrypoint referenced by aw-app.json's runtime.entrypoint
("uc_phd_app.plugin:UcPhdAppPlugin").

Two things happen on activate, in this order:

1. **Seed the database into the app's data dir** (``seed.ensure_seeded()``).
   This must happen before any route can be called, and it must be safe to run
   concurrently — at ``AW_WORKSPACE_WORKERS>1`` every worker activates the app
   independently. ``seed.py`` explains how.
2. **Register the backend sub-app** through the gated ``ctx.routes`` facade
   (capability ``routes:register``), mounted by the runtime at
   ``/api/apps/aw-app-uc-phd`` and on the app's own subdomain.

This app requests exactly two permissions — ``routes:register`` and
``fs:workspace-data`` — and both are low risk. That is deliberate and load-
bearing: the app is distributed through a **private** catalog, and an app that
is not in the official public marketplace is not ``signed``, so
``filter_grants`` silently refuses every high-risk capability it asks for. A
refused capability does not raise; the app activates anyway and the missing
piece shows up as an empty window body or a dead route. Nothing here asks for
one, so nothing can be refused. Do not add ``ui:code`` (or a ``component``
frontend bundle, or ``containers:manage``) while this app stays private —
``docs/app-migration-plan.md`` §2 has the code references.

The scraper is not run from here and there is no ``net:outbound``: refreshing
the data is ``python -m scraper.run`` against the data-dir database.
"""
from __future__ import annotations

import logging

from . import routes as routes_mod
from . import seed

log = logging.getLogger("aw_apps.uc_phd")


class UcPhdAppPlugin:
    async def activate(self, ctx) -> None:
        result = seed.ensure_seeded()
        ctx.routes.register(routes_mod.build_routes())
        log.info(
            "aw-app-uc-phd activated: database %s (%s), routes mounted",
            result.get("db"), result.get("action"),
        )

    async def deactivate(self) -> None:
        # Nothing to undo: no CLI installed, no container, and the data dir is
        # meant to outlive the app (that is the whole point of seeding into
        # it). The framework's journal reverse-replay unmounts the routes.
        log.info("aw-app-uc-phd deactivated")
