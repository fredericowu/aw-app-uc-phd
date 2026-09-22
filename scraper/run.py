"""Entrypoint: `python -m scraper.run`.

Fetches the whole listing in one POST, writes a `scrape_targets` manifest
row per listing row BEFORE any detail fetch (so coverage is a query, not an
act of faith — DESIGN.md §4), then fetches each of the ~398 reachable
detail pages one at a time, 1.5s apart, with retry/backoff on 5xx/timeout.

One-shot script. No daemon, no incremental mode (explicitly out of scope).
"""
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import db
from .detail import parse_detail_page, project_fields
from .listing import LISTING_URL, USER_AGENT, ListingError, fetch_all_projects
from .parse import parse_date, parse_money

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "cisuc.sqlite3"
SLEEP_BETWEEN_DETAIL_FETCHES = 1.5
MAX_ATTEMPTS = 3


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def is_stub_url(url):
    return not url or url.rstrip("/") == LISTING_URL.rstrip("/")


def slug_from_url(url):
    return url.rstrip("/").rsplit("/", 1)[-1]


def fetch_detail_with_retry(session, url):
    """Returns (html_or_None, http_status_or_None, error_or_None)."""
    last_status = None
    last_error = None
    for attempt in range(MAX_ATTEMPTS):
        if attempt > 0:
            time.sleep(2 ** attempt)
        try:
            r = session.get(url, timeout=30)
        except requests.RequestException as exc:
            last_error = str(exc)
            continue
        last_status = r.status_code
        if r.status_code == 200:
            return r.text, r.status_code, None
        if 500 <= r.status_code < 600:
            last_error = f"HTTP {r.status_code}"
            continue
        # Non-5xx (e.g. 404) — retrying won't help.
        return None, r.status_code, f"HTTP {r.status_code}"
    return None, last_status, last_error


def upsert_stub(conn, run_id, title, url, listing_row, target_id):
    fields = {
        "title": title,
        "detail_url": None,
        "slug": None,
        "listing_details": listing_row.get("details"),
        "listing_scope": listing_row.get("scope"),
        "detail_fetched": 0,
        "detail_unavailable_reason": "no detail url published by site",
        "detail_http_status": None,
        "first_seen_at": now_iso(),
        "last_scraped_at": now_iso(),
    }
    db.upsert_project(conn, fields)
    db.update_scrape_target(conn, target_id, status="no_detail_url")


def upsert_success(conn, title, url, listing_row, raw_rows, parsed):
    total_amount, total_currency = parse_money(parsed["total_budget_raw"])
    cisuc_amount, cisuc_currency = parse_money(parsed["cisuc_budget_raw"])

    fields = {
        "title": title,
        "detail_url": url,
        "slug": slug_from_url(url),
        "scope": parsed["scope"],
        "synopsis": parsed["synopsis"],
        "funding_raw": parsed["funding_raw"],
        "partners_raw": parsed["partners_raw"],
        "keywords_raw": parsed["keywords_raw"],
        "total_budget_raw": parsed["total_budget_raw"],
        "total_budget_amount": total_amount,
        "total_budget_currency": total_currency,
        "cisuc_budget_raw": parsed["cisuc_budget_raw"],
        "cisuc_budget_amount": cisuc_amount,
        "cisuc_budget_currency": cisuc_currency,
        "start_date_raw": parsed["start_date_raw"],
        "start_date": parse_date(parsed["start_date_raw"]),
        "end_date_raw": parsed["end_date_raw"],
        "end_date": parse_date(parsed["end_date_raw"]),
        "listing_details": listing_row.get("details"),
        "listing_scope": listing_row.get("scope"),
        "detail_fetched": 1,
        "detail_unavailable_reason": None,
        "detail_http_status": 200,
        "first_seen_at": now_iso(),
        "last_scraped_at": now_iso(),
    }
    project_id = db.upsert_project(conn, fields)
    db.replace_fields_raw(conn, project_id, raw_rows)

    for code, name in parsed["research_groups"]:
        db.upsert_research_group(conn, code, name)
    db.replace_project_groups(conn, project_id, [code for code, _ in parsed["research_groups"]])

    people_rows = []
    if parsed["coordinator"]:
        slug, name = parsed["coordinator"]
        db.upsert_person(conn, slug, name)
        people_rows.append((slug, "coordinator", 0))
    for ordinal, (slug, name) in enumerate(parsed["researchers"]):
        db.upsert_person(conn, slug, name)
        people_rows.append((slug, "researcher", ordinal))
    db.replace_project_people(conn, project_id, people_rows)
    db.replace_project_keywords(conn, project_id, parsed["keywords"])


def upsert_failure(conn, title, url, listing_row, http_status, error):
    fields = {
        "title": title,
        "detail_url": url,
        "slug": slug_from_url(url),
        "listing_details": listing_row.get("details"),
        "listing_scope": listing_row.get("scope"),
        "detail_fetched": 0,
        "detail_unavailable_reason": f"fetch failed: {error}",
        "detail_http_status": http_status,
        "first_seen_at": now_iso(),
        "last_scraped_at": now_iso(),
    }
    db.upsert_project(conn, fields)


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(str(DB_PATH))
    db.apply_schema(conn)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    started_at = now_iso()
    print(f"[{started_at}] fetching listing from {LISTING_URL} ...")
    try:
        listing_rows, total_data = fetch_all_projects(session)
    except ListingError as exc:
        print(f"FATAL: listing fetch failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"listing: {len(listing_rows)} rows, site totalData={total_data}")

    run_id = db.start_scrape_run(conn, started_at)
    conn.commit()

    detail_ok = 0
    detail_failed = 0
    stub_count = 0

    for i, row in enumerate(listing_rows, start=1):
        title = row["title"]
        url = row["url"]
        target_id = db.create_scrape_target(conn, run_id, title, url)
        conn.commit()

        if is_stub_url(url):
            upsert_stub(conn, run_id, title, url, row, target_id)
            conn.commit()
            stub_count += 1
            print(f"[{i}/{len(listing_rows)}] STUB (no detail page): {title}")
            continue

        html, http_status, error = fetch_detail_with_retry(session, url)
        if html is not None:
            raw_rows = parse_detail_page(html)
            parsed = project_fields(raw_rows)
            upsert_success(conn, title, url, row, raw_rows, parsed)
            db.update_scrape_target(conn, target_id, status="ok", http_status=http_status)
            detail_ok += 1
            print(f"[{i}/{len(listing_rows)}] ok: {title}")
        else:
            upsert_failure(conn, title, url, row, http_status, error)
            db.update_scrape_target(conn, target_id, status="http_error", http_status=http_status, error=error)
            detail_failed += 1
            print(f"[{i}/{len(listing_rows)}] FAILED ({error}): {title}", file=sys.stderr)

        conn.commit()
        time.sleep(SLEEP_BETWEEN_DETAIL_FETCHES)

    finished_at = now_iso()
    notes = f"stubs={stub_count}"
    db.finish_scrape_run(conn, run_id, finished_at, total_data, len(listing_rows), detail_ok, detail_failed, notes)
    conn.commit()

    print(
        f"[{finished_at}] done. listing_rows={len(listing_rows)} "
        f"detail_ok={detail_ok} detail_failed={detail_failed} stubs={stub_count}"
    )
    if detail_failed:
        print(f"WARNING: {detail_failed} detail pages failed after retries — see scrape_targets.", file=sys.stderr)


if __name__ == "__main__":
    main()
