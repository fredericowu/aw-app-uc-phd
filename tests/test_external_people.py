"""analysis/external_people.py — the researched display layer, and its limits.

The thing under test is not really "does the JSON load". It is the boundary
that keeps this file from becoming option C, the thesis-name -> person lookup
the Product Owner rejected (``docs/thesis-attribution.md``). Three properties
carry that, and each has a test below that fails loudly if it erodes:

* an entry must name a ``thesis_people`` row that **exists** — otherwise a
  thesis withdrawn upstream leaves a researched identity hanging off nothing
  and the build still reports success;
* an entry must name a row that is still ``unmatched``. This is the load-
  bearing one. The day the matcher resolves one of these names, the entry is
  an obsolete claim sitting beside a real CISUC person, and the build has to
  break rather than render both;
* nothing here reaches the matcher. ``analysis/name_match.py`` must not
  import this module, and no row it writes carries a ``person_slug`` —
  ``identity_coverage`` cannot move when an entry is added, because an
  external person is correctly *unresolved*, not newly resolved.

The committed ``data/external_people.json`` is validated against the real
seed at the bottom, so a matcher improvement that resolves one of these 29
mentions fails here rather than at the next rebuild.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from analysis import build_thesis_facts as build_mod
from analysis import external_people

#: Keyed on the one fixture mention that is genuinely ``unmatched`` — see
#: tests/conftest.py. The shape is one thesis mention, never a name.
ENTRY = {
    "handle": "10316/000001",
    "name_raw": "Author, Ada Unresolved",
    "role": "author",
    "display_name": "Ada Unresolved",
    "affiliation": "Somewhere Else University",
    "source_url": "https://example.test/people/ada",
    "evidence": "Her own institutional page names her and gives the affiliation.",
}


def _write(tmp_path, *entries):
    path = tmp_path / "external_people.json"
    path.write_text(json.dumps({"entries": list(entries)}), encoding="utf-8")
    return path


def _status(overrides=None):
    """The ``{(handle, name_raw, role): match_status}`` map ``validate`` reads,
    mirroring the fixture rows."""
    base = {
        ("10316/000001", "Author, Ada Unresolved", "author"): "unmatched",
        ("10316/000001", "Lovelace, Ada", "supervisor"): "exact",
        ("10316/000003", "Ambiguous, Two People", "supervisor"): "ambiguous",
    }
    base.update(overrides or {})
    return base


# --------------------------------------------------------------------------
# The loader — every refusal, because each one is a silent wrong display
# --------------------------------------------------------------------------


def test_an_entry_naming_a_mention_that_does_not_exist_is_refused(tmp_path):
    """The withdrawn-thesis and re-extracted-name cases. Skipping it would
    stop displaying a researched identity and report a successful build."""
    entries = external_people.load_entries(_write(tmp_path, {**ENTRY, "handle": "10316/999999"}))
    with pytest.raises(external_people.ExternalPersonError, match="no row in thesis_people"):
        external_people.validate(entries, _status())


def test_an_entry_shadowing_a_MATCHED_row_is_refused(tmp_path):
    """THE boundary. This file is display metadata for names nothing can
    match; an entry on a resolved row would put a researched external
    identity next to a real CISUC person. The matcher wins, always, and the
    build breaks until the obsolete entry is removed."""
    entries = external_people.load_entries(
        _write(tmp_path, {**ENTRY, "name_raw": "Lovelace, Ada", "role": "supervisor"})
    )
    with pytest.raises(external_people.ExternalPersonError, match="must never shadow a matched row"):
        external_people.validate(entries, _status())


def test_an_entry_on_an_AMBIGUOUS_row_is_refused_too(tmp_path):
    """``ambiguous`` means several real people fit — the opposite of "nobody
    in CISUC is this person". Attaching an external identity there would
    assert an answer the matcher deliberately refused to give."""
    entries = external_people.load_entries(
        _write(
            tmp_path,
            {**ENTRY, "handle": "10316/000003", "name_raw": "Ambiguous, Two People", "role": "supervisor"},
        )
    )
    with pytest.raises(external_people.ExternalPersonError, match="not 'unmatched'"):
        external_people.validate(entries, _status())


def test_a_mention_resolved_by_a_later_matcher_improvement_breaks_the_build(tmp_path):
    """The durability promise, stated as a test: the entries survive every
    rebuild, and the one thing that can retire one is the matcher learning to
    resolve that name — which must be noisy, not silent."""
    entries = external_people.load_entries(_write(tmp_path, ENTRY))
    external_people.validate(entries, _status())
    resolved = _status({("10316/000001", "Author, Ada Unresolved", "author"): "confident"})
    with pytest.raises(external_people.ExternalPersonError, match="obsolete claim"):
        external_people.validate(entries, resolved)


def test_two_entries_for_one_mention_are_refused(tmp_path):
    entries = external_people.load_entries(
        _write(tmp_path, ENTRY, {**ENTRY, "display_name": "Someone Else"})
    )
    with pytest.raises(external_people.ExternalPersonError, match="already has an entry"):
        external_people.validate(entries, _status())


def test_the_same_name_on_two_different_theses_is_two_entries_not_a_clash(tmp_path):
    """Keying on a mention is what makes same-name-different-person safe, and
    the cost is duplication — Torsten Braun supervises two theses. Both
    entries are legitimate and neither is a duplicate key."""
    second = {**ENTRY, "handle": "10316/000003", "name_raw": "Nobody, At All"}
    entries = external_people.load_entries(_write(tmp_path, ENTRY, second))
    external_people.validate(
        entries,
        _status({("10316/000003", "Nobody, At All", "author"): "unmatched"}),
    )


@pytest.mark.parametrize(
    "key", ["handle", "name_raw", "display_name", "affiliation", "source_url", "evidence"]
)
def test_a_blank_required_field_is_refused_before_any_row_is_looked_up(tmp_path, key):
    """``affiliation`` and ``source_url`` are rendered and checkable
    respectively; a blank ``display_name`` would render emptier than the bare
    "(unattributed)" it replaces."""
    with pytest.raises(external_people.ExternalPersonError, match=f"{key!r} must be a non-empty"):
        external_people.load_entries(_write(tmp_path, {**ENTRY, key: "   "}))


def test_a_source_url_that_is_not_a_url_is_refused(tmp_path):
    """The field is what makes the claim checkable by somebody who was not in
    the room, so "see the presentation" is not one."""
    with pytest.raises(external_people.ExternalPersonError, match="is not a URL"):
        external_people.load_entries(_write(tmp_path, {**ENTRY, "source_url": "the research run"}))


def test_an_unknown_role_is_refused(tmp_path):
    with pytest.raises(external_people.ExternalPersonError, match="is not one of"):
        external_people.load_entries(_write(tmp_path, {**ENTRY, "role": "coordinator"}))


def test_note_is_optional_and_every_other_field_is_not(tmp_path):
    external_people.load_entries(_write(tmp_path, ENTRY))
    external_people.load_entries(_write(tmp_path, {**ENTRY, "note": "Middle names unverified."}))
    entry = {k: v for k, v in ENTRY.items() if k != "affiliation"}
    with pytest.raises(external_people.ExternalPersonError, match=r"missing \['affiliation'\]"):
        external_people.load_entries(_write(tmp_path, entry))


def test_an_unknown_key_is_refused_rather_than_ignored(tmp_path):
    """A ``person_slug`` key is the exact thing this file must never carry,
    and a typo'd key is how an entry ends up meaning something else."""
    with pytest.raises(external_people.ExternalPersonError, match="unknown keys"):
        external_people.load_entries(_write(tmp_path, {**ENTRY, "person_slug": "ada"}))


