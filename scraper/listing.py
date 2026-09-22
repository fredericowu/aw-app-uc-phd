"""Fetch the full project listing via the site's own JSON endpoint.

The listing page is a Vue 2 component that POSTs back to the same URL that
serves the page (`axios.post('projects', {...})`). Laravel enforces CSRF, so
the recipe is: GET the page in a session, scrape the csrf-token meta tag,
then POST with that token + the session's cookies. See DESIGN.md §0.
"""
import re

LISTING_URL = "https://www.cisuc.uc.pt/en/projects"

USER_AGENT = (
    "uc-dei-phd-scraper/0.1 (+https://github.com/tekflox; "
    "one-shot personal research read for Frederico Wu, UC DEI/CISUC PhD work; "
    "contact via the linked GitHub account)"
)

_CSRF_RE = re.compile(r'name="csrf-token" content="([^"]+)"')


class ListingError(RuntimeError):
    pass


def fetch_all_projects(session, length=1000):
    """Returns the full list of {title, url, details, scope} dicts.

    Raises ListingError loudly on anything unexpected — a silent empty
    result here would produce a green exit with zero rows (see DESIGN.md
    §6: "make the failure loud").
    """
    session.headers.setdefault("User-Agent", USER_AGENT)

    r = session.get(LISTING_URL, timeout=30)
    if r.status_code != 200:
        raise ListingError(f"GET {LISTING_URL} returned {r.status_code}")

    m = _CSRF_RE.search(r.text)
    if not m:
        raise ListingError("csrf-token meta tag not found on listing page")
    token = m.group(1)

    headers = {
        "X-CSRF-TOKEN": token,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
        "Referer": LISTING_URL,
        "Content-Type": "application/json",
    }
    body = {
        "page": 1,
        "length": length,
        "search": "",
        "filters": {"scope": "all", "status": "all", "research-group": "all"},
        "sortBy": "scope",
    }
    r2 = session.post(LISTING_URL, json=body, headers=headers, timeout=60)
    if r2.status_code != 200:
        raise ListingError(f"POST {LISTING_URL} returned {r2.status_code}: {r2.text[:200]}")

    payload = r2.json()
    total_data = payload.get("totalData")
    data = payload.get("data", [])

    if total_data is None:
        raise ListingError(f"listing response missing totalData: {payload!r}"[:500])

    if len(data) == total_data:
        return data, total_data

    # length:1000 is not a documented contract (DESIGN.md risk #7) — fall
    # back to real page-by-page pagination if the server ever caps a page.
    all_rows = list(data)
    total_pages = payload.get("totalPages", 1)
    page = 2
    while len(all_rows) < total_data and page <= total_pages:
        body["page"] = page
        r_page = session.post(LISTING_URL, json=body, headers=headers, timeout=60)
        if r_page.status_code != 200:
            raise ListingError(f"POST page {page} returned {r_page.status_code}")
        page_payload = r_page.json()
        all_rows.extend(page_payload.get("data", []))
        page += 1

    if len(all_rows) != total_data:
        raise ListingError(
            f"listing coverage mismatch: got {len(all_rows)} rows, site reports totalData={total_data}"
        )
    return all_rows, total_data
