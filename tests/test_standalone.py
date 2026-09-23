"""Standalone mode (`python -m uc_phd_app`) — boot smoke test plus main().

Unlike the other suites these run against the REAL package: the committed
seed, the real ``sql/`` and the real ``ui/dist``. That is the point — this is
the one place the shipped artefacts are exercised together, so a missing
``ui/dist`` or a renamed query file fails here. The data dir is still
redirected to tmp (``conftest.isolated_data_dir``), so the real workspace data
directory is never touched.
"""
from __future__ import annotations

import json
from unittest.mock import patch

from fastapi.testclient import TestClient

import uc_phd_app.__main__ as main_mod
from uc_phd_app import db, paths
from tests.conftest import ROOT

MANIFEST = json.loads((ROOT / "aw-app.json").read_text())


def test_standalone_serves_the_api_at_both_roots():
    """The SPA derives its API base from where the page was served, so it
    talks to /api/... on the subdomain and to <prefix>/api/... on the path
    mount. Standalone has to answer at both or the mode used to develop the
    UI disagrees with the mode users get."""
    db.load_query.cache_clear()
    client = TestClient(main_mod.build_standalone_app())

    assert client.get("/api/coverage").status_code == 200
    assert client.get(f"/api/apps/{main_mod.SLUG}/api/coverage").status_code == 200
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get(f"/api/apps/{main_mod.SLUG}/healthz").json()["status"] == "ok"


def test_standalone_seeds_the_real_snapshot_into_the_data_dir(isolated_data_dir):
    main_mod.build_standalone_app()
    assert (isolated_data_dir / "cisuc.sqlite3").is_file()
    assert (isolated_data_dir / "seed.json").is_file()


def test_standalone_serves_the_built_spa_at_the_root():
    resp = TestClient(main_mod.build_standalone_app()).get("/")
    assert resp.status_code == 200, (
        "ui/dist is missing — run `npm run build` in ui/ and commit the result; "
        "release CI never builds it"
    )
    assert "text/html" in resp.headers["content-type"]


def test_the_built_spa_uses_relative_asset_paths():
    """`base: './'` in vite.config.js. An absolute /assets/... path works on
    the app's subdomain and 404s on the /api/apps/<slug>/ mount — and since
    the window uses the subdomain, that breakage would ship unnoticed."""
    index = (paths.ui_dist() / "index.html").read_text(encoding="utf-8")
    assert 'src="./' in index or "src='./" in index
    assert 'src="/assets' not in index
    assert 'href="/assets' not in index


def test_slug_and_port_match_the_manifest():
    assert main_mod.SLUG == MANIFEST["id"]
    assert main_mod.DEFAULT_PORT == MANIFEST["runtime"]["standalone"]["default_port"]


def test_main_binds_loopback_on_the_default_port():
    with patch.object(main_mod, "uvicorn") as mock_uvicorn:
        main_mod.main()

    mock_uvicorn.run.assert_called_once()
    _, kwargs = mock_uvicorn.run.call_args
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == main_mod.DEFAULT_PORT


def test_main_notes_an_unbuilt_ui_and_honours_the_env_overrides(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.setattr(main_mod, "UI_DIST", tmp_path / "not-built")
    monkeypatch.setenv("PORT", "9999")
    monkeypatch.setenv("AW_APP_HOST", "0.0.0.0")

    with patch.object(main_mod, "uvicorn") as mock_uvicorn:
        main_mod.main()

    assert "not built yet" in capsys.readouterr().out
    _, kwargs = mock_uvicorn.run.call_args
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 9999


def test_the_api_still_works_in_a_checkout_with_no_built_ui(monkeypatch, tmp_path):
    """A fresh clone before `npm run build`: the static mount is skipped and
    every API route still answers."""
    monkeypatch.setattr(paths, "ui_dist", lambda: tmp_path / "not-built")
    db.load_query.cache_clear()

    client = TestClient(main_mod.build_standalone_app())
    assert client.get("/api/coverage").status_code == 200
    assert client.get("/").status_code == 404
