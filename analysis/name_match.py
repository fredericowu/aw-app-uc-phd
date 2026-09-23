"""Thesis name -> CISUC ``people`` row, deterministically.

Estudo Geral writes an author/supervisor as ``"Surname, Given Names"`` in
full; ``people.name`` holds whatever CISUC's own site published, which is
usually shorter and sometimes abbreviated (``"F. Amilcar Cardoso"``). Joining
the two is the identity spine every downstream feature needs, so it happens
**once, here, offline** — not four times, differently, in four features.

This module is the machine-readable statement of the method
``docs/thesis-attribution.md`` §"Matching method" describes and
``docs/thesis-attribution.json`` recorded the results of by hand. That file
is now this module's **golden fixture** (``tests/test_name_match.py``): every
name a human resolved must come back out of here with the same slugs, or the
suite fails. Nothing below knows a single one of those names — the rules are
general, and the fixture is what proves they reproduce a careful human.

The four tiers, and why ``ambiguous`` is not a failure
-----------------------------------------------------
``exact``      one candidate fits on whole tokens alone.
``confident``  one answer, but a rule beyond whole-token equality got there:
               a standard initial, a duplicate row in ``people``, or the
               primary-given-name tie-break below.
``ambiguous``  more than one person genuinely fits and no rule separates
               them. Surfaced with every candidate attached, never resolved
               by picking one.
``unmatched``  nobody fits.

The corpus is about to grow from 18 theses to 181, so the unmatched and
ambiguous rates will rise. That is the honest outcome, and the reason
``thesis_people.person_slug`` is nullable and ``name_raw`` is the key: a name
this module cannot resolve is preserved as a row, never dropped.

What this deliberately does NOT do — carried verbatim from the hand method:
no edit distance, no similarity threshold, no substring matching, no
transliteration. Two near-misses in the real data (``r-silva`` displayed as
"Rodrigo Tertulino"; "João Braz Simões" vs "…Brás") stay unmatched exactly
because of that, and both are cheaper to leave visible than to guess wrong.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: Portuguese name connectors, dropped from both sides before comparing.
#: ``docs/thesis-attribution.md`` names exactly these six; the list is not
#: widened speculatively, because every addition silently loosens matching on
#: names nobody has looked at.
CONNECTORS = frozenset({"de", "da", "do", "dos", "das", "e"})

EXACT = "exact"
CONFIDENT = "confident"
AMBIGUOUS = "ambiguous"
UNMATCHED = "unmatched"

#: Ordinal, not probabilistic — a rank the UI and downstream queries can sort
#: and threshold on. Nothing here estimates a likelihood, and a number that
#: looked like one would invite exactly that misreading.
CONFIDENCE = {EXACT: 1.0, CONFIDENT: 0.8, AMBIGUOUS: 0.4, UNMATCHED: 0.0}

_NON_WORD = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Person:
    """One row of ``people``. Keyed on ``slug``: 475 rows carry only 472
    distinct names, so ``name`` is not an identity (scraper/schema.sql)."""

    slug: str
    name: str


@dataclass(frozen=True)
class NameMatch:
    """What this module concluded about one raw name, and why."""

    name_raw: str
    status: str
    confidence: float
    people: tuple[Person, ...]
    note: str


def fold(text: str) -> str:
    """Lowercase, diacritics stripped. ``"Proença"`` -> ``"proenca"``."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def tokenize(text: str) -> tuple[str, ...]:
    """Folded word tokens, connectors dropped, order preserved."""
    return tuple(t for t in _NON_WORD.split(fold(text)) if t and t not in CONNECTORS)


