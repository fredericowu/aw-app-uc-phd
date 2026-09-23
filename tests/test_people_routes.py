"""uc_phd_app/api/people.py — the researcher/collaborator profile endpoint.

Runs against the same small fixture database as test_routes.py. The fixture
rows this file leans on, all added for it and all mirroring a real shape in
the production snapshot:

* ``ada`` is coordinator AND researcher on Beta — the (project_id,
  person_slug, role) primary key makes that legal, and every count here has
  to survive it.
* ``grace-1`` carries the same display name as ``grace`` under a second slug.
* ``10316/000003``'s supervisor row is ``ambiguous`` with a NULL slug, and
  Thesis A's author row is ``unmatched`` — neither may resolve to a person.
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


def test_unknown_slug_404s(client):
    resp = client.get("/api/people/nobody")
    assert resp.status_code == 404
    assert "nobody" in resp.json()["detail"]


def test_profile_carries_the_no_biography_caveat(client):
    """The feasibility finding this feature was scoped around rides in the
    payload, not only in UI copy — a frontend change cannot drop it."""
    body = client.get("/api/people/ada").json()
    assert "no biographical data" in body["caveat"]


def test_project_count_is_distinct_projects_not_role_rows(client):
    """THE regression test for this endpoint.

    'ada' is coordinator on Alpha, and BOTH coordinator and researcher on
    Beta — three project_people rows, two projects. A COUNT(*) would say 3.
    The real snapshot has zero dual-role rows today, so this fixture row is
    the only thing standing between that regression and a green suite.
    """
    body = client.get("/api/people/ada").json()["projects"]
    assert body["project_count"] == 2
    assert body["coordinated_count"] == 2
    assert [p["id"] for p in body["items"]] == [2, 1]  # start_date DESC

    beta = next(p for p in body["items"] if p["id"] == 2)
    assert beta["roles"] == ["coordinator", "researcher"], (
        "both roles are listed on the one project entry, not folded away"
    )
    assert beta["groups"] == ["NCS"]


def test_a_researcher_never_counts_as_a_coordinator(client):
    body = client.get("/api/people/alan").json()["projects"]
    assert body["project_count"] == 1
    assert body["coordinated_count"] == 0
    assert body["items"][0]["roles"] == ["researcher"]


def test_cisuc_url_is_read_from_the_stored_href_not_rebuilt(client):
    """project_fields_raw carries the URL the site actually published. The
    fixture's href host is example.test — a profile that concatenated the
    slug onto a hardcoded cisuc.uc.pt would still 'pass' with a real-looking
    URL here, so asserting the fixture host is what proves it was read."""
    person = client.get("/api/people/ada").json()["person"]
    assert person["cisuc_url"] == "https://example.test/people/ada"


def test_no_stored_href_means_no_link_never_a_guessed_one(client):
    """'grace' is on no project, so no project_fields_raw row names her."""
    person = client.get("/api/people/grace").json()["person"]
    assert person["cisuc_url"] is None


def test_groups_come_from_every_project_any_role(client):
    """collab.person_groups()'s answer, reused — Alpha is [AC, NCS] and Beta
    is [NCS], so ada carries both regardless of which role she held."""
    person = client.get("/api/people/ada").json()["person"]
    assert person["groups"] == ["AC", "NCS"]
    assert client.get("/api/people/alan").json()["person"]["groups"] == ["AC", "NCS"]
    assert client.get("/api/people/grace").json()["person"]["groups"] == []


def test_a_duplicate_display_name_is_reported_never_merged(client):
    body = client.get("/api/people/grace").json()
    assert body["person"]["name_siblings"] == [{"slug": "grace-1", "name": "Grace Hopper"}]
    assert body["duplicate_name_caveat"] is not None
    assert "same human" in body["duplicate_name_caveat"]

    # Symmetric, and neither profile absorbs the other's rows: 'grace'
    # supervises Thesis A, 'grace-1' supervises nothing.
    other = client.get("/api/people/grace-1").json()
    assert other["person"]["name_siblings"] == [{"slug": "grace", "name": "Grace Hopper"}]
    assert other["theses"]["supervised"] == []


def test_a_unique_name_carries_no_disambiguation_note(client):
    body = client.get("/api/people/ada").json()
    assert body["person"]["name_siblings"] == []
    assert body["duplicate_name_caveat"] is None


def test_authored_and_supervised_are_separate_lists(client):
    """'alan' authored Thesis B and supervised nothing; 'ada' supervised
    Thesis A and authored nothing. Never one summed number."""
    alan = client.get("/api/people/alan").json()["theses"]
    assert [t["handle"] for t in alan["authored"]] == ["10316/000002"]
    assert alan["supervised"] == []
    assert alan["authored"][0]["full_text"] is False  # Thesis B is embargoed

    ada = client.get("/api/people/ada").json()["theses"]
    assert ada["authored"] == []
    assert [t["handle"] for t in ada["supervised"]] == ["10316/000001"]
    assert ada["supervised"][0]["title"] == "Thesis A"
    assert ada["supervised"][0]["year"] == "2024"


def test_an_ambiguous_thesis_row_is_not_a_person(client, live_db):
    """Thesis C's supervisor is 'ambiguous'. Filtering on
    `person_slug IS NOT NULL` instead of the resolved tiers would be wrong —
    an ambiguous row can carry a slug. Proven by giving one a slug here: it
    must STILL be excluded.
    """
    import sqlite3

    conn = sqlite3.connect(live_db)
    conn.execute(
        "UPDATE thesis_people SET person_slug = 'ada' "
        "WHERE handle = '10316/000003' AND match_status = 'ambiguous'"
    )
    conn.commit()
    conn.close()

    ada = client.get("/api/people/ada").json()["theses"]
    assert [t["handle"] for t in ada["supervised"]] == ["10316/000001"], (
        "an ambiguous row carrying a slug must not reach a profile"
    )
    assert "ambiguous" in ada["caveat"]


def test_keywords_stay_separate_by_source(client):
    """Project keywords (CISUC) and thesis keywords (Estudo Geral) are two
    vocabularies, labelled and never merged. 'graphs' is on Thesis A twice
    (thesis_keywords is keyed on ordinal) and must count as ONE thesis."""
    body = client.get("/api/people/ada").json()["keywords"]
    assert body["project"] == [
        {"keyword": "networks", "project_count": 1},
        {"keyword": "security", "project_count": 1},
    ]
    assert body["thesis"] == [{"keyword": "graphs", "thesis_count": 1}]
    assert "kept separate" in body["caveat"]


def test_collaborators_are_not_in_this_payload(client):
    """Deliberate: collab.enriched_pairs() recomputes all 4,242 pairs per
    call, so the profile header must not block on it — the frontend fetches
    /collab/people/{slug} separately. If a later change folds them in here,
    this test is the reminder of why it should not."""
    body = client.get("/api/people/ada").json()
    assert "collaborators" not in body


def test_every_person_in_the_fixture_resolves(client):
    """475 of 475 people in the real snapshot have at least one project, so a
    profile is never an empty page — but 'grace' has none, and must still
    render as a valid, honest profile rather than a 404 or a crash."""
    body = client.get("/api/people/grace")
    assert body.status_code == 200
    payload = body.json()
    assert payload["projects"]["project_count"] == 0
    assert payload["projects"]["items"] == []
    assert [t["handle"] for t in payload["theses"]["supervised"]] == ["10316/000001"]
