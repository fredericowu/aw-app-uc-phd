"""uc_phd_app/theses.py — the seed's thesis facts -> live research groups.

Runs against the same small fixture database as test_routes.py/test_db.py.
Ada Lovelace coordinates Alpha [AC, NCS] and Beta [NCS]; Alan Turing is only
ever a *researcher* on Alpha, never a coordinator; Grace Hopper is on no
project at all — so the role weighting and the "resolved to a real person who
still has no group" case are both exercised against real rows rather than
asserted in the abstract.

The identity half of this join is no longer re-derived here at all: it is
frozen in ``thesis_people`` by ``analysis/build_thesis_facts.py``, and
tests/test_name_match.py is what holds that half honest.

**Nothing here asserts a real-corpus number.** The fixture database is
synthetic, so "mean 1.29 groups per thesis over 181 theses" is not something
these tests could check even in principle. What they check is the invariants
that make that number mean anything: no thesis carries more than two groups,
a corroborated thesis carries exactly one, and a thesis with neither signal
carries none. See conftest's fixture comment for which thesis covers which
tier.
"""
from __future__ import annotations

import pytest

from uc_phd_app import theses


@pytest.fixture()
def theses_list(live_db):
    return theses.list_theses(db_path=live_db)


def _by_handle(items, handle):
    return next(t for t in items if t["handle"] == handle)


def test_a_matched_supervisor_carries_their_weighted_groups(theses_list):
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
    assert author["group_shares"] == {}

    supervisors = {s["name"]: s for s in a["supervisors"]}
    assert supervisors["Lovelace, Ada"]["status"] == "matched"
    assert supervisors["Lovelace, Ada"]["match_status"] == "exact"
    assert supervisors["Lovelace, Ada"]["matched"] == [{"slug": "ada", "name": "Ada Lovelace"}]
    assert supervisors["Lovelace, Ada"]["groups"] == ["AC", "NCS"]
    # The change S7 made: NCS is not merely present, it carries twice AC's
    # weight, because ada coordinates two NCS projects (Alpha, Beta) and one
    # AC one (Alpha). A set could not say that, and it is why a thesis no
    # longer inherits a supervisor's entire career.
    assert supervisors["Lovelace, Ada"]["group_shares"] == pytest.approx(
        {"AC": 1 / 3, "NCS": 2 / 3}
    )
    # Resolved to a real person who coordinates and researches nothing: a
    # matched name can legitimately carry zero groups.
    assert supervisors["Hopper, Grace"]["groups"] == []
    assert supervisors["Hopper, Grace"]["group_shares"] == {}


def test_a_researcher_role_still_counts_but_less_than_a_coordinator_one(live_db):
    """The coordinator-first / researcher-fallback rule is gone: both roles
    now contribute, weighted 1.0 and 0.4. Asserted on the one person who is
    only ever a researcher, against the one who is only ever a coordinator."""
    from uc_phd_app import theses as theses_mod

    # alan: researcher on Alpha only, which is in both groups -> an even split.
    assert theses_mod._person_group_shares("alan", live_db) == pytest.approx(
        {"AC": 0.4, "NCS": 0.4}
    )
    # ada: coordinator on Alpha [AC, NCS] and Beta [NCS] -> 1.0 / 2.0 raw.
    # She is ALSO a researcher on Beta (see conftest): one membership described
    # by two rows, so Beta contributes 1.0, not 1.0 + 0.4. Summing the rows
    # instead of taking the strongest role per project is the bug this pins.
    assert theses_mod._person_group_shares("ada", live_db) == pytest.approx(
        {"AC": 1.0, "NCS": 2.0}
    )


def test_an_ambiguous_name_is_shown_unattributed_never_resolved(theses_list):
    """Two real people fit and nothing separates them. Picking either is the
    guess the whole spine exists to avoid — so the name is preserved, the
    tier says why, and the thesis gains no *people* group from it."""
    c = _by_handle(theses_list, "10316/000003")
    supervisor = c["supervisors"][0]
    assert supervisor["name"] == "Ambiguous, Two People"
    assert supervisor["status"] == "unattributed"
    assert supervisor["match_status"] == "ambiguous"
    assert supervisor["confidence"] == 0.4
    assert supervisor["matched"] == []

    assert c["authors"][0]["status"] == "unattributed"
    assert c["group_attribution"]["ranked"][0]["people_share"] == 0.0


# ── the two signals and the tier they produce (S7) ──────────────────────────


def test_both_signals_agreeing_yields_one_group_and_the_corroborated_tier(theses_list):
    """The outcome the whole design exists to produce: one group, and a tier
    that says two independent methods picked it."""
    a = _by_handle(theses_list, "10316/000001")
    assert a["groups"] == ["NCS"]
    assert a["attributed"] is True
    assert a["group_attribution"] == {
        "tier": "corroborated",
        "ranked": [{"code": "NCS", "people_share": 0.6667, "content_score": 0.3}],
    }


