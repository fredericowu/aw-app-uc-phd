"""``uc_phd_app/collab.py`` + ``uc_phd_app/api/collab.py``.

Fixture data (see conftest.py's ``build_fixture_db``): 'ada' coordinates
projects 1 and 2, 'alan' researches on project 1 — so (ada, alan) share
exactly 1 project. Alpha (project 1) belongs to both NCS and AC; Beta
(project 2) belongs to NCS only. Thesis 000001 is supervised by 'ada' and
'grace' together — the only co-supervision pair in the fixture. 'grace' is on
no project at all, so she carries no research group.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from uc_phd_app import collab, db
from uc_phd_app.routes import build_routes


@pytest.fixture()
def client(live_db):
    db.load_query.cache_clear()
    return TestClient(build_routes())


# ── uc_phd_app/collab.py ────────────────────────────────────────────────────


def test_co_project_pairs_use_count_distinct_project_not_role_rows(live_db):
    """'ada' holds the coordinator role on both her projects — if the pair
    query grouped by (project_id, person_slug, role) instead of collapsing
    roles first, a person who was ever both coordinator and researcher on
    one project would double that project's weight. The fixture does not
    hit that exact case, but the single project-1 pair must still land at
    weight 1, not 2, proving the DISTINCT membership CTE is doing its job."""
    pairs = {(p["person_a_slug"], p["person_b_slug"]): p for p in collab.enriched_pairs("co_project")}
    assert pairs[("ada", "alan")]["weight"] == 1


def test_co_project_weight_normalized_divides_by_team_size_minus_one(live_db):
    """Project 1 (Alpha) has 2 members (ada, alan) -> team_size=2 ->
    contributes 1/(2-1) = 1.0 to the (ada, alan) pair. Project 2 (Beta) has
    only 'ada' on it -> no pair, no contribution."""
    pairs = {(p["person_a_slug"], p["person_b_slug"]): p for p in collab.enriched_pairs("co_project")}
    assert pairs[("ada", "alan")]["weight_normalized"] == pytest.approx(1.0)


def test_co_project_cross_group_reads_the_persons_own_group_history(live_db):
    """ada's own projects touch NCS and AC (she coordinates both Alpha and
    Beta); alan's only project (Alpha) touches NCS and AC too — so their
    memberships are NOT disjoint and cross_group is False, even though they
    only share one project."""
    pairs = {(p["person_a_slug"], p["person_b_slug"]): p for p in collab.enriched_pairs("co_project")}
    pair = pairs[("ada", "alan")]
    assert sorted(pair["person_a_groups"]) == ["AC", "NCS"]
    assert sorted(pair["person_b_groups"]) == ["AC", "NCS"]
    assert pair["cross_group"] is False


def test_co_supervision_excludes_unmatched_names(live_db):
    """Thesis 000003 has an 'ambiguous' (unresolved) supervisor alongside no
    other supervisor — it contributes no pair at all. Only thesis 000001's
    (ada, grace) pair, both resolved, should appear."""
    pairs = collab.enriched_pairs("co_supervision")
    keys = {(p["person_a_slug"], p["person_b_slug"]) for p in pairs}
    assert keys == {("ada", "grace")}


def test_co_supervision_cross_group_is_none_when_a_person_has_no_groups(live_db):
    """'grace' is on no project at all, so she carries an empty group set —
    cross_group must be null (unknown), never a guessed True/False."""
    pairs = collab.enriched_pairs("co_supervision")
    pair = next(p for p in pairs if {p["person_a_slug"], p["person_b_slug"]} == {"ada", "grace"})
    assert pair["cross_group"] is None
    assert pair["person_b_groups"] == [] or pair["person_a_groups"] == []


def test_summary_reports_people_on_2_or_more_projects(live_db):
    s = collab.summary()
    assert s["total_people"] == 3
    # only 'ada' is on 2+ projects (Alpha and Beta); 'alan' is on 1, 'grace' on 0
    assert s["people_on_multiple_projects"] == 1
    assert s["co_project"]["pair_count"] == 1
    assert s["co_supervision"]["pair_count"] == 1


def test_neighbours_returns_the_other_person_sorted_by_weight(live_db):
    rows = collab.neighbours("ada", "co_project", min_weight=1)
    assert [r["slug"] for r in rows] == ["alan"]
    assert rows[0]["weight"] == 1


def test_neighbours_matches_when_the_anchor_is_person_b_in_the_pair(live_db):
    """Pairs are keyed (person_a < person_b) — 'alan' sits on the person_b
    side of the (ada, alan) pair, exercising the other branch of
    ``neighbours``' person_a/person_b matching."""
    rows = collab.neighbours("alan", "co_project", min_weight=1)
    assert [r["slug"] for r in rows] == ["ada"]