def split_thesis_name(name_raw: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``"Surname, Given Names"`` -> ``(surname_tokens, given_tokens)``.

    Estudo Geral always writes the comma form. A name without one is read as
    Western order (last token is the surname) rather than rejected, so a
    future source with a different convention degrades to a worse match
    instead of a crash.
    """
    surname_part, comma, given_part = name_raw.partition(",")
    if not comma:
        tokens = tokenize(name_raw)
        return tokens[-1:], tokens[:-1]
    return tokenize(surname_part), tokenize(given_part)


def _is_initial_of(token: str, given_tokens: tuple[str, ...]) -> bool:
    """A single letter in ``people.name`` standing in for a given name.

    Restricted to the *given* names on purpose: ``"F. Amilcar Cardoso"``
    abbreviates "Fernando", and letting an initial stand for a surname token
    too would match on almost nothing.
    """
    return len(token) == 1 and any(g.startswith(token) for g in given_tokens)


def _fits(
    candidate_tokens: tuple[str, ...],
    thesis_tokens: tuple[str, ...],
    surname_tokens: tuple[str, ...],
    given_tokens: tuple[str, ...],
) -> tuple[bool, bool]:
    """Does this ``people`` row fit the thesis name? -> ``(fits, used_initial)``

    Two conditions, both from the hand method:

    1. every surname token appears in the candidate — this is what rejects
       "Manuel Pedro" for "Abreu, Pedro Manuel Henriques da Cunha", a
       coincidental collision on two common given names;
    2. every candidate token is accounted for by the thesis name — this is
       what rejects "Nádia Patrícia da Silva Medeiros" for "Medeiros, Júlio
       Cordeiro", who merely shares a surname.

    Asymmetric by design: the thesis form carries every name a person has,
    the CISUC form carries a subset, never the other way round.
    """
    if not surname_tokens or not all(s in candidate_tokens for s in surname_tokens):
        return False, False
    used_initial = False
    for token in candidate_tokens:
        if token in thesis_tokens:
            continue
        if _is_initial_of(token, given_tokens):
            used_initial = True
            continue
        return False, False
    return True, used_initial


def _carries_primary_given(candidate_tokens: tuple[str, ...], primary: str) -> bool:
    """Does the candidate carry the thesis's *first* given name?

    The tie-break, generalised from the one the human wrote down for
    "Antunes, Nuno Manuel dos Santos": both "Nuno Antunes" and "Manuel
    Antunes" fit the two rules above, but only one of them carries the name
    the person is actually called — the first token after the comma. A middle
    name shared with a different real person is not identity.

    Only ever applied to break a tie. As a hard filter it would wrongly
    reject "Jorge Granjal" for "Granjal, António Jorge da Costa", where the
    single fitting candidate carries a middle name and not the first.

    A thesis name with no given part at all (``primary`` empty) separates
    nobody: both tests below are false for every candidate, which leaves the
    tie unbroken and the name ambiguous. That is the right answer.
    """
    return primary in candidate_tokens or any(
        len(t) == 1 and primary.startswith(t) for t in candidate_tokens
    )


def _quoted(people: tuple[Person, ...]) -> str:
    return ", ".join(f'"{p.name}" ({p.slug})' for p in people)


def _same_person_twice(people: tuple[Person, ...]) -> bool:
    """Several rows, one folded name: ``people`` has duplicates of the same
    human (``joao-bicker`` / ``joao-bicker-1``), an inconsistency in the
    scraped source. There is no way to tell which row is "the" one, so all
    of them are kept and downstream unions their groups."""
    return len({fold(p.name) for p in people}) == 1


def match_name(name_raw: str, people: list[Person] | tuple[Person, ...]) -> NameMatch:
    """Resolve one thesis name against ``people``. Pure: no I/O, no network."""
    thesis_tokens = tokenize(name_raw)
    surname_tokens, given_tokens = split_thesis_name(name_raw)
    primary_given = given_tokens[0] if given_tokens else ""
    surname_label = " ".join(surname_tokens).title()

    fitting: list[Person] = []
    used_initial = False
    for person in people:
        fits, initial = _fits(tokenize(person.name), thesis_tokens, surname_tokens, given_tokens)
        if fits:
            fitting.append(person)
            used_initial = used_initial or initial

    if not fitting:
        return NameMatch(
            name_raw,
            UNMATCHED,
            CONFIDENCE[UNMATCHED],
            (),
            f'No row in people carries the surname "{surname_label}" with every '
            "other name token accounted for.",
        )

    candidates = tuple(fitting)
    if len(candidates) == 1:
        if used_initial:
            return NameMatch(
                name_raw,
                CONFIDENT,
                CONFIDENCE[CONFIDENT],
                candidates,
                f"Matched {_quoted(candidates)} via a standard initial "
                "abbreviating one of the given names.",
            )
        return NameMatch(
            name_raw,
            EXACT,
            CONFIDENCE[EXACT],
            candidates,
            f"Every token of {_quoted(candidates)} appears in the thesis name, "
            f'and the surname "{surname_label}" matches.',
        )

    if _same_person_twice(candidates):
        return NameMatch(
            name_raw,
            CONFIDENT,
            CONFIDENCE[CONFIDENT],
            candidates,
            f"people holds {len(candidates)} rows with the same name — "
            f"{_quoted(candidates)} — a duplicate in the scraped source, not "
            "two people. All of them are kept.",
        )

    preferred = tuple(p for p in candidates if _carries_primary_given(tokenize(p.name), primary_given))
    if preferred and (len(preferred) == 1 or _same_person_twice(preferred)):
        rejected = tuple(p for p in candidates if p not in preferred)
        return NameMatch(
            name_raw,
            CONFIDENT,
            CONFIDENCE[CONFIDENT],
            preferred,
            f'{len(candidates)} rows share the surname "{surname_label}"; resolved '
            f'to {_quoted(preferred)} on the primary given name "{primary_given.title()}" '
            f"(the first after the comma). {_quoted(rejected)} carries it only as a "
            "middle name, shared coincidentally.",
        )

    return NameMatch(
        name_raw,
        AMBIGUOUS,
        CONFIDENCE[AMBIGUOUS],
        candidates,
        f'{len(candidates)} rows fit and the primary given name "{primary_given.title()}" '
        f"does not separate them: {_quoted(candidates)}. Surfaced, not resolved.",
    )
