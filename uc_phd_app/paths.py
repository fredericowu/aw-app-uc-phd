"""Where this app's files live — the package dir (read-only, wiped on every
update) versus the data dir (durable).

The distinction is the single most important one in this app. An installed
app's package directory is deleted and re-fetched **wholesale** on update and
uninstall (aw-workspace ``src/apps/runtime.py`` documents the live incident
where exactly this wiped aw-mcp-gateway's persisted bearer token). So:

* ``data/cisuc.sqlite3`` in the repo is a **seed**, never the live database.
* The live database is ``<AW_WORKSPACE_HOME>/data/aw-app-uc-phd/cisuc.sqlite3``
  — the same tree the runtime binds for ``fs:workspace-data``
  (``$AW_APP_DATA`` -> ``paths.workspace_home()/data/<app_id>``), and the same
  resolution the agents-platform-runners app does for Tier-1.

``seed.py`` owns the copy; this module only answers "which path".
"""
from __future__ import annotations

import os
from pathlib import Path

APP_ID = "aw-app-uc-phd"
DB_FILENAME = "cisuc.sqlite3"
SEED_STAMP_FILENAME = "seed.json"

#: Repo/package root — the directory holding ``aw-app.json``.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def workspace_home() -> Path:
    """``AW_WORKSPACE_HOME``, defaulting the way aw-workspace's own
    ``paths.workspace_home()`` does (``~/.aw-workspace``)."""
    env = os.environ.get("AW_WORKSPACE_HOME")
    if env:
        return Path(env)
    return Path(os.path.expanduser("~")) / ".aw-workspace"


def data_dir() -> Path:
    """This app's durable directory, created on demand.

    Overridable with ``AW_APP_UC_PHD_DATA_DIR`` — standalone mode and the
    tests use that rather than writing into the real workspace home.
    """
    override = os.environ.get("AW_APP_UC_PHD_DATA_DIR")
    d = Path(override) if override else workspace_home() / "data" / APP_ID
    d.mkdir(parents=True, exist_ok=True)
    return d


def seed_db_path() -> Path:
    """The committed snapshot shipped inside the package."""
    return PACKAGE_ROOT / "data" / DB_FILENAME


def live_db_path() -> Path:
    """The database every read goes through."""
    return data_dir() / DB_FILENAME


def seed_stamp_path() -> Path:
    """Records which app version the live database was seeded from."""
    return data_dir() / SEED_STAMP_FILENAME


def sql_dir() -> Path:
    """``sql/`` — the committed queries every figure traces back to."""
    return PACKAGE_ROOT / "sql"


def estudo_geral_dir() -> Path:
    """``estudo_geral/`` — S1's committed thesis markdown files. Read-only,
    like ``sql_dir()``; nothing in this app writes here.

    Overridable with ``AW_APP_UC_PHD_ESTUDO_GERAL_DIR``, so tests can point at
    a small fixture directory instead of the 18 real theses.
    """
    override = os.environ.get("AW_APP_UC_PHD_ESTUDO_GERAL_DIR")
    return Path(override) if override else PACKAGE_ROOT / "estudo_geral"


def thesis_attribution_path() -> Path:
    """The hand-verified thesis author/supervisor -> CISUC-person join (see
    ``docs/thesis-attribution.md`` for the full record and methodology).

    Overridable with ``AW_APP_UC_PHD_ATTRIBUTION_PATH`` for tests.
    """
    override = os.environ.get("AW_APP_UC_PHD_ATTRIBUTION_PATH")
    return Path(override) if override else PACKAGE_ROOT / "docs" / "thesis-attribution.json"


def ui_dist() -> Path:
    """``ui/dist/`` — the built SPA. Committed, because the release pipeline
    ships the repo as-is and never runs ``npm run build``."""
    return PACKAGE_ROOT / "ui" / "dist"


def package_version() -> str:
    """This app's version, read from its own manifest."""
    import json

    with open(PACKAGE_ROOT / "aw-app.json", encoding="utf-8") as f:
        return str(json.load(f).get("version") or "0.0.0")
