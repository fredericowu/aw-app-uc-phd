"""Triage the unmatched supervisor names. Offline, one-off, never a matcher.

``python -m analysis.audit_unmatched_supervisors [--db data/cisuc.sqlite3]``

Frederico's ask on card 3fd5bf3b-9510-8128-958f-e1d6b9e63660 was "I want the
collaborators resolving 100%; if one cannot resolve, tell me — and the only
justification I accept is that they are not in the people directory at UC."
Answering it needs a *list*, per name, of which of those two it is. At 2690
theses the unmatched tier is 4453 distinct names, so the list has to be
produced by measurement and then reviewed by a human, not read one name at a
time.

Scope, which is the whole reason the number is answerable
---------------------------------------------------------
Only supervisor mentions on the **CISUC-touching** theses — the 569 whose
author or some supervisor already resolves to a CISUC person. Outside that
set a thesis is a medicine, law or literature doctorate whose committee has
no reason to appear in a computer-science lab's roster, and counting those as
unresolved collaborators is counting the university, not the lab.

What this is NOT
----------------
**``analysis/name_match.py`` must never import this module.** It is triage:
it answers "is this name worth a human's half hour", and it has no verdict,
no slug, no tier and no output anybody ships. The two shapes below are
deliberately *looser* than the matcher — that is the point of a flag — and
anything that read them as a match would be relaxation A or B
(``docs/thesis-attribution.md`` §"Two rejected relaxations"), each of which
bought edges and one confidently wrong person.

The two shapes, and why not surname overlap
-------------------------------------------
Surname overlap flags 1361 pairs in this corpus and is therefore no signal at
all. Every miss this repo has actually recorded — across the Sven Stork
investigation, the 45-name sweep and the reviewed-full-names work — has one
of exactly two shapes, and each already has a curated instrument built for
it:

* **superset** — the surname matches and every thesis token appears in the
  CISUC display name, but the display name carries extra tokens the thesis
  never mentions, so ``_fits()`` rule 2 rejects it. "Cardoso, Amílcar"
  against "F. Amilcar Cardoso"; "Fonseca, Carlos" against "Carlos M.
  Fonseca". Instrument: ``data/person_full_names.json``. Open backlog card:
  ``matching:uc-phd-fits-extra-cisuc-initial``.
* **wrong-ended** — the candidate carries the thesis's primary given name
  *and* at least one further given name, but fails the surname test, because
  CISUC published a form ending in a different name. "Correia, António
  Dourado Pereira" against "António Dourado". Instrument:
  ``data/person_full_names.json``, which is exactly how that one was fixed.

A name flagged by either is "plausibly present — review these candidates". A
name flagged by neither is "no candidate in the roster has a shape any
recorded miss has had", which is the evidence for the absent verdict, not a
proof of it.

Why the roster is allowed to stand for the live directory
---------------------------------------------------------
Because it is checked: ``python -m scraper.people`` re-runs the directory
sync, and on 2026-10-18 it returned 740 site rows adding 0 slugs and renaming
0 names against the committed ``people`` table. The Sven Stork class — a real
CISUC page with no ``people`` row — is therefore empty today, and "absent from
``people``" and "absent from the live directory" are the same statement. Re-run
that sync before trusting this script's absent verdicts again.
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sqlite3
import sys
from pathlib import Path

from .build_thesis_facts import DEFAULT_DB, load_cisuc_people
from .name_match import (
    _carries_primary_given,
    _fits,
    _is_initial_of,
    split_thesis_name,
    tokenize,
)

#: Fixed, and recorded in the report: the singleton sample has to be
#: reproducible by whoever re-reads the audit, or the bound it supports is
#: just an anecdote.
SINGLETON_SAMPLE_SEED = 20261018
SINGLETON_SAMPLE_SIZE = 30

#: The cut for individual review. The in-universe frequency distribution is
#: flat (max 6 edges), so the Product Owner's ">=5 theses" keeps 2 names and
#: ">=10" keeps none — those figures were corpus-wide. >=2 is the only cut
#: that is both non-empty and reviewable in one sitting: 45 names, 113 of the
#: 426 unmatched edges.
REVIEW_CUT = 2


#: This audit's universe, narrowed to CISUC's OWN directory on purpose.
#:
#: The clause at the end is not a new rule — it is what keeps the old one
#: meaning what it meant. `people` used to be CISUC's directory and nothing
#: else, so "resolved to a person" and "resolved to a CISUC person" were the
#: same sentence. Since `scraper/uc_directories/` harvests UC's per-unit staff
#: pages into the same table (`scraper/schema.sql`), a thesis whose only
#: resolved name is an FDUC professor would silently enter this universe, and
#: the published "569 CISUC-touching theses / 636 of 1065 supervisor edges"
#: would change meaning without anybody editing a number. Excluding slugs that
#: carry a `directory_listings` row keeps the 569 the 569.
_CISUC_TOUCHING_SQL = """
SELECT DISTINCT handle FROM thesis_people
WHERE person_slug IS NOT NULL
  AND match_status IN ('exact', 'confident')
  AND person_slug NOT IN (SELECT person_slug FROM directory_listings)
