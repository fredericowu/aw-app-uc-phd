from scraper.parse import parse_money, parse_date, split_list, normalize_ws


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
