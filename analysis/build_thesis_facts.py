"""Build the thesis facts into the committed seed. Offline, by hand.

``python -m analysis.build_thesis_facts``

Reads ``estudo_geral/*.md`` (S1's committed front matter), reconciles it
against ``estudo_geral/manifest.json``, resolves every author and supervisor
name against the ``people`` table with ``analysis.name_match``, and writes
``theses`` / ``thesis_people`` / ``thesis_keywords`` / ``thesis_sets`` into
``data/cisuc.sqlite3``.

Why the seed and not Postgres. Every join partner — people, project_people,
project_groups, project_partners — is already in this file, so structured
thesis facts anywhere else make every advisor or collaboration query a
cross-store join. The seed also ships for free (``uc_phd_app/seed.py``);
Postgres has no seed mechanism, and would need this rebuilt on every install.
Postgres keeps what genuinely needs it: the embeddings. If the corpus passes
~10k documents, or filtered search starts losing recall because over-fetching
``k`` no longer covers the SQLite filter, revisit that split.

Why offline. Same reason ``scraper/run.py`` is offline: this is a one-shot
whose output is reviewable in a diff. The app opens the database ``mode=ro``
and must never be the thing that writes it.

**This script does not freeze research groups.** It freezes *identity* —
name -> person. A person's group stays derived live from their project
history on every request (``uc_phd_app/theses.py``), because a group is a
live fact about a career, not a property of a thesis.
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

import yaml

# The one cross-package import here, and deliberately not a copy: the set ->
# label map is the harvester's definition of corpus scope, and a second copy
# of it in this file would let the report label a community the harvest no
# longer reads. The module is pure stdlib XML parsing — importing it costs
# nothing and opens no socket.
from estudo_geral_extractor.oai import HARVEST_SETS

from . import external_people, multi_thesis_authors, person_aliases, person_full_names
from .name_match import (
    AMBIGUOUS,
    CONFIDENCE,
    CONFIDENT,
    EXACT,
    UNMATCHED,
    Person,
    identity_of,
    match_name,
    split_thesis_name,
    tokenize,
)

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "scraper" / "schema.sql"
DEFAULT_DB = ROOT / "data" / "cisuc.sqlite3"
DEFAULT_ESTUDO_GERAL = ROOT / "estudo_geral"

ROLE_FIELDS = (("author", "authors"), ("supervisor", "supervisors"))
TIERS = (EXACT, CONFIDENT, AMBIGUOUS, UNMATCHED)
THESIS_TABLES = ("thesis_sets", "thesis_keywords", "thesis_people", "theses")

#: Column positions in a ``thesis_people`` row tuple, so the passes below read
#: as names rather than as ``row[3]``.
HANDLE, NAME_RAW, ROLE, SLUG, STATUS, MATCH_CONFIDENCE, NOTE, ORDINAL = range(8)


class ReconciliationError(RuntimeError):
    """The .md files and the manifest disagree about which theses exist."""


def load_front_matters(estudo_geral_dir: Path) -> list[dict]:
    """Every thesis's YAML front matter, body text skipped."""
    out = []
    for md_path in sorted(estudo_geral_dir.glob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        parts = text.split("---\n", 2)
        if len(parts) < 3:
            raise ValueError(f"{md_path}: no YAML front matter delimiters found")
        front_matter = yaml.safe_load(parts[1])
        front_matter["slug"] = md_path.stem
        out.append(front_matter)
    return out


def reconcile(front_matters: list[dict], manifest_path: Path) -> None:
    """The glob is not the inventory — ``manifest.json`` is.

    A download that half-failed leaves a manifest entry with no ``.md``, and
    the glob alone would report that as a smaller corpus with no error at all.
    Both directions are checked because both are real: a stray ``.md`` with no
    manifest row is just as wrong.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared = {row["handle"] for row in manifest}
    extracted = {fm["handle"] for fm in front_matters}
    if declared != extracted:
        raise ReconciliationError(
            f"manifest lists {len(declared)} theses, estudo_geral/*.md holds "
            f"{len(extracted)}; missing .md: {sorted(declared - extracted)}; "
            f"unlisted .md: {sorted(extracted - declared)}"
        )


#: Every ``people`` row with its two reviewed facts attached, when it has
#: them: the canonical identity of an alias group, and the person's full legal
#: name. LEFT JOINs rather than queries folded together in Python — both are
#: properties of the row, and a row carrying neither must come back with NULLs
#: rather than be absent. Both join on a PRIMARY KEY, so neither fans out.
_PEOPLE_SQL = """
SELECT p.slug, p.name, a.to_slug, f.full_name
FROM people p
LEFT JOIN person_aliases a ON a.from_slug = p.slug
LEFT JOIN person_full_names f ON f.slug = p.slug
"""


def load_people(conn: sqlite3.Connection) -> list[Person]:
    return [Person(row[0], row[1], row[2], row[3]) for row in conn.execute(_PEOPLE_SQL)]


def thesis_row(front_matter: dict) -> tuple:
    date = front_matter.get("date") or ""
    source_url = front_matter.get("source_url")
    if not source_url:
        # NOT NULL in the schema; failing here names the thesis, which a
        # bare IntegrityError from sqlite3 would not.
        raise ValueError(f"{front_matter['handle']}: no source_url — provenance is required")
    return (
        front_matter["handle"],
        front_matter["slug"],
        front_matter["title"],
        date or None,
        date[:4] or None,
        source_url,
        front_matter.get("rights"),
        1 if front_matter.get("full_text") else 0,
        front_matter.get("abstract_pt"),
        front_matter.get("abstract_en"),
    )


def people_rows(front_matter: dict, people: list[Person], cache: dict) -> list[tuple]:
    """``thesis_people`` rows for one thesis — one per resolved candidate, and
    exactly one carrying a NULL slug when nothing resolved.

    **The canonical slug is written, not the matched one**, and it happens
    *here* rather than anywhere later in the pipeline. Two reasons, both load-
    bearing:

    * ``resolve_author_conflicts`` below groups author claims BY SLUG. Two
      thesis authors landing on two rows of one alias group have to collide
      and demote; written as the raw slugs they would slip past as two
      separate claimants, which is exactly the false merge that pass exists
      to catch — only harder to see, because the two slugs are one person.
    * ``trg_one_thesis_per_resolved_author`` (scraper/schema.sql) then sees
      canonical slugs too, so the backstop guards the same thing the pass
      does rather than a weaker version of it.

    Deduped, because collapsing an alias group means several candidates now
    name one slug — one person, one row.
    """
    rows = []
    for role, field in ROLE_FIELDS:
        for ordinal, name_raw in enumerate(front_matter.get(field) or []):
            if name_raw not in cache:
                cache[name_raw] = match_name(name_raw, people)
            result = cache[name_raw]
            slugs = (
                list(dict.fromkeys(identity_of(p) for p in result.people))
                if result.status in (EXACT, CONFIDENT)
                else [None]
            )
            for slug in slugs:
                rows.append(
                    (
                        front_matter["handle"],
                        name_raw,
                        role,
                        slug,
                        result.status,
                        result.confidence,
                        result.note,
                        ordinal,
                    )
                )
    return rows


def _token_set(text: str) -> frozenset:
    return frozenset(tokenize(text))


def resolved_author_claims(rows: list[tuple]) -> set[tuple[str, str]]:
    """``{(person_slug, handle)}`` for every author the matcher resolved.

    Read off the rows BEFORE ``resolve_author_conflicts`` runs, because that
    is the fact ``analysis/multi_thesis_authors.validate`` has to check an
    exemption against: an entry is only legitimate while the matcher still
    independently resolves both of its claims.
    """
    return {
        (row[SLUG], row[HANDLE])
        for row in rows
        if row[ROLE] == "author" and row[SLUG] is not None
    }


def resolve_author_conflicts(
    rows: list[tuple],
    people: list[Person],
    exempt_claims: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[list[tuple], list[dict]]:
    """One ``people`` row authors at most one thesis — enforced over the corpus.

    ``match_name`` resolves one name at a time and cannot see that it just
    handed the same slug to a second, differently-spelled author. Subset
    coverage makes that easy: "Martins, Pedro" and "Martins, Pedro Miguel de
    Oliveira" are two real people two years apart, and both fit the one CISUC
    row "Pedro Martins". Tightening the matcher to token-set equality would
    have killed the collision and 121 correct links with it, so the rule lives
    here instead, where the whole corpus is visible at once.

    Who keeps the slug: the claimant whose name is a token-set *equality* with
    the ``people`` row, when exactly one is. Every other claimant is demoted
    to an ``ambiguous``, NULL-slug row carrying the conflict in its note —
    the same shape ``people_rows`` writes for a name nothing resolved, because
    that is now what it is. Zero or several set-equal claimants means nothing
    separates them, so all of them are demoted.

    ``exempt_claims`` is ``{(person_slug, handle)}`` from the reviewed
    ``data/multi_thesis_authors.json`` (``analysis/multi_thesis_authors.py``):
    a human has read both records and confirmed one graduate with two deposits
    — an MSc dissertation and a doctoral thesis, which is the one shape where
    the rule above is wrong about a real person. On a slug with exemptions,
    every exempted claim keeps its slug and **every claim the entry does not
    list is demoted**, because the handle list is exhaustive: an unlisted
    claim is, by that reviewed fact, somebody else. A slug whose claims are
    all exempted is not a conflict at all and is not reported as one. With no
    exemptions, nothing below changes.

    **Authors only.** One supervisor across many theses is the normal case and
    the whole point of the advisor view; the same rule there would delete it.
    """
    names = {p.slug: p.name for p in people}
    claimants: dict[str, dict[tuple[str, str], bool]] = {}
    for row in rows:
        if row[ROLE] != "author" or row[SLUG] is None:
            continue
        claimants.setdefault(row[SLUG], {})[(row[HANDLE], row[NAME_RAW])] = _token_set(
            names.get(row[SLUG], "")
        ) == _token_set(row[NAME_RAW])

    conflicts: list[dict] = []
    demotions: dict[tuple[str, str], str] = {}
    for slug in sorted(s for s, by_claimant in claimants.items() if len(by_claimant) > 1):
        by_claimant = claimants[slug]
        reviewed = sorted(c for c in by_claimant if (slug, c[0]) in exempt_claims)
        if len(reviewed) == len(by_claimant):
            # Every claim on this slug is a reviewed deposit of one graduate.
            # Not a conflict, so not reported as one — and nothing to demote.
            continue
        equal = sorted(c for c, is_equal in by_claimant.items() if is_equal)
        keeper = None if reviewed else (equal[0] if len(equal) == 1 else None)
        for claimant in sorted(by_claimant):
            if claimant == keeper or claimant in reviewed:
                continue
            if reviewed:
                reason = (
                    f"the reviewed entry for {slug} in data/multi_thesis_authors.json "
                    f"lists {', '.join(handle for handle, _ in reviewed)}, and this "
                    "claim is not among them, so that review says it is somebody else"
                )
            elif keeper is not None:
                reason = (
                    f"slug {slug} is also claimed by thesis {keeper[0]}, whose author "
                    f'"{keeper[1]}" equals the CISUC row "{names[slug]}" exactly; this '
                    "subset claim cannot be confirmed against it"
                )
            elif equal:
                # The João Campos shape: several claims ARE set-equal to the
                # row, so the "none of them equals it" branch below would be
                # a lie — and the lie is what sent one investigation of this
                # exact case looking for a matching bug that was not there.
                reason = (
                    f"slug {slug} is claimed by {len(by_claimant)} thesis authors, "
                    f'{len(equal)} of which equal the CISUC row "{names[slug]}" '
                    "exactly, so nothing separates them; if this really is one "
                    "person with several theses in this corpus, record it in "
                    "data/multi_thesis_authors.json"
                )
            else:
                reason = (
                    f"slug {slug} is claimed by {len(by_claimant)} thesis authors and "
                    f'none of them equals the CISUC row "{names[slug]}" exactly; no '
                    "claim can be preferred over another"
                )
            demotions[claimant] = (
                f"Resolved to {slug} on the name alone, then withdrawn: one person "
                f"authors at most one thesis in this corpus, and {reason}."
            )
        conflicts.append(
            {
                "person_slug": slug,
                "person_name": names.get(slug),
                "kept": {"handle": keeper[0], "name_raw": keeper[1]} if keeper else None,
                "demoted": [
                    {"handle": handle, "name_raw": name_raw}
                    for handle, name_raw in sorted(by_claimant)
                    if (handle, name_raw) != keeper and (handle, name_raw) not in reviewed
                ],
                "decision": (
                    f"kept the {len(reviewed)} claims reviewed in "
                    "data/multi_thesis_authors.json, demoted the rest"
                    if reviewed
                    else "kept the one set-equality claim, demoted the rest"
                    if keeper
                    else "no single set-equality claim — demoted every claimant"
                ),
            }
        )

    if not demotions:
        return rows, conflicts

    # The demoted claimant may hold several rows (a duplicated `people` row
    # resolves to two slugs); all of them collapse into the one NULL row.
    first_ordinal: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row[HANDLE], row[NAME_RAW])
        if row[ROLE] == "author" and key in demotions:
            first_ordinal.setdefault(key, row[ORDINAL])

    out: list[tuple] = []
    emitted: set = set()
    for row in rows:
        key = (row[HANDLE], row[NAME_RAW])
        if row[ROLE] != "author" or key not in demotions:
            out.append(row)
            continue
        if key in emitted:
            continue
        emitted.add(key)
        out.append(
            (
                key[0],
                key[1],
                "author",
                None,
                AMBIGUOUS,
                CONFIDENCE[AMBIGUOUS],
                demotions[key],
                first_ordinal[key],
            )
        )
    return out, conflicts


def minimal_evidence_matches(rows: list[tuple], people: list[Person]) -> list[dict]:
    """Resolved authors whose ``people`` row carries nothing but the surname
    and the first given name — the shape the pedro-martins false merge had.

    Two tokens is the weakest evidence this matcher ever acts on, and nothing
    in a name can tell a correct one from a wrong one: the conflict pass above
    only catches a collision when *both* people are in the corpus. This list
    exists so the rest stay visible for a human spot-check rather than being
    silently counted as resolved.
    """
    names = {p.slug: p.name for p in people}
    out: dict[tuple[str, str], dict] = {}
    for row in rows:
        if row[ROLE] != "author" or row[SLUG] is None:
            continue
        key = (row[NAME_RAW], row[SLUG])
        if key in out:
            continue
        surname_tokens, given_tokens = split_thesis_name(row[NAME_RAW])
        floor = set(surname_tokens) | ({given_tokens[0]} if given_tokens else set())
        if _token_set(names.get(row[SLUG], "")) <= floor:
            out[key] = {
                "handle": row[HANDLE],
                "name_raw": row[NAME_RAW],
                "person_slug": row[SLUG],
                "person_name": names.get(row[SLUG]),
            }
    return [out[key] for key in sorted(out)]


def set_rows(front_matter: dict) -> list[tuple]:
    """``thesis_sets`` rows — the OAI communities and collections this thesis
    is listed under, as the harvest recorded them.

    Strict for the same reason ``thesis_row`` is strict about ``source_url``:
    every OAI record header carries its set membership, so a front matter
    without ``oai_sets`` is a file that predates the harvest, not a thesis
    that genuinely belongs to no set. Writing zero rows for it would hide
    that from every grouping query instead of stopping the rebuild — and
    naming the handle is what a quietly short table would not.

    Deduped: the primary key is (handle, set_spec), and a header repeating a
    spec must not turn a provenance detail into an IntegrityError.
    """
    oai_sets = front_matter.get("oai_sets")
    if not oai_sets:
        raise ValueError(
            f"{front_matter['handle']}: no oai_sets — OAI origin is required; "
            "re-run `python -m estudo_geral_extractor.run` to record it"
        )
    return [(front_matter["handle"], spec) for spec in dict.fromkeys(oai_sets)]


def keyword_rows(front_matter: dict) -> list[tuple]:
    return [
        (front_matter["handle"], keyword, ordinal)
        for ordinal, keyword in enumerate(front_matter.get("keywords") or [])
    ]


def build(
    db_path: Path,
    estudo_geral_dir: Path,
    aliases_path: Path | None = None,
    full_names_path: Path | None = None,
    external_people_path: Path | None = None,
    multi_thesis_authors_path: Path | None = None,
) -> dict:
    """Rebuild the three tables from scratch. Returns what it wrote.

    ``person_aliases`` and ``person_full_names`` are rebuilt in the same
    transaction, from their two curated files — the reviewed identity facts
    the matcher then reads. ``external_people`` is rebuilt in that same
    transaction too but on the far side of the matching, because what it is
    validated against is this build's *output*: an entry has to name a row
    that exists and is still ``unmatched``.

    ``multi_thesis_authors`` is the one curated file whose two halves straddle
    the matching, and the order is load-bearing in both directions:

    * it is **read** before ``resolve_author_conflicts``, which consumes the
      exemptions;
    * it is **checked** after it, against the claims the matcher resolved on
      its own — an exemption with no live claim behind it is a hole in the
      one-person-one-thesis check, not a harmless leftover;
    * and its **table is written before the ``thesis_people`` rows**, because
      ``scraper/schema.sql``'s ``trg_one_thesis_per_resolved_author`` reads it
      on every insert. That is the one ordering fact a trigger has that the
      UNIQUE index it replaced did not.
    """
    front_matters = load_front_matters(estudo_geral_dir)
    reconcile(front_matters, estudo_geral_dir / "manifest.json")

    conn = sqlite3.connect(db_path)
    try:
        # Full replace, not upsert: the input is a committed directory, so the
        # tables are a pure function of it and a stale row from a thesis that
        # was withdrawn upstream would otherwise survive forever.
        #
        # It happens BEFORE the schema is applied, not after the inserts where
        # it used to: schema.sql now carries a UNIQUE index over resolved
        # author rows, and `executescript` would try to build that index over
        # the rows this run is about to replace — so rebuilding a seed that
        # still holds a false merge would fail on the very constraint the
        # rebuild exists to satisfy.
        existing = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in THESIS_TABLES:
            if table in existing:
                conn.execute(f"DELETE FROM {table}")

        conn.executescript(SCHEMA.read_text(encoding="utf-8"))

        # Identity before matching, in that order and not the other: the
        # curated "de x para" decides which `people` rows are one human, and
        # `load_people` reads the result of it onto every Person. Validated
        # against the live rows and raised on, never skipped — see
        # analysis/person_aliases.py on why a silent skip un-merges a person.
        aliases = person_aliases.load_and_write(conn, aliases_path)
        full_names = person_full_names.load_and_write(conn, full_names_path)
        people = load_people(conn)

        # Shape-checked here, identity-checked below: the conflict pass needs
        # the exemptions, and the only facts that can judge them are that
        # pass's own input.
        multi_entries = multi_thesis_authors.load_entries(multi_thesis_authors_path)

        cache: dict = {}
        theses = [thesis_row(fm) for fm in front_matters]
        thesis_people: list[tuple] = []
        thesis_keywords: list[tuple] = []
        thesis_sets: list[tuple] = []
        for fm in front_matters:
            thesis_people += people_rows(fm, people, cache)
            thesis_keywords += keyword_rows(fm)
            thesis_sets += set_rows(fm)

        multi_thesis_authors.validate(
            multi_entries,
            {identity_of(person) for person in people},
            {fm["handle"] for fm in front_matters},
            resolved_author_claims(thesis_people),
        )
        thesis_people, author_conflicts = resolve_author_conflicts(
            thesis_people, people, multi_thesis_authors.exempt_claims(multi_entries)
        )
        minimal_evidence = minimal_evidence_matches(thesis_people, people)

        conn.executemany("INSERT INTO theses VALUES (?,?,?,?,?,?,?,?,?,?)", theses)
        # Before the thesis_people rows, not after: the trigger that replaced
        # idx_one_thesis_per_resolved_author reads this table on every insert.
        multi = multi_thesis_authors.write_table(conn, multi_entries)
        conn.executemany("INSERT INTO thesis_people VALUES (?,?,?,?,?,?,?,?)", thesis_people)
        conn.executemany("INSERT INTO thesis_keywords VALUES (?,?,?)", thesis_keywords)
        conn.executemany("INSERT INTO thesis_sets VALUES (?,?)", thesis_sets)

        # After the rows, not before: this is the one curated file whose
        # validator reads `thesis_people` rather than `people`, because an
        # external identity is attached to a MENTION and is only legitimate
        # while that mention is still unmatched. Same transaction, so a
        # refusal here rolls the whole rebuild back instead of leaving the
        # seed holding thesis rows with a half-applied display layer.
        externals = external_people.load_and_write(conn, external_people_path)
        conn.commit()
    finally:
        conn.close()

    tiers = collections.Counter(m.status for m in cache.values())
    return {
        "theses": len(theses),
        "person_aliases": aliases,
        "person_full_names": full_names,
        "multi_thesis_authors": {"people": len(multi_entries), "exempted_claims": multi},
        "external_people": externals,
        "thesis_people_rows": len(thesis_people),
        "thesis_keywords": len(thesis_keywords),
        "thesis_sets": len(thesis_sets),
        # Per-community counts over the sets the harvest actually targets, so
        # "how many theses came from ISR" is a measurement in the build report
        # rather than a query someone has to remember to run.
        "theses_per_harvest_set": {
            label: sum(1 for _, spec in thesis_sets if spec == set_spec)
            for set_spec, label in HARVEST_SETS.items()
        },
        "supervision_edges": sum(
            1 for fm in front_matters for _ in (fm.get("supervisors") or [])
        ),
        "distinct_names": len(cache),
        # What the MATCHER concluded, per distinct name. The conflict pass
        # below overrides some of these per (thesis, name) without moving a
        # count here — deliberately: this is the matcher's own report card,
        # and sql/thesis_match_tiers.sql reads the written rows for the other
        # view. `author_conflicts` is where the two differ.
        "tiers": {tier: tiers.get(tier, 0) for tier in TIERS},
        "unresolved": sorted(
            name for name, m in cache.items() if m.status in (AMBIGUOUS, UNMATCHED)
        ),
        "author_conflicts": author_conflicts,
        "minimal_evidence_matches": minimal_evidence,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--estudo-geral", type=Path, default=DEFAULT_ESTUDO_GERAL)
    parser.add_argument("--person-aliases", type=Path, default=None)
    parser.add_argument("--person-full-names", type=Path, default=None)
    parser.add_argument("--external-people", type=Path, default=None)
    parser.add_argument("--multi-thesis-authors", type=Path, default=None)
    args = parser.parse_args(argv)

    report = build(
        args.db,
        args.estudo_geral,
        args.person_aliases,
        args.person_full_names,
        args.external_people,
        args.multi_thesis_authors,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
