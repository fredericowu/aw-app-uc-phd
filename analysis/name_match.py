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
``exact``      one candidate fits and **the token sets are equal** — neither
               name carries a name the other does not.
``confident``  one answer, but a rule beyond token-set equality got there:
               the candidate's tokens are a strict *subset* of the thesis
               name's, a standard initial, a duplicate row in ``people``, a
               reviewed person alias (``analysis/person_aliases.py``), a
               reviewed full legal name (``analysis/person_full_names.py`` —
               those two are the only inputs here that are a human's decision
               rather than a name rule), or the primary-given-name tie-break
               below.
``ambiguous``  more than one person genuinely fits and no rule separates
               them. Surfaced with every candidate attached, never resolved
               by picking one.
``unmatched``  nobody fits.

Why subset coverage is ``confident`` and not ``exact``. ``_fits()`` accepts a
candidate whose tokens are a subset of the thesis name's, because the CISUC
form is routinely the shorter one ("Pedro Martins" for "Martins, Pedro Miguel
de Oliveira"). That rule is the workhorse — 106 of the 190 distinct names this
resolves rest on it (122 of 213 counting a name once per role, the grain
``sql/thesis_match_tiers.sql`` reports), and most are right — so it still
assigns a slug. What it
cannot do is *prove* identity: the thesis names the candidate does not carry
are unverified, and "Martins, Pedro" and "Martins, Pedro Miguel de Oliveira"
are two different people who both fit one CISUC row. The tier now says which
of the two it is, and ``analysis/build_thesis_facts.py`` enforces the corpus
invariant (one person authors at most one thesis) that catches the collision
the tier alone only describes.

The corpus is about to grow from 18 theses to 181, so the unmatched and
ambiguous rates will rise. That is the honest outcome, and the reason
``thesis_people.person_slug`` is nullable and ``name_raw`` is the key: a name
this module cannot resolve is preserved as a row, never dropped.

The one direction that runs backwards, and why it is gated
----------------------------------------------------------
``_fits()`` is asymmetric on purpose: the CISUC form is the *shorter* one.
CISUC sometimes publishes a person under a form that is not short but
**wrong-ended** — "António Dourado" for António Dourado Pereira Correia,
"Penousal Machado" for Fernando Jorge Penousal Martins Machado — and those
share no token with the thesis's surname at all, so rule 1 rejects them before
anything else gets a say. Relaxing rule 1 to fix that is measured-rejected
relaxation B (docs/thesis-attribution.md): it also produced "Cruz, Luís Alberto
da Silva" -> "Luís Silva", a confidently wrong person.

``_fits_full()`` is the mirror comparison — thesis name ⊆ the person's full
legal name — and it is safe *only* because of its gate: it never runs against
``people.name``, only against a full name a human reviewed, sourced and
recorded in ``data/person_full_names.json``. Luís Silva has no reviewed full
name carrying "cruz", so relaxation B's false match is structurally
unreachable rather than merely unlucky. A match that direction caps at
``confident`` — never ``exact``, even on token-set equality, because what it
agrees with is a reviewed declaration and not CISUC's published identity.

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
    distinct names, so ``name`` is not an identity (scraper/schema.sql).

    ``canonical`` is this row's ``person_aliases.to_slug`` when a human has
    ruled that CISUC lists this same human under another slug too, and
    ``None`` otherwise — which is every row by default, so nothing that
    constructs a ``Person`` from a name and a slug has to know this exists.
    ``full_name`` is this person's full legal name when a human has reviewed
    and sourced one (``person_full_names.full_name``), and ``None`` otherwise —
    which is all but a handful of rows. It is NOT a second display name:
    nothing renders it, and the only thing that reads it is ``_fits_full()``.

    Those two fields are the only things in this module that are not derived
    from the names: see ``analysis/person_aliases.py`` and
    ``analysis/person_full_names.py`` for why those decisions cannot be.

    ``source`` is which directory published this row — ``"cisuc"`` for every
    row of CISUC's own People directory, which is every row this module saw
    before UC's per-unit directories existed, and hence the default. It is
    read by exactly one rule (``_one_folded_name``) and by nothing else: it is
    NOT a trust level, it does not reach a tier, and no comparison in here
    weighs one source above another. See ``analysis/build_thesis_facts.py``
    for the two pools and why the pass order, not this field, is what decides
    which directory answers a name.
    """

    slug: str
    name: str
    canonical: str | None = None
    full_name: str | None = None
    source: str = "cisuc"


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


def _fits_full(
    thesis_tokens: tuple[str, ...],
    surname_tokens: tuple[str, ...],
    full_tokens: tuple[str, ...],
) -> bool:
    """Does the thesis name fit this person's **reviewed full legal name**?

    **This must be unreachable for a person with no ``person_full_names``
    row.** The gate is the design, not a precaution: ``match_name`` only calls
    this when ``Person.full_name`` is set, and ``full_name`` is only ever set
    from a human-reviewed, evidence-carrying entry. Run against
    ``people.name`` it would *be* measured-rejected relaxation B, with its
    confidently wrong "Cruz, Luís Alberto da Silva" -> "Luís Silva".

    The mirror of ``_fits()``, and asymmetric the other way for the same
    reason that one is: a full legal name is a *complete* form, like the
    thesis form and unlike CISUC's truncated display form, so here it is the
    thesis name that must be the subset.

    1. every surname token of the thesis name appears in the full name — the
       same rejection rule 1 of ``_fits()`` makes, and what stops an empty or
       surname-less name from sweeping up every reviewed person;
    2. every thesis token appears in the full name — "Correia, António Maria"
       is not António Dourado Pereira Correia, however much of him it carries
       — *or* is a single letter prefixing one of the full name's tokens, the
       ordinary initial convention ("Pereira, Francisco B." for Francisco
       **B**aptista Pereira).

    The initial escape hatch is **thesis-side only**, and that asymmetry is
    the rule, not an oversight. An entry-side letter stays a typo: a reviewed
    legal name is recorded in full by the human who sourced it, so "F." in a
    ``full_name`` means the entry was copied off the published short form
    instead of off a source, and excusing it would let this comparison run
    against what is effectively ``people.name`` — measured-rejected relaxation
    B. A letter in the *thesis* name is a different thing entirely: Estudo
    Geral did not choose to abbreviate, the deposited record did, and
    ``_fits()`` already excuses exactly that convention on the CISUC side
    (``_is_initial_of``). Mirroring it here stays inside the reviewed-full-
    names gate, so relaxation A's false match ("Fonseca, José Carlos" ->
    Carlos M. Fonseca) remains unreachable: "josé" is a word, not a letter,
    and it appears in no reviewed full name carrying "fonseca".
    """
    if not surname_tokens or not all(s in full_tokens for s in surname_tokens):
        return False
    return all(
        token in full_tokens
        or (len(token) == 1 and any(f.startswith(token) for f in full_tokens))
        for token in thesis_tokens
    )


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


def identity_of(person: Person) -> str:
    """The slug that stands for this row's HUMAN — its canonical when a
    reviewed alias says CISUC lists them twice, else its own slug."""
    return person.canonical or person.slug


def _one_folded_name(people: tuple[Person, ...]) -> bool:
    """Several rows of ONE directory, one folded name: that directory has
    duplicates of the same human (``joao-bicker`` / ``joao-bicker-1``), an
    inconsistency in the scraped source. There is no way to tell which row is
    "the" one, so all of them are kept and downstream unions their groups.

    **Requires a single ``source``, and that is a tightening.** The rule was
    written for CISUC listing one human twice on its own site, which is
    evidence about that site's data entry. Two *different* directories
    publishing the same folded name is not that evidence at all: "João Silva"
    on FDUC's Docentes page and "João Silva" on FFUC's is two people until a
    human says otherwise, and collapsing them would resolve a genuinely
    ambiguous name by picking an arbitrary slug — the one thing this module
    exists not to do.

    Withholding a collapse can only ever turn a ``confident`` into an
    ``ambiguous``; it can never create a match, so it buys zero edges (every
    edge bought by a rule change is a regression, not a win —
    ``docs/thesis-attribution.md``). On the legacy corpus it is a no-op by
    construction: every row there carries ``source="cisuc"``, so the new
    condition is satisfied by every candidate set the golden fixture covers.

    Cross-source pairs that ARE one human are merged the house way instead —
    a ``data/person_aliases.json`` verdict with evidence, which
    ``_one_canonical`` below already honours across sources.
    """
    return len({fold(p.name) for p in people}) == 1 and len({p.source for p in people}) == 1


def _one_canonical(people: tuple[Person, ...]) -> bool:
    """Several rows, one reviewed identity — the ``de x para`` case.

    Byte-equal names (above) only catch the duplicates CISUC happened to
    spell identically. "Jorge Sá Silva" (``jorge-silva``) and "Jorge Miguel
    Sa Silva" (``j-silva``) are one human published twice under two spellings,
    which no comparison of the two names can establish; a person did, against
    the two CISUC pages, and recorded it in ``data/person_aliases.json``.

    Requires EVERY candidate to share the one identity, not merely two of
    them: a third, genuinely different person who also fits the thesis name
    still makes the name ambiguous, and a rule that collapsed anyway would
    resolve them away.
    """
    return len({identity_of(p) for p in people}) == 1


def _same_person_twice(people: tuple[Person, ...]) -> bool:
    """One human under several ``people`` rows — by name, or by review."""
    return _one_folded_name(people) or _one_canonical(people)


def match_name(name_raw: str, people: list[Person] | tuple[Person, ...]) -> NameMatch:
    """Resolve one thesis name against ``people``. Pure: no I/O, no network."""
    thesis_tokens = tokenize(name_raw)
    surname_tokens, given_tokens = split_thesis_name(name_raw)
    primary_given = given_tokens[0] if given_tokens else ""
    surname_label = " ".join(surname_tokens).title()

    fitting: list[Person] = []
    fitted_on_full_name: set[Person] = set()
    used_initial = False
    for person in people:
        fits, initial = _fits(tokenize(person.name), thesis_tokens, surname_tokens, given_tokens)
        if fits:
            fitting.append(person)
            used_initial = used_initial or initial
            continue
        # Only now, and only for a person a human has reviewed. The display
        # name gets the first and ordinary say; the reviewed full name is the
        # second chance CISUC's own truncation makes necessary.
        if person.full_name and _fits_full(
            thesis_tokens, surname_tokens, tokenize(person.full_name)
        ):
            fitting.append(person)
            fitted_on_full_name.add(person)

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
        if candidates[0] in fitted_on_full_name:
            # Capped here, before the token-set-equality test below could call
            # it `exact`: equality with a reviewed full name is agreement with
            # a human's sourced declaration, not with what CISUC published.
            return NameMatch(
                name_raw,
                CONFIDENT,
                CONFIDENCE[CONFIDENT],
                candidates,
                f"{_quoted(candidates)} does not carry this surname, but "
                f'data/person_full_names.json records their full name as '
                f'"{candidates[0].full_name}" on reviewed evidence, and every '
                "token of the thesis name appears in it.",
            )
        if used_initial:
            return NameMatch(
                name_raw,
                CONFIDENT,
                CONFIDENCE[CONFIDENT],
                candidates,
                f"Matched {_quoted(candidates)} via a standard initial "
                "abbreviating one of the given names.",
            )
        candidate_tokens = tokenize(candidates[0].name)
        if set(candidate_tokens) == set(thesis_tokens):
            return NameMatch(
                name_raw,
                EXACT,
                CONFIDENCE[EXACT],
                candidates,
                f"{_quoted(candidates)} carries exactly the tokens of the thesis "
                f'name — the sets are equal and the surname "{surname_label}" '
                "matches.",
            )
        # Set comparison, not length: it also absorbs a thesis name that
        # repeats a token ("Pereira, Francisco Colunas Pereira da Câmara"),
        # which a count would read as an unconfirmed extra given name.
        uncorroborated = list(dict.fromkeys(t for t in thesis_tokens if t not in candidate_tokens))
        return NameMatch(
            name_raw,
            CONFIDENT,
            CONFIDENCE[CONFIDENT],
            candidates,
            f"Every token of {_quoted(candidates)} appears in the thesis name "
            f'and the surname "{surname_label}" matches, but the thesis carries '
            "given names the candidate cannot confirm: "
            f"{', '.join(uncorroborated)}.",
        )

    if _same_person_twice(candidates):
        if _one_folded_name(candidates):
            note = (
                f"people holds {len(candidates)} rows with the same name — "
                f"{_quoted(candidates)} — a duplicate in the scraped source, not "
                "two people. All of them are kept."
            )
        else:
            note = (
                f"CISUC lists this person under {len(candidates)} directory entries — "
                f"{_quoted(candidates)} — which data/person_aliases.json records as one "
                f"human on reviewed evidence, canonical "
                f"{identity_of(candidates[0])}. Resolved to that one identity."
            )
        return NameMatch(name_raw, CONFIDENT, CONFIDENCE[CONFIDENT], candidates, note)

    # Tie-broken on the tokens the fit was actually made against, which for a
    # reviewed full-name fit is the full name. Using the display name here
    # would weigh a truncated form against a complete one and let the
    # truncation win: "Machado, Fernando" would be tie-broken away from the
    # reviewed Penousal Machado onto any plain "Fernando Machado", on nothing
    # better than CISUC having dropped a given name. Two candidates that both
    # carry the primary given name is what ambiguous is for.
    preferred = tuple(
        p
        for p in candidates
        if _carries_primary_given(
            tokenize(p.full_name) if p in fitted_on_full_name else tokenize(p.name),
            primary_given,
        )
    )
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
