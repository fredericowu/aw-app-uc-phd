"""Fetch CISUC's own People directory and upsert it into `people`.

    python -m scraper.people [path/to/cisuc.sqlite3]

Why this exists. Until this module, a name only entered `people` if it
appeared as a named coordinator/researcher on a *scraped project page*
(run.py's upsert_success). Thesis authors and supervisors are a wider
universe than that, so a real CISUC person who never coordinated a scraped
project could structurally never be matched — "Stork, Sven" was the reported
case, absent from `people` entirely while having his own directory page.

Same recipe as listing.py: the directory page is a Vue component that POSTs
back to the URL that served it (`axios.post('people', {...})`), Laravel
enforces CSRF, so GET the page in a session, scrape the csrf-token meta tag,
then POST with that token + the session's cookies.

**Additive, never destructive.** `db.upsert_person` is insert-or-update-name
with no delete, so the ~182 people who are in `people` from a project page
but have since dropped off CISUC's current roster survive by construction.
The counts returned by `sync_people` report that set rather than hiding it.

`filters` goes out EMPTY, not `{"membership": "all", ...}` like the projects
listing sends. The endpoint reads "all" as a literal value and answers 340 of
740 — measured, 2026-10-15. Empty is what the site's own first page sends and
what returns the full roster.

This module deliberately writes NO `scrape_runs` row. sql/coverage.sql reads
the latest run by id to render the scrape manifest, and a people-only row
carries none of the project counts that view is made of — it would read as a
scrape that found zero projects. Inside `python -m scraper.run` the real run
row's notes carry `people_dir=N` instead.
"""
import json
import re
import sys
import time
from pathlib import Path

import requests

from . import db
from .listing import USER_AGENT
from .parse import normalize_ws

PEOPLE_URL = "https://www.cisuc.uc.pt/en/people"

#: One POST covers the whole roster today (740 rows, totalPages=1 at
#: length=1000), exactly like the projects listing. The page-by-page fallback
#: below is still the thing that keeps that from being a silent assumption.
PAGE_LENGTH = 1000

#: Only ever paid in the fallback path, between the extra page POSTs. Same
#: courtesy as run.py's SLEEP_BETWEEN_DETAIL_FETCHES, smaller because a JSON
#: page is not a rendered detail page.
SLEEP_BETWEEN_PAGE_FETCHES = 1.0

_CSRF_RE = re.compile(r'name="csrf-token" content="([^"]+)"')

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "cisuc.sqlite3"


class PeopleError(RuntimeError):
    pass


def slug_from_url(url):
    """Same derivation run.py:36 uses for a project detail URL, plus one fix.

    The two sources disagree about escaping for the same person. A project
    page's HTML carries `href=".../people/Pedro%20Henriques%20Abreu"`, so
    detail.py's slug lands as `Pedro%20Henriques%20Abreu`; this endpoint hands
    back the *decoded* `.../people/Pedro Henriques Abreu`. Taking the tail
    verbatim would therefore file one person under two primary keys — one
    carrying their 8 projects, one carrying none — and the matcher would
    report them as a duplicate CISUC row forever.

    `people.slug` is already a `%20` key space (verified: every stored href
    encodes its spaces, none carries a literal one), so spaces are encoded
    back into it. Only the space is touched: nothing else differs between the
    two sources, and quoting more would invent a mismatch in the other
    direction for a slug like `Armin,Gharibi`.
    """
    return url.rstrip("/").rsplit("/", 1)[-1].replace(" ", "%20")


def _request_headers(token):
    return {
        "X-CSRF-TOKEN": token,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
        "Referer": PEOPLE_URL,
        "Content-Type": "application/json",
    }


