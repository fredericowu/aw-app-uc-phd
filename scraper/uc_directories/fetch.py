"""Getting the HTML, and the one site that will not hand it over plainly.

`www.uc.pt` sits behind BunnyCDN's JavaScript challenge. Every path answers
`403` with `cdn-challenge: true` / `errorcode: 112` to any plain client,
whatever its User-Agent — the spike recorded this for FEUC, and it is in fact
the whole host. A real browser solves the challenge and is handed a
`bunny_shield` cookie, which is NOT http-only, so one browser pass can mint a
credential this module then reuses:

1. Drive any browser at `https://www.uc.pt/`, wait for the title to stop
   saying "Establishing a secure connection", and read `document.cookie`.
2. Pass the `bunny_shield` value as `--shield-cookie` (or
   `UC_SHIELD_COOKIE` in the environment) **together with the browser's own
   `navigator.userAgent`** (`--user-agent` / `UC_SHIELD_USER_AGENT`). The
   cookie is bound to the UA that minted it: the same cookie with a different
   UA is a 403 again, which is a tidy five minutes to lose.

The cookie carries its own expiry and the shield rate-limits bursts, so the
delay between fetches is deliberately generous and a 403 mid-run fails that
unit rather than the run.

`--snapshot-dir` is the offline fallback the design mandates, and it is also
how a page gets harvested when no browser is reachable at all: save the
rendered HTML as `<source>.html` (plus `<source>-2.html`, `<source>-3.html`
for the later pages of a paginated unit) and the same committed parsers run
over it. `listing_url` stays the live URL either way, so a human checking a
match still lands on the real page; the run report records which units came
from a snapshot.

One trap if the snapshots come from an MCP browser rather than a human's
"save page as": a tool that returns the HTML as its *result* and writes that
result to a file writes a JSON **string literal** — the file starts with `"`
and every quote inside it is `\"`. The parsers then read a document with no
attributes and report two rows out of twenty-four, which looks exactly like a
page that changed shape. `json.loads` the file once before saving it.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests

from ..listing import USER_AGENT
from . import parsers
from .units import Unit

#: Courtesy, and self-preservation.
SLEEP_BETWEEN_FETCHES = 3.0

#: The shield is a RATE limiter, not a one-shot gate: with a valid cookie it
#: serves about five requests and then 403s the sixth, and the same request
#: succeeds after a pause. Measured 2026-10-18 — at 3s between fetches it
#: refused the sixth www.uc.pt request of the run; at 20s it served four more
#: in a row. So a 403 mid-unit is retried rather than believed, and only a
#: 403 that survives the retries fails the unit. Without this the harvest
#: reports "FEUC, FDUC and FLUC worked, three units are broken", which is a
#: false statement about three parsers that are fine.
SHIELD_RETRY_SLEEP = 25.0
SHIELD_RETRIES = 2


class FetchError(RuntimeError):
    """This unit could not be read. Fails the unit, never the run."""


def _shield_headers(user_agent: str) -> dict:
    """The header set the challenge checks. The `Sec-Fetch-*` trio is not
    decoration: with the right cookie and the right UA but without them, the
    shield still answers 403."""
    return {
        "User-Agent": user_agent,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    }


def build_session(shield_cookie: str | None = None, user_agent: str | None = None):
    """A session that can reach both `www.uc.pt` (with the cookie) and the
    centres' own sites (without it)."""
    cookie = shield_cookie or os.environ.get("UC_SHIELD_COOKIE") or None
    agent = user_agent or os.environ.get("UC_SHIELD_USER_AGENT") or USER_AGENT
    session = requests.Session()
    session.headers.update(_shield_headers(agent))
    if cookie:
        session.cookies.set("bunny_shield", cookie, domain="www.uc.pt")
    return session


def _get_with_shield_retry(unit: Unit, session, url: str, sleep: float = SHIELD_RETRY_SLEEP):
    """GET, re-trying a 403 from the rate limiter. See SHIELD_RETRY_SLEEP.

    Only a 403 is retried, and only for a unit the registry marks as sitting
    behind the shield: every other status is this unit's real answer and
    re-asking would just be hope.
    """
    for attempt in range(SHIELD_RETRIES + 1):
        try:
            response = session.get(url, timeout=60)
        except requests.RequestException as exc:
            raise FetchError(f"{unit.source}: GET {url} failed: {exc}") from exc
        if response.status_code != 403 or not unit.needs_browser_cookie:
            return response
        if attempt < SHIELD_RETRIES and sleep:
            time.sleep(sleep)
    return response