"""


def cisuc_touching(conn: sqlite3.Connection) -> set[str]:
    """The theses where CISUC's own directory is present at all — this audit's
    universe. See ``_CISUC_TOUCHING_SQL`` on why the UC-directory exclusion is
    what PRESERVES this number rather than redefining it."""
    sql = _CISUC_TOUCHING_SQL
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='directory_listings'"
    ).fetchone():
        sql = sql.split("  AND person_slug NOT IN")[0]
    return {handle for (handle,) in conn.execute(sql)}


def supervisor_edges(
    conn: sqlite3.Connection, handles: set[str], status: str, source: str = "any"
) -> list[tuple]:
    """``[(handle, name_raw)]`` for supervisor mentions at one match_status.

    An EDGE is a (thesis, name) pair, not a row: a name resolving to two
    duplicate ``people`` rows writes two rows and is still one edge, and
    counting rows would quietly inflate the denominator of the headline
    number this audit exists to produce.

    ``source`` splits the resolved side by WHICH directory answered —
    ``cisuc`` is the pool this audit has always counted (and is what keeps the
    published 636/1065 comparable), ``uc`` is the per-unit directories, and
    ``any`` is both. The split exists rather than a redefinition because the
    Product Owner's constraint is that the old number keeps meaning what it
    meant; the new one is reported beside it, never merged into it.
    """
    clause = {
        "any": "",
        "cisuc": " AND person_slug NOT IN (SELECT person_slug FROM directory_listings)",
        "uc": " AND person_slug IN (SELECT person_slug FROM directory_listings)",
    }[source]
    if clause and not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='directory_listings'"
    ).fetchone():
        # No UC pool in this seed at all: every resolved row is a CISUC one.
        clause = "" if source == "cisuc" else " AND 0"
    return sorted(
        {
            (handle, name_raw)
            for handle, name_raw in conn.execute(
                "SELECT handle, name_raw FROM thesis_people WHERE role = 'supervisor' "
                "AND match_status = ?" + clause,
                (status,),
            )
            if handle in handles
        }
    )


def superset_candidates(name_raw: str, people) -> list:
    """The CISUC form carries every token of the thesis form, and more.

    ``_fits()`` run in reverse: rule 1 (surname) must still hold, every
    thesis token must appear in the candidate, and the candidate must be
    rejected by the real fit — otherwise it is simply a match and not a miss.
    """
    thesis_tokens = tokenize(name_raw)
    surname_tokens, given_tokens = split_thesis_name(name_raw)
    if not surname_tokens:
        return []
    out = []
    for person in people:
        candidate_tokens = tokenize(person.name)
        if not all(s in candidate_tokens for s in surname_tokens):
            continue
        if not all(t in candidate_tokens for t in thesis_tokens):
            continue
        if _fits(candidate_tokens, thesis_tokens, surname_tokens, given_tokens)[0]:
            continue
        out.append(person)
    return out


def wrong_ended_candidates(name_raw: str, people) -> tuple[list, list]:
    """CISUC published a form ending in a name the thesis does not use.

    Returns ``(tight, loose)``. Both require the thesis's primary given name
    *plus* at least one further given token, and both require the surname test
    to FAIL — that is what "wrong-ended" means. They differ on one condition,
    and the difference turned out to be the whole signal:

    * **tight** additionally requires every candidate token to be accounted
      for by the thesis name — i.e. ``_fits()`` rule 2 holds while rule 1
      does not. This is the recorded case exactly: "António Dourado"
      ({antonio, dourado}) sits entirely inside "Correia, António Dourado
      Pereira", and only the surname is missing.
    * **loose** is the condition as first specified, without that. Kept, and
      reported, because measuring it is what showed it cannot be used: on the
      358 names in this audit it flags 91 names and **every one of them is a
      coincidence between two common Portuguese given names across different
      surnames** — "Santos, Ana Teresa Moreira Almeida" against "Ana Maria
      Carvalho de Almeida", whose "Maria" and "Carvalho" appear nowhere in
      the thesis name. A reviewer handed the loose list reads 91 names to
      find nothing; the tight list is the one worth reading.
    """
    surname_tokens, given_tokens = split_thesis_name(name_raw)
    if not surname_tokens or len(given_tokens) < 2:
        return [], []
    thesis_tokens = tokenize(name_raw)
    primary, rest = given_tokens[0], given_tokens[1:]
    tight, loose = [], []
    for person in people:
        candidate_tokens = tokenize(person.name)
        if all(s in candidate_tokens for s in surname_tokens):
            continue  # the surname test passes, so this is not the shape
        if not _carries_primary_given(candidate_tokens, primary):
            continue
        if not any(token in candidate_tokens for token in rest):
            continue
        loose.append(person)
        if all(
            token in thesis_tokens or _is_initial_of(token, given_tokens)
            for token in candidate_tokens
        ):
            tight.append(person)
    return tight, loose


def surname_bearing_rows(name_raw: str, people) -> list[tuple]:
    """Every ``people`` row the matcher could *ever* accept for this name, with
    the reason it did not — ``[(slug, name, unaccounted_tokens)]``.

    ``_fits()`` rule 1 is absolute: a candidate that does not carry every
    surname token of the thesis name is rejected before anything else gets a
    say, and no curated instrument in this repo moves that. So an empty list
    here is the strongest absence evidence available short of reading the
    directory by hand — "nobody CISUC publishes carries this surname at all"
    — and a non-empty one is the complete, finite set of rows a reviewer has
    to look at.
    """
    thesis_tokens = tokenize(name_raw)
    surname_tokens, given_tokens = split_thesis_name(name_raw)
    out = []
    for person in people:
        candidate_tokens = tokenize(person.name)
        if not surname_tokens or not all(s in candidate_tokens for s in surname_tokens):
            continue
        unaccounted = [
            token
            for token in candidate_tokens
            if token not in thesis_tokens and not _is_initial_of(token, given_tokens)
        ]
        out.append((person.slug, person.name, unaccounted))
    return sorted(out)


def audit(db_path: Path) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        handles = cisuc_touching(conn)
        people = load_cisuc_people(conn)
        unmatched = supervisor_edges(conn, handles, "unmatched")
        ambiguous = supervisor_edges(conn, handles, "ambiguous")
        matched = len(
            supervisor_edges(conn, handles, "exact", "cisuc")
        ) + len(supervisor_edges(conn, handles, "confident", "cisuc"))
        matched_uc = len(
            supervisor_edges(conn, handles, "exact", "uc")
        ) + len(supervisor_edges(conn, handles, "confident", "uc"))
    finally:
        conn.close()

    handles_by_name = collections.defaultdict(list)
    for handle, name in unmatched:
        handles_by_name[name].append(handle)
    by_name = collections.Counter({name: len(h) for name, h in handles_by_name.items()})

    def dossier(name: str) -> dict:
        """Everything a reviewer needs on one name, and nothing derived from
        it: the shapes that flagged it, and the complete finite set of rows
        the matcher could ever have accepted."""
        supersets = superset_candidates(name, people)
        tight, loose = wrong_ended_candidates(name, people)
        return {
            "edges": by_name[name],
            "handles": sorted(handles_by_name[name]),
            "surname": list(split_thesis_name(name)[0]),
            "superset": [[p.slug, p.name] for p in supersets],
            "wrong_ended": [[p.slug, p.name] for p in tight],
            "wrong_ended_loose": [[p.slug, p.name] for p in loose],
            "surname_bearing_rows": surname_bearing_rows(name, people),
        }

    flagged = {
        name: d
        for name, d in ((name, dossier(name)) for name in by_name)
        if d["superset"] or d["wrong_ended"]
    }

    above_cut = sorted(
        (name for name, edges in by_name.items() if edges >= REVIEW_CUT),
        key=lambda name: (-by_name[name], name),
    )
    singletons = sorted(name for name, edges in by_name.items() if edges < REVIEW_CUT)
    sample = sorted(
        random.Random(SINGLETON_SAMPLE_SEED).sample(
            singletons, min(SINGLETON_SAMPLE_SIZE, len(singletons))
        )
    )
    return {
        "cisuc_touching_theses": len(handles),
        "supervisor_edges": matched + matched_uc + len(unmatched) + len(ambiguous),
        # `matched_edges` is and stays CISUC's own directory: it is the number
        # this repo published as 636 of 1065, and a reader comparing against it
        # has to be comparing the same thing. The UC-directory edges are the
        # separate number next to it.
        "matched_edges": matched,
        "matched_edges_uc_directory": matched_uc,
        "unmatched_edges": len(unmatched),
        "ambiguous_edges": len(ambiguous),
        "distinct_unmatched_names": len(by_name),
        "edge_frequency": dict(sorted(collections.Counter(by_name.values()).items())),
        "review_cut": REVIEW_CUT,
        "above_cut": {name: dossier(name) for name in above_cut},
        "singleton_sample_seed": SINGLETON_SAMPLE_SEED,
        "singleton_sample": {name: dossier(name) for name in sample},
        "singletons_not_sampled": len(singletons) - len(sample),
        "ambiguous_edge_list": ambiguous,
        "flagged_names_total": len(flagged),
        "flagged_above_cut": sorted(name for name in above_cut if name in flagged),
        "flagged_in_sample": sorted(name for name in sample if name in flagged),
        "loose_flagged_names_total": sum(
            1 for name in by_name if wrong_ended_candidates(name, people)[1]
        ),
        "names_with_no_surname_bearing_row": sum(
            1 for name in by_name if not surname_bearing_rows(name, people)
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    print(json.dumps(audit(args.db), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
