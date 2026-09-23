"""uc_phd_app/theses.py — the estudo_geral/*.md -> people/project_groups join.

Uses the same small fixture database as test_routes.py/test_db.py (Ada
Lovelace coordinates Alpha [AC, NCS] and Beta [NCS]; Alan Turing is only ever
a *researcher* on Alpha, never a coordinator) so the coordinator-then-
researcher fallback in ``_person_groups`` is exercised against real rows
rather than asserted in the abstract.
"""
from __future__ import annotations

import json

import pytest

from uc_phd_app import theses

THESIS_A = """---
handle: 10316/000001
title: Thesis A
authors:
- Ada Author
supervisors:
- Curie Coord
- Nomatch Nobody
date: '2024-05-01'
rights: openAccess
full_text: true
source_url: https://estudogeral.uc.pt/handle/10316/000001
---

# Thesis A

Body text nobody needs to read for this test.
"""

THESIS_B = """---
handle: 10316/000002
title: Thesis B
authors:
- Turing Research
supervisors: []
date: '2025-01-01'
rights: embargoedAccess
full_text: false
source_url: https://estudogeral.uc.pt/handle/10316/000002
---

# Thesis B
"""

THESIS_C = """---
handle: 10316/000003
title: Thesis C
authors:
- Nobody Author
supervisors:
- Nobody Supervisor
date: '2023-11-20'
rights: openAccess
full_text: true
source_url: https://estudogeral.uc.pt/handle/10316/000003
---

# Thesis C
"""

ATTRIBUTION = {
    "Ada Author": {"status": "unattributed", "note": "no exact match in people"},
    "Curie Coord": {
        "status": "matched",
        "matches": [{"slug": "ada", "name": "Ada Lovelace"}],
        "note": "test fixture match",
    },
    # Matched to a real person-shaped slug with no project_people rows at
    # all, so _person_groups legitimately returns an empty set for a
    # *matched* name — distinct from "unattributed".
    "Nomatch Nobody": {
        "status": "matched",
        "matches": [{"slug": "nope", "name": "Nobody Project-less"}],
    },
    # alan is only ever a researcher in the fixture DB (never a
    # coordinator), so resolving this name exercises the fallback branch.
    "Turing Research": {
        "status": "matched",
        "matches": [{"slug": "alan", "name": "Alan Turing"}],
    },
    # Thesis C's names are deliberately absent from this table entirely —
    # covers the "no entry at all" unattributed path, distinct from
    # "Ada Author" above where an entry exists but says unattributed.
}


@pytest.fixture()
def estudo_geral_dir(tmp_path):
    d = tmp_path / "estudo_geral"
    d.mkdir()
    (d / "10316-000001.md").write_text(THESIS_A, encoding="utf-8")
    (d / "10316-000002.md").write_text(THESIS_B, encoding="utf-8")
    (d / "10316-000003.md").write_text(THESIS_C, encoding="utf-8")
    return d


@pytest.fixture()
def attribution_path(tmp_path):
    p = tmp_path / "thesis-attribution.json"
    p.write_text(json.dumps(ATTRIBUTION), encoding="utf-8")
    return p


@pytest.fixture()
def theses_list(estudo_geral_dir, attribution_path, live_db):
    return theses.list_theses(
        estudo_geral_dir=estudo_geral_dir,
        attribution_path=attribution_path,
        db_path=live_db,
    )


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
    assert author == {"name": "Ada Author", "status": "unattributed", "note": "no exact match in people", "matched": [], "groups": []}

    supervisors = {s["name"]: s for s in a["supervisors"]}
    assert supervisors["Curie Coord"]["status"] == "matched"
    assert supervisors["Curie Coord"]["groups"] == ["AC", "NCS"]
    # Matched to a real slug, but that slug coordinates/researches nothing —
    # a matched name can still legitimately resolve to zero groups.
    assert supervisors["Nomatch Nobody"]["groups"] == []

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


def test_a_thesis_with_no_entry_at_all_for_any_name_is_unattributed(theses_list):
    c = _by_handle(theses_list, "10316/000003")
    assert c["authors"][0]["status"] == "unattributed"
    assert c["authors"][0]["note"] is None
    assert c["supervisors"][0]["status"] == "unattributed"
    assert c["groups"] == []
    assert c["attributed"] is False


def test_group_breakdown_is_many_to_many_and_counts_the_unattributed(theses_list):
    breakdown = theses.group_breakdown(theses_list)
    # A + B both carry AC and NCS: 2 + 2, not 1 + 1 deduped across theses.
    assert breakdown["counts"] == {"AC": 2, "NCS": 2}
    assert breakdown["unattributed"] == 1  # Thesis C only


def test_malformed_front_matter_raises(tmp_path, attribution_path):
    bad_dir = tmp_path / "estudo_geral"
    bad_dir.mkdir()
    (bad_dir / "broken.md").write_text("# No front matter here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no YAML front matter"):
        theses.list_theses(estudo_geral_dir=bad_dir, attribution_path=attribution_path)


def test_the_committed_attribution_table_covers_every_real_thesis_name():
    """The reviewable record (docs/thesis-attribution.json) must not silently
    drift out of sync with the real estudo_geral/*.md files it documents —
    every author/supervisor name in the real theses needs an entry, matched
    or explicitly unattributed."""
    from uc_phd_app import paths

    with open(paths.thesis_attribution_path(), encoding="utf-8") as f:
        attribution = json.load(f)

    real_theses = theses._load_front_matters()
    assert len(real_theses) == 18

    all_names = set()
    for fm in real_theses:
        all_names.update(fm.get("authors") or [])
        all_names.update(fm.get("supervisors") or [])

    assert all_names == set(attribution), (
        f"missing from docs/thesis-attribution.json: {all_names - set(attribution)}; "
        f"stale entries no thesis references: {set(attribution) - all_names}"
    )
    for name, entry in attribution.items():
        assert entry["status"] in ("matched", "unattributed")
        if entry["status"] == "matched":
            assert entry["matches"], f"{name}: matched status needs at least one match"
