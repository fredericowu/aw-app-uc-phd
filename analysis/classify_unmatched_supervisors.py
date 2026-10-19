"""Classify every supervisor name NEITHER directory resolves. Triage, never a matcher.

``python -m analysis.classify_unmatched_supervisors [--db data/cisuc.sqlite3]``

Frederico's scope on card 3fd5bf3b-9510-8113-a699-ec378da4a0c9 is "resolve
everyone who is actually at UC; I accept a name staying unresolved only if the
person is genuinely not a UC person". Answering that needs the leftover list
split by WHY, so this script produces one dossier per unmatched supervisor
name and a suggested class for it.

How this differs from ``analysis/audit_unmatched_supervisors.py``, which stays
exactly as it is
----------------------------------------------------------------------------
That one asks "is this name worth a human's half hour", over the **569
CISUC-touching theses** — the universe its published numbers describe, and
changing it would quietly change them. This one asks a different question
("which of three product classes is this"), over the **whole corpus**,
because Frederico's scope does not respect the CISUC boundary: Canotilho
supervising a law thesis is a UC supervisor.

The three classes are the Product Owner's, they are binding, and they are
THREE rather than two
---------------------------------------------------------------------------
1. ``never-uc`` — a foreign co-supervisor or external examiner who was never
   UC staff. This is the only justification Frederico accepted.
2. ``former-uc`` — **was** UC staff and appears on no CURRENT directory page:
   retired, left, or deceased. Every per-unit page publishes current staff
   and this corpus starts in the 1990s, so no scraper iteration reaches this
   class. It is counted SEPARATELY and never folded into class 1, because
   folding it would report a ceiling as an accepted justification. If it is
   large, that is a product decision — hand-curate or accept — and it goes
   back to the PO, not to a Coder.
3. ``resolvable-missed`` — this pass should have caught it: a shape the
   matcher is known to miss, or a thesis whose own faculty has no harvested
   unit in the registry yet. **This class is a bug list**, and each entry is
   either fixed or explained before the card closes.

What this is NOT
----------------
**``analysis/name_match.py`` must never import this module**, exactly like the
audit. There is no verdict here, no tier, and — deliberately — **no slug
anywhere in the output**. The candidate information a reviewer gets is a
NAME and the UNIT that publishes it, which is what you check a live page
against; a name->slug pair in a file is the Product-Owner-rejected
attribution table (option C, ``docs/thesis-attribution.md``) with extra
steps. The output lands in ``.tmp/`` and in the Kanban report, never in
``data/``.

``suggested_class`` is a PRIOR, not a verdict. The PO's completeness bar is
that every one of the top 100 names is individually resolved or classified by
a human, with the tail reported in aggregate per class; this script makes that
review possible, it does not perform it.
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

from .audit_unmatched_supervisors import (
    superset_candidates,
    wrong_ended_candidates,
)
from .build_thesis_facts import (
    DEFAULT_DB,
    load_cisuc_people,
    load_uc_directory_people,
)
from .name_match import _fits, _is_initial_of, split_thesis_name, tokenize

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SET_NAMES = ROOT / "data" / "oai_set_names.json"
DEFAULT_OUT = ROOT / ".tmp" / "classify_unmatched_supervisors.json"

#: Bumped whenever a signal or the class prior changes, and recorded in the
#: output. The numbers in a Kanban report have to say which version produced
#: them, or re-reading the report later compares two different measurements.
CLASSIFIER_VERSION = 1

#: The year at or below which a thesis is "old enough that a supervisor could
#: have retired since". A prior, not a fact: UC publishes current staff and
#: this corpus starts in the 1990s, so the further back a thesis is the more
#: of its committee has left. Recorded in the output so a reviewer can see
#: what moved a name into ``former-uc`` and disagree with it.
FORMER_UC_YEAR_CEILING = 2015

#: Which harvested unit a thesis's own OAI set belongs to — substring of the
#: set NAME (``data/oai_set_names.json``, read off Estudo Geral's OAI
#: ``ListSets`` on 2026-10-19) to the registry ``source``.
#:
#: This is the signal that separates class 2 from class 3. "No current listing
#: fits AND this thesis's faculty IS harvested" is evidence the person is gone
#: from that faculty; "no current listing fits AND the faculty is NOT
#: harvested" is evidence about the REGISTRY, not about the person, and lands
#: in class 3 where it belongs — a coverage gap of this pass is a bug in this
#: pass.
UNIT_BY_SET_NAME = (
    ("FEUC", "feuc"),
    ("Faculdade de Economia", "feuc"),
    ("FDUC", "fduc"),
    ("Faculdade de Direito", "fduc"),
    ("FLUC", "fluc"),
    ("Faculdade de Letras", "fluc"),
    ("FFUC", "ffuc"),
    ("Faculdade de Farmácia", "ffuc"),
    ("FPCEUC", "fpce"),
    ("Faculdade de Psicologia", "fpce"),
    ("FCTUC Ciências da Vida", "fctuc-dcv"),
    ("Departamento de Ciências da Vida", "fctuc-dcv"),
    ("FCTUC Eng.Electrotécnica", "fctuc-deec"),
    ("Departamento de Engenharia Electrotécnica", "fctuc-deec"),
    ("CES ", "ces"),
    ("I&D CES", "ces"),
)

NEVER_UC = "never-uc"
FORMER_UC = "former-uc"
RESOLVABLE_MISSED = "resolvable-missed"


def load_set_names(path: Path | None = None) -> dict[str, str]:
    path = path or DEFAULT_SET_NAMES
    return json.loads(path.read_text(encoding="utf-8"))


def unit_for_set(set_name: str) -> str | None:
    for needle, source in UNIT_BY_SET_NAME:
        if needle in set_name:
            return source
    return None


def unmatched_supervisor_edges(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """``[(handle, name_raw)]`` — every supervisor mention NEITHER pool
    resolved, corpus-wide.

    An EDGE is a (thesis, name) pair and not a row, the same grain the audit
    counts at and for the same reason: a name resolving to two duplicate rows
    is one identity decision, and counting rows inflates every denominator.
    """
    return sorted(
        {
            (handle, name_raw)
            for handle, name_raw in conn.execute(
                "SELECT handle, name_raw FROM thesis_people "
                "WHERE role = 'supervisor' AND match_status = 'unmatched'"
            )
        }
    )


def surname_bearing_names(name_raw: str, people) -> list[dict]:
    """Every row either pool could EVER accept for this name, by name only.

    ``_fits()`` rule 1 is absolute — a candidate not carrying every surname
    token of the thesis name is rejected before anything else gets a say —
    so an empty list here is the strongest absence evidence short of reading
    the directory by hand, and a non-empty one is the finite set a reviewer
    has to look at.

    Returns names and sources, **never slugs**: a reviewer checks a candidate
    against a live unit page, and a name->slug pair in a triage file is the
    rejected attribution table. See this module's docstring.
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
        out.append(
            {
                "name": person.name,
                "source": person.source,
                "unaccounted": [
                    token
                    for token in candidate_tokens
                    if token not in thesis_tokens
                    and not _is_initial_of(token, given_tokens)
                ],
            }
        )
    return sorted(out, key=lambda row: (row["source"], row["name"]))


