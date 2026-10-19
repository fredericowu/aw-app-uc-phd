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

from uc_phd_app import db, theses


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


def test_identity_coverage_tiers_are_split_by_role_over_distinct_names(live_db):
    """Eight thesis_people rows over seven distinct names, tiered over NAMES
    and split by ROLE.

    Over names, because "Lovelace, Ada" supervises two theses and is one
    identity decision, not two. Split by role, because pooling the two hides
    the finding: every unresolved name here but one is an author, and an author
    who is not CISUC staff is the matcher being right.
    """
    coverage = theses.identity_coverage(live_db)
    assert coverage["tiers_by_role"] == {
        "author": {"exact": 1, "unmatched": 3},
        "supervisor": {"exact": 2, "ambiguous": 1},
    }
    # The tier counts and the name-grain totals are two readings of one
    # population, so they have to agree — a role whose tiers sum to something
    # other than its total means one of the two queries changed alone.
    for role, tiers in coverage["tiers_by_role"].items():
        assert sum(tiers.values()) == coverage["names"][role]["total"]


def test_identity_coverage_reports_every_grain_the_views_consume(live_db):
    """The fixture, counted at each grain (see conftest's thesis_people).

    Supervisors: Lovelace (000001, 000004), Hopper (000001), and one ambiguous
    name (000003) — 3 distinct names over 4 supervision edges, 3 of them
    resolved. 000002 and 000005 name no supervisor at all, which is why the
    thesis-grain denominator is 3 and not 5.
    """
    coverage = theses.identity_coverage(live_db)
    assert coverage["names"] == {
        "author": {"total": 4, "resolved": 1},
        "supervisor": {"total": 3, "resolved": 2},
    }
    assert coverage["supervision_edges"] == {
        "total": 4,
        "resolved": 3,
        "by_source": {"cisuc": 3, "uc_directory": 0},
    }
    # A SEPARATE number over a different universe, never merged into the one
    # above: the theses where CISUC's own directory is present at all.
    assert coverage["supervision_edges_within_cisuc"] == {
        "theses": 3,
        # 3, not the 4 above: one of the fixture's supervisor edges is on a
        # thesis where nothing resolved at all, so that thesis is outside the
        # CISUC-touching universe. Which is the point of reporting the two
        # separately — they count different things.
        "total": 3,
        "resolved": 3,
        "by_source": {"cisuc": 3, "uc_directory": 0},
    }
    assert coverage["theses"] == {
        "total": 5,
        "listing_a_supervisor": 3,
        "with_a_resolved_supervisor": 2,
        "fully_resolved": 2,
    }
    assert coverage["co_supervision_pairs"] == {"total": 1, "resolved": 1}
    assert coverage["supervisor_people"] == 2


def test_identity_coverage_grains_stay_internally_consistent(live_db):
    """Invariants rather than corpus figures — these must hold at 18 theses, at
    181, and after any reindex, which is the only thing a synthetic fixture can
    honestly promise about the real corpus."""
    coverage = theses.identity_coverage(live_db)
    for grain in ("supervision_edges", "co_supervision_pairs"):
        assert coverage[grain]["resolved"] <= coverage[grain]["total"]
    for role in ("author", "supervisor"):
        assert coverage["names"][role]["resolved"] <= coverage["names"][role]["total"]
    th = coverage["theses"]
    assert th["fully_resolved"] <= th["with_a_resolved_supervisor"]
    assert th["with_a_resolved_supervisor"] <= th["listing_a_supervisor"] <= th["total"]
    # One name is at most one edge per thesis, and aliasing only ever collapses
    # names into FEWER people (91 -> 64 on the real corpus) — never more.
    assert coverage["names"]["supervisor"]["total"] <= coverage["supervision_edges"]["total"]
    assert coverage["supervisor_people"] <= coverage["names"]["supervisor"]["resolved"]


def test_identity_coverage_counts_a_pair_lost_to_one_unresolved_name(live_db):
    """The pair grain is keyed on NAME, not slug, and this is why: a third
    supervisor who does not resolve still forms two co-supervision pairs with
    the two who do, and both are lost. Keyed on slug that cost is invisible —
    an unresolved name has no slug to count."""
    import sqlite3

    conn = sqlite3.connect(live_db)
    conn.execute(
        """
        INSERT INTO thesis_people
            (handle, name_raw, role, person_slug, match_status, match_confidence,
             match_note, ordinal)
        VALUES ('10316/000001', 'Nobody, Co Supervisor', 'supervisor', NULL,
                'unmatched', 0.0, 'no row in people carries that surname', 2)
        """
    )
    conn.commit()
    conn.close()

    coverage = theses.identity_coverage(live_db)
    # Three supervisor names on 000001 -> 3 pairs, only the resolved two of
    # which survive; the thesis is no longer fully resolved but still has one.
    assert coverage["co_supervision_pairs"] == {"total": 3, "resolved": 1}
    assert coverage["theses"]["with_a_resolved_supervisor"] == 2
    assert coverage["theses"]["fully_resolved"] == 1


