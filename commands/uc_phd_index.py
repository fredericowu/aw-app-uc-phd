"""``aw-workspace-cli uc-phd-index`` — this app's own CLI command.

Auto-discovered by aw-workspace-cli from this app's installed directory
(``<apps_root>/aw-app-uc-phd/commands/``, since this file lives at
``commands/`` in this repo's root — see aw-workspace's
``src/cli/discovery.py``).

Everything real lives in ``estudo_geral_extractor.pgvector_index`` (see that
module's own docstring for why the loader sits there and not under
``uc_phd_app/``). This file only puts the app's package dir on ``sys.path``:
Tier-1 apps load under a synthetic ``aw_apps.<id>`` namespace inside the
*workspace* process, so neither ``uc_phd_app`` nor ``estudo_geral_extractor``
is importable as a plain top-level package from the separate
``aw-workspace-cli`` process without it (same trick as ``apps/secrets/
commands/secrets.py``).

Indexing goes straight to Postgres via ``src.apps.db_tables.DbTables``
(``uc_phd_app.store.cli_store()``), not through an HTTP route — this is a
CLI, not a request, and the work (embedding ~5-6k chunks with fastembed) is
minutes long, which a route handler should never be on the hook for. This
also has to run inside the workspace container: an agent-runner container
cannot reach ``aw-remote-host-postgres:5432``.

Usage:
    aw-workspace-cli uc-phd-index ingest              # index every estudo_geral/*.md
    aw-workspace-cli uc-phd-index ingest --reembed    # force re-embed, ignore md_sha256
    aw-workspace-cli uc-phd-index status              # vector store state + row counts
    aw-workspace-cli uc-phd-index bench                # p50/p95/p99 search latency
"""
from __future__ import annotations

import os
import sys

COMMAND = "uc-phd-index"
DESCRIPTION = "Index the Estudo Geral thesis corpus into pgvector (aw-app-uc-phd)"

APP_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def run(args: list[str]) -> int:
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)
    from estudo_geral_extractor.pgvector_index import main

    return main(list(args or []))
