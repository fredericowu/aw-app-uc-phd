"""Reviewed duplicate thesis records — curated, validated, excluded at build.

Estudo Geral occasionally holds **one physical thesis as two records**. Not two
degrees by one graduate (that is ``data/multi_thesis_authors.json``'s fact, and
the opposite one), not two people colliding on a name (``data/person_aliases``'
fact): one submission deposited twice, so the corpus counts a thesis that does
not exist and the dashboard's thesis and student figures are both off by it.

This module supplies the missing **fact**: a human has read both records and
confirmed they are one deposit. ``analysis/build_thesis_facts.py``'s ``build()``
then drops the duplicate's front matter immediately after ``reconcile()`` and
before any table row is derived, so ``theses`` / ``thesis_people`` /
``thesis_keywords`` / ``thesis_sets`` are free of the handle by construction —
no per-table filtering, and no orphan row left pointing at a thesis that is not
in ``theses``.

Three fences, each enforced below rather than merely intended:

* **The key is a THESIS HANDLE and the claim is "this record is not a distinct
  thesis".** It never says whose thesis anything is, and it must never grow a
  person field. That is the same line all three sibling files draw: option C —
  the thesis-name -> person lookup — is rejected (``docs/thesis-attribution.md``),
  and a file whose entries carry no person semantics at all cannot drift across
  it.
* **It detects nothing.** Nothing here reads abstracts or compares titles
  looking for candidates. The duplicate was found by a human, against the OAI
  records, and measured as a one-off across the whole corpus; the rule version
  of this file ("byte-identical abstracts are the same thesis") was weighed and
  rejected, because similarity is not identity in this corpus and a false
  positive here *silently deletes a real thesis*. See the design doc,
  ``docs/design/uc-phd-duplicate-thesis-exclusion.md`` §2.
* **The corpus stays complete on disk.** ``estudo_geral/<slug>.md`` is not
  deleted and its manifest entry stays, so ``reconcile()`` still runs over every
  harvested thesis and the exclusion can never be mistaken for a harvest gap.
  Reverting the call is deleting one JSON entry and rebuilding.

What this module does with ``data/duplicate_theses.json``:

* ``load_entries()``     — read it, with the shape checked rather than assumed.
* ``validate()``         — refuse it loudly, never skip (see below).
* ``excluded_handles()`` — ``{handle}``, what ``build()`` filters the corpus by.
* ``write_table()``      — replace ``duplicate_theses`` in the seed from it.

There is deliberately no ``load_and_write`` here, for the same reason
``analysis/multi_thesis_authors.py`` has none: the steps run at different points
of one build. The file is **read and validated** against the full, reconciled
corpus — the check needs *both* records' front matters, so it cannot run after
the filter — and its **table is written before the ``theses`` inserts**, because
``scraper/schema.sql``'s ``trg_no_excluded_thesis`` reads it on every insert.

**Why it fails loudly.** Same trade as all three siblings, and the stale
direction here is the dangerous one in both halves. An entry is a standing
instruction to *drop* a record, so:

* if the duplicate disappears upstream, the exclusion stands over nothing and
  the next reader has no way to tell a live editorial decision from a leftover;
* if the **survivor** disappears, the entry stops deduplicating a thesis and
  starts erasing one — the corpus would lose the work entirely, quietly;
* if the two records stop being identical in the fields the evidence names,
  the verdict is no longer the one a human reviewed, whatever it has become.

``validate()`` therefore re-proves the whole claim on every build, and an
obsolete entry breaks the build until somebody edits the file.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DUPLICATE_THESES = ROOT / "data" / "duplicate_theses.json"

_REQUIRED_KEYS = frozenset(
    {"duplicate_handle", "kept_handle", "identical_fields", "source_url", "evidence"}
)
_OPTIONAL_KEYS = frozenset({"note"})

#: The floor under ``identical_fields``. An entry resting on ``date`` alone
#: would "prove" every thesis defended on the same day is the same thesis, and
#: one resting on ``authors`` alone would do it to every graduate with two
#: deposits — which is the fact the opposite file, multi_thesis_authors.json,
#: exists to record. Neither is evidence of a duplicated DEPOSIT; together they
#: are the minimum that is, and an entry is free to name more (the committed one
#: names both abstracts).
REQUIRED_IDENTICAL_FIELDS = frozenset({"authors", "date"})


class DuplicateThesisError(RuntimeError):
    """``data/duplicate_theses.json`` cannot be acted on. Never a warning."""


def load_entries(path: Path | None = None) -> list[dict]:
    """The curated duplicate records, with the file's own shape checked.

    Shape errors are raised here and staleness errors in ``validate()``,
    because only the latter needs the corpus to judge — this half is checkable
    with nothing but the file.
    """
    path = path or DEFAULT_DUPLICATE_THESES
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("entries"), list):
        raise DuplicateThesisError(f"{path}: expected an object with an 'entries' list")

    entries = document["entries"]
    duplicates: set[str] = set()
    kept: set[str] = set()
    for index, entry in enumerate(entries):
        where = f"{path}: entries[{index}]"
        if not isinstance(entry, dict):
            raise DuplicateThesisError(f"{where} is not an object")
        missing = _REQUIRED_KEYS - set(entry)
        if missing:
            raise DuplicateThesisError(f"{where} is missing {sorted(missing)}")
        extra = set(entry) - _REQUIRED_KEYS - _OPTIONAL_KEYS
        if extra:
            raise DuplicateThesisError(f"{where} carries unknown keys {sorted(extra)}")
        for key in ("duplicate_handle", "kept_handle", "source_url"):
            if not isinstance(entry[key], str) or not entry[key].strip():
                raise DuplicateThesisError(f"{where}: {key!r} must be a non-empty string")
        if "note" in entry and not isinstance(entry["note"], str):
            raise DuplicateThesisError(f"{where}: 'note' must be a string when present")
        if not isinstance(entry["evidence"], str) or not entry["evidence"].strip():
            raise DuplicateThesisError(
                f"{where}: evidence is required — this entry deletes a thesis from "
                "every count this repo publishes, and an unsourced one is the only "
                "failure mode this file has"
            )
        if not entry["source_url"].startswith(("http://", "https://")):
            raise DuplicateThesisError(
                f"{where}: source_url {entry['source_url']!r} is not a URL — this field "
                "is what makes the claim checkable by somebody who was not in the room"
            )

        duplicate, keeper = entry["duplicate_handle"], entry["kept_handle"]
        if duplicate == keeper:
            raise DuplicateThesisError(
                f"{where}: duplicate_handle and kept_handle are both {duplicate!r} — an "
                "entry asserts a PAIR, and one naming itself as its own survivor would "
                "drop the record and keep nothing"
            )

        fields = entry["identical_fields"]
        if not isinstance(fields, list) or not fields or not all(
            isinstance(field, str) and field.strip() for field in fields
        ):
            raise DuplicateThesisError(
                f"{where}: 'identical_fields' must be a non-empty list of non-empty strings"
            )
        if len(set(fields)) != len(fields):
            raise DuplicateThesisError(
                f"{where}: 'identical_fields' lists the same field twice"
            )
        short = REQUIRED_IDENTICAL_FIELDS - set(fields)
        if short:
            raise DuplicateThesisError(
                f"{where}: 'identical_fields' is missing {sorted(short)} — an entry must "
                f"rest on at least {sorted(REQUIRED_IDENTICAL_FIELDS)}. Neither alone is "
                "evidence of a duplicated deposit: one date is shared by every thesis "
                "defended that day, and one author by every graduate with two deposits "
                "(which is data/multi_thesis_authors.json's fact, and the opposite one)."
            )

        if duplicate in duplicates:
            raise DuplicateThesisError(
                f"{where}: {duplicate!r} already has an entry earlier in the file — one "
                "record is dropped for one reason, and two entries would make which "
                "evidence applies depend on the file's order"
            )
        duplicates.add(duplicate)
        kept.add(keeper)

    chained = duplicates & kept
    if chained:
        raise DuplicateThesisError(
            f"{path}: {sorted(chained)} appears as both a duplicate_handle and a "
            "kept_handle — a record cannot be the survivor of one pair and the "
            "duplicate of another. That is a chain (or a cycle), and it would make "
            "the surviving thesis depend on which entry the build read first; collapse "
            "it by hand into entries that all point at the record that actually stays."
        )
    return entries


def validate(entries: list[dict], front_matters_by_handle: dict[str, dict]) -> None:
    """Every reason an entry cannot be acted on, raised rather than skipped.

    ``front_matters_by_handle`` is this build's **full, reconciled** corpus —
    before the exclusion is applied, because the one check that carries the
    verdict needs the duplicate's own front matter as well as the survivor's.

    Each failure names what went stale and what to do about it, because an
    exclusion is the one curated fact whose silent survival removes a thesis
    from every count this repo publishes.
    """
    for index, entry in enumerate(entries):
        duplicate, keeper = entry["duplicate_handle"], entry["kept_handle"]
        where = f"entries[{index}] ({duplicate} -> {keeper})"

        if duplicate not in front_matters_by_handle:
            raise DuplicateThesisError(
                f"{where}: thesis {duplicate!r} is not in this corpus, so this entry "
                "excludes nothing — Estudo Geral withdrew or merged the duplicate "
                "record upstream, or the handle is a typo. Delete the entry from "
                "data/duplicate_theses.json; leaving it would hide a real harvest "
                "change behind an exclusion nobody re-read."
            )
        if keeper not in front_matters_by_handle:
            raise DuplicateThesisError(
                f"{where}: the SURVIVING thesis {keeper!r} is not in this corpus. This "
                "entry would stop deduplicating a thesis and start erasing one — the "
                "corpus would lose the work entirely. Either the survivor was withdrawn "
                "upstream (in which case the duplicate is now the only record of it and "
                "this entry must go), or the handle is a typo."
            )

        duplicate_fm = front_matters_by_handle[duplicate]
        keeper_fm = front_matters_by_handle[keeper]
        for field in entry["identical_fields"]:
            missing_from = [
                handle
                for handle, front_matter in ((duplicate, duplicate_fm), (keeper, keeper_fm))
                if field not in front_matter
            ]
            if missing_from:
                raise DuplicateThesisError(
                    f"{where}: front matter for {missing_from} no longer carries "
                    f"{field!r}, which this entry's evidence rests on. The records were "
                    "re-extracted or the harvester changed shape; re-read both and "
                    "update identical_fields in data/duplicate_theses.json."
                )
            if duplicate_fm[field] != keeper_fm[field]:
                raise DuplicateThesisError(
                    f"{where}: {field!r} no longer matches between the two records, and "
                    "it is one of the fields this entry's evidence rests on. The verdict "
                    "'one deposit, two records' is no longer the one a human reviewed — "
                    "re-read both records before this build can drop either."
                )


def excluded_handles(entries: list[dict]) -> frozenset[str]:
    """``{handle}`` — the records ``build()`` drops from the corpus.

    Call ``validate()`` first; this does not re-check, so that a caller cannot
    get a half-checked exclusion set by reaching for the cheaper function.
    """
    return frozenset(entry["duplicate_handle"] for entry in entries)


def write_table(conn, entries: list[dict]) -> int:
    """Replace ``duplicate_theses`` from ``entries``. Returns rows written.

    Written so the reason a handle is absent from ``theses`` is *queryable* and
    not only readable in git — "2690 ``.md`` files, 2689 theses" is a
    discrepancy anyone auditing the corpus will hit, and this table is the
    answer to it.

    Called BEFORE the ``theses`` inserts, because ``scraper/schema.sql``'s
    ``trg_no_excluded_thesis`` reads this table on every one of them. That is
    the same ordering fact ``multi_thesis_authors.write_table`` has, for the
    same reason, and it is stated in ``build()``'s docstring.

    Full replace, not upsert, for the reason all four siblings replace their own
    tables: it is a pure function of a committed file, and an exclusion somebody
    *removed* must not survive in the seed — least of all this one, where a
    leftover row would keep the backstop trigger refusing a thesis the file no
    longer excludes.

    Assumes the schema is already applied and does NOT commit — the caller owns
    the transaction.
    """
    conn.execute("DELETE FROM duplicate_theses")
    conn.executemany(
        "INSERT INTO duplicate_theses (duplicate_handle, kept_handle, source_url, evidence) "
        "VALUES (?,?,?,?)",
        sorted(
            (
                entry["duplicate_handle"],
                entry["kept_handle"],
                entry["source_url"],
                entry["evidence"],
            )
            for entry in entries
        ),
    )
    return len(entries)
