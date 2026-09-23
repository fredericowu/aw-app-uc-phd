"""Tests for the in-process ``phd_knowledge_base`` MCP endpoint
(``uc_phd_app/mcp/http_handler.py`` + ``mcp/tools.py``, mounted as POST/GET
``/mcp`` by ``routes.py``) and self-registration (``mcp/self_register.py``) —
the mechanism aw-mcp-gateway's app-scan uses to auto-discover this app's MCP
tools (S4), no manual wiring needed.

Same doubles as ``test_search_routes.py`` (``_FakeDb`` duck-types
``ctx.db``'s ``execute``/``execute_multi``) and the same fixture DB as
``test_theses.py`` (``live_db``, three theses: A/B/C — see
``tests/conftest.py``).
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from uc_phd_app import store as store_mod
from uc_phd_app.mcp import self_register
from uc_phd_app.routes import build_routes


class _FakeDb:
    """Duck-types ctx.db's execute/execute_multi with a canned outcome —
    copied from test_search_routes.py's double rather than imported, so this
    file stays independently readable."""

    def __init__(self, extension_present=True, table_present=True, search_rows=None):
        self.extension_present = extension_present
        self.table_present = table_present
        self.search_rows = search_rows or []

    def execute(self, name, sql, params=None):
        if "pg_extension" in sql:
            return [(1,)] if self.extension_present else []
        if "to_regclass" in sql:
            return [(self.table_present,)]
        raise AssertionError(f"unexpected execute: {sql!r}")

    def execute_multi(self, sql, names, params=None):
        return self.search_rows


def _client(store: store_mod.VectorStore | None = None) -> TestClient:
    return TestClient(build_routes(store=store))


def _call(client, name, arguments=None, req_id=1):
    return client.post("/mcp", json={
        "jsonrpc": "2.0", "id": req_id, "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    })


def _text(resp):
    return resp.json()["result"]["content"][0]["text"]


# ── JSON-RPC framing ─────────────────────────────────────────────────────


def test_initialize():
    resp = _client().post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert resp.status_code == 200
    assert resp.json()["result"]["serverInfo"]["name"] == "phd_knowledge_base"


def test_tools_list_includes_all_three_tools():
    resp = _client().post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in resp.json()["result"]["tools"]}
    assert names == {"search_phd_theses", "get_phd_thesis", "list_phd_theses"}


def test_get_mcp_returns_405():
    assert _client().get("/mcp").status_code == 405


def test_notification_returns_202():
    resp = _client().post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp.status_code == 202


def test_unknown_method_is_a_jsonrpc_error():
    resp = _client().post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "not/a/method"})
    assert resp.json()["error"]["code"] == -32601


def test_unknown_tool_is_error():
    resp = _call(_client(), "not_a_real_tool")
    assert resp.json()["result"]["isError"] is True


def test_batched_jsonrpc_requests(live_db):
    resp = _client().post("/mcp", json=[
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "list_phd_theses", "arguments": {}}},
    ])
    assert resp.status_code == 200
    bodies = resp.json()
    assert len(bodies) == 2
    assert bodies[0]["id"] == 1
    assert bodies[1]["id"] == 2


# ── search_phd_theses ────────────────────────────────────────────────────


def test_search_phd_theses_requires_a_query():
    resp = _call(_client(), "search_phd_theses", {})
    assert resp.json()["result"]["isError"] is True
    assert "query is required" in _text(resp)


def test_search_phd_theses_surfaces_a_degraded_store_as_a_tool_error_not_an_empty_list():
    """S3/S4's degraded-store contract: an agent must never be told "no
    results" when the real answer is "the index is down"."""
    resp = _call(_client(store_mod.VectorStore(None)), "search_phd_theses", {"query": "x"})
    body = resp.json()["result"]
    assert body["isError"] is True
    assert "unavailable" in body["content"][0]["text"]


def _search_rows():
    return [
        ("10316/000001", "Thesis A", "https://estudogeral.uc.pt/handle/10316/000001",
         True, 0, "some chunk about thesis A", 0.1),
        ("10316/000002", "Thesis B", "https://estudogeral.uc.pt/handle/10316/000002",
         False, 0, "some chunk about thesis B", 0.2),
    ]


