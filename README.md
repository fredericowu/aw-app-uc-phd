# aw-app-uc-phd — UC PhD Projects

A **private** aw-workspace app that turns the scraped CISUC / UC DEI projects
dataset into an interactive dashboard and a searchable project catalogue.

Born from [`aw-app-template`](https://github.com/tekflox/aw-app-template)'s
skeleton, grafted onto the original `uc-dei-phd` scraper repo — so the
scraper's history, its design decisions and its data all came across intact.
Built for Frederico Wu's UC DEI/CISUC PhD work.

- **Tier-1** (`inprocess`) — no container, no image build.
- **Permissions: `routes:register` and `fs:workspace-data`. Nothing else.**
- The frontend is a **self-hosted React SPA**, served by the app's own FastAPI
  sub-app and surfaced through a `managed_app` window — deliberately *not* a
  `component`-mode bundle. See "Why no `ui:code`" below; this is the single
  most important design constraint in the repo.

## What it shows

Everything the old static `analysis/presentation.html` covered, plus the two
things a static page could never do:

| View | Source |
|---|---|
| Coverage — 400 projects, 398 detail pages, the scrape manifest | `sql/coverage.sql` |
| Projects per research group (all 6) | `sql/projects_per_group.sql` |
| Top 10 projects per group (all 6), each linking to its CISUC page | `sql/top_projects_per_group.sql` |
| Funding sources | `sql/funding_breakdown.sql` |
| Budget by group / by year | `sql/budget_by_group.sql`, `sql/budget_by_year.sql` |
| Projects started per year | `sql/start_date_timeline.sql` |
| Top coordinators | `sql/top_coordinators.sql` |
| **Searchable, group-filterable project list** | live query, `uc_phd_app/api/projects.py` |
| **Per-project detail**, including every raw `project_fields_raw` pair | live query |

**Every figure still traces to a committed `.sql` file.** That was the best
property of the original repo and it survives the move: `uc_phd_app/db.py`
loads the query from `sql/` at request time. No query was re-expressed as a
Python string literal, and the endpoint docstrings name the file they read.

Two honesty caveats are carried in the API payloads themselves — not just in
the UI copy — so they cannot be dropped by a frontend change:

- Research-group membership is **many-to-many**: the per-group columns sum to
  more than 400 because a project in two groups is counted under both.
- The top-10 ranking is **total budget descending, a documented proxy**. The
  request never specified a metric; budget is the most objective one the data
  offers, and it measures size, not quality or impact.

## Why no `ui:code` (read before "simplifying" the frontend)

The frontend is a plain SPA served by the app itself on its own subdomain,
behind a `managed_app` window. It asks for exactly two permissions, both
low-risk: `routes:register` and `fs:workspace-data`.

That design was originally forced. While the app was distributed through the
**private** catalog it was not `signed` (`src/apps/catalog.py`'s
`is_marketplace_app`, and `app_installs.py` in aw-backend compute `signed`
only from membership of the *official public* marketplace), and
`filter_grants` refuses **every high-risk capability** to an unsigned app —
`ui:code` among them. A refused capability **does not raise**: the app
activates anyway, so a `component`-mode frontend would have produced windows
with intact chrome and a completely empty body, which reads as a bug in the
app rather than a permission problem.

It is no longer forced. This app now ships from the public catalog
`tekflox/aw-marketplace` and reports `signed: true`, so `ui:code` and Tier-2's
`containers:manage` are both available again.

**Keep it anyway.** Being signed *permits* high-risk capabilities; it does not
require them. This SPA is built, tested and driven live through every view,
and the design asks for nothing that can ever be silently taken away — which
is worth more than the capability it declines. `docs/app-migration-plan.md` §2
and §13 have the original argument; `docs/distribution-migration-plan.md` has
the move that relaxed the constraint.

## Where the data lives

```
data/cisuc.sqlite3                                   the committed SEED
<AW_WORKSPACE_HOME>/data/aw-app-uc-phd/cisuc.sqlite3 the LIVE database
```

An installed app's package directory is **deleted and re-fetched wholesale on
every update**. Reading the database from there would mean any scrape a user
ran disappeared at the next version bump, with no error. So `activate()` seeds
the committed snapshot into the app's own data dir and everything reads from
there (`uc_phd_app/seed.py`).

The copy is **atomic and idempotent**, because at `AW_WORKSPACE_WORKERS>1`
every worker activates the app independently and a naive `shutil.copy` race
produces a truncated database that opens fine and answers with garbage.

Upgrade rule: a newer packaged snapshot replaces the live database **unless**
the live one has a `scrape_runs` row newer than the seed's — i.e. your own
`python -m scraper.run` always wins over ours.

## Running it

### Standalone (how the UI is developed)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt fastapi uvicorn
cd ui && npm install && npm run build && cd ..

AW_APP_UC_PHD_DATA_DIR=/tmp/uc-phd .venv/bin/python -m uc_phd_app
# http://127.0.0.1:9482/
```

The standalone app mounts the same sub-app at **both** roots the runtime
exposes it on — `/` (standing in for the app's subdomain) and
`/api/apps/aw-app-uc-phd` (the path mount) — so the mode you develop in
cannot disagree with the mode users get.

### Refreshing the data

Re-scraping is **not** in the app (no `net:outbound`, deliberately). It stays
a CLI run:

```bash
.venv/bin/python -m scraper.run
```

Point it at the data-dir database to refresh what the app serves. See
"How the listing is fetched" below.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q --cov=uc_phd_app
bash tests/standalone_test.sh          # boots standalone, checks /healthz + both roots
.venv/bin/python tests/validate_manifest.py aw-app.json
```

Route and seed tests run against a **small fixture database built from
`scraper/schema.sql`**, never the real 400-row snapshot — so assertions stay
readable and a schema change the app has not caught up with fails loudly.
`tests/test_standalone.py` is the exception: it exercises the real committed
artefacts (seed, `sql/`, `ui/dist`) on purpose.

The coverage gate is **100%, scoped to `uc_phd_app`**. `scraper/` is
deliberately outside it; `pyproject.toml` explains why next to the setting.

`ui/dist` is **committed** — release CI ships the repo as-is and never runs
`npm run build`. CI fails if a fresh build would change it.

---

# The scraper

A one-shot Python scraper that pulls every project listed at
[cisuc.uc.pt/en/projects](https://www.cisuc.uc.pt/en/projects) into
`data/cisuc.sqlite3`.

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
this scraper was built against) still ends up in the database — and the
app's project-detail view renders that table in full for exactly that
reason.

## Schema

- `projects` — one row per listing entry, natural key `title_norm`
  (trimmed/whitespace-collapsed/casefolded title). **Not URL or slug** —
  two projects (`HealthyW8`, `FOCUS-PA`) are published with an empty slug
  and share the bare listing URL; keying on URL would silently merge them.
- `project_fields_raw` — every (label, value, href) pair seen on a detail
  page, verbatim, in document order. The catch-all that makes "is every
  labelled field on the live page in the DB?" a SQL query instead of an
  eyeball.
- `research_groups` / `project_groups` — many-to-many. The site's own
  facet counts sum to 478 memberships across 400 projects.
- `people` / `project_people` — coordinators and researchers, role-tagged.
- `project_keywords` — comma-split from the `Keywords` field, when present.
- `scrape_runs` — one row per scraper invocation.
- `scrape_targets` — **the coverage manifest.** One row per listing row,
  written before that row's detail fetch, updated to a terminal status
  (`ok` / `no_detail_url` / `http_error`) as each completes.

Full schema: `scraper/schema.sql`, applied idempotently with
`CREATE TABLE IF NOT EXISTS` on every run — which is also what lets the
publications/researchers graph (`docs/graph-db-plan.md`) land as new tables
in this same file rather than a migration.

## Coverage (measured 2026-09-22)

| Metric | Value |
|---|---|
| `COUNT(*) FROM projects` | **400** (matches the site's own `totalData`) |
| `COUNT(*) WHERE detail_fetched = 1` | **398** |
| Rows with `detail_unavailable_reason` set | **2** (`HealthyW8`, `FOCUS-PA`) |
| Rows with NULL `title` | **0** |
| `scrape_targets` rows for the latest run | **400**, all terminal |

The app's Coverage view renders these live from `sql/coverage.sql` rather
than from this table.

## What this makes harder later

- The raw catch-all (`project_fields_raw`) encourages never adding typed
  columns — a new field lands there and is invisible to `sql/` until
  someone promotes it. Right default (nothing is lost), but a future "why
  isn't X on the chart" has a boring answer: nobody promoted it.
- Keying on `title_norm` bakes in "CISUC never renames a project."
- The CSRF handshake is undocumented site behaviour. If it changes, the
  scraper fails loudly at the listing step rather than silently degrading.
- Committing the SQLite seed puts binary data in git history. Fine at 1.9 MB
  and this cadence; if the graph data lands as another 20 MB, move the seed
  to a release asset.
- The 2 stub projects (`detail_fetched = 0`) will never gain detail data
  unless CISUC publishes pages for them.

## Docs

- `docs/app-migration-plan.md` — the architect's design for this conversion,
  with the code references behind every constraint above.
- `docs/graph-db-plan.md` — the researchers/publications graph plan. Not built
  yet; §12 of the migration plan explains what this app already does to
  accommodate it.
- `docs/uc/` — reference decks.
