"""scraper/people.py — CISUC's People directory as a second source for `people`.

Two things here are worth asserting rather than assuming, and both are about
*not losing people*:

* the fetch must either cover the whole roster or fail loudly — a silently
  short directory narrows the candidate pool `analysis/name_match.py` runs
  against, which produces confidently-unmatched real people rather than an
  error anyone would notice;
* the sync must never drop a person it cannot see. ~182 rows in the committed
  `people` table came from a project page and are no longer on CISUC's
  current roster; an upsert keeps them by construction, and the preservation
  test below is what says so if that ever becomes a replace.

No network: every test drives a fake session that answers the real payload
shape (`{totalData, totalPages, data:[{name, slug, url, ...}]}`).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scraper import db
from scraper.people import PEOPLE_URL, PeopleError, fetch_all_people, person_rows, sync_people

SCHEMA = Path(__file__).resolve().parent.parent / "scraper" / "schema.sql"

PAGE_HTML = '<html><head><meta name="csrf-token" content="tok123"></head></html>'


def entry(slug, name=None):
    """A directory entry in the shape the live endpoint really returns."""
    return {
        "name": name or slug.replace("-", " ").title(),
        "slug": slug,
        "photo": "https://www.cisuc.uc.pt/images/default-avatar.svg",
        "url": f"https://www.cisuc.uc.pt/people/{slug}",
        "membership": "Integrated PhD Student",
        "research_acronym": "SSE",
        "formerMember": "active",
    }


class FakeResponse:
    def __init__(self, status_code=200, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    """Answers the GET with a page carrying a csrf-token, and each POST with
    the next queued payload. Records the bodies so the tests can assert what
    was actually asked for."""

    def __init__(self, payloads, page_status=200, page_text=PAGE_HTML, post_status=200):
        self.headers: dict = {}
        self._payloads = list(payloads)
        self._page_status = page_status
        self._page_text = page_text
        self._post_status = post_status
        self.posted_bodies: list = []
        self.posted_headers: list = []

    def get(self, url, timeout=None):
        assert url == PEOPLE_URL
        return FakeResponse(status_code=self._page_status, text=self._page_text)

    def post(self, url, json=None, headers=None, timeout=None):
        assert url == PEOPLE_URL
        # A copy: the fetcher reuses and mutates one body dict across pages,
        # so recording the reference would record only the last page's number.
        self.posted_bodies.append(dict(json))
        self.posted_headers.append(headers)
        if self._post_status != 200:
            return FakeResponse(status_code=self._post_status, text="nope")
        return FakeResponse(payload=self._payloads.pop(0))


@pytest.fixture()
def people_db(tmp_path):
    """An empty database with the real schema, nothing else."""
    path = tmp_path / "people.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()
    return db.connect(str(path))


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------


def test_one_page_that_covers_total_data_is_the_whole_fetch():
    """What the live endpoint actually does at length=1000: 740 rows,
    totalPages=1, one POST."""
    rows = [entry(f"p{i}") for i in range(740)]
    session = FakeSession([{"totalData": 740, "totalPages": 1, "data": rows}])

    got, total = fetch_all_people(session)

    assert total == 740
    assert len(got) == 740
    assert len(session.posted_bodies) == 1


def test_the_csrf_token_and_session_headers_go_out_on_the_post():
    session = FakeSession([{"totalData": 1, "totalPages": 1, "data": [entry("ada")]}])

    fetch_all_people(session)

    headers = session.posted_headers[0]
    assert headers["X-CSRF-TOKEN"] == "tok123"
    assert headers["X-Requested-With"] == "XMLHttpRequest"
    assert headers["Referer"] == PEOPLE_URL


def test_filters_go_out_empty_rather_than_all():
    """The endpoint reads `{"membership": "all"}` as a literal and answers 340
    of 740. Empty filters is the full roster — asserted because the sibling
    listing.py sends "all" and copying it here would silently halve the pool."""
    session = FakeSession([{"totalData": 1, "totalPages": 1, "data": [entry("ada")]}])

    fetch_all_people(session)

    assert session.posted_bodies[0]["filters"] == {}


def test_a_capped_page_falls_back_to_real_pagination():
    """The hot path if the server ever caps `length` the way it caps its own
    UI's 50/page: three pages walked, every row kept, in order."""
    pages = [
        {"totalData": 7, "totalPages": 3, "data": [entry(f"p{i}") for i in range(3)]},
        {"totalData": 7, "totalPages": 3, "data": [entry(f"p{i}") for i in range(3, 6)]},
        {"totalData": 7, "totalPages": 3, "data": [entry("p6")]},
    ]
    session = FakeSession(pages)

    got, total = fetch_all_people(session, sleep=0)

    assert total == 7
    assert [r["slug"] for r in got] == [f"p{i}" for i in range(7)]
    assert [b["page"] for b in session.posted_bodies] == [1, 2, 3]


