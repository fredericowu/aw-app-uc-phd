"""Degraded-state + happy-path coverage for /api/search and /api/index/status
(S3's "never look like no results" contract).

``fastembed`` has never been installed in this dev/test environment (that is
itself one of S3's real findings — see ``uc_phd_app/store.py``'s
``model_loaded``/``load_model``), so:

* The degraded-state tests exercise ``VectorStore.probe_state()`` for real,
  against a fake db double — no model needed, since a degraded probe never
  reaches embedding.
* ``test_index_status_reports_the_model_did_not_load`` exercises the ACTUAL
  absence of fastembed in this environment — it is not a mock, it is the
  real "pip_requires failed silently" case S3's first acceptance criterion
  is about.
* The one happy-path test monkeypatches only ``store.embed_query`` (the ONNX
  call), so the rest of the request — probe, SQL shape via a fake db,
  response formatting — runs for real. The full path with a real embedding
  against real Postgres is verified separately, inside the workspace
  container (see the delivery report), not here.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from uc_phd_app import store as store_mod
from uc_phd_app.routes import build_routes


class _FakeDb:
    """Duck-types ctx.db's execute/execute_multi with a canned outcome."""

    def __init__(self, extension_present=True, table_present=True,
                 search_rows=None, raise_on_execute=None):
        self.extension_present = extension_present
        self.table_present = table_present
        self.search_rows = search_rows or []
        self.raise_on_execute = raise_on_execute

    def execute(self, name, sql, params=None):
        if self.raise_on_execute:
            raise self.raise_on_execute
        if "pg_extension" in sql:
            return [(1,)] if self.extension_present else []
        if "to_regclass" in sql:
            return [(self.table_present,)]
        if "count(*)" in sql:
            return [(len(self.search_rows),)]
        raise AssertionError(f"unexpected execute: {sql!r}")

    def execute_multi(self, sql, names, params=None):
        return self.search_rows


def _client(store: store_mod.VectorStore) -> TestClient:
    return TestClient(build_routes(store=store))


# ── degraded states ──────────────────────────────────────────────────────


def test_search_returns_typed_503_when_no_store_is_wired():
    """Standalone-with-no-Postgres shape: build_routes(store=None)."""
    resp = _client(store_mod.VectorStore(None)).get("/api/search", params={"q": "x"})
    assert resp.status_code == 503
    body = resp.json()["detail"]
    assert body["error"] == "unavailable"
    assert "no vector store wired" in body["reason"]


def test_search_returns_typed_503_when_extension_is_missing():
    store = store_mod.VectorStore(_FakeDb(extension_present=False))
    resp = _client(store).get("/api/search", params={"q": "x"})
    assert resp.status_code == 503
    body = resp.json()["detail"]
    assert body["error"] == "missing_extension"
    assert "vector" in body["reason"]


def test_search_returns_typed_503_when_the_table_is_missing():
    """A failed migration is logged, not raised — this is what a caller
    actually sees instead: a table probe that comes back empty."""
    store = store_mod.VectorStore(_FakeDb(extension_present=True, table_present=False))
    resp = _client(store).get("/api/search", params={"q": "x"})
    assert resp.status_code == 503
    body = resp.json()["detail"]
    assert body["error"] == "unavailable"
    assert "chunks" in body["reason"]


def test_search_returns_typed_503_when_the_database_is_unreachable():
    store = store_mod.VectorStore(_FakeDb(raise_on_execute=RuntimeError("connection refused")))
    resp = _client(store).get("/api/search", params={"q": "x"})
    assert resp.status_code == 503
    body = resp.json()["detail"]
    assert body["error"] == "unavailable"
    assert "connection refused" in body["reason"]


def test_search_never_answers_a_degraded_store_with_an_empty_result_list():
    """The whole point of the 503 contract: a degraded store must not be
    indistinguishable from "zero matches"."""
    resp = _client(store_mod.VectorStore(None)).get("/api/search", params={"q": "x"})
    assert resp.status_code != 200
    assert resp.json() != {"results": []}


