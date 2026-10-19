"""One parser per page SHAPE, not per unit.

The spike found the same few templates repeated across UC's estate, so the
registry names a shape and several units share it. Three shapes carry the
first wave:

``uc_cms``
    The current UC CMS person card. Whatever the surrounding template —
    FEUC's accordion, FLUC's A–Z grid, FDUC's rank sections, FCTUC/DCV's
    tables — the person's name is always ``<span class="text-lg font-bold">``,
    which is the one marker these templates DO share (a card class is not:
    FLUC's grid cell has none). Everything else about a person is read from
    the smallest ancestor of that span holding no other name — see
    ``_card_of``, and read its docstring before replacing it with a
    document-order scan, which is wrong here in a way that invents people.

``uc_cms_person_links``
    The CMS's filterable listing view (FPCEUC), which renders no cards at all
    server-side: the names arrive only as anchors to each person's own page,
    ``/<unit>/pessoas/<slug>/``. The anchor text is the name — except for the
    avatar anchor, which carries the person's initials and is dropped.

``ces``
    CES's own site: ``<a class="person-name" href="/pt/ces/pessoas/.../slug">``
    with the name in the **comma form** ("Allegretti, Giovanni").

``uc_legacy_table``
    The pre-CMS department pages still on the estate (FCTUC/DEEC): a table
    whose first cell is the name and which carries a ``mailto:`` per row.

Every parser returns ``list[Listing]`` and nothing else — no database, no
network, no identity decision. Slug minting, collision refusal and cross-unit
dedup all happen in ``run.py``, once, over the union of every unit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..parse import normalize_ws

#: Words that mark a line as an academic rank rather than a name, a unit or an
#: e-mail. Used only to pick which of the lines after a name is
#: ``role_as_published``, which is nullable — a miss costs a null, never a row.
_RANK_WORDS = (
    "professor",
    "professora",
    "investigador",
    "investigadora",
    "assistente",
    "leitor",
    "leitora",
    "docente",
    "monitor",
    "monitora",
    "diretor",
    "diretora",
    "subdiretor",
    "técnic",
    "especialista",
    "emérit",
    "jubilad",
    "aposentad",
    "convidad",
    "coordenador",
    "bolseir",
)

#: Hosts/paths that identify ONE human on the publishing side, in preference
#: order. ``run.py`` collapses two units' listings into one slug only when they
#: agree on one of these — never on a name. Ordered because a person can carry
#: several: the unit's own page is the most local statement of identity, and
#: CiênciaVitae/ORCID are the most stable ones.
_PERSON_URL_PATTERNS = (
    re.compile(r"^https?://(?:www\.)?uc\.pt/[a-z0-9\-]+(?:/[a-z0-9\-]+)*/pessoas/[^/]+/?$", re.I),
    re.compile(r"^https?://apps\.uc\.pt/mypage/faculty/[^/]+", re.I),
    re.compile(r"^https?://(?:www\.)?ces\.uc\.pt/[a-z]{2}/ces/pessoas/[a-z0-9\-]+/[^/]+/?$", re.I),
    # Both forms are live on these pages: FLUC publishes `/portal/<id>`,
    # FEUC publishes the bare `/<id>`, and they are the same record.
    re.compile(r"^https?://(?:www\.)?cienciavitae\.pt/(?:portal/)?[A-Z0-9]{4}-[A-Z0-9\-]+/?$", re.I),
    re.compile(r"^https?://orcid\.org/[0-9X\-]+/?$", re.I),
)

_EMAIL_RE = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")

#: A name that is really a section heading, a rank header or a UI control.
#: These templates put all three in the same visual register as a name.
_NOT_A_NAME = re.compile(
    r"^(?:[A-Z]|professores?|professoras?|docentes?|investigador|filtros?|pessoas|"
    r"corpo\s+docente|jubilados?|aposentados?|in\s+memoriam|contactos?)\b",
    re.I,
)


@dataclass(frozen=True)
class Listing:
    """One person as ONE unit publishes them. Pre-identity: no slug yet."""

    name_as_published: str
    listing_url: str
    person_url: str | None = None
    role_as_published: str | None = None
    email: str | None = None


def canonical_person_url(url: str | None) -> str | None:
    """A per-person URL reduced to the form two units can be compared on.

    Scheme and ``www.`` are dropped and the trailing slash normalised away,
    because FEUC links Boaventura's CES page as ``https://ces.uc.pt/pt/...``
    and CES's own listing publishes ``https://www.ces.uc.pt/pt/...``. Those
    are one page, and a dedup that compared them verbatim would see two
    people. The query and fragment go too: ``?lang=en`` is not an identity.
    """
    if not url:
        return None
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("", host, path, "", "")).lstrip("/") or None


def _is_person_url(url: str) -> int | None:
    """The index of the pattern this URL matches, or ``None``. The index IS
    the preference rank, so the caller sorts on it rather than re-stating the
    order."""
    for rank, pattern in enumerate(_PERSON_URL_PATTERNS):
        if pattern.match(url):
            return rank
    return None


def _pick_person_url(hrefs: list[str], listing_url: str) -> str | None:
    best: tuple[int, str] | None = None
    for href in hrefs:
        absolute = urljoin(listing_url, href)
        rank = _is_person_url(absolute)
        if rank is None:
            continue
        if best is None or rank < best[0]:
            best = (rank, absolute)
    return best[1] if best else None


def _looks_like_a_name(text: str) -> bool:
    """Two or more words, no digits, not a heading or a rank.

    A single word is never a staff name on these pages — it is "Filtros", a
    letter anchor or an initials badge — and requiring two is what keeps the
    document-order scan below from inventing people out of chrome.
    """
    if not text or len(text) > 120 or any(ch.isdigit() for ch in text):
        return False
    if _NOT_A_NAME.match(text) and len(text.split()) < 3:
        return False
    if any(word in text.lower() for word in _RANK_WORDS) and len(text.split()) <= 4:
        return False
    return len(text.split()) >= 2


#: Academic titles some units prefix onto the published name. FDUC publishes
#: every one of its 182 staff as "Doutor <name>" / "Doutora <name>", and
#: leaving it on is not cosmetic: `analysis/name_match.py`'s `_fits()` rule 2
#: requires EVERY candidate token to be accounted for by the thesis name, and
#: no Estudo Geral record says "doutor" — so a title on the candidate makes
#: the whole unit unmatchable rather than merely untidy.
_TITLE_PREFIX = re.compile(
    r"^(?:(?:doutor|doutora|dr|dra|prof|profa|professor|professora|mestre|eng|eng\.?º|enga|"
    r"arq|lic)\.?\s+)+",
    re.I,
)

#: Zero-width / byte-order marks. FLUC and FCTUC/DCV both publish names with a
#: leading U+FEFF, which `fold` happily carries into the slug and into the
#: token stream.
_INVISIBLE = re.compile(r"[﻿​‌‍⁠]")

#: Lowercase in a Portuguese name however the page shouts it. The same six
#: connectors `analysis/name_match.py` drops before comparing, plus the
#: Spanish/Italian ones CES's roster carries.
_PARTICLES = frozenset({"de", "da", "do", "dos", "das", "e", "del", "della", "di", "van", "von"})


def clean_published_name(name: str | None) -> str:
    """The published name with the page's own decorations removed.

    Three things, each measured against a real unit rather than guessed:
    invisible marks (FLUC, FCTUC/DCV), an academic-title prefix (FDUC, all
    182 rows), and SHOUTING (FCTUC/DCV publishes every name in caps). The
    verbatim string is still recorded in
    ``directory_listings.name_as_published``, so this is a display and
    matching decision and nothing is lost by it.
    """
    text = normalize_ws(_INVISIBLE.sub("", name or ""))
    if not text:
        return ""
    text = _TITLE_PREFIX.sub("", text).strip()
    if text and text == text.upper():
        text = " ".join(
            word.lower() if word.lower() in _PARTICLES else word.capitalize()
            for word in text.split()
        )
    return text


def _comma_to_display(name: str) -> str:
    """``"Allegretti, Giovanni"`` -> ``"Giovanni Allegretti"``.

    CES publishes the comma form; CISUC and the UC CMS publish the display
    form, and `people.name` is what the app renders. The token SET is
    unchanged by the flip, so `analysis/name_match.py` is indifferent to it —
    this is purely so a UC person does not render back-to-front next to a
    CISUC one. The verbatim published form is kept in
    ``directory_listings.name_as_published``, so nothing is lost.

    Only the FIRST comma splits: "Almeida Cravo, Teresa" is one surname and
    one given name, and a second comma ("Santos, Maria, Dr.") is left where it
    is rather than reordered on a guess.
    """
    surname, comma, given = name.partition(",")
    if not comma or not given.strip():
        return normalize_ws(name)
    return normalize_ws(f"{given} {surname}")


def display_name(name_as_published: str) -> str:
    """What `people.name` gets: the published form, cleaned and un-inverted."""
    return _comma_to_display(clean_published_name(name_as_published))


# ---------------------------------------------------------------- uc_cms


def _card_of(span, name_span_ids: set):
    """The smallest ancestor of this name span that holds NO OTHER name.

    This is how a "card" is found without knowing any template's class names,
    and it is not the obvious implementation. The obvious one — walk document
    order from each name span to the next and collect what you pass — is
    **wrong on this CMS**, and wrong in a way that produces a confident false
    identity rather than a visible failure: a card's photo anchor sits BEFORE
    its own name span, so a forward scan from card N runs past card N's own
    links and picks up card N+1's photo link. Measured on FEUC's roster, that
    gave "José Alberto Serra Ferreira Rodrigues Fuinhas" the per-person URL of
    the next card, whose person then deduplicated onto his slug and
    overwrote his name — one row claiming to be two different professors,
    found only by reading the matcher's output for a known name.

    Climbing instead is exact: ancestors grow monotonically, so the last one
    that still contains exactly one name is this person's own subtree.
    """
    card = span
    for parent in span.parents:
        if parent.name in (None, "body", "html", "[document]"):
            break
        if sum(1 for s in parent.find_all("span") if id(s) in name_span_ids) != 1:
            break
        card = parent
    return card


def _plain_name_tables(soup, listing_url: str) -> list[Listing]:
    """The one-column name tables the same CMS pages use for RETIRED staff.

    These carry no card, no photo, no e-mail and no rank — just a name per
    ``<td>`` — and the card parser below never sees them, because there is no
    ``span.text-lg.font-bold`` anywhere near. Missing them is not cosmetic:
    FLUC's "Professores Aposentados / Jubilados" table is 109 names, and
    "Irene Maria de Montezuma de Carvalho Mendes Vaquinhas" sits in it with a
    token set EXACTLY equal to the thesis form "Vaquinhas, Irene Maria de
    Montezuma de Carvalho Mendes" — five supervisor edges, free, and she was
    about to be classified as "never UC" instead.

    They are also the only place on UC's whole estate that names the class
    the Product Owner called the real ceiling: a supervisor who has retired
    appears on no current staff listing, and here a Faculty publishes one
    anyway.

    Deliberately narrow, because a one-column table is a generic shape: the
    table must have exactly one cell per row, the cell must hold no link and
    no e-mail (a real person row on these pages always has at least one), and
    the text must pass ``_looks_like_a_name``. A course list or an opening
    hours table fails all three.
    """
    out: list[Listing] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue
        cells = [row.find_all(["td", "th"]) for row in rows]
        if any(len(c) != 1 for c in cells):
            continue
        if table.find("a") or _EMAIL_RE.search(table.get_text(" ")):
            continue
        for (cell,) in cells:
            name = normalize_ws(cell.get_text())
            if _looks_like_a_name(clean_published_name(name)):
                out.append(Listing(name_as_published=name, listing_url=listing_url))
    return out


def parse_uc_cms(html: str, listing_url: str) -> list[Listing]:
    """The current UC CMS person card, scoped by ``_card_of``.

    Keying on ``span.text-lg.font-bold`` rather than a card class is what
    survives four template variants of the same CMS: a container-class
    approach reads 181 of FEUC's rows and 0 of FLUC's, because FLUC's grid
    cell carries no ``item`` class at all.
    """
    soup = BeautifulSoup(html, "html.parser")
    spans = [
        span
        for span in soup.find_all("span")
        if "text-lg" in (span.get("class") or []) and "font-bold" in (span.get("class") or [])
    ]
    name_span_ids = {id(span) for span in spans}

    out: list[Listing] = _plain_name_tables(soup, listing_url)
    for span in spans:
        name = normalize_ws(span.get_text())
        if not _looks_like_a_name(clean_published_name(name)):
            continue
        card = _card_of(span, name_span_ids)
        texts = [t for t in (normalize_ws(s) for s in card.stripped_strings) if t]
        hrefs = [a["href"] for a in card.find_all("a", href=True)]
        role = next(
            (
                normalize_ws(_INVISIBLE.sub("", t))
                for t in texts
                if any(word in t.lower() for word in _RANK_WORDS)
            ),
            None,
        )
        email = next(iter(_EMAIL_RE.findall(" ".join(texts))), None)
        if email is None:
            email = next(
                (h[len("mailto:") :] for h in hrefs if h.lower().startswith("mailto:")),
                None,
            )
        out.append(
            Listing(
                name_as_published=name,
                listing_url=listing_url,
                person_url=_pick_person_url(hrefs, listing_url),
                role_as_published=role,
                email=email,
            )
        )
    return out


# ------------------------------------------------- uc_cms_person_links


def parse_uc_cms_person_links(html: str, listing_url: str) -> list[Listing]:
    """The CMS's filterable listing view: names only as per-person anchors.

    Two anchors point at the same person page — an avatar one whose text is
    their initials, and the name one. ``_looks_like_a_name`` drops the former,
    and the dict below keeps the longer text when both survive, because the
    listing truncates long names in one place and not the other.
    """
    soup = BeautifulSoup(html, "html.parser")
    by_url: dict[str, str] = {}
    for anchor in soup.find_all("a", href=True):
        absolute = urljoin(listing_url, anchor["href"])
        if _is_person_url(absolute) != 0:
            continue
        name = normalize_ws(anchor.get_text())
        if not _looks_like_a_name(clean_published_name(name)):
            continue
        if len(name) > len(by_url.get(absolute, "")):
            by_url[absolute] = name
    return [
        Listing(name_as_published=name, listing_url=listing_url, person_url=url)
        for url, name in by_url.items()
    ]


# ------------------------------------------------------------------- ces


def parse_ces(html: str, listing_url: str) -> list[Listing]:
    """CES's own people list: ``a.person-name`` in the comma form."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[Listing] = []
    for anchor in soup.find_all("a", href=True):
        classes = anchor.get("class") or []
        if "person-name" not in classes:
            continue
        name = normalize_ws(anchor.get_text())
        if not name or len(name.split()) < 2:
            continue
        out.append(
            Listing(
                name_as_published=name,
                listing_url=listing_url,
                person_url=urljoin(listing_url, anchor["href"]),
            )
        )
    return out