def _shape_flags(name_raw: str, people) -> dict:
    """The two shapes every recorded miss in this repo has had, measured
    against one pool. Looser than the matcher on purpose — that is what a
    flag is — and anything that read them as a match would be relaxation A
    or B (``docs/thesis-attribution.md``)."""
    supersets = superset_candidates(name_raw, people)
    tight, _loose = wrong_ended_candidates(name_raw, people)
    return {
        "superset": [[p.name, p.source] for p in supersets],
        "wrong_ended": [[p.name, p.source] for p in tight],
    }


def _fits_any(name_raw: str, people) -> bool:
    thesis_tokens = tokenize(name_raw)
    surname_tokens, given_tokens = split_thesis_name(name_raw)
    return any(
        _fits(tokenize(p.name), thesis_tokens, surname_tokens, given_tokens)[0] for p in people
    )


def suggest_class(dossier: dict) -> tuple[str, str]:
    """``(class, reasoning)`` — a prior over the PO's three classes.

    Order matters and encodes the PO's own priorities: a bug is called a bug
    before anything gets written off, and the ceiling class is only reached
    once the registry has actually looked where the thesis points.
    """
    uc = dossier["uc_directory_pool"]
    cisuc = dossier["cisuc_pool"]
    if uc["superset"] or uc["wrong_ended"] or cisuc["superset"] or cisuc["wrong_ended"]:
        return (
            RESOLVABLE_MISSED,
            "a directory row has one of the two shapes this matcher is known to miss "
            "(the published form carries given names the thesis omits, or it ends in a "
            "different surname) — the documented instrument is a reviewed entry in "
            "data/person_full_names.json, and the rule-level fix is the open backlog "
            "card matching:uc-phd-fits-extra-cisuc-initial",
        )
    if not dossier["units_harvested"] and dossier["units_pointed_at"]:
        return (
            RESOLVABLE_MISSED,
            "this thesis's own faculty has no harvested unit in "
            "scraper/uc_directories/units.py yet, so no candidate pool was ever "
            "consulted for it — this is a coverage gap of this pass, not a fact about "
            "the person",
        )
    if dossier["units_harvested"] and (dossier["max_year"] or 9999) <= FORMER_UC_YEAR_CEILING:
        return (
            FORMER_UC,
            f"the faculty this thesis sits in IS harvested and publishes no row that "
            f"could fit this name, and the thesis is from {dossier['max_year']} — a "
            "supervisor who has since retired, left or died appears on no CURRENT "
            "staff page, which no scraper iteration can fix",
        )
    if not dossier["units_pointed_at"]:
        return (
            RESOLVABLE_MISSED,
            "this thesis carries no OAI set that names a UC faculty, so there is "
            "nothing to check the name against — an extraction/registry gap rather "
            "than a statement about the person",
        )
    return (
        NEVER_UC,
        "no row in either directory carries this surname at all, none of the known "
        "miss shapes fires, and the faculty the thesis sits in IS harvested and "
        "recent — the evidence available says this person is not and was not UC "
        "staff (a foreign co-supervisor or an external examiner)",
    )