# ── happy path (embedding monkeypatched, everything else real) ───────────


def test_search_happy_path_carries_handle_and_source_url(monkeypatch):
    monkeypatch.setattr(store_mod, "embed_query", lambda text: [0.0] * store_mod.VECTOR_DIM)
    rows = [("10316/117599", "Audiovisual Metaphors",
              "https://estudogeral.uc.pt/handle/10316/117599", True, 0,
              "some chunk text here", 0.1234)]
    store = store_mod.VectorStore(_FakeDb(search_rows=rows))
    resp = _client(store).get("/api/search", params={"q": "audiovisual", "k": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"][0]["handle"] == "10316/117599"
    assert body["results"][0]["source_url"].startswith("https://estudogeral.uc.pt")
    assert body["results"][0]["full_text"] is True
    assert "embed_ms" in body and "db_ms" in body


def test_search_marks_the_embargoed_thesis_as_abstract_only(monkeypatch):
    """full_text=False on a result is how a caller distinguishes a hit on
    the embargoed thesis's abstract from a hit on real full text."""
    monkeypatch.setattr(store_mod, "embed_query", lambda text: [0.0] * store_mod.VECTOR_DIM)
    rows = [("10316/119251", "Deep Learning in Drug Development",
              "https://estudogeral.uc.pt/handle/10316/119251", False, 0,
              "abstract-only chunk", 0.3)]
    store = store_mod.VectorStore(_FakeDb(search_rows=rows))
    resp = _client(store).get("/api/search", params={"q": "drug design"})
    assert resp.status_code == 200
    assert resp.json()["results"][0]["full_text"] is False


# ── /api/index/status ──────────────────────────────────────────────────


def test_index_status_reports_the_model_did_not_load():
    """fastembed is not installed in this test environment — this is the
    REAL "pip_requires failed silently" case, not a simulation of it. S3's
    first acceptance criterion is exactly this: report the model state, not
    just that the route answers."""
    store_mod._model = None  # this process may have set it in another test
    store = store_mod.VectorStore(_FakeDb())
    resp = _client(store).get("/api/index/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["model_loaded"] is False
    assert body["model_error"]
    assert body["model_name"] == store_mod.MODEL_NAME
    assert body["vector_store"]["state"] == "ready"


def test_index_status_reports_the_model_loaded_when_it_actually_does(fake_fastembed):
    store_mod._model = None
    store = store_mod.VectorStore(_FakeDb())
    resp = _client(store).get("/api/index/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["model_loaded"] is True
    assert body["model_error"] is None
    assert body["stats"] == {"documents": 0, "chunks": 0}


def test_index_status_reports_vector_store_state_even_without_the_model():
    store = store_mod.VectorStore(_FakeDb(extension_present=False))
    resp = _client(store).get("/api/index/status")
    assert resp.status_code == 200
    assert resp.json()["vector_store"]["state"] == "missing_extension"


def test_index_status_carries_the_latency_block():
    """Not enough samples yet (a fresh VectorStore), but the block must be
    present with its loadavg — the two-watches replacement for the retired
    150ms search-stage trigger."""
    store = store_mod.VectorStore(_FakeDb())
    resp = _client(store).get("/api/index/status")
    body = resp.json()
    assert body["latency"]["evaluated"] is False
    assert body["latency"]["window_size"] == 0
    assert "loadavg1" in body["latency"]


# ── healthz ────────────────────────────────────────────────────────────


def test_healthz_carries_the_search_block(live_db):
    store = store_mod.VectorStore(_FakeDb(extension_present=False))
    resp = _client(store).get("/healthz")
    assert resp.json()["search"]["state"] == "missing_extension"


def test_healthz_carries_the_latency_block(live_db):
    store = store_mod.VectorStore(_FakeDb())
    resp = _client(store).get("/healthz")
    assert "loadavg1" in resp.json()["latency"]