def test_identity_coverage_note_says_unresolved_authors_are_expected():
    """The largest number this coverage reports is a third of author names
    unresolved, and it is the matcher being correct. A reader shown a bare
    percentage assumes every miss is a defect, so the note has to say so — and
    it is rendered, not just carried (ui/src/views/Theses.jsx)."""
    note = theses.IDENTITY_COVERAGE_NOTE
    assert "correct answer, not a gap" in note
    assert "docs/thesis-attribution.md" in note


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


# --------------------------------------------------------------------------
# The external-identity display layer
# --------------------------------------------------------------------------
#
# ``external`` is the one field on a person entry that is NOT about identity.
# The invariants worth asserting are therefore negative ones: it never appears
# on a resolved row, it never produces a slug, and it never moves a coverage
# number. ``analysis/external_people.py`` holds the loader's half.


def test_an_unattributed_name_with_a_researched_identity_carries_it(theses_list):
    a = _by_handle(theses_list, "10316/000001")
    author = a["authors"][0]
    assert author["name"] == "Author, Ada Unresolved"
    assert author["status"] == "unattributed"
    assert author["external"] == {
        "display_name": "Ada Unresolved",
        "affiliation": "Somewhere Else University",
        "source_url": "https://example.test/people/ada",
        "note": None,
    }


def test_an_unattributed_name_nobody_researched_carries_no_external(theses_list):
    """The bare "(unattributed)" has to survive for the names nobody looked
    up — the ambiguous ones, and a real CISUC person missing from the
    directory snapshot."""
    c = _by_handle(theses_list, "10316/000003")
    assert [p["status"] for p in c["authors"]] == ["unattributed"]
    assert all("external" not in p for p in c["authors"] + c["supervisors"])


def test_a_matched_name_never_carries_an_external_identity(theses_list):
    """The boundary, checked at the payload as well as at the loader: an
    external identity beside a resolved CISUC person would be two answers to
    one question."""
    for thesis in theses_list:
        for person in thesis["authors"] + thesis["supervisors"]:
            if person["status"] == "matched":
                assert "external" not in person


def test_an_external_identity_never_becomes_a_slug_or_moves_coverage(live_db):
    """``identity_coverage`` must be blind to this layer — an external person
    is correctly unresolved, not newly resolved."""
    before = theses.identity_coverage(db_path=live_db)
    author = _by_handle(theses.list_theses(db_path=live_db), "10316/000001")["authors"][0]
    assert author["matched"] == []
    assert author["match_status"] == "unmatched"
    assert theses.identity_coverage(db_path=live_db) == before


def test_supervisors_for_carries_an_external_identity_when_there_is_one(live_db, fixture_db):
    """The Fit screen names supervisors and drops groups; an unresolved one
    reads as a dead end unless it can say who the person is. The fixture's
    externals are all authors, so this adds a supervisor one directly."""
    import sqlite3

    conn = sqlite3.connect(live_db)
    try:
        conn.execute(
            "INSERT INTO external_people (handle, name_raw, role, display_name, "
            "affiliation, source_url, note, evidence) VALUES (?,?,?,?,?,?,?,?)",
            ("10316/000003", "Ambiguous, Two People", "supervisor", "X", "Y", "https://z.test", None, "e"),
        )
        conn.commit()
    finally:
        conn.close()
    by_handle = theses.supervisors_for(["10316/000001", "10316/000003"], db_path=live_db)
    # An ambiguous row is not 'matched', so the attachment reaches it — the
    # loader refuses such an entry in the committed file, but the payload
    # layer must not depend on that to stay correct.
    ambiguous = by_handle["10316/000003"][0]
    assert ambiguous["external"]["display_name"] == "X"
    # ...and a resolved supervisor still carries no such key at all.
    assert all("external" not in p for p in by_handle["10316/000001"])


def test_a_seed_built_before_the_table_existed_still_renders(live_db):
    """The older-seed path. Dropping the table is what an install that
    predates this card actually has, and the route must degrade to the bare
    label rather than 500."""
    import sqlite3

    conn = sqlite3.connect(live_db)
    try:
        conn.execute("DROP TABLE external_people")
        conn.commit()
    finally:
        conn.close()
    assert theses.external_people(db_path=live_db) == {}
    author = _by_handle(theses.list_theses(db_path=live_db), "10316/000001")["authors"][0]
    assert author["status"] == "unattributed"
    assert "external" not in author