# ------------------------------------------------------- uc_legacy_table


def parse_uc_legacy_table(html: str, listing_url: str) -> list[Listing]:
    """The pre-CMS department page: one table, name in the first cell.

    A row with no ``mailto:`` is not a person — on these pages that is the
    header row and the odd layout row — so the e-mail is the row filter here
    rather than a field that happens to be collected.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[Listing] = []
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        name = normalize_ws(cells[0].get_text())
        hrefs = [a["href"] for a in row.find_all("a", href=True)]
        email = next(
            (h[len("mailto:") :] for h in hrefs if h.lower().startswith("mailto:")),
            None,
        )
        if not email or not _looks_like_a_name(clean_published_name(name)):
            continue
        # These pages merge office/e-mail/phone into the second cell, so a
        # rank is only read when the cell is actually a rank — otherwise the
        # whole contact block would land in `role_as_published` and be
        # rendered as somebody's job title.
        role = normalize_ws(cells[1].get_text()) if len(cells) > 1 else None
        if role and ("@" in role or not any(word in role.lower() for word in _RANK_WORDS)):
            role = None
        out.append(
            Listing(
                name_as_published=name,
                listing_url=listing_url,
                person_url=_pick_person_url(hrefs, listing_url),
                role_as_published=role,
                email=email,
            )
        )
    return out


def next_url_ces(html: str, current_url: str) -> str | None:
    """CES's own "load more" link, which is the only way to page it.

    `?offset=N` on the listing URL is accepted and silently ignored — it
    serves page 1 forever, which is how a plausible-looking harvest reads 20
    of 200 researchers and reports success. The real pagination hangs off
    `a.jscroll-next`, pointing at a different endpoint
    (`/pt/person/<section-id>/content/0/query?offset=N`), so the only robust
    way to walk it is to follow the link the page itself publishes.
    """
    soup = BeautifulSoup(html, "html.parser")
    anchor = soup.find("a", class_="jscroll-next", href=True)
    return urljoin(current_url, anchor["href"]) if anchor else None


PARSERS = {
    "uc_cms": parse_uc_cms,
    "uc_cms_person_links": parse_uc_cms_person_links,
    "ces": parse_ces,
    "uc_legacy_table": parse_uc_legacy_table,
}

#: How a shape publishes "there is more". Only the shapes that need it appear;
#: `next_url` answers ``None`` for the rest, which is what ends a
#: ``paging="follow_next"`` section.
NEXT_URL = {"ces": next_url_ces}


def parse(parser: str, html: str, listing_url: str) -> list[Listing]:
    try:
        fn = PARSERS[parser]
    except KeyError:
        raise KeyError(f"no parser named {parser!r}; have {sorted(PARSERS)}") from None
    return fn(html, listing_url)


def next_url(parser: str, html: str, current_url: str) -> str | None:
    fn = NEXT_URL.get(parser)
    return fn(html, current_url) if fn else None
