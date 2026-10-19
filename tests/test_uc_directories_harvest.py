"""scraper/uc_directories/ — the per-unit harvest suite.

Three classes of thing are tested here, and each one is a bug that was in the
code and got out only by reading the matcher's output for a name somebody
happened to know:

* **the card scope** (``parsers._card_of``). A document-order scan from each
  name marker picks up the NEXT card's photo link, because the photo anchor
  sits before its own name. That gave one professor another's per-person URL,
  which then deduplicated two different people onto one row.
* **the URL tripwire** (``run._name_compatible``). The SITE publishes a wrong
  per-person URL on at least one real card, so URL evidence is trusted but
  not blindly.
* **the loud floor** (``units.Unit.expected_min``). A page that changes shape
  must fail ITS unit, because a silently short pool narrows the candidate
  pool the identity matcher runs against.
"""
from __future__ import annotations

import sqlite3

import pytest

from scraper import db as db_mod
from scraper.uc_directories import fetch, parsers, run as run_mod
from scraper.uc_directories.units import FACULTY, Unit

#: Two cards in the shape the real UC CMS emits: the photo anchor comes
#: BEFORE the name span, which is the whole reason `_card_of` climbs instead
#: of scanning forward. Card 1 publishes no per-person link of its own.
UC_CMS_HTML = """
<div class="grid">
  <div class="flex items-start item" id="i1">
    <div class="w-16"><a href="mailto:one@uc.pt">photo</a></div>
    <div class="item-content">
      <div class="item-name"><span class="text-lg font-bold">Ana Primeira Silva</span></div>
      <div class="grid leading-snug"><p>Professora Auxiliar</p></div>
    </div>
  </div>
  <div class="flex items-start item" id="i2">
    <div class="w-16">
      <a href="https://www.ces.uc.pt/pt/ces/pessoas/investigadoras-es/beto-segundo">photo</a>
    </div>
    <div class="item-content">
      <div class="item-name"><span class="text-lg font-bold">Beto Segundo Costa</span></div>
      <div class="grid leading-snug"><p>Professor Catedratico</p></div>
      <div><a href="mailto:two@uc.pt">two@uc.pt</a></div>
    </div>
  </div>
</div>
"""

LISTING = "https://www.uc.pt/feuc/pessoas-e-servicos/docentes/"


def test_a_card_never_picks_up_the_next_cards_person_url():
    rows = parsers.parse("uc_cms", UC_CMS_HTML, LISTING)

    assert [r.name_as_published for r in rows] == ["Ana Primeira Silva", "Beto Segundo Costa"]
    # The bug: Ana used to be handed Beto's CES page, and the two then
    # deduplicated onto one slug whose name was whichever card was read last.
    assert rows[0].person_url is None
    assert rows[1].person_url.endswith("/beto-segundo")
    assert rows[0].role_as_published == "Professora Auxiliar"
    assert rows[0].email == "one@uc.pt"


def test_a_published_name_is_stripped_of_titles_shouting_and_invisible_marks():
    # FDUC prefixes every one of its 182 rows with "Doutor"/"Doutora", which
    # `_fits()` rule 2 would then reject for every thesis name in the corpus;
    # FCTUC/DCV shouts; FLUC and DCV both emit a leading U+FEFF.
    assert parsers.display_name("Doutora Maria João Antunes") == "Maria João Antunes"
    assert parsers.display_name("﻿ANA LUISA DOS SANTOS") == "Ana Luisa dos Santos"
    # CES publishes the comma form; `people.name` is a display name.
    assert parsers.display_name("Allegretti, Giovanni") == "Giovanni Allegretti"
    assert parsers.display_name("Almeida Cravo, Teresa") == "Teresa Almeida Cravo"


def test_a_person_url_is_compared_without_scheme_or_www():
    # FEUC links Boaventura's CES page as ces.uc.pt, CES publishes
    # www.ces.uc.pt. One page, and a verbatim comparison would see two people.
    assert parsers.canonical_person_url(
        "https://ces.uc.pt/pt/ces/pessoas/investigadoras-es/x/"
    ) == parsers.canonical_person_url(
        "http://www.ces.uc.pt/pt/ces/pessoas/investigadoras-es/x"
    )


