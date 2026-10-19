"""The person-alias ("de x para") map — curated, validated, written to the seed.

CISUC's own People directory lists some humans **twice**: once under the slug
a project page linked to, once under the slug the directory publishes. Six
families are known today, and the cost is visible in the thesis facts — four
of the eight ``ambiguous`` author names are ambiguous for no better reason
than that two of the candidates are the same person.

No name rule can fix that, and this module does not try. ``people`` carries a
slug and a display name and nothing else, so "Nuno Silva" and "Nuno Pedro de
Jesus Silva" are *token-compatible* and that is all a matcher can ever know
about them — they are, in fact, two different humans (different mailboxes,
different research groups). The same shape with the same evidence available
is ``simao-paredes``/``s-paredes``, who publish the **same ORCID**. The two
cases are indistinguishable from the names alone, so the decision is a
human's, made against the live CISUC pages, and recorded in
``data/person_aliases.json`` with the evidence attached.

What this module does with that file:

* ``load_pairs()``   — read it, with the shape checked rather than assumed.
* ``validate()``     — refuse it loudly if a verdict cannot be acted on:
  an unknown slug, a self-alias, an alias of an alias (a chain), one slug
  claimed by two canonicals, a ``same`` with no canonical, a ``distinct``
  with one, a missing evidence string, or the same pair twice.
* ``alias_map()``    — ``{from_slug: to_slug}`` for every ``same`` verdict.
  This is the "de x para" itself.
* ``reviewed_pairs()`` — every pair under **either** verdict, which is what
  ``scraper/people.py``'s detection pass subtracts so a pair a human has
  already ruled on goes quiet instead of being re-reported forever.
* ``distinct_pairs()`` — the ``distinct`` half on its own, which is what
  ``name_match._same_person_twice`` subtracts so a pair a human has ruled
  **different humans** is never collapsed into one by a name rule.
* ``write_table()``  — replace ``person_aliases`` in the seed from it.

**The ``distinct`` half is a fact, not just a silencer.** Until it was read by
the matcher, a ``distinct`` verdict only quieted the detection pass, and
``name_match._one_folded_name`` went on collapsing ``nuno-silva-1`` /
``nuno-silva-2`` — two reviewed-different humans who happen to be published
under the same display name — into "a duplicate in the scraped source", which
wrote one thesis mention as two rows under two unrelated identities.

**Why it fails loudly.** The alternative — skipping an entry whose slug no
longer exists — would silently *un-merge* a person: the build would succeed,
the matcher would go back to reporting them ambiguous, and nothing anywhere
would say why. An upstream slug rename breaking the build until somebody
edits this file is the deliberate trade.

**Never destructive.** The aliased ``people`` row is kept. ``scraper/people.py``
re-serves both slugs on every sync (``db.upsert_person`` would resurrect a
deleted row), both CISUC pages are live URLs, and ``project_people`` /
``project_fields_raw`` provenance hangs off both slugs. Consumers resolve
*through* the map — the ``people_canonical`` view in ``scraper/schema.sql`` is
the one obvious place to do it from.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ALIASES = ROOT / "data" / "person_aliases.json"

SAME = "same"
DISTINCT = "distinct"
VERDICTS = (SAME, DISTINCT)

_REQUIRED_KEYS = frozenset({"a", "b", "verdict", "canonical", "evidence"})


class AliasError(RuntimeError):
    """``data/person_aliases.json`` cannot be acted on. Never a warning."""


def load_pairs(path: Path | None = None) -> list[dict]:
    """The curated verdicts, with the file's own shape checked.

    Shape errors are raised here and identity errors in ``validate()``,
    because only the latter needs the ``people`` table to judge — this half
    is checkable with nothing but the file.
    """
    path = path or DEFAULT_ALIASES
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("pairs"), list):
        raise AliasError(f"{path}: expected an object with a 'pairs' list")

    pairs = document["pairs"]
    for index, entry in enumerate(pairs):
        where = f"{path}: pairs[{index}]"
        if not isinstance(entry, dict):
            raise AliasError(f"{where} is not an object")
        missing = _REQUIRED_KEYS - set(entry)
        if missing:
            raise AliasError(f"{where} is missing {sorted(missing)}")
        extra = set(entry) - _REQUIRED_KEYS
        if extra:
            raise AliasError(f"{where} carries unknown keys {sorted(extra)}")
        if entry["verdict"] not in VERDICTS:
            raise AliasError(
                f"{where}: verdict {entry['verdict']!r} is not one of {list(VERDICTS)}"
            )
        for key in ("a", "b"):
            if not isinstance(entry[key], str) or not entry[key]:
                raise AliasError(f"{where}: {key!r} must be a non-empty slug")
        if not isinstance(entry["evidence"], str) or not entry["evidence"].strip():
            raise AliasError(
                f"{where}: evidence is required — a verdict with no evidence behind it "
                "is the one thing this file exists to make impossible"
            )
    return pairs


def validate(pairs: list[dict], people_slugs: set[str]) -> None:
    """Every reason a verdict cannot be acted on, raised rather than skipped.

    ``people_slugs`` is the live ``people`` primary keys. Checking against
    them is what catches an upstream slug rename — which otherwise reads as a
    person quietly un-merging.
    """
    seen_pairs: set[tuple[str, str]] = set()
    canonical_of: dict[str, str] = {}

    for index, entry in enumerate(pairs):
        where = f"pairs[{index}] ({entry['a']} / {entry['b']})"
        a, b, verdict = entry["a"], entry["b"], entry["verdict"]

        if a == b:
            raise AliasError(f"{where}: a slug cannot be an alias of itself")
        for slug in (a, b):
            if slug not in people_slugs:
                raise AliasError(
                    f"{where}: no row in people carries the slug {slug!r} — either the "
                    "slug was renamed upstream or this entry is a typo. Fix "
                    "data/person_aliases.json; a skipped entry would silently un-merge "
                    "a person."
                )
        key = (a, b) if a < b else (b, a)
        if key in seen_pairs:
            raise AliasError(f"{where}: this pair already has a verdict earlier in the file")
        seen_pairs.add(key)

        if verdict == DISTINCT:
            if entry["canonical"] is not None:
                raise AliasError(
                    f"{where}: a 'distinct' verdict must carry canonical: null — these "
                    "are two different people, so neither is the other's canonical"
                )
            continue

        canonical = entry["canonical"]
        if canonical not in (a, b):
            raise AliasError(
                f"{where}: canonical {canonical!r} must be one of the two slugs in the pair"
            )
        alias = b if canonical == a else a
        if alias in canonical_of and canonical_of[alias] != canonical:
            raise AliasError(
                f"{where}: {alias!r} is already an alias of {canonical_of[alias]!r} — one "
                "slug cannot resolve to two different people"
            )
        canonical_of[alias] = canonical

    # Chains last: a->b is only a chain once every entry has been read, so
    # the file's own order cannot decide whether this fires.
    for alias, canonical in sorted(canonical_of.items()):
        if canonical in canonical_of:
            raise AliasError(
                f"alias chain: {alias!r} -> {canonical!r} -> {canonical_of[canonical]!r}. "
                "Resolution is one hop by construction (person_aliases.from_slug is a "
                f"PRIMARY KEY, and every consumer does one lookup) — point {alias!r} "
                f"straight at {canonical_of[canonical]!r} instead."
            )


def alias_map(pairs: list[dict]) -> dict[str, str]:
    """``{from_slug: to_slug}`` — the "de x para", ``same`` verdicts only.

    Call ``validate()`` first; this does not re-check, so that a caller
    cannot get a half-checked map by reaching for the cheaper function.
    """
    out: dict[str, str] = {}
    for entry in pairs:
        if entry["verdict"] != SAME:
            continue
        canonical = entry["canonical"]
        out[entry["b"] if canonical == entry["a"] else entry["a"]] = canonical
    return out


def evidence_map(pairs: list[dict]) -> dict[str, str]:
    """``{from_slug: evidence}`` for the ``same`` verdicts — what gets stored
    next to the mapping, so the reason travels with it into the seed."""
    return {
        (entry["b"] if entry["canonical"] == entry["a"] else entry["a"]): entry["evidence"]
        for entry in pairs
        if entry["verdict"] == SAME
    }


def reviewed_pairs(pairs: list[dict]) -> set[tuple[str, str]]:
    """Every pair already ruled on, under **either** verdict, as sorted slug
    tuples. ``distinct`` counts: the point of recording one is that the
    detection pass stops re-reporting it."""
    return {(e["a"], e["b"]) if e["a"] < e["b"] else (e["b"], e["a"]) for e in pairs}


def distinct_pairs(pairs: list[dict]) -> set[tuple[str, str]]:
    """The pairs a human ruled **different humans**, as sorted slug tuples.

    ``reviewed_pairs()``'s ``distinct`` half, separated because the two have
    opposite uses: that one asks "has anybody looked at this pair yet", this
    one asks "did they say no". ``analysis/name_match.match_name`` takes it so
    a reviewed ``distinct`` outranks every name rule that would otherwise read
    two rows as one human — no canonical to write, so there is nothing for
    ``alias_map()`` to carry it on.
    """
    return {
        (e["a"], e["b"]) if e["a"] < e["b"] else (e["b"], e["a"])
        for e in pairs
        if e["verdict"] == DISTINCT
    }


def write_table(conn, pairs: list[dict]) -> int:
    """Replace ``person_aliases`` from ``pairs``. Returns the rows written.

    Full replace, not upsert, for the reason ``build_thesis_facts`` replaces
    the thesis tables: the table is a pure function of a committed file, and a
    verdict somebody *removed* must not survive in the seed forever.

    Assumes the schema is already applied and does NOT commit — the caller
    owns the transaction, so a later failure in the same build cannot leave
    the seed holding a half-applied identity map.
    """
    aliases = alias_map(pairs)
    evidence = evidence_map(pairs)
    conn.execute("DELETE FROM person_aliases")
    conn.executemany(
        "INSERT INTO person_aliases (from_slug, to_slug, evidence) VALUES (?,?,?)",
        [(from_slug, to_slug, evidence[from_slug]) for from_slug, to_slug in sorted(aliases.items())],
    )
    return len(aliases)


def load_and_write(conn, path: Path | None = None) -> dict:
    """The whole step, as ``build_thesis_facts.build()`` needs it: read,
    validate against the live ``people`` rows, write the table, report."""
    pairs = load_pairs(path)
    people_slugs = {row[0] for row in conn.execute("SELECT slug FROM people")}
    validate(pairs, people_slugs)
    written = write_table(conn, pairs)
    return {
        "pairs_reviewed": len(pairs),
        "same": written,
        "distinct": sum(1 for entry in pairs if entry["verdict"] == DISTINCT),
    }
