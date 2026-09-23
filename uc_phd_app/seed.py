"""Copies the committed SQLite snapshot into the app's durable data dir.

Two failure modes this exists to avoid, both silent:

1. **Reading the DB out of the package dir.** That directory is deleted and
   re-fetched on every update (see ``paths.py``), so anything a user's
   scraper run added would vanish at the next version bump with no error.
2. **A naive ``shutil.copy`` racing itself.** At ``AW_WORKSPACE_WORKERS>1``
   every worker activates the app independently, so N processes run this
   function at once. Two of them copying onto the same path yields a
   truncated database that ``sqlite3.connect`` opens perfectly happily and
   then answers with garbage. Every copy here therefore goes to a
   process-unique temp name **in the same directory** and lands with
   ``os.replace``, which is atomic on the same filesystem.

Upgrade rule (deliberately not copy-if-absent alone): if the packaged seed
comes from a newer app version than the one recorded in ``seed.json`` **and**
the live database has no scrape newer than the seed's, re-seed. Copy-if-absent
on its own means a corrected dataset in v0.3.0 never reaches anyone who
installed v0.1.0 — the same trap ``contributes.tasks``/``contributes.agents``
fall into.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

from . import paths

log = logging.getLogger("aw_apps.uc_phd.seed")


def _version_tuple(version: str) -> tuple:
    """Sortable form of a dotted version; unparseable parts sort as 0."""
    parts = []
    for chunk in str(version).split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _read_stamp(stamp_path: Path) -> dict:
    try:
        with open(stamp_path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        # A stamp we cannot read is treated as absent rather than fatal — the
        # worst case is one redundant re-seed, and the alternative is an app
        # that refuses to activate over a corrupt 60-byte JSON file.
        return {}


def _latest_scrape_started_at(db_path: Path) -> str | None:
    """Newest ``scrape_runs.started_at`` in a database, or None."""
    if not db_path.is_file():
        return None
    conn = None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        row = conn.execute(
            "SELECT started_at FROM scrape_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        # Unopenable, corrupt, or predating the scrape_runs table. Treated as
        # "provenance unknown", which makes the caller fall back to the
        # version comparison alone — never a reason to fail activation.
        return None
    finally:
        if conn is not None:
            conn.close()
    return row[0] if row else None


def _atomic_copy(src: Path, dest: Path) -> None:
    """Copy ``src`` onto ``dest`` so no reader ever sees a partial file."""
    fd, tmp_name = tempfile.mkstemp(dir=str(dest.parent), prefix=".seed-", suffix=".tmp")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
    finally:
        # os.replace consumed tmp on success; this only fires if the copy blew
        # up partway, and must not mask the original exception.
        if tmp.exists():  # pragma: no cover - only on a failed copy
            tmp.unlink(missing_ok=True)


def ensure_seeded() -> dict:
    """Make sure the live database exists and is current. Returns what it did.

    Safe to call from every worker concurrently and on every activation.
    """
    seed = paths.seed_db_path()
    live = paths.live_db_path()
    stamp_path = paths.seed_stamp_path()
    version = paths.package_version()

    if not seed.is_file():
        # Nothing to seed from. Not fatal: a workspace whose user already ran
        # the scraper into the data dir is perfectly usable.
        log.warning("uc-phd: no packaged seed at %s", seed)
        return {"action": "no_seed", "db": str(live), "version": version}

    if not live.is_file():
        _atomic_copy(seed, live)
        _write_stamp(stamp_path, version, seed)
        log.info("uc-phd: seeded %s from packaged snapshot (v%s)", live, version)
        return {"action": "seeded", "db": str(live), "version": version}

    stamp = _read_stamp(stamp_path)
    seeded_version = stamp.get("app_version") or "0.0.0"
    if _version_tuple(version) <= _version_tuple(seeded_version):
        return {"action": "kept", "db": str(live), "version": seeded_version}

    # Newer packaged data available — but only take it if the user has not
    # scraped since. Their own scrape always wins over ours.
    live_scrape = _latest_scrape_started_at(live)
    seed_scrape = _latest_scrape_started_at(seed)
    if live_scrape and seed_scrape and live_scrape > seed_scrape:
        log.info(
            "uc-phd: keeping local database (scraped %s, newer than seed %s)",
            live_scrape, seed_scrape,
        )
        return {"action": "kept_local_scrape", "db": str(live), "version": seeded_version}

    _atomic_copy(seed, live)
    _write_stamp(stamp_path, version, seed)
    log.info("uc-phd: re-seeded %s from v%s snapshot", live, version)
    return {"action": "reseeded", "db": str(live), "version": version}


def _write_stamp(stamp_path: Path, version: str, seed: Path) -> None:
    payload = {
        "app_version": version,
        "seed_scrape_started_at": _latest_scrape_started_at(seed),
    }
    # Same atomic dance: a half-written stamp would make the next activation
    # re-seed and clobber a user's data.
    fd, tmp_name = tempfile.mkstemp(dir=str(stamp_path.parent), prefix=".seed-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp_name, stamp_path)


def seed_info() -> dict:
    """What ``/healthz`` reports about provenance."""
    stamp = _read_stamp(paths.seed_stamp_path())
    return {
        "app_version": paths.package_version(),
        "seeded_from_version": stamp.get("app_version"),
        "seed_scrape_started_at": stamp.get("seed_scrape_started_at"),
    }