def test_a_file_without_an_entries_list_is_refused(tmp_path):
    path = tmp_path / "external_people.json"
    path.write_text(json.dumps([ENTRY]), encoding="utf-8")
    with pytest.raises(external_people.ExternalPersonError, match="expected an object"):
        external_people.load_entries(path)


# --------------------------------------------------------------------------
# What the seed ends up holding
# --------------------------------------------------------------------------


def test_write_table_replaces_rather_than_accumulates(tmp_path, fixture_db):
    """The table is a pure function of the file, so an entry somebody removed
    — because the matcher now resolves that name — must not survive."""
    conn = sqlite3.connect(fixture_db)
    try:
        assert external_people.load_and_write(conn, _write(tmp_path, ENTRY)) == {
            "external_people": 1
        }
        assert conn.execute(
            "SELECT handle, name_raw, role, display_name, affiliation, source_url, note "
            "FROM external_people"
        ).fetchall() == [
            (
                "10316/000001",
                "Author, Ada Unresolved",
                "author",
                "Ada Unresolved",
                "Somewhere Else University",
                "https://example.test/people/ada",
                None,
            )
        ]

        external_people.load_and_write(conn, _write(tmp_path))
        assert conn.execute("SELECT COUNT(*) FROM external_people").fetchone()[0] == 0
    finally:
        conn.close()


