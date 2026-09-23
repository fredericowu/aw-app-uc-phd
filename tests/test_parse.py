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


def test_split_partners_rejoins_a_bare_legal_suffix_to_the_preceding_name():
    """"Company Name, S.A." is one partner — the comma before a bare
    legal-entity suffix is not a partner separator. Real repro from a QA
    rejection: 34/881 project_partners rows were bare-suffix fragments
    ("S.A.", "LDA.", "SA", "Lda"/"lda"/"LDA") masquerading as partners."""
    assert split_partners("ALTICE LABS, S.A.") == ["ALTICE LABS, S.A."]
    assert split_partners("CRON, LDA, XAVIER & FALCÃO , S.A.") == [
        "CRON, LDA",
        "XAVIER & FALCÃO, S.A.",
    ]
    assert split_partners("Cork Supply Portugal, SA, Instituto Pedro Nunes") == [
        "Cork Supply Portugal, SA",
        "Instituto Pedro Nunes",
    ]
    assert split_partners("Medrobots, lda, UC-DEEC") == ["Medrobots, lda", "UC-DEEC"]


def test_split_partners_rejoins_a_bare_suffix_followed_by_a_parenthetical_note():
    """"S.A. (LÍDER)" is still a bare suffix once its trailing note is
    stripped for the check — the note itself stays attached to the name."""
    raw = (
        "APS – ADMINISTRAÇÃO DOS PORTOS DE SINES E DO ALGARVE, S.A. (LÍDER), "
        "AMORIM CORK FLOORING, S.A."
    )
    assert split_partners(raw) == [
        "APS – ADMINISTRAÇÃO DOS PORTOS DE SINES E DO ALGARVE, S.A. (LÍDER)",
        "AMORIM CORK FLOORING, S.A.",
    ]


def test_split_partners_recognizes_less_common_legal_suffixes():
    """Not just S.A./Lda — S.L. (Spanish) and EPE (Portuguese public-entity
    suffix) are the same shape of bug, found by scanning real partners_raw
    segments rather than assuming the card's examples were exhaustive."""
    assert split_partners("DREAMGENICS, S.L.") == ["DREAMGENICS, S.L."]
    assert split_partners(
        "Instituto Português de Oncologia do Porto Francisco Gentil, EPE"
    ) == ["Instituto Português de Oncologia do Porto Francisco Gentil, EPE"]


def test_split_partners_does_not_merge_a_real_partner_that_just_starts_with_a_suffix_word():
    """A distinct partner whose own name isn't a bare suffix token must
    still split normally, even directly after another partner's suffix."""
    assert split_partners("Wavecom S.A., Sanofi") == ["Wavecom S.A.", "Sanofi"]


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
