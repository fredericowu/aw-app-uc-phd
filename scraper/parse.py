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
