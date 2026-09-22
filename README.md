# uc-dei-phd — CISUC projects scraper

A one-shot Python scraper that pulls every project listed at
[cisuc.uc.pt/en/projects](https://www.cisuc.uc.pt/en/projects) into a local
SQLite database, plus a script that builds an exploratory-analysis
presentation on top of it.

Built for Frederico Wu's UC DEI/CISUC PhD work. Single-user, offline
artefact — not an aw-workspace app, no deploy, no scheduling.

## How the listing is fetched — no browser

The listing page is a Vue 2 component that POSTs back to the same URL that
serves the page (`axios.post('projects', {...})`). It's a Laravel app with
CSRF enforced, so the recipe is:

1. `GET` the page in a `requests.Session`, scrape the `csrf-token` meta tag.
2. `POST` the same URL with `X-CSRF-TOKEN` + `X-Requested-With:
   XMLHttpRequest`, body `{"page":1,"length":1000,...}`.

`length: 1000` is not capped server-side — all 400 rows return in one
request. No Playwright, no headless browser, no pagination loop (with a
page-by-page fallback in `listing.py` in case that ever changes).

Detail pages are static, server-rendered HTML — `scraper/detail.py` parses
them with a **label-driven parser that has no hardcoded field list**: it
walks the DOM structurally (first `<p>` in a block is the label, the rest
are values) rather than keying on CSS classes, because `End Date`'s label
uses a different class from every other field on the page and a
class-based selector would silently drop it. Every (label, value) pair
found is persisted verbatim into `project_fields_raw`, so a field nobody
thought to name (e.g. `Keywords`, present on ~70% of pages but in no spec
this scraper was built against) still ends up in the database.

See `.tmp/uc-dei-phd/DESIGN.md` in the aw-workspace repo for the full design
rationale (not shipped in this repo — this is a standalone project).

## Setup

```bash
cd repos/uc-dei-phd
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Own `.venv/`, own `requirements.txt` — does not use the aw-workspace venv.

## Running the scraper

```bash
.venv/bin/python -m scraper.run
```

One-shot: fetches the listing, writes a `scrape_targets` manifest row per
listing row, then fetches each detail page 1.5s apart (retrying on
5xx/timeout), upserting into `data/cisuc.sqlite3` as it goes. Takes roughly
10 minutes for ~400 pages. Safe to re-run — every write is
`INSERT ... ON CONFLICT(title_norm) DO UPDATE`, and per-project child rows
(fields, groups, people, keywords) are replaced, not appended.

## Building the presentation

```bash
.venv/bin/python -m analysis.build_presentation
```

Reads every chart's query from a committed file in `sql/`, renders the
result with matplotlib, and writes one self-contained HTML file to
`analysis/presentation.html`. That file is then loaded into the
aw-workspace `aw-presentation` app.

## Schema

- `projects` — one row per listing entry, natural key `title_norm`
  (trimmed/whitespace-collapsed/casefolded title). **Not URL or slug** —
  two projects (`HealthyW8`, `FOCUS-PA`) are published with an empty slug
  and share the bare listing URL; keying on URL would silently merge them.
- `project_fields_raw` — every (label, value, href) pair seen on a detail
  page, verbatim, in document order. The catch-all that makes "is every
  labelled field on the live page in the DB?" a SQL query instead of an
  eyeball, and that will keep catching a field this scraper doesn't
  currently promote to a typed column — anything new lands here first, and
  nowhere else, until someone decides to promote it (see "What this makes
  harder later" below).
- `research_groups` / `project_groups` — many-to-many. The site's own
  facet counts sum to 478 memberships across 400 projects; a project can
  belong to more than one research group.
- `people` / `project_people` — coordinators and researchers, role-tagged.
- `project_keywords` — comma-split from the `Keywords` field, when present.
- `scrape_runs` — one row per scraper invocation.
- `scrape_targets` — **the coverage manifest.** One row per listing row,
  written before that row's detail fetch, updated to a terminal status
  (`ok` / `no_detail_url` / `http_error`) as each completes. Query this,
  filtered to the latest `run_id`, to answer "did we get everything?"
  without trusting a bare row count.

## Coverage (criterion 3, amended)

The 400 listing rows resolve to 399 distinct URLs and 398 reachable detail
pages — two projects (`HealthyW8`, `FOCUS-PA`) are listed with an empty
slug and the site itself publishes no detail page for them.

Measured against the live site (scrape completed 2026-09-22):

| Metric | Value |
|---|---|
| `COUNT(*) FROM projects` | **400** (matches the site's own `totalData`) |
| `COUNT(*) WHERE detail_fetched = 1` | **398** |
| Rows with `detail_unavailable_reason` set | **2** (`HealthyW8`, `FOCUS-PA` — `"no detail url published by site"`) |
| Rows with NULL `title` | **0** |
| `scrape_targets` rows for the latest run | **400**, all terminal (398 `ok`, 2 `no_detail_url`, 0 `http_error`) |
| `detail_url` for the 2 stubs | NULL (not the bare listing URL) |

Query: `sql/coverage.sql`.

## Field fill rates (criterion 4)

Per-field fill rate across the 398 fetched detail pages, driven by
`project_fields_raw` (the site's own label universe — not a hardcoded
field list). Query: `sql/fill_rates.sql`.

| Field | Projects with value | Fill rate |
|---|---|---|
| Scope | 398 | 100.0% |
| Total budget | 398 | 100.0% |
| coordinator | 398 | 100.0% |
| Start Date | 395 | 99.2% |
| End Date | 388 | 97.5% |
| Research Group | 387 | 97.2% |
| Synopsis | 372 | 93.5% |
| Funding | 363 | 91.2% |
| Researchers | 341 | 85.7% |
| Keywords | 288 | 72.4% |
| CISUC budget | 271 | 68.1% |
| Partners | 261 | 65.6% |

`Keywords` is in no spec this scraper was built against, yet is present on
72.4% of pages — exactly the case the label-driven parser (rather than a
hardcoded field list) exists to catch.

A live-vs-DB spot check on 3 randomly sampled fetched projects (ids 167,
79, 205) found zero missing and zero extra labelled fields between the
live page and `project_fields_raw`.

Research group membership: 476 memberships across 400 projects (some
projects belong to 2+ groups) — CMS 117 · AC 101 · SSE 87 · NCS 68 · IS 55
· bAI 48. Query: `sql/projects_per_group.sql`.

## What this makes harder later

- The raw catch-all (`project_fields_raw`) encourages never adding typed
  columns — a new field lands there and is invisible to `sql/` until
  someone promotes it. Right default (nothing is lost), but a future "why
  isn't X on the chart" has a boring answer: nobody promoted it.
- Keying on `title_norm` bakes in "CISUC never renames a project." A
  rename would insert a second row rather than update the existing one.
  Fine for a one-shot; would need revisiting for an incremental scrape,
  which is explicitly out of scope here.
- The CSRF handshake is undocumented site behaviour. If it changes, the
  scraper fails loudly at the listing step (raises rather than returning
  zero rows) rather than silently degrading.
- SQLite + a committed binary DB file means every re-run produces a binary
  diff in git. Fine at this size (~400 projects).
- The 2 stub projects (`detail_fetched = 0`) will never gain detail data
  unless CISUC publishes pages for them.

## Out of scope (explicit, per Product Owner)

Nothing beyond `cisuc.uc.pt/en/projects` + its detail pages. No PDFs, no
scheduled/incremental scraping, not an aw-workspace app, no deploy/CI, no
LLM-derived fields, no dashboard, no Postgres.
