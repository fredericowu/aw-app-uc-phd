"""/api/profile and /api/fit — the Fit screen's HTTP surface.

Same testing stance as tests/test_search_routes.py: the ONNX call is the only
thing monkeypatched, so the probe, the SQL shape, the max-over-facets fusion
and the response formatting all run for real against a fake db double. The
full path with real embeddings against real Postgres is verified separately
(see the delivery report), not here.

The fake db returns per-facet distance columns in the same shape the real
query produces, so the fusion arithmetic under test is the real one.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from uc_phd_app import profile as profile_mod
from uc_phd_app import store as store_mod
from uc_phd_app.api import fit as fit_api
from uc_phd_app.routes import build_routes


class _FakeDb:
    """Duck-types ctx.db's execute/execute_multi for the documents/chunks
    queries the Fit path issues."""

    def __init__(self, *, extension_present=True, table_present=True,
                 match_rows=None, evidence_rows=None, coverage=(18, 18),
                 raise_on_execute=None, document_rows=None):
        self.extension_present = extension_present
        self.table_present = table_present
        self.match_rows = match_rows or []
        self.evidence_rows = evidence_rows
        self.coverage = coverage
        self.raise_on_execute = raise_on_execute
        self.document_rows = document_rows
        self.seen = []

    def execute(self, name, sql, params=None):
        self.seen.append(sql)
        if self.raise_on_execute:
            raise self.raise_on_execute
        if "abstract_embedding <=>" in sql and "count(" not in sql:
            # The real query builds one distance column per facet. Trim the
            # canned rows to match, so a test that edits the profile to N
            # interests cannot feed back a row shaped for the old N.
            n = sum(1 for key in (params or {}) if key.startswith("f"))
            return [r[:4] + r[4:4 + n] for r in self.match_rows]
        if "pg_extension" in sql:
            return [(1,)] if self.extension_present else []
        if "to_regclass" in sql:
            return [(self.table_present,)]
        if "count(abstract_embedding)" in sql:
            return [self.coverage]
        if "abstract_embedding IS NOT NULL FROM" in sql:
            return self.document_rows or []
        if "CROSS JOIN LATERAL" in sql:
            return self.evidence_rows if self.evidence_rows is not None else []
        if "abstract_embedding <=>" in sql:
            return self.match_rows
        if "count(*)" in sql:
            return [(0,)]
        raise AssertionError(f"unexpected execute: {sql!r}")

    def execute_multi(self, sql, names, params=None):  # pragma: no cover - unused here
        return []


@pytest.fixture(autouse=True)
def _live_db(live_db):
    """Every /api/fit response names supervisors, and that join reads the live
    SQLite database — so the fixture DB has to be installed for the whole
    module, not only for the tests that assert on names."""
    return live_db


@pytest.fixture(autouse=True)
def _no_real_embedding(monkeypatch):
    """Deterministic stand-in for the 520 MB ONNX model: facet i becomes the
    i-th basis vector, which keeps the fusion arithmetic checkable by hand."""
    store_mod._facet_cache.clear()

    def fake_embed_query(text):
        vec = [0.0] * store_mod.VECTOR_DIM
        vec[abs(hash(text)) % store_mod.VECTOR_DIM] = 1.0
        return vec

    monkeypatch.setattr(store_mod, "embed_query", fake_embed_query)


def _client(store):
    return TestClient(build_routes(store=store))


def _ready(**kw):
    return store_mod.VectorStore(_FakeDb(**kw))


# ── GET/PUT /api/profile ────────────────────────────────────────────────


def test_get_profile_returns_the_seeded_interests_and_body():
    resp = _client(_ready()).get("/api/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["interests"]) >= 1
    assert body["differs_from_seed"] is False
    # The prose is returned for display but is never what gets embedded.
    assert body["body"]


def test_put_profile_replaces_the_interests_and_flags_divergence():
    client = _client(_ready())
    resp = client.put("/api/profile", json={"interests": ["computational creativity"]})
    assert resp.status_code == 200
    assert resp.json()["interests"] == ["computational creativity"]
    assert resp.json()["differs_from_seed"] is True
    assert client.get("/api/profile").json()["interests"] == ["computational creativity"]


def test_put_profile_can_replace_the_body_too():
    client = _client(_ready())
    resp = client.put("/api/profile", json={"interests": ["ai"], "body": "new prose"})
    assert resp.json()["body"] == "new prose"


def test_put_profile_without_interests_is_a_400():
    resp = _client(_ready()).put("/api/profile", json={"body": "x"})
    assert resp.status_code == 400
    assert "interests" in resp.json()["detail"]


def test_put_profile_with_an_invalid_list_is_a_400_not_a_500():
    resp = _client(_ready()).put("/api/profile", json={"interests": []})
    assert resp.status_code == 400
    assert "at least one interest" in resp.json()["detail"]


def test_reset_restores_the_committed_profile():
    client = _client(_ready())
    client.put("/api/profile", json={"interests": ["computational creativity"]})
    resp = client.post("/api/profile/reset")
    assert resp.status_code == 200
    assert resp.json()["differs_from_seed"] is False


# ── degraded states: never an empty result list ─────────────────────────


def test_fit_returns_typed_503_when_no_store_is_wired():
    resp = _client(store_mod.VectorStore(None)).get("/api/fit")
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "unavailable"


def test_fit_returns_typed_503_when_the_extension_is_missing():
    resp = _client(_ready(extension_present=False)).get("/api/fit")
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "missing_extension"


def test_fit_returns_typed_503_when_the_database_is_unreachable():
    store = store_mod.VectorStore(_FakeDb(raise_on_execute=RuntimeError("connection refused")))
    resp = _client(store).get("/api/fit")
    assert resp.status_code == 503
    assert "connection refused" in resp.json()["detail"]["reason"]


def test_fit_never_answers_a_degraded_store_with_an_empty_result_list():
    """A Fit query CAN legitimately match nothing, so a broken store must not
    be able to produce the same response shape as a real answer."""
    resp = _client(store_mod.VectorStore(None)).get("/api/fit")
    assert resp.status_code != 200
    assert "results" not in resp.json()


def test_fit_reports_an_invalid_profile_as_a_400():
    client = _client(_ready())
    # Write a corrupt profile the way another process would.
    from uc_phd_app import paths
    paths.live_profile_path().write_text("not a profile", encoding="utf-8")
    resp = client.get("/api/fit")
    assert resp.status_code == 400


# ── ranking ─────────────────────────────────────────────────────────────

# handle, title, source_url, full_text, then one distance per facet.
# Handles match tests/conftest.py's fixture database so the REAL
# thesis_people join runs: 000001 has two resolved supervisors, 000003 has an
# ambiguous (unresolved) one, 000002 has none at all.
_ROWS = [
    ("10316/000001", "Thesis A",
     "https://estudogeral.uc.pt/handle/10316/000001", True, 0.41, 0.33, 0.44, 0.47),
    ("10316/000003", "Thesis C",
     "https://estudogeral.uc.pt/handle/10316/000003", True, 0.45, 0.34, 0.35, 0.46),
    ("10316/000002", "Thesis B",
     "https://estudogeral.uc.pt/handle/10316/000002", False, 0.38, 0.49, 0.50, 0.51),
]
_EVIDENCE = [
    ("10316/000001", 12, "fog  computing   resource allocation passage"),
    ("10316/000003", 3, "microservice security passage"),
    ("10316/000002", 1, "drug development abstract passage"),
]


def _matched(**kw):
    return _client(_ready(match_rows=_ROWS, evidence_rows=_EVIDENCE, **kw)).get("/api/fit")


def test_fit_ranks_theses_and_names_the_interest_that_matched():
    body = _matched().json()
    assert [r["rank"] for r in body["results"]] == [1, 2, 3]
    assert body["results"][0]["handle"] == "10316/000001"
    # Facet 1 (0.33) beats facets 0/2/3 for the first row — max-over-facets.
    assert body["results"][0]["facet_index"] == 1
    assert body["results"][0]["matched_interest"] == body["interests"][1]
    # Row 3's best facet is 0 (0.38), not 1 — the winner is per-thesis.
    assert body["results"][2]["facet_index"] == 0


def test_fit_fuses_by_max_similarity_not_by_mean():
    """The reported distance is the MINIMUM over facets (= max similarity),
    never their average — averaging is the failure the facet split undoes."""
    r = _matched().json()["results"][0]
    assert r["distance"] == pytest.approx(0.33)
    assert r["distance"] == pytest.approx(min(r["facet_distances"]))


def test_fit_carries_source_url_and_an_evidence_passage():
    r = _matched().json()["results"][0]
    assert r["source_url"].startswith("https://estudogeral.uc.pt")
    # Whitespace-collapsed real chunk text, not the abstract it ranked on.
    assert r["snippet"] == "fog computing resource allocation passage"
    assert r["ordinal"] == 12


def test_fit_marks_the_embargoed_thesis_as_abstract_only():
    body = _matched().json()
    assert body["results"][2]["full_text"] is False


def test_fit_states_the_corpus_it_searched():
    body = _matched().json()
    assert body["coverage"]["matchable"] == 18
    assert body["coverage"]["dei_doctoral_total"] == fit_api.DEI_DOCTORAL_TOTAL
    assert "18" in body["corpus_note"] and "181" in body["corpus_note"]


def test_fit_reports_theses_that_cannot_be_matched_at_all():
    """A thesis with no abstract gets a NULL vector and ranks nowhere — it
    must be counted, not silently absent."""
    body = _matched(coverage=(18, 16)).json()
    assert body["coverage"]["unmatchable"] == 2


def test_fit_returns_no_percentage_match_score():
    """All 18 are computing PhDs and score in a narrow band, so a percentage
    would read as precision that does not exist (PO/Architect decision)."""
    r = _matched().json()["results"][0]
    assert "score" not in r
    assert "match" not in r
    assert not any(isinstance(v, str) and v.endswith("%") for v in r.values())


def test_fit_survives_a_thesis_with_an_abstract_vector_but_no_chunks():
    """A partial ingest must cost that thesis its passage, not its place."""
    body = _client(_ready(match_rows=_ROWS, evidence_rows=[_EVIDENCE[0]])).get("/api/fit").json()
    assert len(body["results"]) == 3
    assert body["results"][1]["snippet"] is None


def test_fit_honours_k_and_clamps_it():
    client = _client(_ready(match_rows=_ROWS, evidence_rows=_EVIDENCE))
    assert client.get("/api/fit", params={"k": 999}).status_code == 200
    assert client.get("/api/fit", params={"k": 0}).status_code == 200


def test_fit_returns_at_least_five_theses_when_the_corpus_has_them():
    """PO acceptance #1: >=5 theses. Per-thesis ranking makes that structural
    — one row per thesis, so k distinct theses is guaranteed, unlike chunk
    ranking where one long thesis can occupy every slot."""
    rows = [(f"10316/{i}", f"Thesis {i}", f"https://estudogeral.uc.pt/handle/10316/{i}",
             True, 0.3 + i / 100, 0.9, 0.9, 0.9) for i in range(6)]
    body = _client(_ready(match_rows=rows, evidence_rows=[])).get("/api/fit").json()
    assert len({r["handle"] for r in body["results"]}) >= 5


def test_editing_the_profile_changes_the_query_vectors():
    """PO acceptance #2, at the unit level: the profile really is the input.
    The end-to-end falsifiability check against the real model and corpus is
    in the delivery report."""
    client = _client(_ready(match_rows=_ROWS, evidence_rows=_EVIDENCE))
    before = client.get("/api/fit").json()["interests"]
    client.put("/api/profile", json={"interests": ["computational creativity"]})
    after = client.get("/api/fit").json()["interests"]
    assert before != after
    assert after == ["computational creativity"]


# ── supervisors, from the identity spine ────────────────────────────────


def test_every_result_names_its_real_supervisors(live_db):
    """PO acceptance #1. Names come from thesis_people, not front matter."""
    body = _matched().json()
    first = next(r for r in body["results"] if r["handle"] == "10316/000001")
    assert sorted(s["name"] for s in first["supervisors"]) == [
        "Hopper, Grace", "Lovelace, Ada"]
    assert all(s["status"] == "matched" for s in first["supervisors"])