@pytest.mark.parametrize(
    "a, b, compatible",
    [
        # The legitimate cross-source case this dedup exists for.
        ("Paula Abreu", "Maria Paula Abreu", True),
        # An initial counts, the same convention the matcher excuses.
        ("Neide P. Areia", "Neide Luísa Portela Areia", True),
        # The real site error: one URL, two different professors.
        ("Catarina Alexandra Neves Proença", "Daniel Gameiro Francisco", False),
    ],
)
def test_the_url_merge_tripwire(a, b, compatible):
    assert run_mod._name_compatible(a, b) is compatible


def test_a_short_parse_fails_its_own_unit_loudly(tmp_path):
    (tmp_path / "tiny.html").write_text(UC_CMS_HTML, encoding="utf-8")
    unit = Unit(
        source="tiny",
        unit_name="Tiny Faculty",
        kind=FACULTY,
        listing_url=LISTING,
        parser="uc_cms",
        expected_min=50,
        measured="2 cards, fixture",
    )

    with pytest.raises(run_mod.HarvestError) as excinfo:
        run_mod.harvest_unit(unit, fetch.build_session(), tmp_path, sleep=0)

    assert "below the expected_min floor of 50" in str(excinfo.value)
    assert "fix the parser rather than lowering the floor" in str(excinfo.value)


def _unit(source, expected_min=1):
    return Unit(
        source=source,
        unit_name=f"Unit {source.upper()}",
        kind=FACULTY,
        listing_url=f"https://www.uc.pt/{source}/docentes/",
        parser="uc_cms",
        expected_min=expected_min,
        measured="fixture",
    )


def test_slugs_live_in_a_disjoint_namespace_and_a_cisuc_collision_is_refused():
    listings = {"feuc": [parsers.Listing("Ada Lovelace", LISTING)]}
    rows, listing_rows, report = run_mod.resolve_identities(listings, cisuc_slugs={"ada"})

    assert list(rows) == ["uc--feuc--ada-lovelace"]
    assert report["slug_refusals"] == []

    # And the refusal fires if a CISUC row ever DOES hold a slug in this
    # namespace — unreachable by construction, checked anyway.
    rows, _listing_rows, report = run_mod.resolve_identities(
        listings, cisuc_slugs={"uc--feuc--ada-lovelace"}
    )
    assert rows == {}
    assert report["slug_refusals"] == [
        {"slug": "uc--feuc--ada-lovelace", "source": "feuc", "name": "Ada Lovelace"}
    ]


def test_two_units_publishing_one_person_url_become_one_slug_with_two_listings(tmp_path):
    url = "https://www.ces.uc.pt/pt/ces/pessoas/investigadoras-es/paula-abreu"
    harvested = {
        "feuc": [parsers.Listing("Maria Paula Abreu", LISTING, person_url=url)],
        "ces": [parsers.Listing("Abreu, Paula", "https://www.ces.uc.pt/pt/ces/pessoas", url)],
    }
    rows, listing_rows, report = run_mod.resolve_identities(harvested, cisuc_slugs=set())

    assert list(rows) == ["uc--feuc--maria-paula-abreu"]
    assert sorted(row[1] for row in listing_rows) == ["ces", "feuc"]
    assert [m["source"] for m in report["merged_by_person_url"]] == ["ces"]
    assert report["url_identity_conflicts"] == []


def test_two_units_publishing_one_url_for_two_people_stay_two_slugs():
    url = "https://www.ces.uc.pt/pt/ces/pessoas/investigadoras-es/daniel-francisco"
    harvested = {
        "feuc": [parsers.Listing("Catarina Alexandra Neves Proença", LISTING, person_url=url)],
        "ces": [parsers.Listing("Francisco, Daniel Gameiro", "https://www.ces.uc.pt", url)],
    }
    rows, _listing_rows, report = run_mod.resolve_identities(harvested, cisuc_slugs=set())

    assert len(rows) == 2
    assert report["merged_by_person_url"] == []
    assert len(report["url_identity_conflicts"]) == 1
    assert report["url_identity_conflicts"][0]["refused"]["source"] == "ces"


