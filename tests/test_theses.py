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


# ── get_thesis / thesis_body (S4's get_phd_thesis tool) ─────────────────────


def test_get_thesis_carries_both_abstracts_and_the_identity_join(live_db):
    """get_thesis must not just re-run list_theses' join — it also has to
    surface abstract_pt/abstract_en, which list_theses() never selects."""
    t = theses.get_thesis("10316/000001", db_path=live_db)
    assert t["title"] == "Thesis A"
    assert t["abstract_pt"] == "Resumo A."
    assert t["abstract_en"] == "Abstract A."
    assert t["source_url"] == "https://estudogeral.uc.pt/handle/10316/000001"
    # Identity join still runs — same shape as list_theses().
    assert t["groups"] == ["AC", "NCS"]


def test_get_thesis_abstracts_are_none_when_the_seed_has_none(live_db):
    t = theses.get_thesis("10316/000002", db_path=live_db)
    assert t["abstract_pt"] is None
    assert t["abstract_en"] is None


def test_get_thesis_returns_none_for_an_unknown_handle(live_db):
    assert theses.get_thesis("10316/999999", db_path=live_db) is None


def test_get_thesis_body_is_none_when_no_md_file_exists(live_db, tmp_path, monkeypatch):
    empty_dir = tmp_path / "estudo_geral_empty"
    empty_dir.mkdir()
    monkeypatch.setenv("AW_APP_UC_PHD_ESTUDO_GERAL_DIR", str(empty_dir))
    t = theses.get_thesis("10316/000001", db_path=live_db)
    assert t["body"] is None


def test_thesis_body_splits_off_the_yaml_front_matter(tmp_path, monkeypatch):
    estudo_geral = tmp_path / "estudo_geral"
    estudo_geral.mkdir()
    (estudo_geral / "10316-000001.md").write_text(
        "---\nhandle: 10316/000001\ntitle: Fixture Thesis\n---\n\n# Fixture Thesis\n\nBody text.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AW_APP_UC_PHD_ESTUDO_GERAL_DIR", str(estudo_geral))

    assert theses.thesis_body("10316/000001") == "# Fixture Thesis\n\nBody text.\n"


def test_thesis_body_returns_the_raw_file_when_there_is_no_front_matter(tmp_path, monkeypatch):
    estudo_geral = tmp_path / "estudo_geral"
    estudo_geral.mkdir()
    (estudo_geral / "10316-000002.md").write_text("no front matter here", encoding="utf-8")
    monkeypatch.setenv("AW_APP_UC_PHD_ESTUDO_GERAL_DIR", str(estudo_geral))

    assert theses.thesis_body("10316/000002") == "no front matter here"


def test_thesis_body_returns_the_raw_file_when_the_closing_delimiter_is_missing(tmp_path, monkeypatch):
    estudo_geral = tmp_path / "estudo_geral"
    estudo_geral.mkdir()
    raw = "---\nhandle: 10316/000003\ntitle: Unterminated\n"
    (estudo_geral / "10316-000003.md").write_text(raw, encoding="utf-8")
    monkeypatch.setenv("AW_APP_UC_PHD_ESTUDO_GERAL_DIR", str(estudo_geral))

    assert theses.thesis_body("10316/000003") == raw
