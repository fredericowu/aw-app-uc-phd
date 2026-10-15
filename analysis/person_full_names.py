"""Reviewed full legal names — curated, validated, written to the seed.

CISUC publishes a short form for everyone, and for most people that short
form is a *truncation* of the full name, which is all ``analysis/name_match``
needs: the thesis writes "Carvalho, Paulo Fernando Pereira de", CISUC writes
"Paulo Carvalho", and every token of the CISUC form is in the thesis form.

For a handful of people the short form is not a truncation. CISUC drops the
actual trailing surname, or picks a later given name over the first:

* ``antonio-dourado`` is published "António Dourado"; the thesis writes
  "Correia, António Dourado Pereira". **The surnames share nothing.**
* ``penousal-machado`` is published "Penousal Machado"; "Penousal" is his
  third given name, and the thesis writes "Machado, Fernando".

``_fits()`` rejects both, correctly, on the evidence it has — nothing in
"António Dourado" says the person is a Correia. Relaxing ``_fits()`` to accept
them is measured-rejected relaxation B (``docs/thesis-attribution.md``
§"Two rejected relaxations"), which bought 13 edges and one confidently wrong
person. So this module does not relax a rule either. It supplies the missing
**fact** — the person's full legal name, read off a citable source by a human
— and ``name_match._fits_full()`` is the one comparison allowed to use it.

This is ``data/person_aliases.json``'s move, on a different fact. Both record
a decision upstream of any thesis, at the person grain, checkable by anyone
against the source named in ``evidence``. Neither is the PO-rejected
thesis-name -> person lookup table, and this file must never become one:
**the key is a slug, never a thesis name**, and an entry says what somebody is
called, not which thesis is theirs.

What this module does with ``data/person_full_names.json``:

* ``load_entries()``  — read it, with the shape checked rather than assumed.
* ``validate()``      — refuse it loudly, never skip (see below).
* ``full_name_map()`` — ``{slug: full_name}``, what the matcher ends up reading.
* ``write_table()``   — replace ``person_full_names`` in the seed from it.

**Why it fails loudly.** Same trade as ``person_aliases.py``: skipping an
entry whose slug was renamed upstream would silently un-match a person, the
build would report success, and nothing anywhere would say why.

**Why the display name must be covered by the full name.** An entry is a claim
that ``people.slug`` and this legal name are one human, and the cheapest check
on that claim is that CISUC's own published form is a subset of it (initials
allowed, so "F. Amilcar Cardoso" could be covered by "Fernando Amílcar
Cardoso"). An entry that fails it is a typo or the wrong person — and the
check re-fires on every build, so a future directory sync that renames the
display name out from under an entry breaks the build instead of quietly
landing someone else's thesis on this slug.
"""
from __future__ import annotations

import json
from pathlib import Path

from .name_match import tokenize

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FULL_NAMES = ROOT / "data" / "person_full_names.json"

_REQUIRED_KEYS = frozenset({"slug", "full_name", "evidence"})


class FullNameError(RuntimeError):
    """``data/person_full_names.json`` cannot be acted on. Never a warning."""


def load_entries(path: Path | None = None) -> list[dict]:
    """The curated full names, with the file's own shape checked.

    Shape errors are raised here and identity errors in ``validate()``,
    because only the latter needs the ``people`` table to judge — this half is
    checkable with nothing but the file.
    """
    path = path or DEFAULT_FULL_NAMES
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("entries"), list):
        raise FullNameError(f"{path}: expected an object with an 'entries' list")

    entries = document["entries"]
    for index, entry in enumerate(entries):
        where = f"{path}: entries[{index}]"
        if not isinstance(entry, dict):
            raise FullNameError(f"{where} is not an object")
        missing = _REQUIRED_KEYS - set(entry)
        if missing:
            raise FullNameError(f"{where} is missing {sorted(missing)}")
        extra = set(entry) - _REQUIRED_KEYS
        if extra:
            raise FullNameError(f"{where} carries unknown keys {sorted(extra)}")
        for key in ("slug", "full_name"):
            if not isinstance(entry[key], str) or not entry[key].strip():
                raise FullNameError(f"{where}: {key!r} must be a non-empty string")
        if not isinstance(entry["evidence"], str) or not entry["evidence"].strip():
            raise FullNameError(
                f"{where}: evidence is required — this entry lands a person on a thesis "
                "at the confident tier, and an unsourced one is the only failure mode "
                "this file has"
            )
    return entries


def validate(entries: list[dict], names_by_slug: dict[str, str]) -> None:
    """Every reason an entry cannot be acted on, raised rather than skipped.

    ``names_by_slug`` is the live ``people`` table. Checking against it is
    what catches an upstream slug rename *and* an upstream display-name
    change — both of which otherwise read as a person quietly un-matching, or
    worse, as a stale claim still resolving.
    """
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        slug, full_name = entry["slug"], entry["full_name"]
        where = f"entries[{index}] ({slug})"

        if slug not in names_by_slug:
            raise FullNameError(
                f"{where}: no row in people carries the slug {slug!r} — either the slug "
                "was renamed upstream or this entry is a typo. Fix "
                "data/person_full_names.json; a skipped entry would silently un-match "
                "a person."
            )
        if slug in seen:
            raise FullNameError(
                f"{where}: this slug already has a full name earlier in the file — one "
                "person has one legal name, and two entries would make which one wins "
                "depend on the file's order"
            )
        seen.add(slug)

        display = names_by_slug[slug]
        full_tokens = tokenize(full_name)
        unaccounted = [
            token
            for token in tokenize(display)
            # An initial on the CISUC side stands for a given name spelled out
            # in the full name ("F." for "Fernando") — the same convention
            # name_match._is_initial_of excuses on the matching side.
            if token not in full_tokens
            and not (len(token) == 1 and any(f.startswith(token) for f in full_tokens))
        ]
        if unaccounted:
            raise FullNameError(
                f"{where}: the full name {full_name!r} does not account for "
                f"{unaccounted} from the CISUC display name {display!r}. Either this is "
                "a typo, or it is a different human than the one CISUC publishes under "
                f"{slug!r} — and a wrong entry here lands a wrong person on a thesis at "
                "the confident tier."
            )


def full_name_map(entries: list[dict]) -> dict[str, str]:
    """``{slug: full_name}`` — what ``Person.full_name`` is filled from.

    Call ``validate()`` first; this does not re-check, so that a caller cannot
    get a half-checked map by reaching for the cheaper function.
    """
    return {entry["slug"]: entry["full_name"] for entry in entries}


def write_table(conn, entries: list[dict]) -> int:
    """Replace ``person_full_names`` from ``entries``. Returns rows written.

    Full replace, not upsert, for the reason ``person_aliases.write_table``
    replaces its own: the table is a pure function of a committed file, and an
    entry somebody *removed* must not survive in the seed forever.

    Assumes the schema is already applied and does NOT commit — the caller
    owns the transaction.
    """
    conn.execute("DELETE FROM person_full_names")
    conn.executemany(
        "INSERT INTO person_full_names (slug, full_name, evidence) VALUES (?,?,?)",
        sorted((e["slug"], e["full_name"], e["evidence"]) for e in entries),
    )
    return len(entries)


def load_and_write(conn, path: Path | None = None) -> dict:
    """The whole step, as ``build_thesis_facts.build()`` needs it: read,
    validate against the live ``people`` rows, write the table, report."""
    entries = load_entries(path)
    names_by_slug = dict(conn.execute("SELECT slug, name FROM people"))
    validate(entries, names_by_slug)
    return {"full_names": write_table(conn, entries)}