def test_a_thesis_with_no_recorded_supervisor_returns_an_empty_list(live_db):
    """Not an error and not a guess — 000002 genuinely has no supervisor row."""
    body = _matched().json()
    none = next(r for r in body["results"] if r["handle"] == "10316/000002")
    assert none["supervisors"] == []


def test_an_unresolved_supervisor_name_still_renders_flagged(live_db):
    """The committed query LEFT JOINs for exactly this. A name the matcher
    could not resolve is shown with its raw name and its tier — dropping it
    would quietly shrink the list of people he could approach."""
    body = _matched().json()
    ambiguous = next(r for r in body["results"] if r["handle"] == "10316/000003")
    assert [s["name"] for s in ambiguous["supervisors"]] == ["Ambiguous, Two People"]
    assert ambiguous["supervisors"][0]["status"] == "unattributed"
    assert ambiguous["supervisors"][0]["match_status"] == "ambiguous"


def test_authors_never_appear_as_supervisors(live_db):
    """role='supervisor' only. 000001's author is unresolved and must not be
    promoted into the supervisor list, and a project coordinator is never an
    orientador — thesis_people has no coordinator role so that conflation
    cannot be reintroduced by a query."""
    body = _matched().json()
    everyone = [s["name"] for r in body["results"] for s in r["supervisors"]]
    assert "Author, Ada Unresolved" not in everyone
    assert "Nobody, At All" not in everyone


