"""The seed copy — the part of this app that fails silently if it is wrong.

Covers the three behaviours the migration plan calls out by name: absent
target copies, present target is not clobbered, and concurrent activation
never leaves a partial file.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

import pytest

from uc_phd_app import paths, seed
from tests.conftest import build_fixture_db


@pytest.fixture()
def packaged_seed(tmp_path, monkeypatch):
    """Point PACKAGE_ROOT at a throwaway package layout so the tests never
    depend on (or rewrite) the real committed snapshot."""
    pkg = tmp_path / "pkg"
    (pkg / "data").mkdir(parents=True)
    build_fixture_db(pkg / "data" / "cisuc.sqlite3")
    (pkg / "aw-app.json").write_text(json.dumps({"version": "0.1.0"}))
    monkeypatch.setattr(paths, "PACKAGE_ROOT", pkg)
    return pkg


def _set_version(pkg: Path, version: str) -> None:
    (pkg / "aw-app.json").write_text(json.dumps({"version": version}))


def _row_count(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    finally:
        conn.close()


def test_absent_target_gets_seeded_and_stamped(packaged_seed):
    result = seed.ensure_seeded()

    assert result["action"] == "seeded"
    live = paths.live_db_path()
    assert live.is_file()
    assert _row_count(live) == 3
    stamp = json.loads(paths.seed_stamp_path().read_text())
    assert stamp["app_version"] == "0.1.0"
    assert stamp["seed_scrape_started_at"] == "2026-01-01T00:00:00+00:00"


def test_existing_database_is_not_clobbered_at_the_same_version(packaged_seed):
    seed.ensure_seeded()
    live = paths.live_db_path()
    conn = sqlite3.connect(live)
    conn.execute(
        "INSERT INTO projects (id, title, title_norm, detail_fetched, first_seen_at) "
        "VALUES (99, 'User Added', 'user added', 0, '2026-02-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    assert seed.ensure_seeded()["action"] == "kept"
    assert _row_count(live) == 4, "a re-activation must not wipe the user's database"


def test_a_newer_packaged_version_reseeds_a_stale_database(packaged_seed):
    """Copy-if-absent alone means a corrected dataset in a later version never
    reaches anyone who installed an earlier one."""
    seed.ensure_seeded()
    live = paths.live_db_path()
    conn = sqlite3.connect(live)
    conn.execute("DELETE FROM projects WHERE id = 3")
    conn.commit()
    conn.close()
    assert _row_count(live) == 2

    _set_version(packaged_seed, "0.2.0")
    assert seed.ensure_seeded()["action"] == "reseeded"
    assert _row_count(live) == 3
    assert json.loads(paths.seed_stamp_path().read_text())["app_version"] == "0.2.0"


def test_a_users_own_newer_scrape_beats_a_newer_packaged_seed(packaged_seed):
    """`python -m scraper.run` is the supported refresh path, so a database
    scraped after the packaged snapshot must survive an app update."""
    seed.ensure_seeded()
    live = paths.live_db_path()
    conn = sqlite3.connect(live)
    conn.execute(
        "INSERT INTO scrape_runs (id, started_at) VALUES (2, '2026-06-01T00:00:00+00:00')"
    )
    conn.execute("DELETE FROM projects WHERE id = 3")
    conn.commit()
    conn.close()

    _set_version(packaged_seed, "0.2.0")
    assert seed.ensure_seeded()["action"] == "kept_local_scrape"
    assert _row_count(live) == 2


def test_concurrent_activation_never_leaves_a_partial_database(packaged_seed):
    """At AW_WORKSPACE_WORKERS>1 every worker activates independently. A naive
    shutil.copy race produces a truncated file that sqlite3 opens without
    complaint and then answers with garbage."""
    results, errors = [], []
    barrier = threading.Barrier(8)

    def worker():
        try:
            barrier.wait()
            results.append(seed.ensure_seeded())
        except Exception as exc:  # pragma: no cover - a failure is the assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    live = paths.live_db_path()
    assert _row_count(live) == 3
    assert live.stat().st_size == paths.seed_db_path().stat().st_size
    # No temp files left behind by the atomic replace.
    assert not list(paths.data_dir().glob(".seed-*"))


def test_a_missing_packaged_seed_is_reported_not_fatal(tmp_path, monkeypatch):
    """A workspace whose user already scraped into the data dir is usable even
    if the packaged snapshot is somehow absent — activation must not raise."""
    pkg = tmp_path / "empty-pkg"
    pkg.mkdir()
    (pkg / "aw-app.json").write_text(json.dumps({"version": "0.1.0"}))
    monkeypatch.setattr(paths, "PACKAGE_ROOT", pkg)

    assert seed.ensure_seeded()["action"] == "no_seed"


def test_an_unreadable_stamp_is_treated_as_absent(packaged_seed):
    seed.ensure_seeded()
    paths.seed_stamp_path().write_text("{not json")

    _set_version(packaged_seed, "0.2.0")
    # Version 0.2.0 > the unreadable stamp's implied 0.0.0, and the live DB has
    # no newer scrape, so it re-seeds rather than refusing to activate.
    assert seed.ensure_seeded()["action"] == "reseeded"


def test_seed_info_reports_provenance(packaged_seed):
    seed.ensure_seeded()
    info = seed.seed_info()
    assert info["app_version"] == "0.1.0"
    assert info["seeded_from_version"] == "0.1.0"
    assert info["seed_scrape_started_at"] == "2026-01-01T00:00:00+00:00"


@pytest.mark.parametrize(
    "a,b",
    [("0.1.0", "0.2.0"), ("0.9.0", "0.10.0"), ("1.0.0", "1.0.1"), ("0.0.0", "0.1.0")],
)
def test_version_ordering_is_numeric_not_lexicographic(a, b):
    assert seed._version_tuple(a) < seed._version_tuple(b)


def test_version_parsing_survives_a_non_numeric_component():
    assert seed._version_tuple("1.2.3rc1") == (1, 2, 31)
    assert seed._version_tuple("1.x.3") == (1, 0, 3)


def test_latest_scrape_helper_handles_a_missing_or_schemaless_file(tmp_path):
    assert seed._latest_scrape_started_at(tmp_path / "nope.sqlite3") is None

    empty = tmp_path / "empty.sqlite3"
    sqlite3.connect(empty).close()
    assert seed._latest_scrape_started_at(empty) is None

    no_runs = build_fixture_db(tmp_path / "no-runs.sqlite3")
    conn = sqlite3.connect(no_runs)
    conn.execute("DELETE FROM scrape_runs")
    conn.commit()
    conn.close()
    assert seed._latest_scrape_started_at(no_runs) is None


def test_latest_scrape_helper_rejects_a_directory_before_opening_it(tmp_path):
    d = tmp_path / "adir.sqlite3"
    d.mkdir()
    assert seed._latest_scrape_started_at(d) is None


def test_latest_scrape_helper_handles_a_file_that_is_not_a_database(tmp_path):
    junk = tmp_path / "junk.sqlite3"
    junk.write_bytes(b"this is definitely not a sqlite database")
    assert seed._latest_scrape_started_at(junk) is None