def test_a_coverage_shortfall_raises_rather_than_returning_a_short_roster():
    """The failure that matters: 5 rows delivered against totalData=7 and the
    pages exhausted. Returning 5 would quietly shrink the candidate pool."""
    pages = [
        {"totalData": 7, "totalPages": 2, "data": [entry(f"p{i}") for i in range(3)]},
        {"totalData": 7, "totalPages": 2, "data": [entry("p3"), entry("p4")]},
    ]
    session = FakeSession(pages)

    with pytest.raises(PeopleError, match="coverage mismatch: got 5 rows.*totalData=7"):
        fetch_all_people(session, sleep=0)


def test_a_missing_total_data_raises():
    session = FakeSession([{"totalPages": 1, "data": [entry("ada")]}])

    with pytest.raises(PeopleError, match="missing totalData"):
        fetch_all_people(session)


def test_a_page_without_a_csrf_token_raises():
    session = FakeSession([], page_text="<html><head></head></html>")

    with pytest.raises(PeopleError, match="csrf-token meta tag not found"):
        fetch_all_people(session)


def test_a_non_200_page_raises():
    session = FakeSession([], page_status=503)

    with pytest.raises(PeopleError, match="GET .* returned 503"):
        fetch_all_people(session)


def test_a_non_200_post_raises():
    session = FakeSession([], post_status=419)

    with pytest.raises(PeopleError, match="POST .* returned 419"):
        fetch_all_people(session)


# --------------------------------------------------------------------------
# Slug derivation
# --------------------------------------------------------------------------


def test_the_slug_comes_off_the_person_url():
    rows, no_page = person_rows([entry("sven-stork", "Sven Stork")])

    assert rows == [("sven-stork", "Sven Stork")]
    assert no_page == 0


def test_a_trailing_slash_does_not_become_an_empty_slug():
    row = entry("ada")
    row["url"] = "https://www.cisuc.uc.pt/people/ada/"

    assert person_rows([row])[0] == [("ada", "Ada")]


def test_an_entry_with_no_published_page_is_skipped_and_counted():
    """16 of the 740 live entries are real people the directory lists with
    `url` pointing back at the index and no slug. `people.slug` is the primary
    key, so there is no key to store them under — the same call detail.py
    already makes for a project person whose href yields no slug. Counted so
    the number is visible, not swallowed."""
    rows = [
        entry("ada"),
        {"name": "Alexandra Maria Galval Ribeiro", "slug": "", "url": "https://www.cisuc.uc.pt/people"},
        {"name": "Boshra Banoei Zadeh", "slug": "", "url": ""},
    ]

    people, no_page = person_rows(rows)

    assert people == [("ada", "Ada")]
    assert no_page == 2


def test_a_slug_with_no_name_raises():
    """Not the same case as above: an entry that has a page but no name means
    the payload changed shape, and `people.name` is what the matcher reads."""
    row = entry("ada")
    row["name"] = ""

    with pytest.raises(PeopleError, match="slug but no name"):
        person_rows([row])


def test_a_decoded_url_lands_in_the_same_slug_space_as_a_project_href():
    """The real collision. CISUC publishes `.../people/Pedro Henriques Abreu`
    here and `href=".../people/Pedro%20Henriques%20Abreu"` on a project page,
    so the verbatim tail would file one person under two primary keys — the
    project one holding their 8 projects, the directory one holding none."""
    row = entry("x", "Pedro Henriques Abreu")
    row["url"] = "https://www.cisuc.uc.pt/people/Pedro Henriques Abreu"

    assert person_rows([row])[0] == [("Pedro%20Henriques%20Abreu", "Pedro Henriques Abreu")]


