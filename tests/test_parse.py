from scraper.parse import (
    classify_partner,
    normalize_ws,
    parse_date,
    parse_money,
    split_list,
    split_partners,
)


def test_parse_money_plain_space_thousands():
    amount, currency = parse_money("€ 343 875.40")
    assert amount == 343875.40
    assert currency == "€"


def test_parse_money_nbsp_thousands():
    amount, currency = parse_money("€ 343 875.40")
    assert amount == 343875.40
    assert currency == "€"


def test_parse_money_zero():
    amount, currency = parse_money("€ 0.00")
    assert amount == 0.0
    assert currency == "€"


def test_parse_money_unparseable():
    assert parse_money("") == (None, None)
    assert parse_money(None) == (None, None)
    assert parse_money("N/A") == (None, None)


def test_parse_date_valid():
    assert parse_date("2026-01-01") == "2026-01-01"


def test_parse_date_invalid():
    assert parse_date("not a date") is None
    assert parse_date(None) is None
    assert parse_date("") is None


def test_split_list():
    assert split_list("a, b,  c") == ["a", "b", "c"]
    assert split_list("") == []
    assert split_list(None) == []


def test_normalize_ws_collapses_nbsp():
    assert normalize_ws("343 875") == "343 875"
    assert normalize_ws("  a   b  ") == "a b"
    assert normalize_ws(None) is None


def test_split_partners_plain_comma_list():
    assert split_partners("Sanofi, GSK, Feedzai") == ["Sanofi", "GSK", "Feedzai"]
    assert split_partners("") == []
    assert split_partners(None) == []


def test_split_partners_keeps_a_comma_inside_parentheses_intact():
    """A plain comma split would cut "(Coordinator, Greece)" into two
    partners — the trap measured in 4/261 real partners_raw values."""
    raw = "EXODUS S. A. (Coordinator, Greece), CSEM (Switzerland)"
    assert split_partners(raw) == [
        "EXODUS S. A. (Coordinator, Greece)",
        "CSEM (Switzerland)",
    ]


def test_split_partners_survives_an_unbalanced_parenthesis():
    """Seen once in the real data ("UPV (EU Coordinator") — must not raise
    or drop everything after it, just split at what it can parse."""
    assert split_partners("UPV (EU Coordinator") == ["UPV (EU Coordinator"]
    assert split_partners("A (note, B (nested, C), D") == ["A (note, B (nested, C), D"]


def test_classify_partner_recognizes_academic_markers():
    for name in (
        "University of Coimbra",
        "Universidade de Coimbra",
        "Instituto Superior Técnico",
        "Hospital de São João",
        "Faculdade de Ciências e Tecnologia da Universidade de Coimbra (FCT/UC)",
        "CISUC",
        "INESC TEC",
        "UC (PT)",
    ):
        assert classify_partner(name) == "academic", name


def test_classify_partner_defaults_bare_company_names_to_industry():
    for name in ("Sanofi", "GSK", "Thales", "Philips", "Critical Software", "Ubiwhere Lda"):
        assert classify_partner(name) == "industry", name


def test_classify_partner_token_match_does_not_false_positive_on_substrings():
    """"UC" must match as a whole token, not as a substring of an unrelated
    word — a naive `"uc" in lowered` check would misclassify this."""
    assert classify_partner("Production Systems Inc") == "industry"