def test_resolve_person_rows_reads_the_table_itself_when_not_handed_one(live_db):
    """``list_theses`` passes the map in so the lookup happens once per
    request; a direct caller must still get the attachment."""
    rows = [
        {
            "handle": "10316/000001",
            "name_raw": "Author, Ada Unresolved",
            "role": "author",
            "person_slug": None,
            "match_status": "unmatched",
            "match_confidence": 0.0,
            "match_note": "nobody fits",
            "person_name": None,
        }
    ]
    resolved = theses._resolve_person_rows(rows, live_db, with_groups=False)
    assert resolved[0]["external"]["display_name"] == "Ada Unresolved"


def test_the_identity_note_explains_that_externals_stay_unresolved():
    """A reader shown a researched name next to an unresolved count will
    assume one of the two is wrong unless the note says which."""
    assert "external" in theses.IDENTITY_COVERAGE_NOTE
    assert "still counted as" in theses.IDENTITY_COVERAGE_NOTE


# ---------------------------------------------------------------------------
# The UC unit-directory payload field. Same three paths the `external_people`
# block above covers, for the same reasons: the happy path, the older-seed
# path, and the caller that does not hand the map in.
# ---------------------------------------------------------------------------


def _list_a_uc_supervisor(live_db):
    """A resolved supervisor who is a UC-directory person.

    `grace` and not `ada`, and that is the whole point of the test below:
    `ada` is on two CISUC projects, so listing HER in a Faculty directory
    produces a person with both a unit badge and a research group — a state
    that cannot occur in the real seed (a UC-directory person appears in no
    `project_people` row) and which would make the "never a group" assertion
    pass for the wrong reason. `grace` is on no project at all, which is
    exactly the shape every real UC-directory person has.
    """
    import sqlite3

    slug = "grace"
    conn = sqlite3.connect(live_db)
    try:
        conn.execute(
            "INSERT INTO directory_listings (person_slug, source, unit_name, listing_url, "
            "person_url, name_as_published, role_as_published, fetched_at) VALUES "
            "(?, 'feuc', 'Faculdade de Economia (FEUC)', "
            "'https://www.uc.pt/feuc/pessoas-e-servicos/docentes/', NULL, 'X', NULL, "
            "'2026-10-19T00:00:00+00:00')",
            (slug,),
        )
        conn.commit()
    finally:
        conn.close()
    return slug


def test_a_uc_directory_supervisor_carries_its_unit_and_never_a_group(live_db):
    """The two halves of the product requirement in one assertion: the person
    is resolved and linked like anybody else, AND the payload says which unit
    publishes them so the UI can never imply they are a CISUC member. The
    group list stays EMPTY — they have no CISUC project history, and that is
    the correct display rather than a gap to fill."""
    slug = _list_a_uc_supervisor(live_db)

    listings = theses.directory_listings(db_path=live_db)
    assert listings[slug][0]["source"] == "feuc"
    assert listings[slug][0]["listing_url"] == (
        "https://www.uc.pt/feuc/pessoas-e-servicos/docentes/"
    )

    supervisors = _by_handle(theses.list_theses(db_path=live_db), "10316/000001")["supervisors"]
    resolved = [s for s in supervisors if s["status"] == "matched"]
    assert resolved, "the fixture must have a resolved supervisor for this to mean anything"
    entry = next(s for s in resolved if any(m["slug"] == slug for m in s["matched"]))
    assert entry["directory"]["source"] == "feuc"
    assert entry["directory"]["unit_name"] == "Faculdade de Economia (FEUC)"
    assert entry["directory"]["units"] == [entry["directory"]["units"][0]]
    assert entry["groups"] == []
    assert entry["group_shares"] == {}


def test_a_cisuc_supervisor_carries_no_directory_key_at_all(live_db):
    """The payload shape for every row that existed before this feature."""
    supervisors = _by_handle(theses.list_theses(db_path=live_db), "10316/000001")["supervisors"]
    assert all("directory" not in s for s in supervisors)


def test_a_seed_built_before_directory_listings_existed_still_renders(live_db):
    """An install that predates this card has no table, and every person in it
    is a CISUC person — which is the correct answer, not a 500."""
    import sqlite3

    conn = sqlite3.connect(live_db)
    try:
        conn.execute("DROP TABLE directory_listings")
        conn.commit()
    finally:
        conn.close()
    assert theses.directory_listings(db_path=live_db) == {}
    supervisors = _by_handle(theses.list_theses(db_path=live_db), "10316/000001")["supervisors"]
    assert all("directory" not in s for s in supervisors)


def test_resolve_person_rows_reads_the_listings_itself_when_not_handed_them(live_db):
    """``list_theses`` passes the map in so the lookup happens once per
    request; a caller that omits it must still get the field rather than
    silently losing the unit badge."""
    slug = _list_a_uc_supervisor(live_db)
    rows = db.rows(db.load_query("thesis_people"), (), live_db)
    supervisor_rows = [
        r for r in rows if r["role"] == "supervisor" and r["person_slug"] == slug
    ]
    resolved = theses._resolve_person_rows(supervisor_rows, db_path=live_db)
    assert resolved[0]["directory"]["source"] == "feuc"
