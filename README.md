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
| **Collaboration & teams** — ranked co-project/co-supervision pairs, one person's own neighbourhood, or a filtered node-link graph (node size = degree within the rendered floor) | `sql/collab_co_project.sql`, `sql/collab_co_supervision.sql`, `sql/collab_person_groups.sql`, aggregated in `uc_phd_app/collab.py` — degree is derived in Python over those same rows, not a new query (see `collab.py`'s docstring for why) |
| The 181 Estudo Geral doctoral theses | `sql/theses.sql` |
| Each thesis's authors/supervisors, resolved to a CISUC person or not | `sql/thesis_people.sql` |
| How far the name matcher reaches (per tier, over distinct names, **split by role** — an unresolved author is the correct answer, an unresolved supervisor is a hole) | `sql/thesis_match_tiers.sql` |
| **Identity coverage** at the grains the advisor/collaboration views consume: supervision edges, theses, co-supervision pairs, and how many name variants collapse to one person | `sql/thesis_attribution_coverage.sql` — rendered on the Theses view and quoted in the co-supervision caveat; see `docs/thesis-attribution.md` |
| Each thesis's research group(s) and how confident that is | `sql/person_group_shares.sql` (live) + `sql/thesis_group_affinity.sql` (seeded), combined in `uc_phd_app/theses.py` — see `docs/thesis-attribution.md` |
| **Searchable, group-filterable project list** | live query, `uc_phd_app/api/projects.py` |
| **Per-project detail**, including every raw `project_fields_raw` pair | live query |
| **Fit** — theses matched against an editable interest profile, with their real supervisors | `profile/research_interests.md` + `sql/thesis_people.sql`, ranked in pgvector |
| **Bibliography** — every work cited anywhere in the corpus, ranked by how many theses cite it, each expandable to the citing theses and their own wording of the citation | `sql/bibliography_summary.sql`, `sql/bibliography_cited_by_histogram.sql`, `sql/bibliography_match_tiers.sql`, `sql/bibliography_per_thesis.sql`, aggregated in `uc_phd_app/bibliography.py`; the tables are built offline by `analysis/build_bibliography.py` |

**Every figure still traces to a committed `.sql` file.** That was the best
property of the original repo and it survives the move: `uc_phd_app/db.py`
loads the query from `sql/` at request time. No query was re-expressed as a
Python string literal, and the endpoint docstrings name the file they read.

Three honesty caveats are carried in the API payloads themselves — not just in
the UI copy — so they cannot be dropped by a frontend change:

- Research-group membership is **many-to-many**: the per-group columns sum to
  more than 400 because a project in two groups is counted under both.
- The top-10 ranking is **total budget descending, a documented proxy**. The
  request never specified a metric; budget is the most objective one the data
  offers, and it measures size, not quality or impact.