def fetch_all_people(session, length=PAGE_LENGTH, sleep=SLEEP_BETWEEN_PAGE_FETCHES):
    """Returns (rows, total_data) — every directory entry, verbatim.

    Raises PeopleError loudly on anything unexpected, including a coverage
    shortfall: a silently short result here would quietly *narrow* the
    candidate pool the identity matcher runs against, which is worse than
    not running at all (DESIGN.md §6, "make the failure loud").
    """
    session.headers.setdefault("User-Agent", USER_AGENT)

    r = session.get(PEOPLE_URL, timeout=30)
    if r.status_code != 200:
        raise PeopleError(f"GET {PEOPLE_URL} returned {r.status_code}")

    m = _CSRF_RE.search(r.text)
    if not m:
        raise PeopleError("csrf-token meta tag not found on people page")
    headers = _request_headers(m.group(1))

    body = {"page": 1, "length": length, "search": "", "filters": {}, "sortBy": "name"}
    r2 = session.post(PEOPLE_URL, json=body, headers=headers, timeout=60)
    if r2.status_code != 200:
        raise PeopleError(f"POST {PEOPLE_URL} returned {r2.status_code}: {r2.text[:200]}")

    payload = r2.json()
    total_data = payload.get("totalData")
    data = payload.get("data", [])

    if total_data is None:
        raise PeopleError(f"people response missing totalData: {payload!r}"[:500])

    if len(data) == total_data:
        return data, total_data

    # `length` is not a documented contract — fall back to real page-by-page
    # pagination if the server caps a page (it serves 50/page to its own UI).
    all_rows = list(data)
    total_pages = payload.get("totalPages", 1)
    page = 2
    while len(all_rows) < total_data and page <= total_pages:
        if sleep:
            time.sleep(sleep)
        body["page"] = page
        r_page = session.post(PEOPLE_URL, json=body, headers=headers, timeout=60)
        if r_page.status_code != 200:
            raise PeopleError(f"POST page {page} returned {r_page.status_code}")
        all_rows.extend(r_page.json().get("data", []))
        page += 1

    if len(all_rows) != total_data:
        raise PeopleError(
            f"people coverage mismatch: got {len(all_rows)} rows, "
            f"site reports totalData={total_data}"
        )
    return all_rows, total_data


def person_rows(rows):
    """Returns (people, no_page_count) — (slug, name) pairs worth upserting.

    An entry whose URL carries no slug is a real person the directory lists
    without publishing a page for them (16 of 740, measured 2026-10-15).
    `people.slug` is the primary key, so there is no key to store them under
    — they are skipped and counted, the same call detail.py:150 already makes
    for a project-page person whose href yields no slug. Counted, not
    swallowed: `sync_people` reports the number.

    A missing *name* on an entry that does have a slug is a different thing —
    the payload changed shape — and raises.
    """
    people = []
    no_page = 0
    for row in rows:
        url = row.get("url") or ""
        slug = slug_from_url(url) if url else ""
        if not slug or slug == slug_from_url(PEOPLE_URL):
            no_page += 1
            continue
        name = normalize_ws(row.get("name"))
        if not name:
            raise PeopleError(f"directory entry has a slug but no name: {row!r}"[:500])
        people.append((slug, name))
    return people, no_page


def sync_people(conn, rows):
    """Upsert every directory entry into `people`. Returns the counts.

    `name_updated` and `absent_from_directory` are the two that need a human
    eye: the first is this source overwriting a name the project pages wrote
    (last writer wins, and run.py puts this step last), the second is the
    historical project-only people this source cannot see.
    """
    people, no_page = person_rows(rows)

    existing = {row[0]: row[1] for row in conn.execute("SELECT slug, name FROM people")}

    new = 0
    name_updated = 0
    unchanged = 0
    renames = []
    for slug, name in people:
        if slug not in existing:
            new += 1
        elif existing[slug] != name:
            name_updated += 1
            renames.append({"slug": slug, "was": existing[slug], "now": name})
        else:
            unchanged += 1
        db.upsert_person(conn, slug, name)
    conn.commit()

    directory_slugs = {slug for slug, _ in people}
    return {
        "fetched": len(rows),
        "with_page": len(people),
        "no_page_skipped": no_page,
        "new": new,
        "name_updated": name_updated,
        "unchanged": unchanged,
        "absent_from_directory": len(set(existing) - directory_slugs),
        "people_total_after": len(set(existing) | directory_slugs),
        "renames": renames,
    }


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    db_path = Path(argv[0]) if argv else DB_PATH

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    rows, total_data = fetch_all_people(session)

    conn = db.connect(str(db_path))
    try:
        db.apply_schema(conn)
        counts = sync_people(conn, rows)
    finally:
        conn.close()

    counts["site_total_data"] = total_data
    print(json.dumps(counts, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
