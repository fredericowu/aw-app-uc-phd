"""analysis/audit_unmatched_supervisors.py — the triage, and what it is not.

This script answers "which unmatched supervisor names are worth a human's
half hour". It is not a matcher, it ships no verdict, and the two shapes it
flags are deliberately LOOSER than ``_fits()`` — so the thing worth testing
is that each shape flags the case it was derived from, refuses the case it
was derived *against*, and stays out of the matcher's way.

The loose/tight split in ``wrong_ended_candidates`` is the finding this
module exists to carry forward, so it is asserted rather than described: the
condition as first specified (primary given name plus one more, surname test
failing) fires on any two common Portuguese given names across different
surnames, and only the added "every candidate token is accounted for by the
thesis name" makes it the Dourado shape.
"""
from __future__ import annotations

import sqlite3

from analysis import audit_unmatched_supervisors as audit
from analysis.name_match import Person

#: The two recorded misses, and two rows that must never be flagged.
DOURADO = Person("antonio-dourado", "António Dourado")
CARDOSO = Person("f-cardoso", "F. Amilcar Cardoso")
CARLOS_FONSECA = Person("carlos-fonseca", "Carlos M. Fonseca")
ANA_ALMEIDA = Person("ana-almeida", "Ana Maria Carvalho de Almeida")
MANUEL_PEDRO = Person("manuel-pedro", "Manuel Pedro")


def test_the_superset_shape_flags_the_cardoso_family():
    """"Cardoso, Amílcar" against "F. Amilcar Cardoso": the surname matches,
    every thesis token is in the candidate, and the candidate's "F." is not an
    initial of any given name the thesis carries — so ``_fits()`` rule 2
    rejects it and this flags it."""
    assert audit.superset_candidates("Cardoso, Amílcar", [CARDOSO, DOURADO]) == [CARDOSO]


def test_the_superset_shape_does_not_flag_a_name_the_matcher_already_resolves():
    """A candidate the real fit accepts is a match, not a miss. Flagging it
    would put resolved names on a reviewer's worklist."""
    assert audit.superset_candidates("Cardoso, Fernando Amílcar", [CARDOSO]) == []


def test_the_superset_shape_does_not_flag_a_mere_surname_overlap():
    """The rejection the whole discriminator exists to make: surname overlap
    flags 1361 pairs in this corpus and is therefore no signal."""
    assert audit.superset_candidates("Fonseca, Maria", [CARLOS_FONSECA]) == []


def test_the_wrong_ended_shape_flags_dourado_tight():
    """"Correia, António Dourado Pereira" against "António Dourado": the
    surname test fails (nothing in the CISUC form says Correia) while every
    token of the CISUC form sits inside the thesis name."""
    tight, loose = audit.wrong_ended_candidates(
        "Correia, António Dourado Pereira", [DOURADO, CARDOSO]
    )
    assert tight == [DOURADO]
    assert loose == [DOURADO]


def test_the_loose_wrong_ended_shape_fires_on_two_common_given_names():
    """The measured finding. "Santos, Ana Teresa Moreira Almeida" shares the
    primary given name "Ana" and the further token "Almeida" with "Ana Maria
    Carvalho de Almeida" — whose "Maria" and "Carvalho" appear nowhere in the
    thesis name, so they are different people. The loose condition flags it;
    only the tight one does not, which is why the tight one is the list a
    reviewer reads."""
    tight, loose = audit.wrong_ended_candidates(
        "Santos, Ana Teresa Moreira Almeida", [ANA_ALMEIDA]
    )
    assert loose == [ANA_ALMEIDA]
    assert tight == []


def test_the_tight_wrong_ended_shape_still_has_false_positives_by_construction():
    """Honest about its own precision: a CISUC person whose whole published
    name happens to be two of a thesis person's given names IS the tight
    shape. "Santos, Pedro Manuel Pinto dos" against "Manuel Pedro" is a
    reviewer's reject, not a bug, and the script's job ends at the flag."""
    tight, _ = audit.wrong_ended_candidates("Santos, Pedro Manuel Pinto dos", [MANUEL_PEDRO])
    assert tight == [MANUEL_PEDRO]


