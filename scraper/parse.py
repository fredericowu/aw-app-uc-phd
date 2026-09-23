"""Pure parsing helpers: money and dates. No I/O, no network."""
import re

NBSP = "\xa0"


def normalize_ws(text):
    """Collapse NBSP and regular whitespace runs into single spaces, strip ends."""
    if text is None:
        return None
    text = text.replace(NBSP, " ")
    return re.sub(r"\s+", " ", text).strip()


_MONEY_RE = re.compile(
    r"([A-Z€$£]+)?\s*([\d][\d\s]*[.,]?\d*)\s*([A-Z€$£]+)?"
)


def parse_money(raw):
    """'€ 343 875.40' -> (343875.40, '€'). Returns (None, None) if unparseable.

    Thousands separator is a space (plain or non-breaking); decimal separator
    is a period. Never raises — a parse failure is a caller-visible None, not
    an exception, because a raw value can't be recovered once the field is
    reported as unparseable.
    """
    if raw is None:
        return None, None
    text = normalize_ws(raw)
    if not text:
        return None, None

    m = re.search(r"([€$£]|[A-Za-z]{2,4})?\s*([\d][\d ]*(?:\.\d+)?)\s*([€$£]|[A-Za-z]{2,4})?", text)
    if not m:
        return None, None
    currency = m.group(1) or m.group(3)
    number_raw = m.group(2)
    if number_raw is None:
        return None, None
    number_str = number_raw.replace(" ", "")
    try:
        amount = float(number_str)
    except ValueError:
        return None, None
    return amount, currency


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(raw):
    """'2026-01-01' -> '2026-01-01' (validated ISO date string) or None."""
    if raw is None:
        return None
    text = normalize_ws(raw)
    if not text:
        return None
    m = _DATE_RE.match(text)
    if not m:
        return None
    year, month, day = (int(g) for g in m.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return text


def split_list(raw, sep=","):
    """'a, b, c' -> ['a', 'b', 'c'], normalized and empty-filtered."""
    if not raw:
        return []
    parts = [normalize_ws(p) for p in raw.split(sep)]
    return [p for p in parts if p]


def split_partners(raw):
    """'A, B (Coordinator, Country), C' -> ['A', 'B (Coordinator, Country)', 'C'].

    partners_raw is free text, comma-separated, but a parenthesised note can
    itself contain a comma — e.g. "EXODUS S. A. (Coordinator, Greece), CSEM
    (Switzerland)" is 2 partners, not 3. A plain ``split_list`` would cut
    that note in two, so this tracks paren depth and only splits on
    top-level commas. An unbalanced '(' (seen once in the real data) just
    means nothing after it splits — best effort, nothing invented, same as
    every other free-text field this scraper parses.
    """
    if not raw:
        return []
    parts = []
    depth = 0
    current = []
    for ch in raw:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return [normalize_ws(p) for p in parts if normalize_ws(p)]


# classify_partner()'s vocabulary — multi-language "university" plus the
# generic institutional words that actually occur in the real partners_raw
# data (measured against all 636 distinct partner names split out of the
# 261/398 projects that have one; see docs comment on classify_partner).
# A keyword list, not a model, by design: "a reasonable heuristic based on
# the entity name/type... don't over-engineer this into an ML classification
# task" (the card this was built for).
_ACADEMIC_WORD_MARKERS = (
    "university", "universidade", "universidad", "università", "universita",
    "universität", "universitat", "universitet", "universiteit", "universiteti",
    "universitatea", "univerza", "univerzita", "univerzitet", "egyetem",
    "yliopisto", "ulikool", "sveuciliste",
    "instituto", "institute", "institut", "institution",
    "faculdade", "faculty", "faculté", "facultad",
    "politecnico", "politécnico", "polytechnic", "politecnica", "politécnica",
    "college", "colegio", "école", "escola",
    "hospital", "hospitais", "clinic", "clínica", "clinique",
    "academia", "academy",
    "laboratório", "laboratory", "laboratoire", "laboratorio",
    "fundação", "fundacion", "fundación",
    "research institute", "research institution", "research center",
    "research centre", "consiglio nazionale delle ricerche", "conselho",
    "consejo superior",
)

# Short acronyms only safe to match as a whole token — a substring check on
# "uc" would also hit "produce"/"structure"/... Sourced from acronyms that
# resolve to a full academic name elsewhere in the same partners_raw data
# (e.g. "CISUC/FCTUC (University of Coimbra)", "INESC TEC – INSTITUTO DE
# ENGENHARIA DE SISTEMAS E COMPUTADORES").
_ACADEMIC_TOKEN_MARKERS = frozenset({
    "uc", "cisuc", "fctuc", "feup", "fcul", "ist", "isec", "ipn", "inesc",
    "cnc", "isr", "cmuc", "icbr", "huc", "chuc", "ipo", "ibili", "iict",
    "mit", "eth", "kth", "agh",
})

_WORD_RE = re.compile(r"[^\W\d_]+")


def classify_partner(name):
    """'University of Coimbra' -> 'academic'; 'Sanofi' -> 'industry'.

    Not verified per partner. A company name with no legal-entity suffix
    (Sanofi, Thales, GSK, ...) falls to 'industry' by default because that
    is the common case in this data; an unmarked research institute (e.g.
    "CSEM") is the known false-negative this heuristic trades off for it.
    The caveat travels with the data — see sql/partners_breakdown.sql.
    """
    lowered = name.lower()
    if any(marker in lowered for marker in _ACADEMIC_WORD_MARKERS):
        return "academic"
    tokens = {t.lower() for t in _WORD_RE.findall(name)}
    if tokens & _ACADEMIC_TOKEN_MARKERS:
        return "academic"
    return "industry"
