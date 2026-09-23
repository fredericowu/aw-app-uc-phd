"""uc_phd_app/paths.py — the package-dir vs data-dir distinction.

Getting this wrong is invisible until an app update wipes the database, so the
resolution rules are asserted rather than assumed.
"""
from __future__ import annotations

import os
from pathlib import Path

from uc_phd_app import paths


def test_data_dir_follows_the_explicit_override(isolated_data_dir):
    assert paths.data_dir() == isolated_data_dir
    assert paths.live_db_path() == isolated_data_dir / "cisuc.sqlite3"
    assert paths.seed_stamp_path() == isolated_data_dir / "seed.json"


def test_data_dir_is_under_workspace_home_when_not_overridden(tmp_path, monkeypatch):
    monkeypatch.delenv("AW_APP_UC_PHD_DATA_DIR", raising=False)
    monkeypatch.setenv("AW_WORKSPACE_HOME", str(tmp_path / "home"))

    assert paths.workspace_home() == tmp_path / "home"
    assert paths.data_dir() == tmp_path / "home" / "data" / "aw-app-uc-phd"
    assert paths.data_dir().is_dir(), "the data dir is created on demand"


def test_workspace_home_falls_back_to_the_dotdir_in_the_users_home(monkeypatch):
    monkeypatch.delenv("AW_WORKSPACE_HOME", raising=False)
    assert paths.workspace_home() == Path(os.path.expanduser("~")) / ".aw-workspace"


def test_the_seed_lives_in_the_package_and_the_live_db_does_not(isolated_data_dir):
    """The package dir is deleted and re-fetched wholesale on every update. If
    these two ever resolve to the same tree, the next version bump silently
    destroys the user's data."""
    seed = paths.seed_db_path()
    live = paths.live_db_path()

    assert seed.parent.parent == paths.PACKAGE_ROOT
    assert paths.PACKAGE_ROOT not in live.parents
    assert seed != live


def test_the_committed_seed_and_sql_directory_really_exist():
    assert paths.seed_db_path().is_file(), "data/cisuc.sqlite3 must stay committed"
    assert paths.sql_dir().is_dir()
    assert list(paths.sql_dir().glob("*.sql"))


def test_estudo_geral_dir_defaults_to_the_package_directory(monkeypatch):
    monkeypatch.delenv("AW_APP_UC_PHD_ESTUDO_GERAL_DIR", raising=False)
    assert paths.estudo_geral_dir() == paths.PACKAGE_ROOT / "estudo_geral"
    assert paths.estudo_geral_dir().is_dir(), "estudo_geral/ must stay committed"


def test_estudo_geral_dir_follows_the_explicit_override(tmp_path, monkeypatch):
    monkeypatch.setenv("AW_APP_UC_PHD_ESTUDO_GERAL_DIR", str(tmp_path))
    assert paths.estudo_geral_dir() == tmp_path


def test_thesis_attribution_path_points_at_the_golden_fixture():
    """No longer runtime input and no longer overridable: it is the fixture
    tests/test_name_match.py replays 50 hand-made decisions from, and a test
    that could be pointed at a different file proves nothing."""
    default = paths.thesis_attribution_path()
    assert default == paths.PACKAGE_ROOT / "docs" / "thesis-attribution.json"
    assert default.is_file(), "docs/thesis-attribution.json must stay committed"


def test_fastembed_cache_dir_is_under_the_data_dir_not_tmp(isolated_data_dir):
    """fastembed defaults FASTEMBED_CACHE_PATH to /tmp — a ~520 MB
    re-download on every container restart if left there."""
    cache = paths.fastembed_cache_dir()
    assert cache == isolated_data_dir / "fastembed_cache"
    assert cache.is_dir()


def test_estudo_geral_pdf_cache_dir_is_under_the_data_dir_not_the_package(isolated_data_dir):
    """PDFs are a cache (PO decision, S3) — they must not live under
    PACKAGE_ROOT, which is wiped wholesale on every app update."""
    cache = paths.estudo_geral_pdf_cache_dir()
    assert cache == isolated_data_dir / "estudo_geral" / "pdfs"
    assert paths.PACKAGE_ROOT not in cache.parents
    assert cache.is_dir()
