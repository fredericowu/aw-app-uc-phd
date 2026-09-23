"""Build the bibliography tables into the committed seed. Offline, by hand.

``python -m analysis.build_bibliography``

Reads every ``estudo_geral/*.md`` body, pulls its reference entries out with
``analysis.reference_parse``, groups them into distinct works across the whole
corpus, and writes ``bib_references`` / ``thesis_references`` into
``data/cisuc.sqlite3``.

Why the seed and not Postgres. Same answer as
``analysis/build_thesis_facts.py``, and it is worth repeating rather than
cross-referencing: every join partner — ``theses``, ``thesis_people``,
``people`` — is already in this file, so putting citations anywhere else makes
"which theses cite this work" a cross-store join. The seed ships for free
(``uc_phd_app/seed.py``); Postgres has no seed mechanism and would need this
rebuilt on every install. Postgres keeps what genuinely needs it: embeddings.

Why offline. Parsing the references out of this corpus reads 68 MB of markdown
and takes about a minute. Doing it per request would do that on every page
load. The output is a diff-reviewable table in a committed database, the same
contract ``scraper/run.py`` and ``build_thesis_facts.py`` already have.

Two tiers, and the honest version of what they buy
--------------------------------------------------
* **Tier 1, DOI.** Exact, high precision, and sparse — most entries carry no
  DOI at all, and the ones that do are concentrated in the newer theses.
  Truncated DOIs are rejected twice (``clean_doi``, then ``drop_truncated``
  across the whole corpus) because a line-wrapped DOI groups unrelated works
  with total confidence.
* **Tier 2, normalised author+title.** Medium recall: this script measures it
  against the DOI groups on every run and prints the figure, rather than
  asserting a number that was true once. It was **52.6%** (30 of 57
  shared-DOI groups) at ``MATCHER_VERSION = 1``.

Expect almost no overlap, and do not "fix" it
---------------------------------------------
~99% of the references in this corpus are cited by exactly one thesis. That is
a true property of 181 theses spanning ~20 years across six different DEI /
CISUC research groups, not a parser failure — they barely share a bibliography.
The report this script prints includes the full ``cited_by`` histogram so the
number is checked every run instead of assumed. It is also what decides the
UI: see ``uc_phd_app/bibliography.py``'s ``DEFAULT_MIN_CITED_BY``.
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

from . import reference_parse as rp

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "scraper" / "schema.sql"
DEFAULT_DB = ROOT / "data" / "cisuc.sqlite3"
DEFAULT_ESTUDO_GERAL = ROOT / "estudo_geral"


def parse_corpus(estudo_geral_dir: Path) -> dict[str, list[str]]:
    """``slug -> [raw entry, ...]`` for every thesis that yielded any.

    A thesis with no parseable references is simply absent from the result.
    That is the honest shape: 42 of the files are metadata-only stubs with no
    body at all, and a handful more have a body whose bibliography did not
    survive extraction. Both are "no data", not "zero references", and
    ``coverage()`` reports them separately.
    """
    out: dict[str, list[str]] = {}
    for md_path in sorted(estudo_geral_dir.glob("*.md")):
        text = md_path.read_text(encoding="utf-8", errors="replace")
        entries = rp.parse_document(text)
        if entries:
            out[md_path.stem] = entries
    return out


def _dois_in(per_thesis: dict[str, list[str]]) -> dict[tuple[str, str], str]:
    """``(slug, entry) -> doi`` for every entry carrying a usable DOI.

    Two passes, because ``drop_truncated`` needs to see the whole corpus
    before it can tell a real DOI from a line-wrapped one.
    """
    raw: dict[tuple[str, str], str] = {}
    for slug, entries in per_thesis.items():
        for entry in entries:
            match = rp.DOI.search(entry)
            if not match:
                continue
            doi = rp.clean_doi(match.group(0))
            if doi:
                raw[(slug, entry)] = doi
    kept = rp.drop_truncated(set(raw.values()))
    return {k: v for k, v in raw.items() if v in kept}


def group(per_thesis: dict[str, list[str]]) -> tuple[list[dict], list[tuple]]:
    """Fold every entry into distinct works. Returns ``(works, citations)``.

    DOI wins over the normalised key when an entry has both: it is the more
    precise of the two, and letting the weaker key claim the entry would merge
    works the DOI says are different.
    """
    doi_of = _dois_in(per_thesis)
    works: dict[str, dict] = {}
    citations: list[tuple] = []

    for slug in sorted(per_thesis):
        for ordinal, entry in enumerate(per_thesis[slug]):
            doi = doi_of.get((slug, entry))
            if doi:
                key, tier = f"doi:{doi}", "doi"
            else:
                derived = rp.normalised_key(entry)
                if derived:
                    key, tier = derived, "title"
                else:
                    # No derivable identity. A per-row key keeps it countable
                    # as one reference instead of collapsing every unparseable
                    # entry in the corpus into a single bogus "most cited" row.
                    key, tier = f"raw:{slug}:{ordinal}", "unmatched"

            work = works.get(key)
            if work is None:
                work = {
                    "normalised_key": key,
                    "display_string": rp.display_form(entry),
                    "doi": doi,
                    "year": rp.extract_year(entry),
                    "first_author": rp.extract_first_author(entry),
                    "match_tier": tier,
                    "handles": set(),
                }
                works[key] = work
            elif len(rp.display_form(entry)) > len(work["display_string"]):
                # Keep the longest wording seen — see the schema comment.
                work["display_string"] = rp.display_form(entry)
                work["year"] = work["year"] or rp.extract_year(entry)
                work["first_author"] = work["first_author"] or rp.extract_first_author(entry)
            work["handles"].add(slug)
            citations.append((slug, key, entry, ordinal))

    ordered = sorted(works.values(), key=lambda w: (-len(w["handles"]), w["normalised_key"]))
    return ordered, citations


def measure_tier2_recall(per_thesis: dict[str, list[str]]) -> dict:
    """Recompute tier 2's recall against tier 1, every run.

    For each DOI cited by two or more theses — the only ground truth this
    corpus offers about "the same work written two different ways" — check
    whether the normalised author+title key alone would have grouped them.
    Printing this rather than hard-coding it is the point: the number is a
    property of the current matcher, and a change that quietly costs recall
    should be visible in the build output, not discovered later.
    """
    doi_of = _dois_in(per_thesis)
    groups: dict[str, dict[str, str]] = collections.defaultdict(dict)
    for (slug, entry), doi in doi_of.items():
        groups[doi].setdefault(slug, entry)
    shared = {doi: members for doi, members in groups.items() if len(members) >= 2}
    agreed = disagreed = unkeyed = 0
    for members in shared.values():
        keys = {rp.normalised_key(entry) for entry in members.values()}
        if None in keys:
            unkeyed += 1
        elif len(keys) == 1:
            agreed += 1
        else:
            disagreed += 1
    total = len(shared)
    return {
        "shared_doi_groups": total,
        "title_key_agreed": agreed,
        "title_key_disagreed": disagreed,
        "title_key_absent": unkeyed,
        "recall": round(agreed / total, 3) if total else None,
    }


def coverage(estudo_geral_dir: Path, per_thesis: dict[str, list[str]]) -> dict:
    """How much of the corpus this actually reached, split by why it did not.

    ``full_text`` is read from the front matter, NOT used as a filter — the
    split is reported so a shortfall is attributable, and gating parsing on it
    would be the trap the design notes warn about.
    """
    import yaml

    total = with_body = 0
    for md_path in sorted(estudo_geral_dir.glob("*.md")):
        total += 1
        front = yaml.safe_load(md_path.read_text(encoding="utf-8", errors="replace").split("---\n", 2)[1])
        if front.get("full_text"):
            with_body += 1
    return {
        "files": total,
        "with_body_text": with_body,
        "metadata_only_stubs": total - with_body,
        "parsed": len(per_thesis),
        "body_but_unparsed": with_body - len(per_thesis),
        "coverage_of_body_files": round(len(per_thesis) / with_body, 3) if with_body else None,
    }


def build(db_path: Path, estudo_geral_dir: Path) -> dict:
    """Rebuild both tables from scratch. Returns what it wrote."""
    per_thesis = parse_corpus(estudo_geral_dir)
    works, citations = group(per_thesis)

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        known = {row[0] for row in conn.execute("SELECT slug FROM theses")}
        handle_of = {row[0]: row[1] for row in conn.execute("SELECT slug, handle FROM theses")}

        # A .md with no `theses` row would violate the FK and, more to the
        # point, means the two builders disagree about which theses exist.
        unknown = sorted(set(per_thesis) - known)
        if unknown:
            raise ValueError(
                f"{len(unknown)} thesis .md files have no row in `theses` — run "
                f"`python -m analysis.build_thesis_facts` first: {unknown[:5]}"
            )

        # Full replace, not upsert: the input is a committed directory, so
        # these tables are a pure function of it and a row from a withdrawn
        # thesis would otherwise survive forever. Same rule as
        # build_thesis_facts.py.
        conn.execute("DELETE FROM thesis_references")
        conn.execute("DELETE FROM bib_references")

        ids: dict[str, int] = {}
        rows = []
        for i, work in enumerate(works, start=1):
            ids[work["normalised_key"]] = i
            rows.append(
                (
                    i,
                    work["normalised_key"],
                    work["display_string"],
                    work["doi"],
                    work["year"],
                    work["first_author"],
                    work["match_tier"],
                    rp.MATCHER_VERSION,
                    len(work["handles"]),
                )
            )
        conn.executemany("INSERT INTO bib_references VALUES (?,?,?,?,?,?,?,?,?)", rows)
        conn.executemany(
            "INSERT INTO thesis_references VALUES (?,?,?,?)",
            [(handle_of[slug], ids[key], entry, ordinal) for slug, key, entry, ordinal in citations],
        )
        conn.commit()
    finally:
        conn.close()

    histogram = collections.Counter(len(w["handles"]) for w in works)
    tiers = collections.Counter(w["match_tier"] for w in works)
    return {
        "coverage": coverage(estudo_geral_dir, per_thesis),
        "references": len(works),
        "citations": len(citations),
        "match_tiers": dict(tiers),
        "cited_by_histogram": {str(k): v for k, v in sorted(histogram.items())},
        "cited_by_2_or_more": sum(v for k, v in histogram.items() if k >= 2),
        "tier2_recall": measure_tier2_recall(per_thesis),
        "matcher_version": rp.MATCHER_VERSION,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--estudo-geral", type=Path, default=DEFAULT_ESTUDO_GERAL)
    args = parser.parse_args(argv)

    report = build(args.db, args.estudo_geral)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