def test_the_screen_carries_no_research_group(live_db):
    """PO cut #5 — group attribution is 3.72 of 6 groups per thesis (S7), so
    a group here would look authoritative and mean nothing."""
    body = _matched().json()
    for r in body["results"]:
        for s in r["supervisors"]:
            assert "groups" not in s


# ── the facet embedding cache ───────────────────────────────────────────


def test_facet_vectors_are_cached_on_the_interest_text(monkeypatch):
    calls = []

    def counting_embed(text):
        calls.append(text)
        return [0.0] * store_mod.VECTOR_DIM

    monkeypatch.setattr(store_mod, "embed_query", counting_embed)
    store_mod._facet_cache.clear()
    store_mod.embed_facets(["a", "b"])
    assert len(calls) == 2
    store_mod.embed_facets(["a", "b"])
    assert len(calls) == 2  # served from cache
    store_mod.embed_facets(["a", "c"])
    assert len(calls) == 4  # different content -> different key


def test_the_facet_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(store_mod, "embed_query", lambda t: [0.0] * store_mod.VECTOR_DIM)
    store_mod._facet_cache.clear()
    for i in range(store_mod._FACET_CACHE_MAX + 3):
        store_mod.embed_facets([f"interest {i}"])
    assert len(store_mod._facet_cache) <= store_mod._FACET_CACHE_MAX


def test_the_cache_key_is_content_not_identity():
    """At WORKERS>1 there is no cross-process invalidation, so an edit in
    another worker has to miss this worker's cache by content alone."""
    assert store_mod.facet_cache_key(["a", "b"]) == store_mod.facet_cache_key(["a", "b"])
    assert store_mod.facet_cache_key(["a", "b"]) != store_mod.facet_cache_key(["b", "a"])
    # A separator that cannot appear in normalised interest text, so ["ab"]
    # and ["a", "b"] can never collide.
    assert store_mod.facet_cache_key(["ab"]) != store_mod.facet_cache_key(["a", "b"])
