"""The generic label-driven parser for a project detail page.

Scoped to `#project-container`. Two regions, two markups; key on the LABEL
TEXT, never on CSS class — the trap documented in DESIGN.md §4: most
right-column labels are `<p class="bold red m-0">`, but `End Date` is
`<p class="m-0 font-weight-semi-bold color-primary">`. Selecting on class
silently loses End Date and nothing downstream would notice.

Left column (`div.project-details > div`, direct children — the last block,
Researchers, has no `mb-24` class, so we can't select on that either):
    <p class="small bold">Label</p>
    <p class="small">Value</p> (repeated for multi-value fields)

Right column (`.col-md-9 > .row > .col-12 > div.mb-24`, direct children):
    first <p> = label, remaining <p>s = values.
    Synopsis is a distinct shape: `<h3>Synopsis</h3>` + `div.short_description`
    and is handled as its own branch.
    Empty blocks (zero <p> children, no <h3>) are unfilled slots — skipped.
"""
from bs4 import BeautifulSoup

from .parse import normalize_ws

SYNOPSIS_LABEL = "Synopsis"


def _text(el):
    return normalize_ws(el.get_text(separator=" ", strip=True))


def _href(el):
    a = el.find("a")
    return a.get("href") if a else None


def _left_column_rows(container):
    rows = []
    project_details = container.select_one(".project-details")
    if project_details is None:
        return rows
    for block in project_details.find_all("div", recursive=False):
        ps = block.find_all("p", recursive=False)
        if not ps:
            continue
        label = _text(ps[0])
        for ordinal, value_p in enumerate(ps[1:]):
            rows.append((label, ordinal, _text(value_p), _href(value_p)))
    return rows


def _right_column_rows(container):
    rows = []
    col9 = container.select_one(".col-md-9")
    if col9 is None:
        return rows
    row_el = col9.find("div", class_="row", recursive=False)
    if row_el is None:
        return rows
    col12 = row_el.find("div", class_="col-12", recursive=False)
    if col12 is None:
        return rows

    for block in col12.find_all("div", class_="mb-24", recursive=False):
        h3 = block.find("h3", recursive=False)
        if h3 is not None:
            label = _text(h3)
            short_desc = block.select_one(".short_description")
            if short_desc is None:
                continue
            paragraphs = [_text(p) for p in short_desc.find_all("p", recursive=False)]
            value_text = " ".join(p for p in paragraphs if p)
            if value_text:
                rows.append((label, 0, value_text, None))
            continue

        ps = block.find_all("p", recursive=False)
        if not ps:
            continue  # unfilled slot
        label = _text(ps[0])
        if len(ps) == 1:
            # Label with no value paragraph — record as-is, value None.
            rows.append((label, 0, None, None))
            continue
        for ordinal, value_p in enumerate(ps[1:]):
            rows.append((label, ordinal, _text(value_p), _href(value_p)))
    return rows


def parse_detail_page(html):
    """Returns [(label, ordinal, value_text, href_or_None), ...] in document order.

    Verbatim — no interpretation beyond whitespace normalization. This is
    what gets persisted into `project_fields_raw`.
    """
    soup = BeautifulSoup(html, "lxml")
    container = soup.select_one("#project-container")
    if container is None:
        return []
    return _left_column_rows(container) + _right_column_rows(container)


def slug_from_href(href):
    if not href:
        return None
    return href.rstrip("/").rsplit("/", 1)[-1]


def project_fields(raw_rows):
    """Project the raw (label, ordinal, value, href) rows into the known,
    typed shape. Labels are matched casefolded (`coordinator` is lowercase
    in the HTML — DESIGN.md risk #4). An unrecognized label is simply left
    out here; it still lives in `project_fields_raw` untouched.
    """
    fields = {
        "scope": None,
        "coordinator": None,       # (slug, name) or None
        "researchers": [],         # [(slug, name), ...]
        "research_groups": [],     # [(code, name), ...]
        "synopsis": None,
        "funding_raw": None,
        "total_budget_raw": None,
        "keywords_raw": None,
        "keywords": [],
        "start_date_raw": None,
        "partners_raw": None,
        "cisuc_budget_raw": None,
        "end_date_raw": None,
    }

    by_label = {}
    for label, ordinal, value_text, href in raw_rows:
        by_label.setdefault(label.casefold(), []).append((ordinal, value_text, href))

    def values(label):
        return sorted(by_label.get(label, []), key=lambda t: t[0])

    scope_rows = values("scope")
    if scope_rows:
        fields["scope"] = scope_rows[0][1]

    for _, name, href in values("research group"):
        code = slug_from_href(href)
        if code and name:
            fields["research_groups"].append((code, name))

    coord_rows = values("coordinator")
    if coord_rows:
        _, name, href = coord_rows[0]
        slug = slug_from_href(href)
        if slug and name:
            fields["coordinator"] = (slug, name)

    for _, name, href in values("researchers"):
        slug = slug_from_href(href)
        if slug and name:
            fields["researchers"].append((slug, name))

    synopsis_rows = values(SYNOPSIS_LABEL.casefold())
    if synopsis_rows:
        fields["synopsis"] = synopsis_rows[0][1]

    funding_rows = values("funding")
    if funding_rows:
        fields["funding_raw"] = funding_rows[0][1]

    budget_rows = values("total budget")
    if budget_rows:
        fields["total_budget_raw"] = budget_rows[0][1]

    keyword_rows = values("keywords")
    if keyword_rows:
        raw = keyword_rows[0][1]
        fields["keywords_raw"] = raw
        fields["keywords"] = [k.strip() for k in (raw or "").split(",") if k.strip()]

    start_rows = values("start date")
    if start_rows:
        fields["start_date_raw"] = start_rows[0][1]

    partners_rows = values("partners")
    if partners_rows:
        fields["partners_raw"] = partners_rows[0][1]

    cisuc_rows = values("cisuc budget")
    if cisuc_rows:
        fields["cisuc_budget_raw"] = cisuc_rows[0][1]

    end_rows = values("end date")
    if end_rows:
        fields["end_date_raw"] = end_rows[0][1]

    return fields
