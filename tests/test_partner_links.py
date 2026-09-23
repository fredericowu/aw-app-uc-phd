"""uc_phd_app/partner_links.py — partner -> project -> person -> thesis.

Runs against the same fixture DB as test_routes.py/test_theses.py. In that
fixture, Alpha (project 1) carries two partners (one academic, one
industry) and two project_people rows: ada (coordinator) and alan
(researcher). ada supervises Thesis A and Thesis D (exact matches) and alan
authors Thesis B (exact match) — so every partner reaches three theses, each
through a different person and a different role on both sides. Grace
supervises Thesis A too but is on no project at all, so she must never
appear in a link. Theses C and E resolve nobody, so they must never appear
either.
"""
from __future__ import annotations

from uc_phd_app import partner_links


def test_every_partner_reaches_both_theses_through_the_shared_project(live_db):
    links = partner_links.list_links(live_db)
    assert len(links) == 6  # 2 partners x 3 (person, thesis) paths

    by_partner = {}
    for link in links:
        by_partner.setdefault(link["partner_name"], []).append(link)

    assert set(by_partner) == {"University of Testcoimbra", "Partner Industries Lda"}

    for partner_name, rows in by_partner.items():
        paths = {(r["via_person_slug"], r["thesis_handle"]) for r in rows}
        assert paths == {
            ("ada", "10316/000001"),
            ("ada", "10316/000004"),
            ("alan", "10316/000002"),
        }

        by_person = {(r["via_person_slug"], r["thesis_handle"]): r for r in rows}
        ada_link = by_person[("ada", "10316/000001")]
        assert ada_link["project_title"] == "Alpha Project"
        assert ada_link["via_project_role"] == "coordinator"
        assert ada_link["thesis_role"] == "supervisor"
        assert ada_link["match_status"] == "exact"
        assert ada_link["match_confidence"] == 1.0

        alan_link = by_person[("alan", "10316/000002")]
        assert alan_link["via_project_role"] == "researcher"
        assert alan_link["thesis_role"] == "author"


def test_a_supervisor_off_every_project_never_produces_a_link(live_db):
    """Grace supervises Thesis A but is on no project_people row — a real
    identity match is not enough on its own, a shared project is required."""
    links = partner_links.list_links(live_db)
    assert all(link["via_person_slug"] != "grace" for link in links)


def test_a_thesis_with_no_resolved_person_never_appears(live_db):
    links = partner_links.list_links(live_db)
    assert all(link["thesis_handle"] not in ("10316/000003", "10316/000005") for link in links)


def test_coverage_counts_reach_and_total_separately(live_db):
    cov = partner_links.coverage(live_db)
    assert cov == {
        "distinct_partners": 2,
        "partners_with_a_thesis_link": 2,
        "total_theses": 5,
        "theses_with_a_partner_link": 3,
    }
