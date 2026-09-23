"""TestClient coverage for uc_phd_app/routes.py's build_routes().

Builds the sub-app fresh per test (``build_routes()`` must stay
call-idempotent — ``plugin.py`` and ``__main__.py`` both call it) and asserts
HTTP against it directly, with no framework runtime involved.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from uc_phd_app import db
from uc_phd_app.routes import build_routes


@pytest.fixture()
def client(live_db):
    db.load_query.cache_clear()
    return TestClient(build_routes())


# ── the ordering trap ───────────────────────────────────────────────────────


def test_static_mount_does_not_swallow_the_api(client):
    """THE regression test for this app.

    ``StaticFiles(html=True)`` is mounted at "/" and a Starlette ``Mount("/")``
    matches everything, so an API router registered after it is not 404'd —
    it is answered with index.html, which surfaces as a JSON parse error in
    the browser with no hint about the cause. This asserts both halves at
    once: the static mount is present AND the API still answers JSON.
    """
    assert any(getattr(r, "name", None) == "ui" for r in build_routes().routes), (
        "ui/dist is not built in this checkout — run `npm run build` in ui/; "
        "without the static mount this test proves nothing"
    )

    resp = client.get("/api/coverage")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "coverage" in resp.json()


def test_spa_is_served_at_the_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# ── healthz ─────────────────────────────────────────────────────────────────


def test_healthz_reports_db_path_row_counts_and_seed_provenance(client, live_db):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["db_path"] == str(live_db)
    assert body["db_exists"] is True
    assert body["row_counts"]["projects"] == 3
    assert body["row_counts"]["research_groups"] == 2
    assert "app_version" in body["seed"]


def test_healthz_is_degraded_rather_than_500_without_a_database(isolated_data_dir):
    # No live_db fixture here: the data dir is empty.
    body = TestClient(build_routes()).get("/healthz").json()
    assert body["status"] == "degraded"
    assert body["db_exists"] is False
    assert "error" in body


# ── one endpoint per committed sql/ file ────────────────────────────────────


def test_coverage_counts_come_from_the_committed_query(client):
    c = client.get("/api/coverage").json()["coverage"]
    assert c["total_projects"] == 3
    assert c["detail_fetched_ok"] == 2
    assert c["detail_unavailable"] == 1
    assert c["null_titles"] == 0
    assert c["site_total_data"] == 3
    assert c["scrape_targets_rows"] == 3
    assert c["scrape_targets_terminal"] == 3


def test_groups_carries_the_many_to_many_caveat(client):
    body = client.get("/api/groups").json()
    counts = {g["code"]: g["project_count"] for g in body["groups"]}
    assert counts == {"NCS": 2, "AC": 1}
    # 2 + 1 = 3 memberships across 2 projects-with-a-group: the caveat is not
    # decoration, the numbers really do over-sum.
    assert "more than one research group" in body["caveat"]


def test_budget_by_group_and_by_year(client):
    groups = client.get("/api/budget/by-group").json()["groups"]
    assert {g["code"]: g["total_budget_sum"] for g in groups} == {"NCS": 1500.0, "AC": 1000.0}

    years = client.get("/api/budget/by-year").json()["years"]
    assert {y["start_year"]: y["total_budget_sum"] for y in years} == {
        "2020": 1000.0,
        "2021": 500.0,
    }


def test_timeline_and_funding_and_coordinators(client):
    years = client.get("/api/timeline").json()["years"]
    assert {y["start_year"]: y["project_count"] for y in years} == {"2020": 1, "2021": 1}

    funders = client.get("/api/funding").json()["funders"]
    assert {f["funder"]: f["project_count"] for f in funders} == {"FCT": 2}

    coord_body = client.get("/api/coordinators").json()
    # Ada coordinates both projects: Alpha (NCS + AC) and Beta (NCS), so her
    # bar genuinely stacks two segments rather than picking one group.
    assert coord_body["coordinators"] == [
        {
            "coordinator_slug": "ada",
            "coordinator": "Ada Lovelace",
            "project_count": 2,
            "NCS": 2,
            "AC": 1,
        }
    ]
    assert coord_body["group_names"] == {
        "NCS": "Networks, Communications and Security",
        "AC": "Adaptive Computation",
    }
    assert "slug" in coord_body["caveat"]
    assert "UNGROUPED" in coord_body["caveat"]


# ── top projects ────────────────────────────────────────────────────────────


def test_top_projects_for_one_group_surfaces_the_proxy_caveat(client):
    body = client.get("/api/groups/NCS/top-projects").json()
    assert body["code"] == "NCS"
    assert body["name"] == "Networks, Communications and Security"
    assert [p["title"] for p in body["projects"]] == ["Alpha Project", "Beta Project"]
    assert [p["rank_in_group"] for p in body["projects"]] == [1, 2]
    assert "proxy" in body["caveat"]
    # detail_url is what the UI links to; losing it would make the table dead.
    assert body["projects"][0]["detail_url"] == "https://example.test/alpha"


def test_top_projects_for_an_unknown_group_is_404(client):
    assert client.get("/api/groups/NOPE/top-projects").status_code == 404


def test_top_projects_all_groups_is_grouped_and_keeps_the_caveat(client):
    body = client.get("/api/top-projects").json()
    assert {g["code"] for g in body["groups"]} == {"NCS", "AC"}
    # Alpha is in two groups, so it legitimately appears in both top lists.
    for group in body["groups"]:
        assert "Alpha Project" in [p["title"] for p in group["projects"]]
    assert "proxy" in body["caveat"]


# ── list and detail ─────────────────────────────────────────────────────────


def test_projects_list_is_paged_and_reports_group_membership(client):
    body = client.get("/api/projects?limit=2&offset=0").json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert len(body["projects"]) == 2
    alpha = next(p for p in body["projects"] if p["title"] == "Alpha Project")
    assert alpha["groups"] == ["AC", "NCS"]
    stub = client.get("/api/projects?limit=10&offset=2").json()["projects"]
    assert stub[0]["groups"] == []


def test_projects_list_filters_by_group_and_title(client):
    assert client.get("/api/projects?group=AC").json()["total"] == 1
    assert client.get("/api/projects?q=beta").json()["total"] == 1
    assert client.get("/api/projects?q=  ").json()["total"] == 3
    assert client.get("/api/projects?group=AC&q=beta").json()["total"] == 0


def test_project_search_treats_like_wildcards_as_literal_characters(client):
    """A user searching for "%" means the character. Without escaping, "%"
    matches every row and the result set looks plausible but is wrong."""
    assert client.get("/api/projects?q=%25").json()["total"] == 0
    assert client.get("/api/projects?q=_").json()["total"] == 0


def test_project_detail_includes_the_raw_field_pairs(client):
    p = client.get("/api/projects/1").json()["project"]
    assert p["title"] == "Alpha Project"
    assert p["synopsis"] == "Alpha solves A."
    assert [g["code"] for g in p["groups"]] == ["AC", "NCS"]
    # Coordinator first, then researchers — the UI relies on that order.
    assert [(x["name"], x["role"]) for x in p["people"]] == [
        ("Ada Lovelace", "coordinator"),
        ("Alan Turing", "researcher"),
    ]
    assert p["keywords"] == ["networks", "security"]
    raw = {f["label"]: f for f in p["fields_raw"]}
    assert "Keywords" in raw, "the catch-all table is the whole point of this view"
    assert raw["coordinator"]["href"] == "https://example.test/people/ada"


def test_project_detail_404s_for_an_unknown_id(client):
    assert client.get("/api/projects/999").status_code == 404


def test_routes_are_relative_so_both_modes_expose_the_same_shape():
    """No path in the sub-app may carry the /api/apps/<slug> prefix — the
    runtime adds it in integrated mode and __main__ adds it in standalone."""
    paths = [r.path for r in build_routes().routes if hasattr(r, "path")]
    assert not any(p.startswith("/api/apps/") for p in paths)
    assert "/healthz" in paths
