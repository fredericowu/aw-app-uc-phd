"""Researched identities for thesis mentions that will never get a slug.

``person_aliases.py`` and ``person_full_names.py`` both fix a defect in
CISUC's own directory: a human listed twice, or listed under a name that is
not a truncation of theirs. This module is for the names where the directory
is **right to be silent**. Of the 45 unattributed authors/supervisors
researched for the name sweep, 29 are real people with no CISUC person row
and no reason to have one — an ISEP professor who co-supervised one thesis,
a CERN project leader, a UFPB academic, a Critical Software founder, a
graduate who left in 2015. Nothing can match them, and nothing should.

What was still wrong is the *display*: the app printed a bare
"(unattributed)" next to a name whose person, affiliation and source we now
know. This supplies that, and only that.

**This is display metadata for one thesis mention. It is not an identity
table, and it is never matcher input.** The distinction is the whole design,
because the thing it most resembles is option C — the thesis-name -> person
lookup the Product Owner rejected (``docs/thesis-attribution.md``). Three
properties keep it on the right side of that line, and all three are
enforced below rather than merely intended:

* **It assigns no ``person_slug``, ever.** The matched row and the
  ``external_people`` row are disjoint by construction: ``validate()``
  refuses an entry whose ``thesis_people`` row is anything other than
  ``unmatched``, so this file structurally cannot override, shadow or
  second-guess a matcher verdict. ``identity_coverage`` does not move.
* **``analysis/name_match.py`` must never import it.** The matcher's inputs
  are the two reviewed *person-grain* files and nothing else; a name this
  resolves is still an unresolved name as far as every count, join and tier
  in this repo is concerned.
* **The key is a mention, not a name:** ``(handle, name_raw, role)``. Option
  C mapped a name to a person and so applied to every thesis forever —
  which is this corpus's core trap, since "Martins, Pedro" is two different
  people two years apart. An entry here says "the Francisco Pereira *on this
  thesis, in this role* is this human", and a future thesis carrying the
  same string inherits nothing. The accepted cost is duplication: Torsten
  Braun supervises two theses and therefore has two entries.

What this module does with ``data/external_people.json``:

* ``load_entries()`` — read it, with the shape checked rather than assumed.
* ``validate()``     — refuse it loudly, never skip (see below).
* ``write_table()``  — replace ``external_people`` in the seed from it.

**Why it fails loudly.** Same trade as its two siblings, one step weaker in
consequence and identical in mechanism. A skipped entry here cannot land a
wrong person on a thesis — it has no slug to land — but it can silently
*stop* displaying a researched identity, or keep displaying one for a row the
matcher has since resolved, which is a stale claim sitting next to a real
person's name. The build breaking until somebody edits this file is the
deliberate trade, and the ``unmatched`` check is what makes a future matcher
improvement surface the entries it has made obsolete instead of quietly
contradicting them.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXTERNAL_PEOPLE = ROOT / "data" / "external_people.json"

ROLES = ("author", "supervisor")

_REQUIRED_KEYS = frozenset(
    {
        "handle",
        "name_raw",
        "role",
        "display_name",
        "affiliation",
        "source_url",
        "evidence",
    }
)
_OPTIONAL_KEYS = frozenset({"note"})

#: The fields with nothing to fall back on. ``note`` is genuinely optional —
#: most entries have no caveat worth carrying — but an entry with no
#: affiliation or no source is exactly the unsourced claim this file exists
#: to make impossible, and an empty ``display_name`` would render as a blank
#: where the bare "(unattributed)" at least told the truth.
_REQUIRED_TEXT = ("handle", "name_raw", "display_name", "affiliation", "source_url", "evidence")


class ExternalPersonError(RuntimeError):
    """``data/external_people.json`` cannot be acted on. Never a warning."""


def load_entries(path: Path | None = None) -> list[dict]:
    """The curated external identities, with the file's own shape checked.

    Shape errors are raised here and identity errors in ``validate()``,
    because only the latter needs ``thesis_people`` to judge — this half is
    checkable with nothing but the file.
    """
    path = path or DEFAULT_EXTERNAL_PEOPLE
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("entries"), list):
        raise ExternalPersonError(f"{path}: expected an object with an 'entries' list")

    entries = document["entries"]
    for index, entry in enumerate(entries):
        where = f"{path}: entries[{index}]"
        if not isinstance(entry, dict):
            raise ExternalPersonError(f"{where} is not an object")
        missing = _REQUIRED_KEYS - set(entry)
        if missing:
            raise ExternalPersonError(f"{where} is missing {sorted(missing)}")
        extra = set(entry) - _REQUIRED_KEYS - _OPTIONAL_KEYS
        if extra:
            raise ExternalPersonError(f"{where} carries unknown keys {sorted(extra)}")
        if entry["role"] not in ROLES:
            raise ExternalPersonError(
                f"{where}: role {entry['role']!r} is not one of {list(ROLES)}"
            )
        for key in _REQUIRED_TEXT:
            if not isinstance(entry[key], str) or not entry[key].strip():
                raise ExternalPersonError(f"{where}: {key!r} must be a non-empty string")
        if "note" in entry and not isinstance(entry["note"], str):
            raise ExternalPersonError(f"{where}: 'note' must be a string when present")
        if not entry["source_url"].startswith(("http://", "https://")):
            raise ExternalPersonError(
                f"{where}: source_url {entry['source_url']!r} is not a URL — this field is "
                "what makes the claim checkable by somebody who was not in the room"
            )
    return entries


def validate(entries: list[dict], mention_status: dict[tuple[str, str, str], str]) -> None:
    """Every reason an entry cannot be acted on, raised rather than skipped.

    ``mention_status`` is ``{(handle, name_raw, role): match_status}`` read
    off the ``thesis_people`` rows this build just wrote. Checking against it
    is what catches the two ways an entry goes stale — the mention
    disappearing (a thesis withdrawn upstream, a name re-extracted) and the
    matcher *resolving* it, which would leave a researched external identity
    hanging off a row that now names a real CISUC person.
    """
    seen: set[tuple[str, str, str]] = set()
    for index, entry in enumerate(entries):
        key = (entry["handle"], entry["name_raw"], entry["role"])
        where = f"entries[{index}] ({entry['handle']} / {entry['name_raw']} / {entry['role']})"

        if key not in mention_status:
            raise ExternalPersonError(
                f"{where}: no row in thesis_people carries this (handle, name_raw, role) — "
                "either the thesis or the name changed upstream, or this entry is a typo. "
                "Fix data/external_people.json; a skipped entry would silently stop "
                "displaying a researched identity and report a successful build."
            )
        status = mention_status[key]
        if status != "unmatched":
            raise ExternalPersonError(
                f"{where}: this mention is {status!r}, not 'unmatched' — the matcher now "
                "resolves it to a CISUC person, so this entry is an obsolete claim sitting "
                "next to a real identity. This file is display metadata for names nothing "
                "can match; it must never shadow a matched row. Remove the entry."
            )
        if key in seen:
            raise ExternalPersonError(
                f"{where}: this mention already has an entry earlier in the file — one "
                "mention has one researched identity, and two entries would make which "
                "one wins depend on the file's order"
            )
        seen.add(key)


def write_table(conn, entries: list[dict]) -> int:
    """Replace ``external_people`` from ``entries``. Returns rows written.

    Full replace, not upsert, for the reason its two siblings replace their
    own tables: this is a pure function of a committed file, and an entry
    somebody *removed* — because the matcher now resolves that name — must
    not survive in the seed forever.

    Assumes the schema is already applied and does NOT commit — the caller
    owns the transaction.
    """
    conn.execute("DELETE FROM external_people")
    conn.executemany(
        "INSERT INTO external_people "
        "(handle, name_raw, role, display_name, affiliation, source_url, note, evidence) "
        "VALUES (?,?,?,?,?,?,?,?)",
        sorted(
            (
                e["handle"],
                e["name_raw"],
                e["role"],
                e["display_name"],
                e["affiliation"],
                e["source_url"],
                e.get("note"),
                e["evidence"],
            )
            for e in entries
        ),
    )
    return len(entries)


def load_and_write(conn, path: Path | None = None) -> dict:
    """The whole step, as ``build_thesis_facts.build()`` needs it: read,
    validate against the ``thesis_people`` rows already written in this
    transaction, write the table, report.

    Runs **after** the thesis rows are inserted, unlike its two siblings,
    which run before the matcher: the facts it is checked against are this
    build's own output rather than its input.
    """
    entries = load_entries(path)
    mention_status = {
        (handle, name_raw, role): status
        for handle, name_raw, role, status in conn.execute(
            "SELECT handle, name_raw, role, match_status FROM thesis_people"
        )
    }
    validate(entries, mention_status)
    return {"external_people": write_table(conn, entries)}