def test_neighbours_respects_the_floor(live_db):
    assert collab.neighbours("ada", "co_project", min_weight=2) == []


def test_pairs_for_and_enriched_pairs_reject_an_unknown_kind():
    with pytest.raises(ValueError):
        collab._pairs_for("bogus")
    with pytest.raises(ValueError):
        collab.enriched_pairs("bogus")


# ── uc_phd_app/api/collab.py ─────────────────────────────────────────────────


def test_summary_route_carries_default_floors_and_caveats(client):
    body = client.get("/api/collab/summary").json()
    assert body["default_min_weight"] == {"co_project": 2, "co_supervision": 1}
    assert "co_project" in body["caveats"] and "co_supervision" in body["caveats"]
    assert body["total_people"] == 3


def test_pairs_route_defaults_to_a_floor_of_2_for_co_project(client):
    """The (ada, alan) pair sits at weight 1 — below the default co_project
    floor of 2 — so the default ranked table must come back empty, not
    silently show it."""
    body = client.get("/api/collab/pairs?kind=co_project").json()
    assert body["min_weight"] == 2
    assert body["total"] == 0
    assert body["pairs"] == []


def test_pairs_route_sort_normalized_for_co_project(client):
    body = client.get("/api/collab/pairs?kind=co_project&min_weight=1&sort=normalized").json()
    assert body["sort"] == "normalized"
    assert body["total"] == 1


def test_pairs_route_min_weight_1_surfaces_the_pair(client):
    body = client.get("/api/collab/pairs?kind=co_project&min_weight=1").json()
    assert body["total"] == 1
    pair = body["pairs"][0]
    assert {pair["person_a_slug"], pair["person_b_slug"]} == {"ada", "alan"}
    assert pair["weight"] == 1
    assert "weight_normalized" in pair


def test_pairs_route_co_supervision_has_no_normalized_weight_and_default_floor_1(client):
    body = client.get("/api/collab/pairs?kind=co_supervision").json()
    assert body["min_weight"] == 1
    assert body["total"] == 1
    assert body["pairs"][0]["weight_normalized"] is None


def test_pairs_route_rejects_an_unknown_kind(client):
    resp = client.get("/api/collab/pairs?kind=bogus")
    assert resp.status_code == 400


def test_people_route_lists_by_name_and_project_count(client):
    body = client.get("/api/collab/people").json()
    slugs = [p["slug"] for p in body["people"]]
    assert "ada" in slugs and "alan" in slugs and "grace" in slugs
    ada = next(p for p in body["people"] if p["slug"] == "ada")
    assert ada["project_count"] == 2


def test_people_route_search_escapes_like_wildcards(client):
    """Same escaping discipline as /api/projects — a user searching '%'
    means the character, not 'match everything'."""
    resp = client.get("/api/collab/people?q=%25")
    assert resp.json()["people"] == []


def test_people_route_search_filters_by_name(client):
    body = client.get("/api/collab/people?q=Ada").json()
    assert [p["slug"] for p in body["people"]] == ["ada"]


def test_person_neighbours_route(client):
    body = client.get("/api/collab/people/ada?kind=co_project&min_weight=1").json()
    assert body["person"]["name"] == "Ada Lovelace"
    assert sorted(body["person"]["groups"]) == ["AC", "NCS"]
    assert body["total"] == 1
    assert body["collaborators"][0]["slug"] == "alan"


def test_person_neighbours_route_404s_for_an_unknown_person(client):
    resp = client.get("/api/collab/people/nobody")
    assert resp.status_code == 404


def test_person_neighbours_route_empty_is_not_an_error(client):
    """'grace' co-supervises with 'ada' but shares no project with anyone —
    an empty collaborator list for co_project is a valid answer."""
    body = client.get("/api/collab/people/grace?kind=co_project&min_weight=1").json()
    assert body["total"] == 0
    assert body["collaborators"] == []