def test_disagreeing_signals_yield_two_ranked_groups_and_the_contested_tier(theses_list):
    """Requirement #3 on the card: where the signal is genuinely ambiguous the
    ambiguity is *shown*, not averaged away. The people candidate leads."""
    b = _by_handle(theses_list, "10316/000002")
    assert b["full_text"] is False
    assert b["rights"] == "embargoedAccess"
    assert b["supervisors"] == []
    assert b["authors"][0]["status"] == "matched"

    assert b["group_attribution"]["tier"] == "contested"
    ranked = b["group_attribution"]["ranked"]
    assert [entry["code"] for entry in ranked] == ["AC", "NCS"]
    assert ranked[0]["content_score"] == 0.05
    assert ranked[1]["content_score"] == 0.4
    # `groups` stays a *sorted* list of codes — the frontend chips and the MCP
    # filter read it, and neither knows about ranking.
    assert b["groups"] == ["AC", "NCS"]


def test_no_resolved_name_but_real_text_is_content_only_not_unattributed(theses_list):
    """Thesis C's names are unmatched and ambiguous, so the people signal is
    empty — but the thesis itself still says what it is about, and that is a
    group honestly earned rather than a blank."""
    c = _by_handle(theses_list, "10316/000003")
    assert c["groups"] == ["AC"]
    assert c["attributed"] is True
    assert c["group_attribution"]["tier"] == "content-only"


def test_no_content_signal_at_all_falls_back_to_the_people_signal(theses_list):
    """Thesis D has no affinity rows — no keywords, no abstract, and a title
    alone is not evidence (see build_group_affinity.thesis_documents). The
    people signal is all there is, and the tier says so."""
    d = _by_handle(theses_list, "10316/000004")
    assert d["groups"] == ["NCS"]
    assert d["group_attribution"]["tier"] == "people-only"
    assert d["group_attribution"]["ranked"][0]["content_score"] == 0.0


def test_neither_signal_leaves_the_thesis_unattributed_never_guessed(theses_list):
    """Requirement #4: an honestly-unattributed thesis beats a wrong one."""
    e = _by_handle(theses_list, "10316/000005")
    assert e["groups"] == []
    assert e["attributed"] is False
    assert e["group_attribution"] == {"tier": "unattributed", "ranked": []}


def test_no_thesis_can_carry_more_than_two_groups(theses_list):
    """The acceptance condition, as an invariant rather than as the corpus
    number it was measured at: two signals can name at most two groups, so
    the six-group tag that made this attribution useless is unrepresentable."""
    assert max(len(t["groups"]) for t in theses_list) <= 2
    for thesis in theses_list:
        tier = thesis["group_attribution"]["tier"]
        expected = {"corroborated": 1, "contested": 2, "people-only": 1,
                    "content-only": 1, "unattributed": 0}[tier]
        assert len(thesis["groups"]) == expected, thesis["handle"]


def test_a_tied_people_signal_resolves_by_group_code_not_by_row_order(live_db):
    """alan sits on exactly one project that is in both groups, so his shares
    tie at 0.5. Ties have to break on something stable or the same seed would
    produce a different dashboard on a different day."""
    from uc_phd_app import theses as theses_mod

    assert theses_mod._top({"NCS": 0.5, "AC": 0.5}) == "AC"
    assert theses_mod._top({"AC": 0.5, "NCS": 0.5}) == "AC"
    assert theses_mod._top({}) is None


def test_two_people_rows_for_one_human_do_not_count_that_human_twice(live_db):
    """thesis_people's key is (handle, name_raw, role, person_slug) and the
    scraped `people` table holds duplicate rows for one human
    (joao-bicker / joao-bicker-1). Summing over rows would give that name
    double the weight of a name that resolved to one row — so the shares are
    normalised per *name*, not per slug.
    """
    import sqlite3

    conn = sqlite3.connect(live_db)
    conn.execute("INSERT INTO people (slug, name) VALUES ('ada-1', 'Ada Lovelace')")
    conn.execute(
        "INSERT INTO project_people (project_id, person_slug, role, ordinal)"
        " VALUES (1, 'ada-1', 'coordinator', 2)"
    )
    conn.execute(
        "INSERT INTO thesis_people (handle, name_raw, role, person_slug, match_status,"
        " match_confidence, match_note, ordinal)"
        " VALUES ('10316/000004', 'Lovelace, Ada', 'supervisor', 'ada-1', 'exact', 1.0,"
        " 'duplicate people row for one human', 0)"
    )
    conn.commit()
    conn.close()

    d = _by_handle(theses.list_theses(db_path=live_db), "10316/000004")
    supervisor = d["supervisors"][0]
    assert [m["slug"] for m in supervisor["matched"]] == ["ada", "ada-1"]
    # Both rows contribute, but the name still sums to exactly 1.0 — it is one
    # human, and the duplicate only shifts the balance between their groups.
    assert sum(supervisor["group_shares"].values()) == pytest.approx(1.0)


