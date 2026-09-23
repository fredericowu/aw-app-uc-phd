"""TestClient coverage for uc_phd_app/api/bibliography.py.

Asserts HTTP against a freshly built sub-app, the same way
tests/test_routes.py does — no framework runtime involved.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from uc_phd_app import bibliography
from uc_phd_app.routes import build_routes


@pytest.fixture()
def client(live_db):
    return TestClient(build_routes())


def test_summary_route_serves_the_distribution_and_both_caveats(client):
    body = client.get("/api/bibliography/summary").json()
    assert body["references_total"] == 5
    assert body["cited_by_histogram"] == {"1": 3, "2": 2}
    assert body["default_min_cited_by"] == bibliography.DEFAULT_MIN_CITED_BY
    assert body["caveat"] == bibliography.BIBLIOGRAPHY_CAVEAT
    assert body["match_tier_caveat"] == bibliography.MATCH_TIER_CAVEAT


def test_listing_defaults_to_the_documented_floor(client):
    body = client.get("/api/bibliography").json()
    assert body["min_cited_by"] == bibliography.DEFAULT_MIN_CITED_BY
    assert body["total"] == 2


def test_listing_honours_floor_search_tier_and_paging(client):
    body = client.get("/api/bibliography?min_cited_by=1&limit=2&offset=0").json()
    assert body["total"] == 5 and len(body["references"]) == 2
    assert client.get("/api/bibliography?min_cited_by=1&q=Xception").json()["total"] == 1
    assert client.get("/api/bibliography?min_cited_by=1&tier=doi").json()["total"] == 2


def test_an_unknown_tier_is_a_400_naming_the_valid_ones(client):
    response = client.get("/api/bibliography?tier=nope")
    assert response.status_code == 400
    assert "doi" in response.json()["detail"]


def test_min_cited_by_zero_is_rejected_by_validation(client):
    """ge=1: a floor of 0 means the same as 1 and reads as a bug."""
    assert client.get("/api/bibliography?min_cited_by=0").status_code == 422


def test_limit_is_capped_at_the_documented_page_size(client):
    assert client.get(f"/api/bibliography?limit={bibliography.MAX_PAGE_SIZE}").status_code == 200
    assert client.get(f"/api/bibliography?limit={bibliography.MAX_PAGE_SIZE + 1}").status_code == 422


def test_detail_route_returns_the_citing_theses_with_their_own_wording(client):
    body = client.get("/api/bibliography/1").json()
    assert body["cited_by"] == 2
    assert body["doi"] == "10.1109/32.666826"
    assert len({t["entry_raw"] for t in body["theses"]}) == 2
    # `handle` is the key the SPA's thesis route needs to link through.
    assert all("handle" in t for t in body["theses"])


def test_detail_route_404s_for_an_unknown_id(client):
    response = client.get("/api/bibliography/999999")
    assert response.status_code == 404
    assert "999999" in response.json()["detail"]


def test_theses_route_is_not_swallowed_by_the_detail_route(client):
    """The ordering trap api/theses.py documents. /bibliography/{id} uses an
    int converter so "theses" could not match it today — pinned anyway,
    because the next route added here might not be an int."""
    body = client.get("/api/bibliography/theses").json()
    assert len(body["theses"]) == 5
    assert body["caveat"] == bibliography.COVERAGE_CAVEAT


def test_healthz_counts_the_bibliography_tables(client):
    """A table missing from table_counts() is a table nobody notices is
    empty after a bad seed."""
    counts = client.get("/healthz").json()["row_counts"]
    assert counts["bib_references"] == 5
    assert counts["thesis_references"] == 7
