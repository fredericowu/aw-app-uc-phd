"""Unit tests for uc_phd_app/plugin.py — this app's whole aw-workspace
integration surface.

``ctx`` is a lightweight double, not the real runtime: activate() touches
``ctx.routes`` (register the sub-app), ``ctx.db`` (probe the pgvector
store), and ``ctx.notify`` (only when that probe comes back degraded).
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from uc_phd_app import paths
from uc_phd_app.plugin import UcPhdAppPlugin
from tests.conftest import ROOT, build_fixture_db

MANIFEST = json.loads((ROOT / "aw-app.json").read_text())


@pytest.fixture()
def packaged_seed(tmp_path, monkeypatch):
    pkg = tmp_path / "pkg"
    (pkg / "data").mkdir(parents=True)
    build_fixture_db(pkg / "data" / "cisuc.sqlite3")
    (pkg / "aw-app.json").write_text(json.dumps({"version": "0.1.0"}))
    monkeypatch.setattr(paths, "PACKAGE_ROOT", pkg)
    return pkg


def test_activate_seeds_the_database_then_registers_routes(packaged_seed):
    ctx = MagicMock()

    asyncio.run(UcPhdAppPlugin().activate(ctx))

    assert paths.live_db_path().is_file(), "routes are useless without a database"
    ctx.routes.register.assert_called_once()
    registered = ctx.routes.register.call_args[0][0]
    assert [r.path for r in registered.routes if hasattr(r, "path")].count("/healthz") == 1


def test_activate_is_idempotent(packaged_seed):
    """The reconciler re-runs activate on every boot and once per worker."""
    for _ in range(3):
        asyncio.run(UcPhdAppPlugin().activate(MagicMock()))
    assert paths.live_db_path().is_file()


def test_activate_installs_no_system_cli(packaged_seed):
    """This app contributes no CLI, so it must never touch ctx.commands — it
    does not request `commands:install` and the call would be refused."""
    ctx = MagicMock()

    asyncio.run(UcPhdAppPlugin().activate(ctx))

    ctx.commands.install_system_cli.assert_not_called()


class _DegradedDb:
    """Duck-types ctx.db with an always-missing extension — see
    uc_phd_app/store.py's VectorStore.probe_state()."""

    def execute(self, name, sql, params=None):
        return []


def test_activate_notifies_when_the_vector_store_is_degraded(packaged_seed):
    ctx = MagicMock()
    ctx.db = _DegradedDb()

    asyncio.run(UcPhdAppPlugin().activate(ctx))

    ctx.notify.assert_called_once()
    message = ctx.notify.call_args[0][0]
    assert "missing_extension" in message


def test_deactivate_completes_without_touching_ctx():
    assert asyncio.run(UcPhdAppPlugin().deactivate()) is None


# ── manifest invariants the app's design depends on ─────────────────────────


def test_manifest_requests_only_low_risk_permissions():
    """This app is distributed through the public catalog and IS signed, but
    the capability set stays free of any high-risk entry regardless — that
    is what keeps `filter_grants`'s unsigned-app leniency irrelevant here.
    `db:own-tables` (added for S3's pgvector store) is `risk: low` too — no
    signing gate, same invariant holds.
    """
    assert sorted(MANIFEST["permissions"]) == [
        "db:own-tables", "fs:workspace-data", "net:outbound", "routes:register",
    ]


def test_manifest_has_no_component_frontend():
    """A `component`-mode bundle needs `ui:code`, which is high risk. Refused,
    it renders every window body empty with the chrome intact — which reads as
    a bug in the app rather than a permission problem."""
    assert "frontend" not in MANIFEST["contributes"]


def test_manifest_window_is_a_managed_app_namespaced_under_the_app_id():
    windows = MANIFEST["contributes"]["windows"]
    assert len(windows) == 1
    assert windows[0]["id"] == f"{MANIFEST['id']}.main"
    assert windows[0]["body"]["type"] == "managed_app"


def test_manifest_entrypoint_and_route_prefix_match_the_package():
    assert MANIFEST["runtime"]["entrypoint"] == "uc_phd_app.plugin:UcPhdAppPlugin"
    assert MANIFEST["runtime"]["standalone"]["module"] == "uc_phd_app"
    assert MANIFEST["contributes"]["routes"][0]["prefix"] == f"/api/apps/{MANIFEST['id']}"


def test_package_version_helper_reads_the_real_manifest():
    assert paths.package_version() == MANIFEST["version"]