def classify(db_path: Path, set_names_path: Path | None = None, top: int = 100) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cisuc = load_cisuc_people(conn)
        uc = load_uc_directory_people(conn)
        edges = unmatched_supervisor_edges(conn)
        years = {
            handle: year
            for handle, year in conn.execute("SELECT handle, year FROM theses")
        }
        sets_by_handle: dict[str, list[str]] = collections.defaultdict(list)
        for handle, spec in conn.execute("SELECT handle, set_spec FROM thesis_sets"):
            sets_by_handle[handle].append(spec)
        resolved_uc_edges = conn.execute(
            "SELECT COUNT(*) FROM (SELECT handle, name_raw FROM thesis_people "
            "WHERE role = 'supervisor' AND person_slug IN "
            "(SELECT person_slug FROM directory_listings) GROUP BY handle, name_raw)"
        ).fetchone()[0]
    finally:
        conn.close()

    set_names = load_set_names(set_names_path)
    harvested_sources = {person.source for person in uc}

    handles_by_name: dict[str, list[str]] = collections.defaultdict(list)
    for handle, name in edges:
        handles_by_name[name].append(handle)

    def dossier(name: str) -> dict:
        handles = sorted(handles_by_name[name])
        thesis_years = sorted({years.get(h) for h in handles if years.get(h)})
        pointed: set[str] = set()
        set_labels: set[str] = set()
        for handle in handles:
            for spec in sets_by_handle.get(handle, ()):
                label = set_names.get(spec)
                if not label:
                    continue
                set_labels.add(label)
                source = unit_for_set(label)
                if source:
                    pointed.add(source)
        out = {
            "edges": len(handles),
            "handles": handles,
            "years": thesis_years,
            "max_year": int(thesis_years[-1]) if thesis_years else None,
            "surname": list(split_thesis_name(name)[0]),
            "oai_sets": sorted(set_labels),
            "units_pointed_at": sorted(pointed),
            "units_harvested": sorted(pointed & harvested_sources),
            "cisuc_pool": {
                **_shape_flags(name, cisuc),
                "surname_bearing": surname_bearing_names(name, cisuc),
                "any_fit": _fits_any(name, cisuc),
            },
            "uc_directory_pool": {
                **_shape_flags(name, uc),
                "surname_bearing": surname_bearing_names(name, uc),
                "any_fit": _fits_any(name, uc),
            },
        }
        suggested, reasoning = suggest_class(out)
        out["suggested_class"] = suggested
        out["reasoning"] = reasoning
        return out

    by_edges = collections.Counter({name: len(h) for name, h in handles_by_name.items()})
    ranked = [name for name, _ in by_edges.most_common()]
    dossiers = {name: dossier(name) for name in ranked}

    tail = ranked[top:]
    return {
        "classifier_version": CLASSIFIER_VERSION,
        "inputs": {
            "db": str(db_path),
            "oai_set_names": str(set_names_path or DEFAULT_SET_NAMES),
            "cisuc_pool_size": len(cisuc),
            "uc_directory_pool_size": len(uc),
            "harvested_units": sorted(harvested_sources),
            "former_uc_year_ceiling": FORMER_UC_YEAR_CEILING,
        },
        "universe": {
            "scope": "corpus-wide, every supervisor mention neither pool resolved",
            "unmatched_supervisor_edges": len(edges),
            "distinct_unmatched_names": len(handles_by_name),
            "resolved_via_uc_directories_edges": resolved_uc_edges,
            "edge_frequency": dict(sorted(collections.Counter(by_edges.values()).items())),
        },
        # The PO's completeness bar: every one of these is individually
        # reviewed. The tail below it is reported per class, in aggregate.
        "top": {name: dossiers[name] for name in ranked[:top]},
        "top_class_counts": dict(
            collections.Counter(dossiers[n]["suggested_class"] for n in ranked[:top])
        ),
        "tail_class_counts": dict(
            collections.Counter(dossiers[n]["suggested_class"] for n in tail)
        ),
        "tail_edge_counts": {
            cls: sum(dossiers[n]["edges"] for n in tail if dossiers[n]["suggested_class"] == cls)
            for cls in (NEVER_UC, FORMER_UC, RESOLVABLE_MISSED)
        },
        "top_edge_counts": {
            cls: sum(
                dossiers[n]["edges"]
                for n in ranked[:top]
                if dossiers[n]["suggested_class"] == cls
            )
            for cls in (NEVER_UC, FORMER_UC, RESOLVABLE_MISSED)
        },
        "tail_size": len(tail),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--oai-set-names", type=Path, default=None)
    parser.add_argument("--top", type=int, default=100)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="where the full dossier JSON lands; .tmp/ by default, never data/",
    )
    args = parser.parse_args(argv)

    report = classify(args.db, args.oai_set_names, args.top)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    # stdout carries the summary; the per-name dossiers are large and go to the
    # file, which is what a human reads alongside the Kanban report.
    summary = {k: v for k, v in report.items() if k != "top"}
    summary["top_names"] = list(report["top"])
    summary["written_to"] = str(args.out)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
