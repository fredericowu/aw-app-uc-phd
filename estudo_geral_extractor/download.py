"""The bot gate and the PDF download itself.

Every bitstream URL on estudogeral.uc.pt self-redirects ~50x (infinite loop)
unless the request carries the `browser_check=human` + `JSESSIONID` cookies
the site's own item-landing page issues. Loading `/handle/<handle>` first,
through a `requests.Session`, gets both for free — confirmed by isolation
(bare / UA-only / Referer-only / UA+Referer all loop; item-page-first does
not). There is no auth and no ToS problem: it is an anti-hotlink gate, not
access control.

The item page's own "View/Open" link comes in two shapes depending on the
item (not on client-vs-server rendering — both are plain server-rendered
`<a href>` tags, just two different paths DSpace-CRIS uses):
  - `/bitstream/<handle>/<seq>/<filename>`  (most items)
  - `/retrieve/<bitstream_id>/<filename>`   (a handful of items)
A stray `/bitstream/<handle>/-1/<filename>` link is sometimes also present
(an OpenURL/citation-export artifact) and always 404s — never used here.
"""
import re
import time

import requests

BASE = "https://estudogeral.uc.pt"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

_BITSTREAM_RE = re.compile(r'href="(/bitstream/\d+/[^"]+\.pdf)"')
_RETRIEVE_RE = re.compile(r'href="(/retrieve/\d+/[^"]+\.pdf)"')


def bootstrap_session():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def fetch_item_page(session, handle):
    """Network: GET the item landing page. Also issues the bot-gate cookies."""
    r = session.get(f"{BASE}/handle/{handle}", timeout=30)
    r.raise_for_status()
    return r.text


def find_download_link(html):
    """Pure: item-page HTML -> absolute PDF URL, or None if no real link is present.

    A `/bitstream/.../-1/...` match is a decoy (always 404s) — only accept a
    non-negative sequence number.
    """
    for m in _BITSTREAM_RE.finditer(html):
        path = m.group(1)
        seq = path.split("/")[4]
        if seq != "-1":
            return BASE + path
    m = _RETRIEVE_RE.search(html)
    if m:
        return BASE + m.group(1)
    return None


def download_pdf(session, url, dest_path, max_attempts=3, sleep_between_attempts=None):
    """Network, with retry/backoff on transient failure. Returns (ok, http_status, error)."""
    last_status = None
    last_error = None
    for attempt in range(max_attempts):
        if attempt > 0:
            time.sleep(sleep_between_attempts(attempt) if sleep_between_attempts else 2**attempt)
        try:
            r = session.get(url, timeout=60, stream=True)
        except requests.RequestException as exc:
            last_error = str(exc)
            continue
        last_status = r.status_code
        content_type = r.headers.get("content-type", "")
        if r.status_code == 200 and "pdf" in content_type.lower():
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
            return True, r.status_code, None
        if r.status_code == 200:
            # 200 with a non-PDF body is the embargo/login redirect landing page.
            last_error = f"200 but content-type={content_type!r} (likely login/embargo page)"
            break
        if 500 <= r.status_code < 600:
            last_error = f"HTTP {r.status_code}"
            continue
        last_error = f"HTTP {r.status_code}"
        break
    return False, last_status, last_error