- Collaboration's `cross_group` is **co-occurrence, not complementarity** —
  true only when two people's own project histories share no research group,
  null when either has none to compare, and never a claim about how well they
  actually complement each other.

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
.venv/bin/python -m analysis.build_thesis_facts     # estudo_geral/*.md -> the thesis tables
.venv/bin/python -m analysis.build_bibliography     # estudo_geral/*.md -> the bibliography tables
.venv/bin/python -m analysis.build_group_affinity   # thesis text x group project text -> thesis_group_affinity
```

Point the scraper at the data-dir database to refresh what the app serves.
See "How the listing is fetched" below. See "The Estudo Geral extractor" at
the bottom of this file for the thesis pull.

The third one is the **identity spine**, and it is the step to re-run after
either of the other two: it reads the committed `.md` front matter (checked
against `manifest.json`, not just the glob), resolves every author and
supervisor name against `people` with a deterministic matcher, and writes
`theses` / `thesis_people` / `thesis_keywords` into the seed. It prints what
it wrote, including how many names it could **not** resolve — today 14 of 50,
all thesis authors or external co-supervisors. Those names are preserved as
rows with a NULL `person_slug`, never dropped.

The fourth builds the **content signal** for research-group attribution:
TF-IDF cosine between each thesis's own text and each research group's
project text, written into `thesis_group_affinity`. Re-run it after either
data pull as well.

Two halves that deliberately do not move together: **identity is frozen**
into the seed by `build_thesis_facts`, while a matched person's **research
group stays derived live** on every request from their project history
(`uc_phd_app/theses.py`). A group is a live fact about a career; rebuilding
the seed must never be what it takes for a new project to move someone's
group.

The same split, one level up, is what decides a *thesis's* group: the people
signal is live, the content signal is seeded, and the two are combined by
whether they **agree** — one group where they corroborate each other, two
ranked and flagged where they do not, and nothing at all where neither signal
exists. Measured on the committed seed: mean 1.29 groups per thesis, maximum
2, 3 unattributed, against the 2.70/6-with-35-theses-carrying-all-six that
unioning the people signal alone produced. The cost is **two clocks** — a
re-scrape moves the people half immediately and the content half only when
`analysis.build_group_affinity` re-runs. Full reasoning, including why the
pgvector embeddings were rejected for this and what would overturn that, is
in `docs/thesis-attribution.md`.

`docs/thesis-attribution.json` — 50 name decisions a human made by hand, with
written reasoning — is no longer read at runtime. It is the **golden fixture**
the matcher is replayed against in `tests/test_name_match.py`: reproduce all
36 matches, resolve none of the 14 the human refused to, or the suite fails.

The fourth one must run **after** `build_thesis_facts` — it needs a `theses`
row per `.md` and says so by name rather than failing on a bare foreign key.

## Bibliography — what the numbers are, and what they are not

`analysis/build_bibliography.py` parses reference lists out of the extracted
PDF text and writes `bib_references` / `thesis_references` into the seed.
Measured on the committed corpus at matcher version 1:

| | |
|---|---|
| Theses whose references parsed | **133 of 181** (95.7% of the 139 with body text; 42 are metadata-only stubs) |
| Distinct works | 23,316 |
| Citations | 24,559 |
| Works cited by 2+ theses | 707 (3.0%) |
| Tier-2 recall vs DOI ground truth | **52.6%** (30 of 57 shared-DOI groups) |

Three things about that table are load-bearing, and the UI states all three
rather than leaving them here:

- **97.0% of works are cited exactly once.** That is real — 181 theses, ~20
  years, six research groups that barely share a bibliography — not a parser
  failure. It is why the ranked view defaults to a floor of 2 citing theses
  (`bibliography.DEFAULT_MIN_CITED_BY`), the same answer `collab.py` reached
  for its 4,242 co-project pairs. The full list stays reachable at `≥1`.
- **`cited_by` is a floor, not a count.** Tier-2 matching succeeds about half
  the time, so a work shown at 1 may genuinely be cited twice. The per-row
  `match_tier` column says which tier established each identity, because a
  count of 3 at tier `title` is a weaker claim than a count of 3 at `doi`.
- **`matcher_version` is stored per row.** The normalised key is frozen into a
  committed seed, so improving the matcher needs a rebuild *and* an app
  version bump — `uc_phd_app/seed.py`'s upgrade rule is what then carries the
  new seed to an already-installed workspace.

⚠️ **Counting this corpus with `grep` gives wrong answers.** 21 of the 181
`.md` files contain NUL bytes, so `grep` classifies them as binary and
silently prints nothing for them — no error, no warning. Pass `-a`, or read
the files in Python. Three separate "anomalies" in this feature's design notes
(a `full_text` field that looked missing, a references heading that looked
lost, two marker counts that disagreed) turned out to be that one cause.

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

The coverage gate is **100%, scoped to `uc_phd_app`**. `scraper/`,
`estudo_geral_extractor/` and `analysis/` are deliberately outside it;
`pyproject.toml` explains why next to the setting. (`analysis/` was at 100%
when it landed regardless — what actually holds it is the golden fixture,
not the gate.)

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
every UC DEI doctoral thesis, all-time, from
[estudogeral.uc.pt](https://estudogeral.uc.pt/) — the University of
Coimbra's institutional repository — into `estudo_geral/<handle>.md`, one
file per thesis, full YAML front-matter plus extracted body text. Stage 1 of
the Estudo Geral roadmap (Kanban target `uc-dei-phd-estudo-geral-kb`); later
stages (semantic index, `phd_knowledge_base` MCP, dashboard, search UI) are
separate cards and out of scope here.

## The population — 181, widened from an original 18

OAI-PMH's `set=com_10316_255` (the DEI community) `ListRecords`, full history
(no deposit-date floor), returns **891** records. Of those, **181** are
`dc:type=doctoralThesis` — that's the actual population, no publication-year
floor. `oai.py`'s `select_dei_doctoral_theses` does this filter and is
unit-tested against a fixture. CISUC's own community (`com_10316_27707`) has
zero theses — Estudo Geral files them under the department, not the research
centre.

The extractor originally floored the harvest at `from=2024-01-01` (deposit
date) and additionally required `dc:date` year >= 2024, landing 18 theses —
too few to rank anything (max 3 theses per supervisor across 32 distinct
supervisors). The corpus-widening card dropped both floors; see that card
for the measured facts that drove the decision.

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

# The pgvector prototype (P0)

`estudo_geral_extractor/index.py` — chunk, embed and semantically search the
`estudo_geral/*.md` extracts in the **workspace's own Postgres**, using the
`vector` extension that is already installed there.

**This is the P0 prototype and its table is disposable.** It is deliberately
NOT wired into `uc_phd_app/`: no route, no MCP tool, no plugin change, no
`migrations/` entry. Its job was to prove ingestion works end to end and to
produce a real latency baseline — the numbers below. The production path is
`uc_phd_app/store.py` + `estudo_geral_extractor/pgvector_index.py`, which own
`__documents` / `__chunks`; this one owns `__chunks_proto` and nothing else.

```bash
python -m estudo_geral_extractor.index ingest --report /tmp/ingest.json
python -m estudo_geral_extractor.index query "computational creativity" -k 5
python -m estudo_geral_extractor.index bench --reps 10
python -m estudo_geral_extractor.index stats
python -m estudo_geral_extractor.index drop      # the only thing that removes it
```

## Measured, 2026-09-23 — the P0 baseline

18 documents (17 with full text, 1 embargoed and therefore title-only),
**6 513 chunks**, table + HNSW index **64 MB**.

| | |
|---|---|
| Embedding | 3 540 s (59 min) — **1.8 chunks/s**, `threads=4`, host at load ~20 |
| Inserts | 13.4 s total for 6 513 rows, in 100-row batches |
| Model load | 1.9 s warm; 14.7 s on the first run (520 MB download) |

Query latency, 200 samples (20 queries × 10 repetitions), warm, host load ~11:

| stage | p50 | **p95** | p99 | max |
|---|---|---|---|---|
| vector search (Postgres only) | 2.2 ms | **5.7 ms** | 9.8 ms | 17.6 ms |
| query embedding (ONNX, CPU) | 28.3 ms | **50.4 ms** | 55.3 ms | 63.3 ms |
| end-to-end | 30.5 ms | **53.9 ms** | 59.0 ms | 75.5 ms |

Two things worth carrying forward:

- **The vector search is not the cost — the query embedding is**, by about
  9x. The 150 ms migration trigger was written as though pgvector were the
  risk; at this corpus size Postgres answers in single-digit milliseconds and
  the ONNX forward pass over the query string is the whole user-visible
  latency. Any future "is it still fast enough" check belongs on that stage.
- **HNSW is used at 6 513 rows, and it wins.** `EXPLAIN ANALYZE` picks
  `Index Scan using chunks_proto_embedding_hnsw` at **0.88 ms**; forcing the
  exact scan with `enable_indexscan = off` gives `Seq Scan` + top-N heapsort
  at **24.3 ms**. At the handful-of-rows scale the extension was first probed
  at, the planner correctly ignores the index — that is a property of the row
  count, not a broken index, and it stops being true well before this corpus
  size.

## It has to run inside the workspace container

An agent runner container shares `/opt/aw-workspace` but is a different
network namespace, and `aw-remote-host-postgres:5432` is not reachable from
it — the failure is `Connection refused`, which reads like a dead database
rather than a wrong netns. Run it as:

```bash
podman exec aw-remote-host-workspace sh -c \
  'cd /opt/aw-workspace/repos/aw-app-uc-phd && \
   FASTEMBED_CACHE_PATH=/opt/aw-workspace/.aw-workspace/data/aw-app-uc-phd/fastembed_cache \
   PYTHONPATH="${PYTHONPATH}:/opt/aw-workspace" <venv>/bin/python -m estudo_geral_extractor.index ...'
```

`PYTHONPATH="${PYTHONPATH}:/opt/aw-workspace"` **appends** — plain
`PYTHONPATH=/opt/aw-workspace` replaces the inherited `PYTHONPATH` (which
carries the venv's own site-packages), and every invocation then dies with
`ModuleNotFoundError: sqlalchemy`. The append is what makes
`src.apps.db_tables` importable on top of the venv, not instead of it; the
connection URL and schema come from `AW_WORKSPACE_DB_URL` /
`AW_WORKSPACE_SCHEMA`, which the workspace container already exports.

The repo's own `.venv` does **not** work there — it was built by a different
container and its `bin/python` symlinks `/usr/bin/python3.12`, which does not
exist in the workspace container (its interpreter is
`/usr/local/bin/python3.12`). Build the venv where it will run.

## Five things that will bite

1. **Never spell the table name.** The prefix is `app__aw-app-uc-phd__`, with
   hyphens, so an unquoted identifier is a syntax error — and
   `schema_translate_map` only rewrites SQLAlchemy `Table` constructs, never
   text SQL, so a raw string also lands in the wrong schema. Everything here
   goes through `src.apps.db_tables.DbTables` and its `{table}` placeholder.
2. **`vector` lives in schema `public`, the table lives in `workspace_aw`.**
   Every reference is written `public.vector(768)` /
   `public.vector_cosine_ops` rather than trusting `search_path` to stay
   `"$user", public`.
3. **`DbTables.execute` commits before a non-`SELECT` result can be read**, so
   `EXPLAIN` through it raises on iteration. `cmd_stats` uses the facade's
   `session()` instead (and `qualified_table()` for the name, so the quoting
   still isn't hand-written).
4. **A `pip_requires` failure is silent** (`src/apps/runtime.py:1905-1916`
   logs and returns). "The script started" therefore proves nothing about
   `fastembed`. `get_model()` raising is the only acceptance signal, and the
   first thing `ingest` prints is how long the model took to load.
5. **NUL bytes.** Three of the 18 theses carry NULs in their `pypdf`-extracted
   text (36 in total). Postgres `text` cannot store one, so they are stripped
   at the chunk boundary — see `_CONTROL_CHARS`. Left alone, ingestion dies
   with `DataError` partway through a document, after the embedding cost for
   that document has already been paid.

## Embeddings

`nomic-ai/nomic-embed-text-v1.5` via `fastembed` (ONNX, no PyTorch), 768-dim,
task-prefix aware (`search_document:` when indexing, `search_query:` when
querying) — the same model the `kb` app uses (`apps/kb/kb_app/kb_pg.py`), on
purpose, so the two indexes stay comparable.

The model is ~520 MB on first load. `FASTEMBED_CACHE_PATH` defaults to `/tmp`,
which means re-downloading it on every container restart; point it at
`.aw-workspace/data/aw-app-uc-phd/fastembed_cache`, which survives.

`threads=4` is measured, not guessed: on this host (12 cores, load ~20 from
the rest of the workspace) 1 thread gives 0.83 chunks/s, 2 gives 1.50, 4 gives
2.14 and **8 gives 1.25** — more ONNX intra-op threads than the box has
*spare* cores is slower, not faster (4 over 8 is a 1.7x throughput gap).

**That gap is a `batch_size=8` indexing measurement — it does not transfer to
per-query latency.** `estudo_geral_extractor/index.py:101` pins `threads=4`
from the benchmark above; `uc_phd_app/store.py`'s `embed_query` (used on
every `/api/search` call, `batch_size=1`) passes no `threads` argument at
all. A controlled A/B on the query-embedding stage specifically (same host,
same query set) measured only a ~1.15x p95 difference between the two —
batching is most of where extra threads pay off, and a single query is the
`batch_size=1` case where they mostly don't. Worth writing down, not worth
pinning `threads` on the query path for a 1.15x that the loaded-host noise
above is the same order as.

Chunking is 1500 characters with a 200-character overlap, both boundaries
snapped to whitespace so no chunk opens or closes on a word fragment. 1500 is
the `kb` app's own per-input embedding cap — there it *truncates* a document,
here it *sizes a chunk*, which is why a 500 KB thesis keeps all of its text
instead of losing everything after the first page.

`ingest` is resumable: a document whose chunk count already matches what is in
the table is skipped without being re-embedded. `ON CONFLICT DO NOTHING`
protects the insert; this protects the hour of CPU.

## Fit — matching a personal interest profile against the corpus

`#/fit` answers a different question from `#/search`. Search ranks *passages*
against a question you type; Fit ranks *theses* against a profile that
persists, and returns the people who supervised them. Two design points look
like preferences and are actually measurements — changing either silently
degrades the screen:

**The profile is a list of interests, each embedded separately.** The
committed seed (`profile/research_interests.md`) carries an `interests:` list
in its front matter plus the prose it was drawn from in the body. Only the
list is embedded; the prose is displayed as context. Embedding the prose as
one vector instead ranks the human-factors theses 1–2–3 and drops the
privacy/security-architecture thesis out of the top 10 of 18 — half that
paragraph is career narrative, and averaging four distinct interests into one
768-dim vector lands the query near-equidistant from everything (top1–top5
spread 0.022, against 0.081 for a single facet). Four separate queries fused
by **max** put 4 of the top 5 on the stated interests instead of 2.

**Ranking is per-thesis, not per-chunk.** `/api/search` ranks the `chunks`
table: 6609 chunks across 18 theses, 858 for the longest down to 8 for the
embargoed one, with the top 3 theses holding 29.6% of all chunks. No `k` over
chunks guarantees 5 distinct theses. `migrations/0002` adds one
`abstract_embedding` per thesis (title + both abstracts) so "≥5 distinct
theses" is structural. Evidence passages still come from `chunks`, so the
ranking is balanced while the quoted text stays real.

What the screen deliberately does **not** show: a percentage match score (all
18 are computing PhDs and score in a narrow band — top-1 to top-5 spans 0.007
for the seeded profile, so "67%" would be precision that does not exist; it
shows rank, the matched interest and the passage), any research-group filter
(a thesis's group is now discriminating — see docs/thesis-attribution.md — but
this screen ranks theses by a research profile, and a group filter on top of
that would narrow an already-narrow result to nothing), any supervisor
ranking (the ceiling is 3 theses), and any generated prose.

### Editing the profile

The committed file is a **versioned baseline**; the live editable copy lives
in the data dir, because the package directory is wiped wholesale on every app
update. `GET /api/profile` reports whether the two have diverged so the screen
can offer a reset — the same seed/live split `cisuc.sqlite3` has.

### Re-indexing after migration 0002

`migrations/0002` adds `abstract_embedding` as a NULL column to rows that are
already fully indexed. The loader's resume check therefore tests **both** the
content hash and the presence of that vector (`VectorStore.needs_reindex`) —
on the hash alone every thesis would be skipped, every vector would stay NULL,
and the Fit screen would answer "no matches" while looking perfectly healthy.
When only the vector is missing, `ingest` backfills just that rather than
re-embedding 6609 chunks:

```bash
aw-workspace-cli uc-phd-index ingest     # backfills abstract vectors in place
aw-workspace-cli uc-phd-index status     # prints matchable_on_fit=N/N
```

`ingest` warns on stderr if any thesis ends up without an abstract vector,
since such a thesis ranks nowhere on Fit however well-chunked it is.
