# aw-app-uc-phd — UC PhD Projects

A **private** aw-workspace app that turns the scraped CISUC / UC DEI projects
dataset into an interactive dashboard and a searchable project catalogue.

Born from [`aw-app-template`](https://github.com/tekflox/aw-app-template)'s
skeleton, grafted onto the original `uc-dei-phd` scraper repo — so the
scraper's history, its design decisions and its data all came across intact.
Built for Frederico Wu's UC DEI/CISUC PhD work.

- **Tier-1** (`inprocess`) — no container, no image build.
- **Permissions: `routes:register`, `fs:workspace-data`, and `net:outbound`.**
  The last one is `risk: low` (no signing gate) and exists solely for the
  one-shot `estudo_geral_extractor/` CLI below — the app itself makes no
  outbound calls at request time.
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

Re-scraping is **not** in the app at request time — both data pulls stay
one-shot CLI runs, never triggered by a route:

```bash
.venv/bin/python -m scraper.run                    # CISUC projects -> data/cisuc.sqlite3
.venv/bin/python -m estudo_geral_extractor.run      # DEI PhD theses -> estudo_geral/*.md
```

Point the scraper at the data-dir database to refresh what the app serves.
See "How the listing is fetched" below. See "The Estudo Geral extractor" at
the bottom of this file for the thesis pull.

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

The coverage gate is **100%, scoped to `uc_phd_app`**. `scraper/` and
`estudo_geral_extractor/` are deliberately outside it; `pyproject.toml`
explains why next to the setting.

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

---

# The Estudo Geral extractor

A one-shot Python CLI (`python -m estudo_geral_extractor.run`) that pulls
every UC DEI doctoral thesis published 2024-or-later from
[estudogeral.uc.pt](https://estudogeral.uc.pt/) — the University of
Coimbra's institutional repository — into `estudo_geral/<handle>.md`, one
file per thesis, full YAML front-matter plus extracted body text. Stage 1 of
the Estudo Geral roadmap (Kanban target `uc-dei-phd-estudo-geral-kb`); later
stages (semantic index, `phd_knowledge_base` MCP, dashboard, search UI) are
separate cards and out of scope here.

## The population — 18, and why it isn't 28

OAI-PMH's `set=com_10316_255` (the DEI community) `ListRecords` with
`from=2024-01-01` returns **211** records — that filter is the *deposit*
datestamp, not publication year. Of those, **18** are
`dc:type=doctoralThesis` with a `dc:date` (publication year) of 2024 or
later — that's the actual population, re-derived independently of the
Product Owner's own count and matching it exactly. `oai.py`'s
`select_dei_doctoral_theses_2024_plus` does this filter and is unit-tested
against a fixture. CISUC's own community (`com_10316_27707`) has zero
theses — Estudo Geral files them under the department, not the research
centre.

## The bot gate

Every bitstream/PDF URL on this site self-redirects up to 50x unless the
request carries the `browser_check=human` + `JSESSIONID` cookies the site's
own **item landing page** (`/handle/<handle>`) issues on first load. A
`requests.Session()` gets both for free by hitting the item page before the
PDF — no auth, no ToS problem, an anti-hotlink gate rather than access
control. `download.py` documents the isolation that confirmed this.

The gate applies to the item page's own redirect too, which is easy to
misdiagnose with a bare `curl -IL`: `curl`'s `-L` does **not** persist
cookies across redirects unless you also pass `-c/-b` a cookie jar, so a
plain `curl -IL https://estudogeral.uc.pt/handle/<handle>` loops 50x and
looks broken, while the same URL opens instantly in any real browser or
`requests.Session` (both persist cookies across redirects by default).
`source_url` in every front-matter block is exactly this URL — it resolves,
this curl gotcha is not a defect in it.

## The one real unknown, resolved: two download-link shapes, not client vs. server rendering

6 of the 18 (handles `.../119251`, `/119257`, `/119336`, `/119444`,
`/119468`, `/119520`) were flagged as needing investigation — their item
pages appeared not to expose a `/bitstream/<handle>/<seq>/<name>` link.
Measured directly: they are **not** client-side rendered. Their "View/Open"
link is a second, equally server-rendered pattern DSpace-CRIS uses for some
items — `/retrieve/<bitstream_id>/<filename>` — sitting in the same HTML
next to a `/bitstream/.../-1/<filename>` decoy link (an OpenURL/citation
artifact that always 404s). `download.find_download_link` tries the real
`/bitstream/.../<seq>/` pattern first (skipping any `-1` sequence), then
falls back to `/retrieve/<id>/`. No headless browser needed — the Playwright
escalation the parent card warned about never became necessary.

## The one genuine gap: an actual embargo, not a scraping problem

`10316/119251` is `dc.rights = embargoedAccess` with
`embargoEnd = 2028-05-08` (still ~19 months out as of this run) — its REST
bitstream list is empty and its item page's download link redirects to a
login page. **This corrects the parent card's premise** that all 6 were
`openAccess`: 5 were, 1 genuinely is not, independent of anything this
extractor could do differently. Its `.md` still carries full metadata and
both abstracts (`full_text: false` in front-matter records this
explicitly) — consistent with the Product Owner's own finding that all 18
serve the correlation goal on metadata alone; only the semantic-search goal
(a later stage) needs the body text.

Net result: **17/18 with full text extracted**, exceeding the ≥12
acceptance bar, and the 6-thesis unknown resolved to 5 solved + 1 correctly
reported as blocked by a real embargo rather than a technical gap.

## Where the metadata comes from

OAI-PMH (`oai.py`) is used only for enumeration — it is cheap to paginate
but its `oai_dc` format carries no language tags, so bilingual
titles/abstracts/subjects cannot be told apart reliably from element order
alone. Every field that lands in front-matter instead comes from the legacy
`/rest/` API (`restapi.py`), which tags each value with its language
(`eng`/`por`) — `title` prefers the English `dc.title`/`dc.title.alternative`
value, falling back to whatever exists.

## Rate limiting

~0.8s between every request (item page, REST call, PDF download) —
comfortably under the ~1 req/s throttling threshold hit while investigating
this card. `download_pdf` retries transient (5xx/network) failures with
exponential backoff; a non-retryable failure (embargo redirect, 404) is
recorded in the manifest instead of aborting the run.

## Output

- `estudo_geral/<handle-with-dash>.md` — one per thesis, front-matter keys
  `handle`, `title`, `authors`, `supervisors`, `date`, `keywords`,
  `abstract_pt`, `abstract_en`, `source_url`, `rights`, `full_text`.
- `estudo_geral/manifest.json` — one row per thesis: title, date, rights,
  authors, byte count, and (for the one that failed) the exact error — the
  count this README states is a query over this file, not an assertion.
- `estudo_geral/pdfs/` — the downloaded PDFs (~480 MB; sizes match each
  bitstream's `sizeBytes` in REST exactly — one thesis alone is 167 MB).
  **Gitignored** — the `.md` extracts are the committed provenance, not the
  source PDFs.

## Tests

`tests/test_estudo_geral_extractor.py` covers the pure functions — OAI
record parsing/selection, the two download-link shapes (including the `-1`
decoy), REST metadata language-splitting, and front-matter/markdown
rendering — against fixtures, same convention as `tests/test_parse.py` for
the scraper. The network paths (OAI pagination, REST fetch, item-page fetch,
PDF download) are exercised for real by running the CLI, not by the test
suite — see the coverage-gate comment in `pyproject.toml`.

## What this makes harder later

- `/retrieve/<bitstream_id>/` requires the bitstream's numeric REST id,
  which is a live lookup, not something derivable from the handle alone —
  fine at 18 items scanned per run, would need caching at a much larger
  scale.
- The embargoed thesis's full text will not become available until 2028
  without a re-run after `embargoEnd` passes; nothing here polls for that.
- PDF text extraction (`pypdf`) is not layout-aware — tables, footnotes and
  multi-column pages extract as a single text stream. Fine for the
  correlation/keyword-search goals; a later semantic-search stage may want a
  layout-aware extractor if chunk quality suffers.
