"""uc_phd_app/theses.py — the seed's thesis facts -> live research groups.

Runs against the same small fixture database as test_routes.py/test_db.py.
Ada Lovelace coordinates Alpha [AC, NCS] and Beta [NCS]; Alan Turing is only
ever a *researcher* on Alpha, never a coordinator; Grace Hopper is on no
project at all — so the coordinator-then-researcher fallback and the
"resolved to a real person who still has no group" case are both exercised
against real rows rather than asserted in the abstract.

The identity half of this join is no longer re-derived here at all: it is
frozen in ``thesis_people`` by ``analysis/build_thesis_facts.py``, and
tests/test_name_match.py is what holds that half honest.
"""
from __future__ import annotations

import pytest

from uc_phd_app import theses


@pytest.fixture()
def theses_list(live_db):
    return theses.list_theses(db_path=live_db)


def _by_handle(items, handle):
    return next(t for t in items if t["handle"] == handle)


def test_a_matched_supervisor_carries_their_coordinator_groups(theses_list):
    a = _by_handle(theses_list, "10316/000001")
    assert a["title"] == "Thesis A"
    assert a["year"] == "2024"
    assert a["rights"] == "openAccess"
    assert a["full_text"] is True
    assert a["source_url"] == "https://estudogeral.uc.pt/handle/10316/000001"

    author = a["authors"][0]
    assert author["name"] == "Author, Ada Unresolved"
    assert author["status"] == "unattributed"
    assert author["match_status"] == "unmatched"
    assert author["matched"] == []
    assert author["groups"] == []

    supervisors = {s["name"]: s for s in a["supervisors"]}
    assert supervisors["Lovelace, Ada"]["status"] == "matched"
    assert supervisors["Lovelace, Ada"]["match_status"] == "exact"
    assert supervisors["Lovelace, Ada"]["matched"] == [{"slug": "ada", "name": "Ada Lovelace"}]
    assert supervisors["Lovelace, Ada"]["groups"] == ["AC", "NCS"]
    # Resolved to a real person who coordinates and researches nothing: a
    # matched name can legitimately carry zero groups.
    assert supervisors["Hopper, Grace"]["groups"] == []

    # Thesis-level groups are the union across every resolved name.
    assert a["groups"] == ["AC", "NCS"]
    assert a["attributed"] is True


def test_researcher_role_is_the_fallback_when_a_person_never_coordinates(theses_list):
    b = _by_handle(theses_list, "10316/000002")
    assert b["full_text"] is False
    assert b["rights"] == "embargoedAccess"
    assert b["supervisors"] == []

    author = b["authors"][0]
    assert author["status"] == "matched"
    # alan never coordinates in the fixture DB, so this is the researcher
    # fallback, not the coordinator branch.
    assert author["groups"] == ["AC", "NCS"]
    assert b["groups"] == ["AC", "NCS"]


def test_an_ambiguous_name_is_shown_unattributed_never_resolved(theses_list):
    """Two real people fit and nothing separates them. Picking either is the
    guess the whole spine exists to avoid — so the name is preserved, the
    tier says why, and the thesis gains no group from it."""
    c = _by_handle(theses_list, "10316/000003")
    supervisor = c["supervisors"][0]
    assert supervisor["name"] == "Ambiguous, Two People"
    assert supervisor["status"] == "unattributed"
    assert supervisor["match_status"] == "ambiguous"
    assert supervisor["confidence"] == 0.4
    assert supervisor["matched"] == []

    assert c["authors"][0]["status"] == "unattributed"
    assert c["groups"] == []
    assert c["attributed"] is False


def test_the_matcher_note_survives_into_the_payload(theses_list):
    """The UI renders it as the name's tooltip — it is the only place a
    reader finds out *why* a name went unattributed."""
    a = _by_handle(theses_list, "10316/000001")
    assert a["authors"][0]["note"] == "no row in people carries that surname"


def test_group_breakdown_is_many_to_many_and_counts_the_unattributed(theses_list):
    breakdown = theses.group_breakdown(theses_list)
    # A + B both carry AC and NCS: 2 + 2, not 1 + 1 deduped across theses.
    assert breakdown["counts"] == {"AC": 2, "NCS": 2}
    assert breakdown["unattributed"] == 1  # Thesis C only


def test_match_tiers_counts_distinct_names_not_rows(live_db):
    """Six thesis_people rows, six distinct names, and the tiers reported over
    names — a supervisor on three theses is one identity decision."""
    assert theses.match_tiers(live_db) == {"exact": 3, "unmatched": 2, "ambiguous": 1}


def test_a_thesis_with_no_people_rows_at_all_still_lists(live_db, tmp_path):
    """Nothing in the corpus should vanish because its names were lost — the
    thesis is still a thesis, just fully unattributed."""
    import sqlite3

    conn = sqlite3.connect(live_db)
    conn.execute("DELETE FROM thesis_people WHERE handle = '10316/000003'")
    conn.commit()
    conn.close()

    c = _by_handle(theses.list_theses(db_path=live_db), "10316/000003")
    assert c["authors"] == []
    assert c["supervisors"] == []
    assert c["attributed"] is False