def test_search_phd_theses_happy_path_carries_authors_and_source_url(monkeypatch, live_db):
    monkeypatch.setattr(store_mod, "embed_query", lambda text: [0.0] * store_mod.VECTOR_DIM)
    store = store_mod.VectorStore(_FakeDb(search_rows=_search_rows()))
    resp = _call(_client(store), "search_phd_theses", {"query": "x"})
    assert resp.json()["result"]["isError"] is False
    payload = json.loads(_text(resp))
    assert payload["results"][0]["handle"] == "10316/000001"
    assert payload["results"][0]["authors"] == ["Author, Ada Unresolved"]
    assert payload["results"][0]["source_url"].startswith("https://estudogeral.uc.pt")


def test_search_phd_theses_filters_by_year(monkeypatch, live_db):
    monkeypatch.setattr(store_mod, "embed_query", lambda text: [0.0] * store_mod.VECTOR_DIM)
    store = store_mod.VectorStore(_FakeDb(search_rows=_search_rows()))
    resp = _call(_client(store), "search_phd_theses", {"query": "x", "year": "2025"})
    payload = json.loads(_text(resp))
    assert [r["handle"] for r in payload["results"]] == ["10316/000002"]


def test_search_phd_theses_filters_by_author_case_insensitively(monkeypatch, live_db):
    monkeypatch.setattr(store_mod, "embed_query", lambda text: [0.0] * store_mod.VECTOR_DIM)
    store = store_mod.VectorStore(_FakeDb(search_rows=_search_rows()))
    resp = _call(_client(store), "search_phd_theses", {"query": "x", "author": "turing"})
    payload = json.loads(_text(resp))
    assert [r["handle"] for r in payload["results"]] == ["10316/000002"]


def test_search_phd_theses_respects_limit(monkeypatch, live_db):
    monkeypatch.setattr(store_mod, "embed_query", lambda text: [0.0] * store_mod.VECTOR_DIM)
    store = store_mod.VectorStore(_FakeDb(search_rows=_search_rows()))
    resp = _call(_client(store), "search_phd_theses", {"query": "x", "limit": 1})
    payload = json.loads(_text(resp))
    assert len(payload["results"]) == 1


def test_search_phd_theses_skips_a_hit_with_no_matching_thesis_row(monkeypatch, live_db):
    """A chunk hit for a handle that has since dropped out of the theses seed
    is dropped rather than crashing the whole search."""
    monkeypatch.setattr(store_mod, "embed_query", lambda text: [0.0] * store_mod.VECTOR_DIM)
    rows = [("10316/999999", "Ghost", "https://estudogeral.uc.pt/handle/10316/999999",
              True, 0, "chunk", 0.1)]
    store = store_mod.VectorStore(_FakeDb(search_rows=rows))
    resp = _call(_client(store), "search_phd_theses", {"query": "x"})
    payload = json.loads(_text(resp))
    assert payload["results"] == []


# ── get_phd_thesis ───────────────────────────────────────────────────────


def test_get_phd_thesis_requires_a_handle():
    resp = _call(_client(), "get_phd_thesis", {})
    assert resp.json()["result"]["isError"] is True


def test_get_phd_thesis_unknown_handle_is_error(live_db):
    resp = _call(_client(), "get_phd_thesis", {"handle": "10316/999999"})
    assert resp.json()["result"]["isError"] is True
    assert "no thesis" in _text(resp)


def test_get_phd_thesis_happy_path_carries_abstracts_body_and_source_url(live_db, tmp_path, monkeypatch):
    estudo_geral = tmp_path / "estudo_geral"
    estudo_geral.mkdir()
    (estudo_geral / "10316-000001.md").write_text(
        "---\nhandle: 10316/000001\ntitle: Thesis A\n---\n\nThe extracted body.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AW_APP_UC_PHD_ESTUDO_GERAL_DIR", str(estudo_geral))

    resp = _call(_client(), "get_phd_thesis", {"handle": "10316/000001"})
    assert resp.json()["result"]["isError"] is False
    payload = json.loads(_text(resp))
    assert payload["title"] == "Thesis A"
    assert payload["abstract_pt"] == "Resumo A."
    assert payload["abstract_en"] == "Abstract A."
    assert payload["body"] == "The extracted body.\n"
    assert payload["source_url"] == "https://estudogeral.uc.pt/handle/10316/000001"


