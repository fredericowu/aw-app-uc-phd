from pathlib import Path

from scraper.detail import parse_detail_page, project_fields, slug_from_href

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_faiser_baseline_all_fields_present():
    rows = parse_detail_page(load("faiser.html"))
    fields = project_fields(rows)

    assert fields["scope"] == "International"
    assert fields["research_groups"] == [("NCS", "Networks, Communications and Security")]
    assert fields["coordinator"] == ("marilia-curado", "Marilia Curado")
    assert ("david-abreu", "David Perez Abreu") in fields["researchers"]
    assert len(fields["researchers"]) == 3
    assert "SAGIN" in fields["synopsis"]
    assert fields["funding_raw"] == "Macao SAR Government - Macao Science and Technology Development Fund"
    assert fields["total_budget_raw"] == "€ 343 875.40"
    assert fields["cisuc_budget_raw"] == "€ 127 125.84"
    assert fields["start_date_raw"] == "2026-01-01"
    assert fields["partners_raw"] == "Macao Polytechnic University, Universidade Estadual de Campinas (UNICAMP)"
    assert fields["keywords_raw"] is None


def test_end_date_survives_the_different_css_class():
    """End Date's label <p> has a different class from every other
    right-column label (`font-weight-semi-bold color-primary` vs
    `bold red`). A class-based selector would silently drop it — this
    parser keys on structural position (first <p> = label) instead.
    """
    for fixture in ("faiser.html", "multiobjective.html", "atmosphere.html", "s3p.html"):
        rows = parse_detail_page(load(fixture))
        fields = project_fields(rows)
        assert fields["end_date_raw"] is not None, f"End Date missing in {fixture}"

    fields = project_fields(parse_detail_page(load("faiser.html")))
    assert fields["end_date_raw"] == "2028-12-31"


def test_multi_research_group_page():
    rows = parse_detail_page(load("multiobjective.html"))
    fields = project_fields(rows)

    codes = {code for code, _ in fields["research_groups"]}
    assert codes == {"AC", "NCS"}
    assert fields["coordinator"] == ("carlos-fonseca", "Carlos M. Fonseca")
    assert len(fields["researchers"]) == 5
    # This page has no Synopsis block at all — must not crash, must be None.
    assert fields["synopsis"] is None


def test_page_missing_cisuc_budget_and_keywords():
    """s3p.html has Partners but no CISUC budget and no Keywords block —
    the parser must leave those NULL rather than erroring or misaligning
    the fixed-position slots.
    """
    rows = parse_detail_page(load("s3p.html"))
    fields = project_fields(rows)

    assert fields["cisuc_budget_raw"] is None
    assert fields["keywords_raw"] is None
    # Fields that ARE present on this page must still come through.
    assert fields["partners_raw"] == "CISUC, PT Inovação"
    assert fields["funding_raw"] == "PT Inovação"
    assert fields["end_date_raw"] == "2009-02-28"


def test_page_missing_partners():
    rows = parse_detail_page(load("atmosphere.html"))
    fields = project_fields(rows)
    assert fields["partners_raw"] is None
    # And it must not have leaked a neighboring field's value into it.
    assert fields["total_budget_raw"] == "€ 0.00"


def test_keywords_field_not_in_any_named_spec_is_still_captured():
    """Keywords appears on ~70% of live pages but is in no spec anyone was
    handed. The label-driven parser must catch it anyway.
    """
    rows = parse_detail_page(load("atmosphere.html"))
    fields = project_fields(rows)

    assert fields["keywords_raw"] == "trustworthiness, cloud computing, self-adaptive systems"
    assert fields["keywords"] == ["trustworthiness", "cloud computing", "self-adaptive systems"]
    assert fields["partners_raw"] is None


def test_unknown_label_lands_in_raw_rows_even_if_not_projected():
    rows = parse_detail_page(load("atmosphere.html"))
    labels = {label.casefold() for label, _, _, _ in rows}
    assert "keywords" in labels


def test_coordinator_label_is_lowercase_in_html_but_matched_casefolded():
    rows = parse_detail_page(load("faiser.html"))
    raw_labels = [label for label, _, _, _ in rows]
    assert "coordinator" in raw_labels  # lowercase, as rendered
    fields = project_fields(rows)
    assert fields["coordinator"] is not None


def test_slug_from_href():
    assert slug_from_href("https://www.cisuc.uc.pt/en/people/marilia-curado") == "marilia-curado"
    assert slug_from_href("https://www.cisuc.uc.pt/NCS") == "NCS"
    assert slug_from_href(None) is None


def test_double_parse_is_stable_and_does_not_duplicate_rows():
    """Parsing the same page twice must produce identical output — this is
    the parser-level half of the idempotency guarantee; db.py's
    replace_fields_raw (delete-then-insert per project) is the other half.
    """
    html = load("faiser.html")
    assert parse_detail_page(html) == parse_detail_page(html)
