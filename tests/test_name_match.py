"""analysis/name_match.py — the rules, and the golden fixture that proves them.

``docs/thesis-attribution.json`` is 50 name -> CISUC-person decisions a human
made by hand, with written reasoning on every hard one. It is the most
valuable artefact in this repo and it is **not** runtime input any more: it is
the fixture this test replays. If a rule change makes the matcher disagree
with that human on a single name, this file fails.

The point is that the matcher does not know any of those names. Nothing below
feeds it a lookup table, and nothing in ``analysis/name_match.py`` mentions a
person — the rules are general and the fixture is the evidence they reproduce
careful human judgement. Hardcoding a name to force this green would convert
a validation asset into a lookup table and destroy the only thing it proves.

**GREEN HERE DOES NOT MEAN A RULE CHANGE IS SAFE.** The fixture covers the 18
theses it documents; the corpus is 181. Two relaxations of ``_fits()`` were
implemented and measured against the real corpus and BOTH produced a
confidently wrong person — ``"Fonseca, José Carlos"`` -> ``Carlos M. Fonseca``
and ``"Cruz, Luís Alberto da Silva"`` -> ``Luís Silva`` — while every test in
this file stayed green, because neither name is in the 50. The fixture's role
is unchanged and it is still the most valuable artefact here, but it can no
longer police the matcher's rules on its own: a rule change has to be measured
against all 181 theses for new matches AND inspected for wrong ones.
``docs/thesis-attribution.md`` ("Two rejected relaxations") has both, with the
edge counts each bought.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from analysis import name_match
from analysis.name_match import AMBIGUOUS, CONFIDENT, EXACT, UNMATCHED, Person, match_name
from uc_phd_app import paths

# A small stand-in people table for the rule tests. Deliberately not the real
# 475 rows: a rule test that depends on production data stops being a rule
# test the next time the site is scraped.
PEOPLE = [
    Person("ada", "Ada Lovelace"),
    Person("alan", "Alan Turing"),
    Person("g-hopper", "G. Hopper"),
    Person("grace-h", "Grace Hopper"),
    Person("grace-h-1", "Grace Hopper"),
    Person("noether", "Emmy Noether"),
    Person("noether-b", "Bernhard Noether"),
    Person("proenca", "Ana Proença"),
]


def _real_people() -> list[Person]:
    with sqlite3.connect(f"file:{paths.seed_db_path()}?mode=ro", uri=True) as conn:
        return [Person(slug, name) for slug, name in conn.execute("SELECT slug, name FROM people")]


def _golden() -> dict:
    with open(paths.thesis_attribution_path(), encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# The golden fixture
# --------------------------------------------------------------------------


def test_the_matcher_reproduces_every_hand_verified_match():
    """Every name the human resolved must come back with exactly the same
    slug(s) — no more (a wrong extra candidate is a wrong answer), no fewer."""
    people = _real_people()
    disagreements = []
    for name, entry in _golden().items():
        if entry["status"] != "matched":
            continue
        result = match_name(name, people)
        got = {p.slug for p in result.people} if result.status in (EXACT, CONFIDENT) else set()
        want = {m["slug"] for m in entry["matches"]}
        if got != want:
            disagreements.append(f"{name!r}: human {sorted(want)}, matcher {result.status} {sorted(got)}")
    assert not disagreements, "matcher regressed against docs/thesis-attribution.json:\n" + "\n".join(
        disagreements
    )


def test_the_matcher_never_resolves_a_name_the_human_left_unattributed():
    """The other half, and the one that actually protects people: a name a
    human looked at and refused to resolve must not be silently resolved
    here. ``ambiguous`` is an acceptable answer, a slug is not."""
    people = _real_people()
    wrongly_resolved = []
    for name, entry in _golden().items():
        if entry["status"] != "unattributed":
            continue
        result = match_name(name, people)
        if result.status in (EXACT, CONFIDENT):
            wrongly_resolved.append(f"{name!r} -> {[p.slug for p in result.people]}")
    assert not wrongly_resolved, "matcher guessed where a human deliberately did not:\n" + "\n".join(
        wrongly_resolved
    )


# The 18 handles docs/thesis-attribution.json was hand-verified against,
# frozen at the corpus-widening card (2026-09-23, PO decision) — before that
# card grew estudo_geral/ to ~181 theses without a matching ~150-name manual
# re-verification. Each handle is a real, independently checkable thesis
# (https://estudogeral.uc.pt/handle/<handle>); the names below still come
# live from that thesis's own estudo_geral/*.md front matter, never typed by
# hand — only the *set of theses in scope* is pinned, not the names.
S1_2024_PLUS_HANDLES = {
    "10316/116663", "10316/117181", "10316/117187", "10316/117373", "10316/117599",
    "10316/118274", "10316/118279", "10316/118328", "10316/118421", "10316/118700",
    "10316/118764", "10316/118766", "10316/119251", "10316/119257", "10316/119336",
    "10316/119444", "10316/119468", "10316/119520",
}


def test_the_golden_fixture_still_covers_every_real_name():
    """The fixture must not drift out of sync with the corpus it documents —
    a new thesis adds names nobody has hand-checked, and this is what says so.

    Scoped to ``S1_2024_PLUS_HANDLES`` rather than the live ``estudo_geral/``
    directory: post-widening the corpus is ~181 theses and the golden fixture
    is still 18-theses/50-names, so comparing against the live corpus would
    fail on every one of the ~150 new, deliberately unverified names. This
    test's job is proving the matcher reproduces human judgement on the
    fixture it has, not that the live corpus is fully attributed (that gap is
    a separate, tracked follow-up — see the corpus-widening card).

    (Was ``test_the_committed_attribution_table_covers_every_real_thesis_name``
    in test_theses.py, before that module stopped reading the file.)
    """
    from analysis.build_thesis_facts import DEFAULT_ESTUDO_GERAL, load_front_matters

    front_matters = [
        fm for fm in load_front_matters(DEFAULT_ESTUDO_GERAL)
        if fm["handle"] in S1_2024_PLUS_HANDLES
    ]
    assert len(front_matters) == len(S1_2024_PLUS_HANDLES)

    all_names = set()
    for front_matter in front_matters:
        all_names.update(front_matter.get("authors") or [])
        all_names.update(front_matter.get("supervisors") or [])

    golden = _golden()
    assert all_names == set(golden), (
        f"missing from docs/thesis-attribution.json: {sorted(all_names - set(golden))}; "
        f"stale entries no thesis references: {sorted(set(golden) - all_names)}"
    )


def test_the_measured_tier_distribution_is_what_the_card_reports():
    """The honest number, asserted rather than claimed in a report: 50 distinct
    names, 43 resolved, 7 not. Change the rules and this moves — which is the
    point, because a rule that quietly resolves five more names should have to
    say so here first.

    **This moved once without a rule change, and that is why the numbers are
    not the ones the original card reported.** It was 36/14 against a ``people``
    table built only from scraped *project* pages; the people-directory card
    added CISUC's own 740-person directory as a second source
    (``scraper/people.py``), and 7 of the 14 then resolved against candidates
    that had simply never been in the pool. Nothing in ``name_match.py``
    changed. Each of the 7 was checked by hand against the thesis and the
    person's CISUC page before ``docs/thesis-attribution.json`` was moved to
    ``matched``, with the evidence in each entry's note — two of them
    (``Pereira, Tiago Oliveira``, ``Silva, Leonardo Soares e``) are two-token
    minimal-evidence shapes that were confirmed on the page's e-mail address
    carrying the exact middle name the display name drops, not on the name
    string. The widened pool also costs one: ``Moraes, Caroline Relva de`` now
    finds two directory rows for the same human and reads ``ambiguous``, which
    is the designed answer and still not a resolution.

    The split *within* the resolved set carries the earlier tier redefinition
    (pedro-martins card): most of these names resolve on a candidate whose
    tokens are a strict subset of the thesis name's, which used to read
    ``exact``/1.0 and now reads ``confident``/0.8. Same slug, honest tier —
    only the 7 ``exact`` are the token-set equality that tier now means."""
    people = _real_people()
    tiers = {EXACT: 0, CONFIDENT: 0, AMBIGUOUS: 0, UNMATCHED: 0}
    for name in _golden():
        tiers[match_name(name, people).status] += 1
    assert tiers == {EXACT: 7, CONFIDENT: 36, AMBIGUOUS: 1, UNMATCHED: 6}
    assert tiers[EXACT] + tiers[CONFIDENT] == 43


# --------------------------------------------------------------------------
# The rules themselves
# --------------------------------------------------------------------------


def test_folding_strips_diacritics_and_case():
    assert name_match.fold("Proença, JOÃO") == "proenca, joao"


def test_tokenizing_drops_portuguese_connectors():
    assert name_match.tokenize("Cunha, Paulo José Osório Rupino da") == (
        "cunha",
        "paulo",
        "jose",
        "osorio",
        "rupino",
    )


def test_a_name_without_a_comma_reads_as_western_order():
    assert name_match.split_thesis_name("Ada Lovelace") == (("lovelace",), ("ada",))


def test_an_exact_match_needs_no_tie_break():
    result = match_name("Lovelace, Ada", PEOPLE)
    assert result.status == EXACT
    assert [p.slug for p in result.people] == ["ada"]
    assert result.confidence == 1.0


# --------------------------------------------------------------------------
# The exact/confident boundary — redefined at the pedro-martins false merge
# --------------------------------------------------------------------------


def test_exact_means_the_token_sets_are_equal():
    """``exact`` is now a claim about both names, not just the candidate: the
    thesis name carries nothing the ``people`` row does not."""
    result = match_name("Lovelace, Ada", PEOPLE)
    assert result.status == EXACT
    assert result.confidence == 1.0
    assert "sets are equal" in result.note


def test_a_single_subset_candidate_is_confident_not_exact():
    """The pedro-martins case, on the synthetic table. "Ada Lovelace" fits
    "Lovelace, Ada Augusta Byron" and gets the slug — subset coverage is the
    rule 106 of the 190 names resolved in the real corpus rest on, so removing
    it would cost ~105 correct links to kill one wrong one. What it must not do
    is claim 1.0: "Augusta" and "Byron" are unverified, and some other
    Lovelace may own them."""
    result = match_name("Lovelace, Ada Augusta Byron", PEOPLE)
    assert result.status == CONFIDENT
    assert result.confidence == 0.8
    assert [p.slug for p in result.people] == ["ada"]
    assert "cannot confirm: augusta, byron" in result.note


def test_a_thesis_name_repeating_a_token_is_still_an_equality():
    """Generalised from "Pereira, Francisco Colunas Pereira da Câmara": the
    surname recurs among the given names, so a token *count* would read the
    repeat as an unconfirmed extra. Sets do not."""
    result = match_name("Noether, Emmy Noether", [Person("noether", "Emmy Noether")])
    assert result.status == EXACT


def test_a_surname_alone_is_not_a_match():
    """The rule that rejects "Nádia Patrícia da Silva Medeiros" for
    "Medeiros, Júlio Cordeiro": sharing a surname is not being the same
    person, so every candidate token has to be accounted for.

    "Emmy Noether" still resolves for "Noether, Amalie Emmy" — at ``confident``
    since the tier redefinition, because "Amalie" is a thesis given name the
    candidate does not carry. The rule under test is the second line."""
    assert match_name("Noether, Amalie Emmy", PEOPLE).status == CONFIDENT
    assert match_name("Noether, Wolfgang", PEOPLE).status == UNMATCHED


def test_a_given_name_collision_without_the_surname_is_rejected():
    """"Manuel Pedro" for "Abreu, Pedro Manuel …" — two common given names
    colliding, not a person. Both of the candidate's tokens appear in the
    thesis name; it still fails, because neither is the surname."""
    people = [Person("mp", "Manuel Pedro")]
    assert match_name("Abreu, Pedro Manuel Henriques", people).status == UNMATCHED


def test_a_single_letter_is_read_as_an_initial_of_a_given_name():
    result = match_name("Hopper, Grace Brewster", [PEOPLE[2]])
    assert result.status == CONFIDENT
    assert [p.slug for p in result.people] == ["g-hopper"]
    assert "initial" in result.note


def test_an_initial_only_abbreviates_a_given_name_never_a_surname():
    """Letting an initial stand in for a surname too would make almost
    anything match: "G." can abbreviate Grace, "H." must not abbreviate
    Hopper."""
    people = [Person("grace-h", "Grace H.")]
    assert match_name("Hopper, Grace", people).status == UNMATCHED


def test_duplicate_rows_for_one_human_are_all_kept():
    """people holds joao-bicker AND joao-bicker-1, both "João Bicker" — an
    inconsistency in the scraped source. There is no way to tell which row is
    the real one, so both are kept and downstream unions their groups."""
    result = match_name("Hopper, Grace Brewster", PEOPLE[3:5])
    assert result.status == CONFIDENT
    assert sorted(p.slug for p in result.people) == ["grace-h", "grace-h-1"]
    assert "duplicate" in result.note


def test_the_primary_given_name_breaks_a_tie_between_two_real_people():
    """Generalised from "Antunes, Nuno Manuel dos Santos": both "Nuno
    Antunes" and "Manuel Antunes" fit, and the first name after the comma is
    the one the person is actually called."""
    people = [Person("emmy", "Emmy Noether"), Person("bernhard", "Bernhard Noether")]
    result = match_name("Noether, Emmy Bernhard", people)
    assert result.status == CONFIDENT
    assert [p.slug for p in result.people] == ["emmy"]
    assert "primary given name" in result.note


def test_the_primary_given_name_is_only_a_tie_break_not_a_filter():
    """As a hard filter it would reject "Jorge Granjal" for "Granjal, António
    Jorge da Costa", where the one fitting candidate carries a middle name
    and not the first."""
    result = match_name("Turing, Christopher Alan", [Person("alan", "Alan Turing")])
    # Resolved, which is the point here; ``confident`` rather than ``exact``
    # because "Christopher" is unconfirmed — see the tier redefinition below.
    assert result.status == CONFIDENT
    assert [p.slug for p in result.people] == ["alan"]


def test_two_people_the_tie_break_cannot_separate_stay_ambiguous():
    """Surfaced with both candidates attached, never resolved by picking
    one — the outcome that keeps the matcher honest as the corpus grows."""
    people = [Person("a", "Emmy Noether"), Person("b", "Emmy Amalie Noether")]
    result = match_name("Noether, Emmy Amalie", people)
    assert result.status == AMBIGUOUS
    assert result.confidence == 0.4
    assert sorted(p.slug for p in result.people) == ["a", "b"]
    assert "not resolved" in result.note


@pytest.mark.parametrize("name", ["Unknown, Nobody At All", "Nobody"])
def test_nobody_matching_is_unmatched_not_an_error(name):
    result = match_name(name, PEOPLE)
    assert result.status == UNMATCHED
    assert result.people == ()
    assert result.confidence == 0.0


def test_an_empty_name_cannot_match_anything():
    """No surname token means no rule 1, and a blank name must never sweep up
    a candidate by having nothing to contradict."""
    assert match_name("", PEOPLE).status == UNMATCHED
