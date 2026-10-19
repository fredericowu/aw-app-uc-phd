"""Harvest every registered UC unit directory. Offline, one-shot, by hand.

    python -m scraper.uc_directories.run [--db data/cisuc.sqlite3] \
        --shield-cookie <bunny_shield> --user-agent "<the browser's UA>"
    python -m scraper.uc_directories.run --snapshot-dir .tmp/uc-snapshots

Writes `people` (additively, `db.upsert_person` semantics) and
`directory_listings` (the provenance that makes a row's scope derivable —
`scraper/schema.sql`), prints a JSON report per unit, and exits non-zero
naming every unit that failed. Same contract as `scraper/run.py`'s people
step: commit what succeeded, fail loudly on the rest, never half-harvest in
silence.

Three identity rules, and they are the whole reason this file is longer than
the parsers put together:

1. **Disjoint slug namespace.** A UC-directory person's slug is always
   `uc--<source>--<name-slug>`. CISUC's slugs are URL tails off its own site
   and can be anything, so the prefix makes collision structurally
   impossible — and the harvester REFUSES, loudly, any slug that already
   exists in `people` outside its own namespace, so the guarantee is enforced
   rather than intended.
2. **Cross-unit dedup on URL evidence only, never on a name.** Boaventura de
   Sousa Santos is on FEUC's Docentes page and on CES's Pessoas page, and
   FEUC's card links his CES page — so the two listings agree on one
   per-person URL and collapse into one slug carrying two listing rows (which
   is exactly what the `(person_slug, source)` grain exists for). Two units
   publishing the same NAME with no shared URL stay two slugs and are
   reported as `possible_duplicates`, settled the house way: a
   `data/person_aliases.json` verdict with evidence. "João Silva" at FDUC and
   "João Silva" at FFUC is two people until a human says otherwise — this
   repo's whole post-relaxation architecture is built on refusing to derive an
   identity decision from a name (`docs/thesis-attribution.md`).
   The URL is trusted, but not blindly: `_name_compatible` refuses a merge
   whose two published forms share no name at all, because one real FEUC card
   links a CES page belonging to somebody else. A refused pair is reported as
   `url_identity_conflicts` and stays two slugs.
3. **A UC name that folds onto a CISUC `people.name` is reported, never
   merged.** `cisuc_name_collisions` is the list; it is a flag for a human,
   like `scraper/people.py`'s `possible_duplicates`, and the matcher is
   unaffected either way because pass 1 answers first (see
   `analysis/build_thesis_facts.py`).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path

from analysis.name_match import fold, tokenize

from .. import db
from . import fetch, parsers, units as units_mod

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = REPO_ROOT / "data" / "cisuc.sqlite3"

#: The one namespace every row this module writes lives in. Nothing else in
#: the repo may mint a slug starting with it, and nothing it mints may collide
#: with a slug outside it.
SLUG_PREFIX = "uc--"

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


class HarvestError(RuntimeError):
    """One unit failed. Collected, reported, and turned into a non-zero exit —
    never allowed to abort the units that worked."""


def name_slug(name: str) -> str:
    """The `fold`-style normalisation the rest of the repo uses, hyphenated.

    Deliberately `analysis.name_match.fold` and not a second ad-hoc
    normaliser: a UC page publishes "Boaventura de Sousa Santos" with the
    accents CISUC drops, and a slug derived differently from the one the
    matcher folds against would make the collision refusal and the duplicate
    report misfire on exactly the names they exist for.
    """
    ascii_only = unicodedata.normalize("NFKD", fold(name))
    ascii_only = "".join(ch for ch in ascii_only if not unicodedata.combining(ch))
    return _SLUG_STRIP.sub("-", ascii_only).strip("-")


def mint_slug(source: str, name: str, taken: set[str]) -> str:
    """`uc--<source>--<name-slug>`, suffixed on collision WITHIN one unit.

    A unit publishing two people under one name is the `joao-bicker` shape
    one level out, and the suffix keeps both rows rather than letting the
    second silently overwrite the first.
    """
    base = f"{SLUG_PREFIX}{source}--{name_slug(name)}"
    if base not in taken:
        return base
    index = 2
    while f"{base}-{index}" in taken:
        index += 1
    return f"{base}-{index}"


def _name_compatible(a: str, b: str) -> bool:
    """Could these two published forms be one human?

    The tripwire on URL-based dedup, and it is needed because the SITE gets
    this wrong: FEUC's card for Catarina Proença links her research centre
    ("CeBER") to a CES person page belonging to Daniel Francisco, so two
    different professors publish one per-person URL. Merging on that URL
    alone silently produces one row claiming to be both of them.

    The test is a subset, not equality, because the legitimate cross-source
    case is exactly a different form of one name: CES publishes "Abreu,
    Paula" and FEUC publishes "Maria Paula Abreu" for one human, and the
    whole point of the URL evidence is to catch that. "Proença" against
    "Francisco" shares nothing, so it is refused and reported.

    This is a tightening: it can only ever withhold a merge, never create
    one. A refused pair becomes two slugs, which is the safe answer — a
    `data/person_aliases.json` verdict can still merge them later on
    evidence, and nothing can un-merge a wrong collapse after the fact.
    """
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return False

    def covered(small, large):
        # An initial counts, the same convention `_is_initial_of` excuses on
        # CISUC's side: CES publishes "Neide P. Areia" and FEUC publishes
        # "Neide Luísa Portela Areia", one human, and a plain token-subset
        # test refuses that merge over the "P.".
        return all(
            token in large or (len(token) == 1 and any(w.startswith(token) for w in large))
            for token in small
        )

    return covered(ta, tb) or covered(tb, ta)


def harvest_unit(unit: units_mod.Unit, session, snapshot_dir: Path | None, sleep: float):
    """Every person one unit publishes, deduped within the unit by person URL.

    Raises `HarvestError` when the parse comes back under `expected_min` — a
    page that changed shape must fail ITS unit loudly, because a silently
    short pool narrows the candidate pool the identity matcher runs against,
    which is worse than not running the unit at all.
    """
    listings: list[parsers.Listing] = []
    #: WITHIN one unit, the same person URL — or failing that the same folded
    #: name — is the same row served twice: A–Z anchors repeat a card, and
    #: CES's infinite scroll re-serves its letter headers on every page. This
    #: is not the cross-unit dedup (`resolve_identities`), which is URL-only;
    #: one page-set is one source's single statement about itself, so a
    #: repeated name inside it is a repeat and not a second person.
    seen: set[str] = set()

    def on_page(listing_url: str, html: str) -> int:
        fresh = 0
        for listing in parsers.parse(unit.parser, html, listing_url):
            url_key = parsers.canonical_person_url(listing.person_url)
            key = url_key or "name:" + fold(listing.name_as_published)
            if key in seen:
                continue
            seen.add(key)
            listings.append(listing)
            fresh += 1
        return fresh

    pages = fetch.fetch_unit_pages(unit, session, on_page, snapshot_dir, sleep)
    if len(listings) < unit.expected_min:
        raise HarvestError(
            f"{unit.source}: parsed {len(listings)} people from {pages} page(s), "
            f"below the expected_min floor of {unit.expected_min} "
            f"(measured at registration: {unit.measured}) — the page shape has "
            "probably changed; fix the parser rather than lowering the floor"
        )
    return listings, pages


def resolve_identities(
    harvested: dict[str, list[parsers.Listing]],
    cisuc_slugs: set[str],
    known: dict | None = None,
):
    """Turn per-unit listings into `(people_rows, listing_rows, report)`.

    Runs over the union of every unit at once, because that is the only place
    the cross-unit facts are visible: one person URL published by two units is
    one human, and a slug already held by a CISUC row is a collision nobody
    may write through.

    ``known`` is what the DB already holds from earlier runs —
    ``{"by_person_url": {canonical_url: slug}, "names": {slug: name}}`` — and
    it is what makes an incremental harvest behave like a full one. Without
    it, `python -m ... --only ces` after a run that did FEUC would mint a
    second slug for Boaventura instead of adding a CES listing row to the one
    he already has, and the two rows would then compete as two candidates for
    his name.
    """
    known = known or {}
    by_person_url: dict[str, str] = dict(known.get("by_person_url") or {})
    # `taken` and `names` span earlier runs; `people_rows` is strictly what
    # THIS run produced, so the report says what this run did rather than
    # re-listing the whole pool.
    names: dict[str, str] = dict(known.get("names") or {})
    taken: set[str] = set(names)
    people_rows: dict[str, str] = {}
    listing_rows: list[tuple] = []
    merged: list[dict] = []
    refused: list[dict] = []
    url_conflicts: list[dict] = []
    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    for source, listings in harvested.items():
        unit = units_mod.by_source(source)
        for listing in listings:
            display = parsers.display_name(listing.name_as_published)
            url_key = parsers.canonical_person_url(listing.person_url)
            slug = by_person_url.get(url_key) if url_key else None
            if slug is not None and not _name_compatible(names.get(slug, ""), display):
                # One URL, two incompatible names — the site's own error, not
                # ours. Two slugs, and a line in the report for a human.
                url_conflicts.append(
                    {
                        "person_url": listing.person_url,
                        "already_held_by": {"slug": slug, "name": names.get(slug)},
                        "refused": {"source": source, "name": display},
                    }
                )
                slug = None
            if slug is not None:
                merged.append(
                    {
                        "person_slug": slug,
                        "source": source,
                        "name_as_published": listing.name_as_published,
                        "person_url": listing.person_url,
                    }
                )
            else:
                slug = mint_slug(source, display, taken)
                taken.add(slug)
                if url_key:
                    by_person_url[url_key] = slug
            if slug in cisuc_slugs:
                # Unreachable by construction — a CISUC slug is a URL tail off
                # cisuc.uc.pt and cannot begin `uc--` — and checked anyway,
                # because "the prefix makes this impossible" is a claim and
                # this is the proof. A hit means the two directories are now
                # one key space, which is the one failure that would silently
                # overwrite a CISUC person with a UC one.
                refused.append({"slug": slug, "source": source, "name": display})
                continue
            # Last writer wins on the display name, same call scraper/people.py
            # makes; the verbatim published form is kept per listing row.
            people_rows[slug] = display
            names[slug] = display
            listing_rows.append(
                (
                    slug,
                    source,
                    unit.unit_name,
                    listing.listing_url,
                    listing.person_url,
                    listing.name_as_published,
                    listing.role_as_published,
                    fetched_at,
                )
            )

    return (
        people_rows,
        listing_rows,
        {
            "merged_by_person_url": merged,
            "slug_refusals": refused,
            "url_identity_conflicts": url_conflicts,
        },
    )


def possible_duplicates(people_rows: dict[str, str], listing_rows: list[tuple]) -> list[dict]:
    """Same folded name in two different units with no shared person URL.

    Suggest only, and it must stay that way. `scraper/people.py`'s own
    `possible_duplicates` docstring has the full argument: the name shape that
    proves two entries are one human is carried by pairs who are two
    different humans, so the output is a list for a reviewer and
    `data/person_aliases.json` is where the answer goes.
    """
    sources_by_slug = {row[0]: row[1] for row in listing_rows}
    by_name: dict[str, list[str]] = collections.defaultdict(list)
    for slug, name in people_rows.items():
        by_name[fold(name)].append(slug)
    out = []
    for name, slugs in sorted(by_name.items()):
        if len(slugs) < 2:
            continue
        out.append(
            {
                "folded_name": name,
                "slugs": sorted(slugs),
                "sources": sorted({sources_by_slug.get(s, "?") for s in slugs}),
                "display_name": people_rows[sorted(slugs)[0]],
            }
        )
    return out


def cisuc_name_collisions(people_rows: dict[str, str], cisuc_people: dict) -> list[dict]:
    """A UC-directory name that folds onto a CISUC `people.name`.

    Reported, never merged, and the matcher is unaffected either way: pass 1
    runs against the CISUC pool alone and its verdict stands, so a name that
    fits a CISUC row never reaches the UC pool at all
    (`analysis/build_thesis_facts.py`). This list is the human's way in — the
    `cross_directory_fits` entry in the build report is the matcher-shaped
    version of the same question.
    """
    cisuc_by_fold: dict[str, list[str]] = collections.defaultdict(list)
    for slug, name in cisuc_people.items():
        cisuc_by_fold[fold(name)].append(slug)
    out = []
    for slug, name in sorted(people_rows.items()):
        hits = cisuc_by_fold.get(fold(name))
        if hits:
            out.append({"uc_slug": slug, "name": name, "cisuc_slugs": sorted(hits)})
    return out


def write(conn, people_rows: dict[str, str], listing_rows: list[tuple]) -> dict:
    """Upsert both tables in one transaction. Additive on `people`; a listing
    row is replaced in place, because a re-harvest is this unit's current
    statement about where a person is listed and a stale `fetched_at` would
    make the provenance lie."""
    existing = {row[0] for row in conn.execute("SELECT slug FROM people")}
    new = sum(1 for slug in people_rows if slug not in existing)
    for slug, name in sorted(people_rows.items()):
        db.upsert_person(conn, slug, name)
    conn.executemany(
        "INSERT INTO directory_listings (person_slug, source, unit_name, listing_url, "
        "person_url, name_as_published, role_as_published, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(person_slug, source) DO UPDATE SET "
        "unit_name = excluded.unit_name, listing_url = excluded.listing_url, "
        "person_url = excluded.person_url, name_as_published = excluded.name_as_published, "
        "role_as_published = excluded.role_as_published, fetched_at = excluded.fetched_at",
        listing_rows,
    )
    conn.commit()
    return {"people_new": new, "people_upserted": len(people_rows), "listings": len(listing_rows)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--snapshot-dir", type=Path, default=None)
    parser.add_argument("--shield-cookie", default=None)
    parser.add_argument("--user-agent", default=None)
    parser.add_argument(
        "--only",
        action="append",
        default=None,
        help="harvest only these sources (repeatable); default is every registered unit",
    )
    parser.add_argument("--sleep", type=float, default=fetch.SLEEP_BETWEEN_FETCHES)
    args = parser.parse_args(argv)

    wanted = [u for u in units_mod.UNITS if not args.only or u.source in args.only]
    if args.only:
        unknown = sorted(set(args.only) - set(units_mod.sources()))
        if unknown:
            parser.error(f"no unit registered under {unknown}; have {list(units_mod.sources())}")

    session = fetch.build_session(args.shield_cookie, args.user_agent)
    harvested: dict[str, list[parsers.Listing]] = {}
    per_unit: dict[str, dict] = {}
    failures: dict[str, str] = {}
    for unit in wanted:
        try:
            listings, pages = harvest_unit(unit, session, args.snapshot_dir, args.sleep)
        except (HarvestError, fetch.FetchError) as exc:
            failures[unit.source] = str(exc)
            continue
        harvested[unit.source] = listings
        per_unit[unit.source] = {
            "unit_name": unit.unit_name,
            "kind": unit.kind,
            "listing_url": unit.listing_url,
            "parser": unit.parser,
            "pages_read": pages,
            "people_parsed": len(listings),
            "with_person_url": sum(1 for row in listings if row.person_url),
            "expected_min": unit.expected_min,
            "from_snapshot": args.snapshot_dir is not None,
        }

    conn = db.connect(str(args.db))
    try:
        db.apply_schema(conn)
        cisuc_people = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT slug, name FROM people WHERE slug NOT IN "
                "(SELECT person_slug FROM directory_listings)"
            )
        }
        known = {
            "by_person_url": {
                parsers.canonical_person_url(url): slug
                for slug, url in conn.execute(
                    "SELECT person_slug, person_url FROM directory_listings "
                    "WHERE person_url IS NOT NULL"
                )
                if parsers.canonical_person_url(url)
            },
            "names": {
                row[0]: row[1]
                for row in conn.execute(
                    "SELECT p.slug, p.name FROM people p "
                    "JOIN directory_listings d ON d.person_slug = p.slug"
                )
            },
        }
        people_rows, listing_rows, identity = resolve_identities(
            harvested, set(cisuc_people), known
        )
        counts = write(conn, people_rows, listing_rows)
    finally:
        conn.close()

    report = {
        "db": str(args.db),
        "units_requested": [u.source for u in wanted],
        "units_harvested": sorted(harvested),
        "units_failed": failures,
        "per_unit": per_unit,
        **counts,
        "merged_by_person_url": identity["merged_by_person_url"],
        "slug_refusals": identity["slug_refusals"],
        "url_identity_conflicts": identity["url_identity_conflicts"],
        "possible_duplicates": possible_duplicates(people_rows, listing_rows),
        "cisuc_name_collisions": cisuc_name_collisions(people_rows, cisuc_people),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if failures:
        print(
            "FAILED units (committed what succeeded): " + ", ".join(sorted(failures)),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