# ── list_phd_theses ──────────────────────────────────────────────────────


def test_list_phd_theses_enumerates_everything(live_db):
    resp = _call(_client(), "list_phd_theses", {})
    payload = json.loads(_text(resp))
    assert payload["total"] == 3
    assert {t["handle"] for t in payload["theses"]} == {
        "10316/000001", "10316/000002", "10316/000003",
    }


def test_list_phd_theses_filters_by_year(live_db):
    resp = _call(_client(), "list_phd_theses", {"year": "2024"})
    payload = json.loads(_text(resp))
    assert payload["total"] == 1
    assert payload["theses"][0]["handle"] == "10316/000001"


def test_list_phd_theses_filters_by_group(live_db):
    """A and B both resolve to [AC, NCS] in the fixture (see test_theses.py);
    C resolves to no group at all — so "AC" discriminates {A, B} from {C}."""
    resp = _call(_client(), "list_phd_theses", {"group": "AC"})
    payload = json.loads(_text(resp))
    assert payload["total"] == 2
    assert {t["handle"] for t in payload["theses"]} == {"10316/000001", "10316/000002"}


def test_list_phd_theses_respects_limit(live_db):
    resp = _call(_client(), "list_phd_theses", {"limit": 1})
    payload = json.loads(_text(resp))
    assert payload["total"] == 3
    assert len(payload["theses"]) == 1


# ── self_register.py ─────────────────────────────────────────────────────


def test_register_self_writes_mcp_json(tmp_path, monkeypatch):
    monkeypatch.delenv("AW_WORKSPACE_API_KEY", raising=False)
    self_register.register_self(str(tmp_path), 9482)

    data = json.loads((tmp_path / "mcp.json").read_text())
    entry = data["mcpServers"]["phd_knowledge_base"]
    assert entry["type"] == "http"
    assert entry["url"].endswith(":9482/api/apps/aw-app-uc-phd/mcp")
    assert entry["enabled"] is True
    assert "headers" not in entry


def test_register_self_includes_api_key_header_when_available(tmp_path, monkeypatch):
    monkeypatch.setenv("AW_WORKSPACE_API_KEY", "the-key")
    self_register.register_self(str(tmp_path), 9482)

    data = json.loads((tmp_path / "mcp.json").read_text())
    assert data["mcpServers"]["phd_knowledge_base"]["headers"] == {"X-Api-Key": "the-key"}


def test_register_self_preserves_other_servers_in_existing_mcp_json(tmp_path, monkeypatch):
    monkeypatch.delenv("AW_WORKSPACE_API_KEY", raising=False)
    (tmp_path / "mcp.json").write_text(json.dumps({
        "mcpServers": {"other-app": {"type": "http", "url": "http://x/mcp"}}
    }))

    self_register.register_self(str(tmp_path), 9482)

    data = json.loads((tmp_path / "mcp.json").read_text())
    assert "other-app" in data["mcpServers"]
    assert "phd_knowledge_base" in data["mcpServers"]


def test_register_self_is_idempotent_noop_when_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("AW_WORKSPACE_API_KEY", "the-key")
    self_register.register_self(str(tmp_path), 9482)
    first_mtime = (tmp_path / "mcp.json").stat().st_mtime_ns

    self_register.register_self(str(tmp_path), 9482)
    second_mtime = (tmp_path / "mcp.json").stat().st_mtime_ns
    assert first_mtime == second_mtime


def test_register_self_noops_when_package_dir_missing(tmp_path):
    missing = tmp_path / "does-not-exist"
    self_register.register_self(str(missing), 9482)
    assert not missing.exists()


def test_register_self_logs_rather_than_raises_on_a_write_failure(tmp_path, monkeypatch):
    """WORKERS>1 means register_self runs concurrently in every worker — a
    transient write failure must be swallowed, not crash activate()."""
    def _raise(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(self_register.os, "replace", _raise)
    self_register.register_self(str(tmp_path), 9482)  # must not raise