def _next_url(unit: Unit, html: str, current: str, index: int, base: str) -> str | None:
    """The next page of this section, or ``None`` when there is none.

    Two shapes, and the difference is not cosmetic:

    * ``page`` — ``?page=N`` on the listing URL, which the UC CMS honours.
    * ``follow_next`` — the link the PAGE publishes. CES accepts
      ``?offset=N`` on its listing URL and ignores it, serving page 1
      forever, so a constructed URL reads 20 of 200 researchers and reports
      success. Its real pagination lives on a different endpoint, which only
      the page knows.
    """
    if unit.paging == "page":
        separator = "&" if "?" in base else "?"
        return f"{base}{separator}page={index + 2}"
    if unit.paging == "follow_next":
        nxt = parsers.next_url(unit.parser, html, current)
        return nxt if nxt and nxt != current else None
    raise FetchError(f"{unit.source}: unknown paging mode {unit.paging!r}")


def snapshot_paths(unit: Unit, snapshot_dir: Path) -> list[Path]:
    """`<source>.html`, then `<source>-2.html`, `<source>-3.html`, … while
    they exist. A gap ends the sequence rather than being skipped: a missing
    middle page means an incomplete save, and the `expected_min` floor is what
    turns that into a loud failure for the unit."""
    first = snapshot_dir / f"{unit.source}.html"
    if not first.is_file():
        raise FetchError(f"{unit.source}: no snapshot at {first}")
    out = [first]
    index = 2
    while True:
        nxt = snapshot_dir / f"{unit.source}-{index}.html"
        if not nxt.is_file():
            return out
        out.append(nxt)
        index += 1


def fetch_unit_pages(
    unit: Unit,
    session,
    on_page,
    snapshot_dir: Path | None = None,
    sleep: float = SLEEP_BETWEEN_FETCHES,
) -> int:
    """Hand every page of one unit to ``on_page(listing_url, html) -> int``.

    Returns the number of pages read. ``on_page`` returns how many NEW people
    that page yielded, and returning 0 is what ends a paginated section: both
    CMSes answer a past-the-end page with ``200`` and an empty list rather
    than a 404. Parsing therefore drives pagination, which is also what keeps
    this module free of any knowledge of page shape.

    The URL handed over is the page the people were actually read off, so a
    human checking a match opens exactly what the harvester read.
    """
    # Per-unit and opportunistic, not a whole-run mode: a snapshot is used
    # for a unit that HAS one and the rest are fetched live in the same run.
    # That matters for more than convenience — cross-unit deduplication only
    # sees the units of one run, so splitting the shielded units into a
    # separate invocation from the unshielded ones is what loses the
    # FEUC-links-his-CES-page merges this feature is built on.
    if snapshot_dir is not None and (snapshot_dir / f"{unit.source}.html").is_file():
        paths = snapshot_paths(unit, snapshot_dir)
        for path in paths:
            on_page(unit.listing_url, path.read_text(encoding="utf-8"))
        return len(paths)

    pages = 0
    for base in (unit.listing_url, *unit.extra_paths):
        url: str | None = base
        index = 0
        while url is not None and index < unit.max_pages:
            if pages and sleep:
                time.sleep(sleep)
            response = _get_with_shield_retry(unit, session, url)
            if response.status_code != 200:
                if index == 0:
                    raise FetchError(
                        f"{unit.source}: GET {url} returned {response.status_code}"
                        + (
                            " — www.uc.pt needs a browser-minted bunny_shield cookie,"
                            " see this module's docstring"
                            if response.status_code == 403 and unit.needs_browser_cookie
                            else ""
                        )
                    )
                break
            pages += 1
            # The URL recorded against these people is the SECTION page, not
            # page 7 of it: `?offset=120` is a scroll position, and a human
            # checking a match needs the page the roster lives on.
            fresh = on_page(base, response.text)
            if unit.paging == "none":
                break
            url = _next_url(unit, response.text, url, index, base)
            if not fresh:
                break
            index += 1
    return pages
