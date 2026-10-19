"""The committed registry: which UC units are in the candidate pool.

Curated, not discovered. Crawling uc.pt for pages that look like staff
listings would turn "which units are in the pool" into a scrape artifact
nobody reviews; a registry makes it a reviewable diff. Units do not churn.

`expected_min` is the honesty mechanism, exactly `scraper/people.py`'s
coverage check: a parse yielding fewer rows than the floor raises for that
unit instead of silently narrowing the matcher's candidate pool. The floors
are set BELOW the count measured at the first manual look, which is recorded
in `measured` on every entry — that is what lets the next person tell page
drift (a few rows either way) from breakage (a parser that now reads nothing).

`needs_browser_cookie` records a fact about the site, not a preference:
`www.uc.pt` sits behind BunnyCDN's JavaScript challenge (`cdn-challenge: true`,
`errorcode: 112`) and 403s plain `requests` on every path. One browser pass
mints a `bunny_shield` cookie, which `fetch.py` then reuses — see its
docstring for the two ways to supply it, and `--snapshot-dir` for the offline
fallback when neither is available.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Faculty, department or research centre. Recorded rather than derived: a
#: reader of `directory_listings` should be able to tell "the whole Faculty of
#: Law" from "one FCTUC department" without knowing UC's org chart.
FACULTY = "faculty"
DEPARTMENT = "department"
CENTRE = "centre"


@dataclass(frozen=True)
class Unit:
    """One harvestable directory.

    ``listing_url`` is the page a human opens to check a match against, and it
    is what lands in ``directory_listings.listing_url``. ``extra_paths`` are
    the *other* pages of the same directory (CES splits its people across a
    dozen sections); they are fetched and parsed identically, but the citable
    URL recorded against a person is the page they were actually read off.

    ``paging`` is how the unit serves a long list:

    * ``none``   — one page carries everything (FEUC: 181 rows, 687 kB).
    * ``page``   — ``?page=N``, 1-based, stop on the first page that yields
      no new names (the UC CMS's own listing views).
    * ``follow_next`` — follow the "load more" link the page itself
      publishes, which is the only thing that pages CES (its listing URL
      accepts ``?offset=N`` and ignores it — see ``fetch._next_url``).
    """

    source: str
    unit_name: str
    kind: str
    listing_url: str
    parser: str
    expected_min: int
    measured: str
    extra_paths: tuple[str, ...] = ()
    paging: str = "none"
    max_pages: int = 40
    needs_browser_cookie: bool = False


#: CES publishes its people in sections rather than as one roster. These are
#: the RESEARCHER sections plus `in-memoriam`, which is the only page on UC's
#: whole estate that names a dead supervisor — exactly the class the leftover
#: classifier (`analysis/classify_unmatched_supervisors.py`) has to count
#: separately rather than fold into "never UC".
#:
#: Two sections are deliberately NOT here. `doutorandas-os` and `alumni` are
#: doctoral students and former doctoral students, and the Product Owner's
#: fence is explicit: a PhD student is not staff, authors are not matched
#: against a staff directory, and admitting students into the identity space
#: invites exactly the staff/student name collisions this corpus fears.
#: `funcionarias-os` is administrative staff, who supervise no theses — every
#: row in the pool is a potential competitor for a common surname, so a
#: section that can only add competitors is left out.
_CES_SECTIONS = (
    "https://www.ces.uc.pt/pt/ces/pessoas/investigadoras-es",
    "https://www.ces.uc.pt/pt/ces/pessoas/investigadoras-es-colaboradoras-es",
    "https://www.ces.uc.pt/pt/ces/pessoas/investigadoras-es-em-pos-doutoramento",
    "https://www.ces.uc.pt/pt/ces/pessoas/investigadoras-es-juniores",
    "https://www.ces.uc.pt/pt/ces/pessoas/investigadoras-es-em-situacao-de-licenca",
    "https://www.ces.uc.pt/pt/ces/pessoas/investigadoras-es-visitantes",
    "https://www.ces.uc.pt/pt/ces/pessoas/in-memoriam",
)


UNITS: tuple[Unit, ...] = (
    # ---------------------------------------------------------------- faculties
    Unit(
        source="feuc",
        unit_name="Faculdade de Economia (FEUC)",
        kind=FACULTY,
        listing_url="https://www.uc.pt/feuc/pessoas-e-servicos/docentes/",
        parser="uc_cms",
        expected_min=150,
        measured="181 name cards, 2026-10-18",
        needs_browser_cookie=True,
    ),
    Unit(
        source="fduc",
        unit_name="Faculdade de Direito (FDUC)",
        kind=FACULTY,
        listing_url="https://www.uc.pt/fduc/docencia/corpo-docente/",
        parser="uc_cms",
        expected_min=150,
        measured="182 name cards, 2026-10-18",
        needs_browser_cookie=True,
    ),
    Unit(
        source="fluc",
        unit_name="Faculdade de Letras (FLUC)",
        kind=FACULTY,
        listing_url="https://www.uc.pt/fluc/quem-somos/pessoas/docentes/",
        parser="uc_cms",
        expected_min=320,
        measured="364 = 254 name cards (careers + invited) + 110 retired, 2026-10-19",
        needs_browser_cookie=True,
    ),
    Unit(
        source="fpce",
        unit_name="Faculdade de Psicologia e de Ciências da Educação (FPCEUC)",
        kind=FACULTY,
        listing_url="https://www.uc.pt/fpce/pessoas/",
        parser="uc_cms_person_links",
        expected_min=120,
        measured="9 pages x 24 person links, 207 distinct, 2026-10-19",
        paging="page",
        max_pages=15,
        needs_browser_cookie=True,
    ),
    Unit(
        source="ffuc",
        unit_name="Faculdade de Farmácia (FFUC)",
        kind=FACULTY,
        # NOT `/ffuc/people/`, which exists, answers 200, and renders an empty
        # filter shell: the roster lives under the statutes section. A
        # plausible-looking URL that serves no people is how a unit gets
        # "harvested" at zero rows, which is what `expected_min` is for.
        listing_url="https://www.uc.pt/ffuc/a-faculdade/estatutos-e-organizacao/corpo-docente/",
        parser="uc_cms",
        expected_min=90,
        measured="110 name cards, 2026-10-19",
        needs_browser_cookie=True,
    ),
    # --------------------------------------------------------------- departments
    # FCTUC publishes nothing at faculty level — its staff live on twelve
    # department pages, each its own site generation. These two are the ones
    # the corpus actually touches outside CISUC's own roster; the rest are a
    # registry diff away, which is the point of the registry.
    Unit(
        source="fctuc-dcv",
        unit_name="FCTUC — Departamento de Ciências da Vida",
        kind=DEPARTMENT,
        listing_url="https://www.uc.pt/fctuc/dcv/pessoas/docentes/",
        parser="uc_cms",
        expected_min=55,
        measured="67 name cards, 2026-10-18",
        needs_browser_cookie=True,
    ),
    Unit(
        source="fctuc-deec",
        unit_name="FCTUC — Departamento de Engenharia Eletrotécnica e de Computadores",
        kind=DEPARTMENT,
        listing_url="https://www.uc.pt/fctuc/deec/pessoas/docentes",
        parser="uc_legacy_table",
        expected_min=30,
        measured="41 table rows, 2026-10-18",
        needs_browser_cookie=True,
    ),
    # ------------------------------------------------------------------- centres
    Unit(
        source="ces",
        unit_name="Centro de Estudos Sociais (CES)",
        kind=CENTRE,
        listing_url=_CES_SECTIONS[0],
        parser="ces",
        expected_min=200,
        measured="7 sections, 20 per page, followed via a.jscroll-next, 2026-10-18",
        extra_paths=_CES_SECTIONS[1:],
        paging="follow_next",
        max_pages=30,
    ),
)


def by_source(source: str) -> Unit:
    for unit in UNITS:
        if unit.source == source:
            return unit
    raise KeyError(f"no unit registered under source {source!r}")


def sources() -> tuple[str, ...]:
    return tuple(unit.source for unit in UNITS)