def test_a_slug_that_is_not_a_space_is_left_exactly_as_published():
    """Only the space is normalised. Quoting more would invent the same split
    in the other direction for the comma and underscore slugs CISUC also
    publishes."""
    for slug in ("Armin,Gharibi", "Paulo_Goncalves", "NunoAntunes", "Daniel-Martins"):
        row = entry(slug)
        row["url"] = f"https://www.cisuc.uc.pt/people/{slug}"
        assert person_rows([row])[0][0][0] == slug


def test_a_double_spaced_display_name_is_normalised():
    """Live payload really does carry "Jorge  Proença". Without this the
    directory overwrites the project page's clean name with a worse one,
    because run.py puts this step last."""
    assert person_rows([entry("jorge-proenca-1", "Jorge  Proença")])[0] == [
        ("jorge-proenca-1", "Jorge Proença")
    ]


# --------------------------------------------------------------------------
# Syncing
# --------------------------------------------------------------------------


def test_sync_inserts_every_directory_person(people_db):
    counts = sync_people(people_db, [entry("ada", "Ada Lovelace"), entry("alan", "Alan Turing")])

    stored = dict(people_db.execute("SELECT slug, name FROM people"))
    assert stored == {"ada": "Ada Lovelace", "alan": "Alan Turing"}
    assert counts["new"] == 2
    assert counts["unchanged"] == 0
    assert counts["name_updated"] == 0


def test_a_person_absent_from_the_directory_survives_with_their_name_intact(people_db):
    """The preservation invariant. ~182 rows in the committed seed came from a
    project page and are not on CISUC's current roster; if this module ever
    becomes a replace instead of an upsert, every one of them — and the
    project_people rows pointing at them — goes. This is the test that fails."""
    db.upsert_person(people_db, "left-cisuc", "Someone Who Left")
    people_db.commit()

    counts = sync_people(people_db, [entry("ada", "Ada Lovelace")])

    stored = dict(people_db.execute("SELECT slug, name FROM people"))
    assert stored["left-cisuc"] == "Someone Who Left"
    assert stored["ada"] == "Ada Lovelace"
    assert counts["absent_from_directory"] == 1
    assert counts["people_total_after"] == 2


def test_an_existing_person_keeps_their_slug_and_gets_the_directory_name(people_db):
    """Last writer wins on `name`, and run.py runs this step last — so the
    directory's fuller form is what the overlap ends up with. Reported as
    `name_updated` + `renames` precisely because it is a silent overwrite
    otherwise."""
    db.upsert_person(people_db, "ada", "A. Lovelace")
    people_db.commit()

    counts = sync_people(people_db, [entry("ada", "Ada Lovelace")])

    assert dict(people_db.execute("SELECT slug, name FROM people")) == {"ada": "Ada Lovelace"}
    assert counts["new"] == 0
    assert counts["name_updated"] == 1
    assert counts["renames"] == [{"slug": "ada", "was": "A. Lovelace", "now": "Ada Lovelace"}]


def test_syncing_twice_changes_nothing_the_second_time(people_db):
    rows = [entry("ada", "Ada Lovelace"), entry("alan", "Alan Turing")]
    sync_people(people_db, rows)

    counts = sync_people(people_db, rows)

    assert counts["new"] == 0
    assert counts["name_updated"] == 0
    assert counts["unchanged"] == 2


def test_sync_never_touches_project_people(people_db):
    """`people.slug` is an FK target for project_people. An upsert cannot
    orphan one; a delete-and-reload would, which is why it is not one."""
    db.upsert_person(people_db, "left-cisuc", "Someone Who Left")
    project_id = db.upsert_project(
        people_db,
        {"title": "P", "detail_fetched": 1, "first_seen_at": "2026-01-01", "last_scraped_at": "2026-01-01"},
    )
    db.replace_project_people(people_db, project_id, [("left-cisuc", "coordinator", 0)])
    people_db.commit()

    sync_people(people_db, [entry("ada", "Ada Lovelace")])

    assert [
        row["person_slug"] for row in people_db.execute("SELECT person_slug FROM project_people")
    ] == ["left-cisuc"]


def test_sync_writes_no_scrape_run_row(people_db):
    """sql/coverage.sql reads the latest scrape_runs row by id to render the
    manifest. A people-only row carries none of the project counts that view
    is made of, so it would read as a scrape that found nothing."""
    sync_people(people_db, [entry("ada", "Ada Lovelace")])

    assert people_db.execute("SELECT COUNT(*) FROM scrape_runs").fetchone()[0] == 0