def test_the_same_name_in_two_units_is_reported_and_never_merged():
    harvested = {
        "fduc": [parsers.Listing("João Silva", "https://www.uc.pt/fduc/docencia/corpo-docente/")],
        "ffuc": [parsers.Listing("João Silva", "https://www.uc.pt/ffuc/corpo-docente/")],
    }
    rows, listing_rows, _report = run_mod.resolve_identities(harvested, cisuc_slugs=set())

    assert sorted(rows) == ["uc--fduc--joao-silva", "uc--ffuc--joao-silva"]
    suspects = run_mod.possible_duplicates(rows, listing_rows)
    assert [s["folded_name"] for s in suspects] == ["joao silva"]
    assert suspects[0]["sources"] == ["fduc", "ffuc"]


def test_an_incremental_run_adds_a_listing_instead_of_minting_a_second_slug(tmp_path):
    """Cross-unit dedup only sees the units of ONE run, so a second
    invocation has to be told what the database already holds — otherwise
    `--only ces` after a FEUC run mints a second Boaventura who then competes
    with the first as two candidates for his name."""
    url = "https://www.ces.uc.pt/pt/ces/pessoas/investigadoras-es/paula-abreu"
    known = {
        "by_person_url": {parsers.canonical_person_url(url): "uc--feuc--maria-paula-abreu"},
        "names": {"uc--feuc--maria-paula-abreu": "Maria Paula Abreu"},
    }
    harvested = {"ces": [parsers.Listing("Abreu, Paula", "https://www.ces.uc.pt", url)]}
    rows, listing_rows, report = run_mod.resolve_identities(harvested, set(), known)

    assert list(rows) == ["uc--feuc--maria-paula-abreu"]
    assert [row[1] for row in listing_rows] == ["ces"]
    assert len(report["merged_by_person_url"]) == 1


def test_the_harvest_writes_people_and_listings_and_is_additive(tmp_path):
    path = tmp_path / "harvest.sqlite3"
    conn = db_mod.connect(str(path))
    db_mod.apply_schema(conn)
    try:
        rows = {"uc--feuc--ada-lovelace": "Ada Lovelace"}
        listing_rows = [
            (
                "uc--feuc--ada-lovelace",
                "feuc",
                "Faculdade de Economia (FEUC)",
                LISTING,
                None,
                "Ada Lovelace",
                "Professora Auxiliar",
                "2026-10-19T00:00:00+00:00",
            )
        ]
        first = run_mod.write(conn, rows, listing_rows)
        second = run_mod.write(conn, rows, listing_rows)
    finally:
        conn.close()

    assert first["people_new"] == 1
    # Re-running is idempotent rather than duplicating: the PK is
    # (person_slug, source) and a re-harvest is this unit's current statement.
    assert second["people_new"] == 0
    con = sqlite3.connect(path)
    assert con.execute("SELECT COUNT(*) FROM directory_listings").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM people").fetchone()[0] == 1
    con.close()


def test_a_snapshot_is_used_per_unit_so_one_run_can_mix_snapshots_and_live(tmp_path):
    """`--snapshot-dir` is opportunistic, not a whole-run mode. Splitting the
    shielded units into their own invocation is what loses the cross-unit
    merges, so a unit with no snapshot has to fall through to the network in
    the SAME run."""
    (tmp_path / "feuc.html").write_text(UC_CMS_HTML, encoding="utf-8")
    seen = []
    fetched = []

    def on_page(url, html):
        seen.append(url)
        return 1

    class _Session:
        def get(self, url, timeout=None):
            fetched.append(url)
            return _Response()

    class _Response:
        status_code = 200
        text = UC_CMS_HTML

    assert fetch.fetch_unit_pages(_unit("feuc"), _Session(), on_page, tmp_path, sleep=0) == 1
    assert seen == ["https://www.uc.pt/feuc/docentes/"]
    assert fetched == []

    # Same run, same snapshot dir, a unit with no snapshot: it goes to the
    # network rather than failing, which is what keeps every unit in one run.
    assert fetch.fetch_unit_pages(_unit("fduc"), _Session(), on_page, tmp_path, sleep=0) == 1
    assert fetched == ["https://www.uc.pt/fduc/docentes/"]

    # And `snapshot_paths` itself is still strict, which is what a
    # snapshot-only invocation relies on.
    with pytest.raises(fetch.FetchError) as excinfo:
        fetch.snapshot_paths(_unit("fduc"), tmp_path)
    assert "no snapshot at" in str(excinfo.value)