def test_a_name_with_one_given_name_is_never_wrong_ended():
    """Both shapes need a second given token; one common given name plus a
    different surname is the coincidence, not the signal."""
    assert audit.wrong_ended_candidates("Santos, Ana", [ANA_ALMEIDA]) == ([], [])


def test_surname_bearing_rows_is_the_complete_finite_set_a_reviewer_must_read():
    """``_fits()`` rule 1 is absolute and no curated instrument moves it, so
    an empty list here is the absence evidence and a non-empty one is the
    whole worklist, with the rejection reason attached."""
    assert audit.surname_bearing_rows("Stork, Sven", [DOURADO, CARDOSO]) == []
    assert audit.surname_bearing_rows("Cardoso, Amílcar", [CARDOSO]) == [
        ("f-cardoso", "F. Amilcar Cardoso", ["f"])
    ]


def test_an_edge_is_a_thesis_and_a_name_not_a_row():
    """A name resolving to two duplicate ``people`` rows writes two rows and
    is still one collaboration; counting rows would inflate the denominator of
    the number this audit exists to report."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE thesis_people (handle TEXT, name_raw TEXT, role TEXT, "
        "person_slug TEXT, match_status TEXT);"
        "INSERT INTO thesis_people VALUES"
        " ('t1', 'Bicker, João Manuel', 'supervisor', 'joao-bicker', 'confident'),"
        " ('t1', 'Bicker, João Manuel', 'supervisor', 'joao-bicker-1', 'confident'),"
        " ('t1', 'Stork, Sven', 'supervisor', NULL, 'unmatched'),"
        " ('t2', 'Stork, Sven', 'author', NULL, 'unmatched');"
    )
    assert audit.supervisor_edges(conn, {"t1", "t2"}, "confident") == [
        ("t1", "Bicker, João Manuel")
    ]
    # The author row is out of scope, and so is a thesis outside the universe.
    assert audit.supervisor_edges(conn, {"t1"}, "unmatched") == [("t1", "Stork, Sven")]
    assert audit.supervisor_edges(conn, set(), "unmatched") == []


def test_the_audit_reproduces_the_universe_it_reported_on():
    """The numbers the Kanban report is built from, re-derived from the seed
    that ships. A harvest or a directory sync that moves them should make
    whoever reads the report re-run it, not quietly invalidate it.

    **The two halves of this assertion behave differently on purpose, and
    that is the point of the UC-directory work.** The UNIVERSE is unchanged —
    569 theses, 1055 supervisor edges, and `matched_edges` still 626, because
    `cisuc_touching` and the matched count are both pinned to CISUC's own
    directory (``_CISUC_TOUCHING_SQL``). Had they not been, a thesis whose
    only resolved name is an FDUC professor would have walked into the 569 and
    changed what every figure here means without anybody editing a number.

    The UNMATCHED half did move, and it moved because 92 of those edges (76
    distinct names) now resolve against UC's per-unit directories: 426 -> 334
    edges, 358 -> 282 names. That is the feature working, and it is reported
    beside the old number as ``matched_edges_uc_directory`` rather than folded
    into it.
    """
    report = audit.audit(audit.DEFAULT_DB)
    assert report["cisuc_touching_theses"] == 569
    assert report["supervisor_edges"] == 1055
    assert report["matched_edges"] == 626
    assert report["matched_edges_uc_directory"] == 92
    assert report["distinct_unmatched_names"] == 282
    assert report["unmatched_edges"] == 334
    assert report["ambiguous_edges"] == 3
    assert report["edge_frequency"] == {1: 249, 2: 22, 3: 7, 4: 2, 6: 2}
    assert len(report["above_cut"]) == 33
    assert len(report["singleton_sample"]) == 30
    assert report["singletons_not_sampled"] == 219
    # The sample is seeded, so the 30 names reviewed are the 30 names anybody
    # re-running this gets. Without that the bound it supports is an anecdote.
    assert audit.audit(audit.DEFAULT_DB)["singleton_sample"] == report["singleton_sample"]


def test_the_matcher_does_not_import_the_triage():
    """The one structural rule. Every shape here is looser than ``_fits()`` by
    design, so a matcher that read one would be relaxation A or B."""
    source = (audit.__file__.rsplit("/", 1)[0] + "/name_match.py")
    with open(source, encoding="utf-8") as handle:
        assert "audit_unmatched_supervisors" not in handle.read()