def test_tier_breakdown_reports_every_tier_including_the_empty_ones(theses_list):
    assert theses.tier_breakdown(theses_list) == {
        "corroborated": 1,
        "contested": 1,
        "people-only": 1,
        "content-only": 1,
        "unattributed": 1,
    }


def test_the_matcher_note_survives_into_the_payload(theses_list):
    """The UI renders it as the name's tooltip — it is the only place a
    reader finds out *why* a name went unattributed."""
    a = _by_handle(theses_list, "10316/000001")
    assert a["authors"][0]["note"] == "no row in people carries that surname"


def test_group_breakdown_is_many_to_many_and_counts_the_unattributed(theses_list):
    breakdown = theses.group_breakdown(theses_list)
    # Still many-to-many — B is contested and counts towards both — but a
    # thesis can now contribute at most 2, never 6.
    assert breakdown["counts"] == {"AC": 2, "NCS": 3}
    assert breakdown["unattributed"] == 1  # Thesis E only


def test_match_tiers_counts_distinct_names_not_rows(live_db):
    """Eight thesis_people rows over seven distinct names, and the tiers
    reported over names — "Lovelace, Ada" supervises two theses and is one
    identity decision, not two."""
    assert theses.match_tiers(live_db) == {"exact": 3, "unmatched": 3, "ambiguous": 1}


def test_a_thesis_with_no_people_rows_at_all_still_lists(live_db, tmp_path):
    """Nothing in the corpus should vanish because its names were lost — the
    thesis is still a thesis, just fully unattributed."""
    import sqlite3

    conn = sqlite3.connect(live_db)
    conn.execute("DELETE FROM thesis_people WHERE handle = '10316/000004'")
    conn.commit()
    conn.close()

    # D is the people-only thesis, so losing its names loses its only signal.
    d = _by_handle(theses.list_theses(db_path=live_db), "10316/000004")
    assert d["authors"] == []
    assert d["supervisors"] == []
    assert d["attributed"] is False
    assert d["group_attribution"]["tier"] == "unattributed"


# ── get_thesis / thesis_body (S4's get_phd_thesis tool) ─────────────────────


def test_get_thesis_carries_both_abstracts_and_the_identity_join(live_db):
    """get_thesis must not just re-run list_theses' join — it also has to
    surface abstract_pt/abstract_en, which list_theses() never selects."""
    t = theses.get_thesis("10316/000001", db_path=live_db)
    assert t["title"] == "Thesis A"
    assert t["abstract_pt"] == "Resumo A."
    assert t["abstract_en"] == "Abstract A."
    assert t["source_url"] == "https://estudogeral.uc.pt/handle/10316/000001"
    # Identity join and both attribution signals still run — same shape as
    # list_theses(), group_attribution included.
    assert t["groups"] == ["NCS"]
    assert t["group_attribution"]["tier"] == "corroborated"


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


# ── get_thesis(with_body=False) (S5's detail route) ─────────────────────────


def test_get_thesis_with_body_false_skips_the_file_read_entirely(live_db, tmp_path, monkeypatch):
    """The detail route passes with_body=False specifically so it never reads
    the .md file — assert that by pointing AW_APP_UC_PHD_ESTUDO_GERAL_DIR at
    a directory that does not exist. If this read the file, it would raise;
    passing proves the read never happened, not just that body is None."""
    monkeypatch.setenv("AW_APP_UC_PHD_ESTUDO_GERAL_DIR", str(tmp_path / "does-not-exist"))
    t = theses.get_thesis("10316/000001", db_path=live_db, with_body=False)
    assert t is not None
    assert t["body"] is None
    assert t["title"] == "Thesis A"
    assert t["abstract_pt"] == "Resumo A."


def test_get_thesis_with_body_true_is_still_the_default(live_db, tmp_path, monkeypatch):
    """The MCP tool (mcp/tools.py:62) calls get_thesis(handle) with no
    with_body kwarg — its contract must not change."""
    estudo_geral = tmp_path / "estudo_geral"
    estudo_geral.mkdir()
    (estudo_geral / "10316-000001.md").write_text("no front matter here", encoding="utf-8")
    monkeypatch.setenv("AW_APP_UC_PHD_ESTUDO_GERAL_DIR", str(estudo_geral))

    t = theses.get_thesis("10316/000001", db_path=live_db)
    assert t["body"] == "no front matter here"
