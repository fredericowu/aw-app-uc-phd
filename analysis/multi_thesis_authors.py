"""Reviewed multi-thesis authors — curated, validated, written to the seed.

``analysis/build_thesis_facts.py``'s ``resolve_author_conflicts`` enforces
"one ``people`` row authors at most one thesis in this corpus", and that rule
is why "Martins, Pedro" (2014, computer vision) and "Martins, Pedro Miguel de
Oliveira" (2016, ETL) are two students instead of one. It is also, at
university scale, occasionally wrong about a real person: Estudo Geral holds
both the MSc dissertation and the doctoral thesis of the same graduate, filed
under the identical author string, and the gate withdraws both links because
nothing in a name can tell "the same person twice" from "two people who
collide".

This module supplies the missing **fact**: a human has read both records and
confirmed they are one human. That is ``data/person_aliases.json``'s and
``data/person_full_names.json``'s move on a third fact, and it stays on the
same side of the line the Product Owner drew (option C — the thesis-name ->
person lookup — is rejected, ``docs/thesis-attribution.md``):

* **It creates no match.** Nothing here reaches ``analysis/name_match.py``,
  which must never import it. Both of João Campos's claims were already
  resolved, independently, by the matcher on the names alone; all an entry
  does is stop the corpus-wide conflict pass from *withdrawing* them. A name
  the matcher does not resolve cannot be resolved by adding an entry here.
* **The key is a person**, ``slug``, and an entry says how many theses that
  person has in this corpus — not which person a thesis belongs to. The
  handles are the *evidence for the count*, which is why they are exhaustive:
  a claim on an exempted slug for a handle the entry does not list is demoted
  exactly as it is today, because the reviewed fact says that is somebody
  else.
* **It is reviewed per person, never derived from a name.** The byte-identical
  author string is what makes João's case *look* safe and is precisely the
  reason a rule must not act on it — byte-identical is the maximally similar
  pair of claims, and in this corpus similarity is not identity. The rule
  version of this file was weighed and rejected (the design for card
  3fd5bf3b-9510-8128-958f-e1d6b9e63660, §1 "Rejected alternatives").

What this module does with ``data/multi_thesis_authors.json``:

* ``load_entries()``  — read it, with the shape checked rather than assumed.
* ``validate()``      — refuse it loudly, never skip (see below).
* ``exempt_claims()`` — ``{(slug, handle)}``, what the conflict pass reads.
* ``write_table()``   — replace ``multi_thesis_authors`` in the seed from it.

There is deliberately no ``load_and_write`` here, unlike all three siblings:
the four steps run at three different points of one build, and ``build()``'s
docstring says which. The exemptions must be *read* before the conflict pass
(which consumes them), *checked* against the matcher's own verdicts, and the
table *written* before the ``thesis_people`` rows, because the schema trigger
that enforces the invariant reads it on every insert.

**Why it fails loudly.** Same trade as all three siblings, and here the stale
direction is the dangerous one. An entry is a standing instruction to *keep* a
slug on two theses, so an entry that has gone stale — a thesis withdrawn
upstream, a name re-extracted, the matcher no longer resolving one of the two
claims — is an exemption with nothing behind it, and the one thing it would
suppress is the collision check. ``validate()`` therefore re-proves every
enumerated claim on every build: the slug must exist in ``people`` (as the
*canonical* slug, since that is what ``people_rows`` writes), the handle must
be in the corpus, and the claim must actually have resolved to that slug at
``exact`` or ``confident``. An obsolete entry breaks the build until somebody
edits the file. That is the house trade — see ``analysis/external_people.py``
for the same check in the mirror direction.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MULTI_THESIS_AUTHORS = ROOT / "data" / "multi_thesis_authors.json"

_REQUIRED_KEYS = frozenset({"slug", "handles", "source_url", "evidence"})
_OPTIONAL_KEYS = frozenset({"note"})

#: Two is the whole point: an entry listing one handle exempts nothing (one
#: claim is never a conflict), so it is either a typo or the leftover of a
#: thesis that went away — and a file full of no-ops is a file nobody trusts.
MIN_HANDLES = 2


class MultiThesisAuthorError(RuntimeError):
    """``data/multi_thesis_authors.json`` cannot be acted on. Never a warning."""


def load_entries(path: Path | None = None) -> list[dict]:
    """The curated multi-thesis authors, with the file's own shape checked.

    Shape errors are raised here and identity errors in ``validate()``,
    because only the latter needs the corpus and the matcher's verdicts to
    judge — this half is checkable with nothing but the file.
    """
    path = path or DEFAULT_MULTI_THESIS_AUTHORS
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("entries"), list):
        raise MultiThesisAuthorError(f"{path}: expected an object with an 'entries' list")

    entries = document["entries"]
    for index, entry in enumerate(entries):
        where = f"{path}: entries[{index}]"
        if not isinstance(entry, dict):
            raise MultiThesisAuthorError(f"{where} is not an object")
        missing = _REQUIRED_KEYS - set(entry)
        if missing:
            raise MultiThesisAuthorError(f"{where} is missing {sorted(missing)}")
        extra = set(entry) - _REQUIRED_KEYS - _OPTIONAL_KEYS
        if extra:
            raise MultiThesisAuthorError(f"{where} carries unknown keys {sorted(extra)}")
        for key in ("slug", "source_url"):
            if not isinstance(entry[key], str) or not entry[key].strip():
                raise MultiThesisAuthorError(f"{where}: {key!r} must be a non-empty string")
        if "note" in entry and not isinstance(entry["note"], str):
            raise MultiThesisAuthorError(f"{where}: 'note' must be a string when present")
        if not isinstance(entry["evidence"], str) or not entry["evidence"].strip():
            raise MultiThesisAuthorError(
                f"{where}: evidence is required — this entry suppresses the one check "
                "that catches two real people colliding on one slug, and an unsourced "
                "one is the only failure mode this file has"
            )
        if not entry["source_url"].startswith(("http://", "https://")):
            raise MultiThesisAuthorError(
                f"{where}: source_url {entry['source_url']!r} is not a URL — this field "
                "is what makes the claim checkable by somebody who was not in the room"
            )
        handles = entry["handles"]
        if not isinstance(handles, list) or not all(
            isinstance(handle, str) and handle.strip() for handle in handles
        ):
            raise MultiThesisAuthorError(
                f"{where}: 'handles' must be a list of non-empty strings"
            )
        if len(set(handles)) != len(handles):
            raise MultiThesisAuthorError(f"{where}: 'handles' lists the same handle twice")
        if len(handles) < MIN_HANDLES:
            raise MultiThesisAuthorError(
                f"{where}: 'handles' lists {len(handles)} thesis, and an entry needs at "
                f"least {MIN_HANDLES} to exempt anything — one claim on a slug is never "
                "a conflict. Either a handle is missing, or this entry is obsolete and "
                "should be deleted."
            )
    return entries


def validate(
    entries: list[dict],
    canonical_slugs: set[str],
    corpus_handles: set[str],
    resolved_author_claims: set[tuple[str, str]],
) -> None:
    """Every reason an entry cannot be acted on, raised rather than skipped.

    The three inputs are this build's own facts, in the order an entry can go
    stale:

    * ``canonical_slugs`` — every ``people`` slug *after* ``person_aliases``
      collapses an alias group, because ``people_rows`` writes the canonical
      slug and so that is what the conflict pass groups by. An entry naming
      the non-canonical half of an alias pair would exempt a slug no row ever
      carries.
    * ``corpus_handles`` — the theses this build read. A withdrawn thesis
      leaves an exemption standing over a handle that is gone.
    * ``resolved_author_claims`` — ``{(person_slug, handle)}`` for every
      author row the matcher resolved at ``exact`` or ``confident`` *before*
      the conflict pass ran. This is the load-bearing check: an exemption is
      only meaningful while the matcher still independently resolves both
      claims, and an entry that has outlived that is an exemption suppressing
      a collision check for no reason anybody reviewed.
    """
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        slug, handles = entry["slug"], entry["handles"]
        where = f"entries[{index}] ({slug})"

        if slug in seen:
            raise MultiThesisAuthorError(
                f"{where}: this slug already has an entry earlier in the file — one "
                "person has one list of theses, and two entries would make which one "
                "wins depend on the file's order"
            )
        seen.add(slug)

        if slug not in canonical_slugs:
            raise MultiThesisAuthorError(
                f"{where}: no row in people carries the canonical slug {slug!r} — either "
                "the slug was renamed upstream, or data/person_aliases.json now rules it "
                "the alias of another slug (name the canonical one instead), or this "
                "entry is a typo. Fix data/multi_thesis_authors.json; a skipped entry "
                "would silently withdraw a reviewed person's thesis links."
            )

        for handle in handles:
            if handle not in corpus_handles:
                raise MultiThesisAuthorError(
                    f"{where}: thesis {handle!r} is not in this corpus — it was withdrawn "
                    "upstream, or the handle is a typo. An exemption over a thesis that "
                    "does not exist is an unreviewed hole in the one-person-one-thesis "
                    "check; remove the handle."
                )
            if (slug, handle) not in resolved_author_claims:
                raise MultiThesisAuthorError(
                    f"{where}: the matcher does not resolve the author of thesis {handle!r} "
                    f"to {slug!r} at exact or confident, so there is no claim here to "
                    "exempt. This entry only ever prevented two independent matches from "
                    "being withdrawn; it must never be the thing that creates one. Either "
                    "the author name changed upstream, or this entry is obsolete — fix "
                    "data/multi_thesis_authors.json."
                )


def exempt_claims(entries: list[dict]) -> frozenset[tuple[str, str]]:
    """``{(person_slug, handle)}`` — what ``resolve_author_conflicts`` reads.

    Call ``validate()`` first; this does not re-check, so that a caller cannot
    get a half-checked exemption set by reaching for the cheaper function.
    """
    return frozenset(
        (entry["slug"], handle) for entry in entries for handle in entry["handles"]
    )


def write_table(conn, entries: list[dict]) -> int:
    """Replace ``multi_thesis_authors`` from ``entries``. Returns rows written.

    One row per exempted claim rather than one per person, because the
    ``thesis_people`` trigger in ``scraper/schema.sql`` tests membership of a
    ``(person_slug, handle)`` pair and a JSON list in a column would make that
    a string search.

    Full replace, not upsert, for the reason all three siblings replace their
    own tables: it is a pure function of a committed file, and an exemption
    somebody *removed* must not survive in the seed forever — least of all
    this one, where a leftover row keeps the schema backstop switched off.

    Assumes the schema is already applied and does NOT commit — the caller
    owns the transaction.
    """
    conn.execute("DELETE FROM multi_thesis_authors")
    conn.executemany(
        "INSERT INTO multi_thesis_authors (person_slug, handle, source_url, evidence) "
        "VALUES (?,?,?,?)",
        sorted(
            (entry["slug"], handle, entry["source_url"], entry["evidence"])
            for entry in entries
            for handle in entry["handles"]
        ),
    )
    return sum(len(entry["handles"]) for entry in entries)