def test_the_evidence_and_the_note_travel_into_the_table(tmp_path, fixture_db):
    conn = sqlite3.connect(fixture_db)
    try:
        external_people.load_and_write(
            conn, _write(tmp_path, {**ENTRY, "note": "Middle names unverified."})
        )
        assert conn.execute("SELECT note, evidence FROM external_people").fetchone() == (
            "Middle names unverified.",
            ENTRY["evidence"],
        )
    finally:
        conn.close()


def test_the_table_has_no_person_slug_column_and_cannot_grow_one_by_accident(fixture_db):
    """Stated as a test because it is the design, not an omission: there is no
    column for a slug, so nothing downstream can mistake an external identity
    for a resolved one."""
    conn = sqlite3.connect(fixture_db)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(external_people)")}
    finally:
        conn.close()
    assert "person_slug" not in columns
    assert columns == {
        "handle",
        "name_raw",
        "role",
        "display_name",
        "affiliation",
        "source_url",
        "note",
        "evidence",
    }


def test_the_matcher_does_not_import_this_module():
    """The gate, checked at the import graph rather than argued in a comment.
    A name this file describes is still unresolved to every count and tier."""
    source = (build_mod.ROOT / "analysis" / "name_match.py").read_text(encoding="utf-8")
    assert "external_people" not in source


# --------------------------------------------------------------------------
# The file that actually ships
# --------------------------------------------------------------------------


def test_the_committed_entries_validate_against_the_real_seed():
    """A mention the matcher has learned to resolve fails HERE, not at the
    next seed rebuild — and a thesis or name that changed upstream too."""
    conn = sqlite3.connect(f"file:{build_mod.DEFAULT_DB}?mode=ro", uri=True)
    try:
        status = {
            (handle, name_raw, role): match_status
            for handle, name_raw, role, match_status in conn.execute(
                "SELECT handle, name_raw, role, match_status FROM thesis_people"
            )
        }
    finally:
        conn.close()
    entries = external_people.load_entries()
    external_people.validate(entries, status)
    # 28 since the UC unit-directory pool landed: "Cruz, Luís Alberto da
    # Silva" now resolves to his own FCTUC/DEEC listing, so his entry was an
    # obsolete claim sitting next to a real identity and the validator above
    # refuses it by design (analysis/external_people.py). The floor is a
    # "don't silently lose entries" guard, not a target.
    assert len(entries) >= 28


def test_the_committed_seed_carries_the_external_people_table_the_app_reads():
    """The app opens the shipped seed, so the table has to be in it — not
    only in scraper/schema.sql."""
    conn = sqlite3.connect(f"file:{build_mod.DEFAULT_DB}?mode=ro", uri=True)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='external_people'"
        ).fetchone()[0] == 1
        # 28 since "Cruz, Luís Alberto da Silva" started resolving to his own
        # FCTUC/DEEC listing — see the floor above and the loader's own
        # refusal of an entry whose mention is no longer unmatched.
        assert conn.execute("SELECT COUNT(*) FROM external_people").fetchone()[0] >= 28
    finally:
        conn.close()
