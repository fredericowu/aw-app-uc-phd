# Migration plan — `uc-dei-phd` → `aw-app-uc-phd` (private aw-workspace app)

Architect decision for Kanban card `feature:aw-app-uc-phd-conversion`
(page `3e45bf3b-9510-811d-8d16-ebf126984c0a`). Written 2026-09-23.

Everything below is grounded in files that exist today; paths are cited so a
Coder can disagree with a specific line rather than with a vibe.

---

## 1. The approach, in five sentences

Keep this repo and its git history, rename the directory to
`repos/aw-app-uc-phd`, and **graft `aw-app-template`'s current skeleton onto
it** rather than starting a fresh template checkout and copying the data in.
Make it a **Tier-1 (`inprocess`) app** whose backend is one mode-agnostic
`build_routes()` FastAPI sub-app serving JSON from the existing SQLite file,
plus a **self-hosted React SPA served by that same sub-app**, surfaced through
a `managed_app` window — **not** a `component`-mode frontend bundle.
The SQLite file is **seeded from the repo into the app's own data dir on first
activate** and read from there, because an app's installed package dir is
wiped on every update.
Distribution is the **private** path that already works in this workspace:
a private GitHub repo + a release workflow pointed at
`tekflox/aw-marketplace-private`, which this workspace already has registered
as a marketplace source.
The data layer stays **one SQLite file with idempotent
`CREATE TABLE IF NOT EXISTS` schema**, and the HTTP surface is split by
domain, so the researchers/publications graph from the sibling card lands as
new tables + a new router instead of a rewrite.

---

## 2. The decision that shapes everything else: no `ui:code`

The template's default frontend is `contributes.frontend.mode: "component"`
(`repos/aw-app-template/aw-app.json:44-47`), which needs the `ui:code`
permission. `ui:code` is **high risk**
(`src/apps/capabilities.py` — the catalog table in
`skills/aw-create-app/SKILL.md:197`), and `filter_grants` refuses every
high-risk capability to an app that is not `signed`
(`src/apps/capabilities.py:95-120`).

`signed` is computed **only** from membership of the *official public*
catalog:

- `src/apps/catalog.py:463-497` — `is_marketplace_app` skips any entry whose
  `_source` is not `tekflox/aw-marketplace@master`, and its docstring says in
  so many words that an app from a user-added private source must **not** be
  treated as signed locally.
- `repos/aw-backend/src/api/routes/app_installs.py:163` — the cloud registry
  does the same: `signed = is_marketplace_app(app_id, row.repo)` against
  `tekflox/aw-marketplace` only (`src/api/marketplace_catalog.py:31,79-91`).

Live confirmation in this workspace: `agents-platform-test-fixtures` is
listed only in `tekflox/aw-marketplace-private@master` and reports
`signed: false` in `GET /api/apps`.

So: **a genuinely private app must be designed to need zero high-risk
capabilities.** A `component`-mode bundle in a private app is the worst
possible failure here, because a refused `ui:code` does not error — the
window chrome still draws and every body is empty, which reads as a bug in
the app (this exact failure is on record in this workspace).

The replacement costs nothing and is what the template itself recommends for
a full app surface (`repos/aw-app-template/README.md:200-213`,
`repos/aw-app-template/docs/window-contract.md:8-39`):

```
contributes.windows[0].body = { "type": "managed_app", "kind": "web", "path": "/" }
```

That renders as an `app_iframe` widget pointed at the app's **own subdomain**
(`repos/aw-workspace-ui/src/components/AppWindowBody.jsx:11-32`,
`repos/aw-workspace-ui/src/apiBase.js:127-129`). Tier-1 apps get that
subdomain: `_attach_mount` registers a `Host("<app_id>.app.{_:str}")` route
onto the **same** guarded ASGI sub-app as the `/api/apps/<id>` mount
(`src/apps/runtime.py:1161-1192`), and core explicitly supports
`managed_app` on an `inprocess` app
(`src/tests/unit/apps/test_manifest.py:196-203`,
`src/apps/manifest.py:418-433`).

Bonus: because the SPA is a normal page on its own origin and not a plugin
bundle in the host SPA, it is **not** bound by the "exactly one shared React
instance" rule (`skills/aw-create-app/SKILL.md:501-539`). The frontend may
bring its own React and its own charting library.

**Falsifiable claim, and one caveat:** `crispal` is also listed only in the
private catalog yet currently reports `signed: true` and runs Tier-2 with
the high-risk `containers:manage`. That contradicts the code path above and
I could not explain it in the time available — most likely a stale registry
row from before trust re-derivation, since `signed` is only recomputed on an
install/update POST. **The design above is deliberately immune to the
answer**: it works whether the app ends up signed or not. Do not "simplify"
it back to `ui:code` on the strength of the crispal observation.

---

## 3. Tier: Tier-1 `inprocess`

- Everything the app needs is already in the workspace image: Python ≥3.11,
  FastAPI, stdlib `sqlite3`. No extra binaries, no browser, no native deps.
- Tier-2 requires `containers:manage`, which is **high risk**
  (`skills/aw-create-app/SKILL.md:191`) — i.e. per §2, likely refused for a
  private app. Tier-2 is not merely more expensive here, it may be
  unavailable.
- Tier-2 would also add an image build + publish workflow and a GHCR package
  for what is a read-mostly 1.9 MB SQLite file.

**Permissions requested: `routes:register`, `fs:workspace-data`. That is
all.** Both are low-risk, so nothing is refused whatever `signed` resolves
to.

- Drop the template's `commands:install`, `ui:code`, `ui:slots:core.nav`.
- Do **not** request `db:own-tables` — the app owns its own SQLite file, not
  workspace tables.
- Do **not** request `net:outbound` in v1 — see §7, re-scraping stays a
  manual CLI run.
- Honest note: `fs:workspace-data` has **no Tier-1 facade**
  (`src/apps/base.py:523-532` lists the facade map; there is no `fs` entry).
  For Tier-1 it is declaration-only — it is enforced only for Tier-2 volume
  expansion (`src/apps/runtime.py:1634-1655`). Declare it anyway because the
  app genuinely writes under its data dir and the manifest should say so.

---

## 4. Rename: evolve this repo, do not start a fresh checkout

The card left this open. **Decision: keep this repo, rename the directory,
copy the template's skeleton in.**

Why:

- The template's own "Use this template" path creates a repo with **no git
  history and no fork relationship**
  (`repos/aw-app-template/README.md:25-27`) — so "born from the template" is
  a claim about *structure*, not ancestry, and starting fresh buys no
  lineage that a skeleton copy doesn't.
- This repo's history is worth keeping: 6 commits carrying the scraper's
  real design decisions and the just-delivered graph-db plan
  (`a67ce45`, `docs/graph-db-plan.md`).
- Structural equivalence is checkable: after the graft, a Coder can diff the
  skeleton against `repos/aw-app-template` and a QA agent can run the
  template's own `tests/validate_manifest.py`, which is fully generic
  (`repos/aw-app-template/README.md:79-80`).

**Runner-up (rejected):** fresh `gh repo create --template` checkout, migrate
`scraper/`, `sql/`, `data/`, `docs/` into it. Cleaner provenance, but throws
away the history and makes the "did anything get dropped in the move?"
question un-auditable. Reconsider only if the graft leaves the tree visibly
un-template-like.

### Step 0 — commit the dirty tree first (blocking)

`git -C repos/uc-dei-phd status` is **not clean** right now:

```
 M analysis/build_presentation.py
 M analysis/presentation.html
?? analysis/problem_summaries.py
?? sql/top_projects_per_group.sql
```

That is the delivered-but-uncommitted output of the already-**Done** card
`feature:uc-dei-phd-top10-per-group`. Commit it **before** touching anything
else, or the rename buries work that is already signed off.

### What moves, what is added, what is deleted

| Path today | Fate |
|---|---|
| `scraper/` (`db.py`, `detail.py`, `listing.py`, `parse.py`, `run.py`, `schema.sql`) | **Moves unchanged.** Still the writer of the DB; still runnable standalone. |
| `data/cisuc.sqlite3` (1.9 MB) | **Stays committed**, but becomes a *seed* — see §5. |
| `sql/*.sql` (9 files) | **Moves unchanged and stays load-bearing** — see §6. |
| `tests/test_parse.py`, `tests/test_detail_parser.py`, `tests/fixtures/*.html` | **Move unchanged.** |
| `docs/uc/*.pdf`, `docs/graph-db-plan.md`, this file | **Move unchanged.** |
| `analysis/build_presentation.py`, `analysis/problem_summaries.py`, `analysis/presentation.html` | **Deleted after the frontend covers their content.** `problem_summaries.py` holds real per-project summarisation logic — check whether the SPA needs it before deleting; if it does, it moves into the app package instead. |
| `requirements.txt`, `.venv/` | `requirements.txt` stays for the scraper. The app's own runtime deps go in `runtime.pip_requires` (expected: empty). |
| — | **Added from the template:** `aw-app.json`, `pyproject.toml`, `requirements-dev.txt`, `.github/workflows/{release,test,security-scan}.yml`, `tests/validate_manifest.py`, `SECURITY.md`, `ui/`, and the app package. |
| `scripts/`, `installer.py`, `system_clis`, `external-client/`, `examples/`, `docs/contributing-*.md`, `docs/host-power.md` | **Not copied.** This app installs no CLI and has no external client. |

### Renames (the template's own walkthrough, `README.md:34-91`)

- `template_app/` → `uc_phd_app/`
- `TemplateAppPlugin` → `UcPhdAppPlugin`
- manifest `id` → `aw-app-uc-phd`, `runtime.entrypoint` →
  `uc_phd_app.plugin:UcPhdAppPlugin`, `runtime.standalone.module` →
  `uc_phd_app`
- `contributes.routes[0].prefix` → `/api/apps/aw-app-uc-phd`
- the `aw-ws/1` `_DOMAIN` constant, if any socket survives, is the id with
  `-`→`_` **mechanically**: `aw_app_uc_phd`
  (`repos/aw-app-template/template_app/routes.py:98-100`)
- `SLUG` in `ui/src/*.js` and `uc_phd_app/__main__.py`
- Directory: `mv repos/uc-dei-phd repos/aw-app-uc-phd`

Grep for leftovers before declaring done:
`grep -rni 'template\|uc-dei-phd' --exclude-dir=.git .`

---

## 5. Where the data lives (the part that silently breaks if you get it wrong)

**Do not read the SQLite file out of the installed package dir.** An app's
package dir is deleted and re-fetched wholesale on update/uninstall —
`src/apps/runtime.py:1466-1472` documents the live incident where exactly
this wiped `aw-mcp-gateway`'s persisted token.

Rule:

1. `data/cisuc.sqlite3` stays committed in the repo as the **seed**.
2. On `activate(ctx)`, resolve the app data dir the way every other Tier-1
   app does — `<AW_WORKSPACE_HOME>/data/<app-id>`, matching the Tier-2
   `$AW_APP_DATA` expansion at `src/apps/runtime.py:1646` and the Tier-1
   precedent at
   `apps/agents-platform-runners/agents_platform_runners_app/skills_sync.py:51-55`.
   `AW_WORKSPACE_HOME` defaults to `/opt/aw-workspace/.aw-workspace`.
3. Copy the seed there **if the target does not exist**. Write a sibling
   `seed.json` recording the app version the copy came from.
4. On a later activation, if the packaged seed's version is newer than
   `seed.json`'s **and** the live DB has no `scrape_runs` row newer than the
   seed, re-copy. Otherwise leave the user's DB alone. This is the same trap
   `contributes.tasks`/`contributes.agents` fall into
   (`skills/aw-create-app/SKILL.md:339-354`) — copy-if-absent alone means a
   corrected dataset in v0.3.0 never reaches anyone who installed v0.1.0.
5. Serve every read over a **read-only** connection
   (`sqlite3.connect("file:...?mode=ro", uri=True)`), one per request,
   `check_same_thread=False` not needed if you do not share it.

At `AW_WORKSPACE_WORKERS>1` every worker activates the app independently
(`src/apps/runtime.py:1179-1188`). The seed copy must therefore be
atomic-and-idempotent: copy to a temp name in the same directory, then
`os.replace`. Two workers racing a naive `shutil.copy` onto the same path
produces a truncated database that opens fine and returns garbage.

---

## 6. Backend shape — keep the SQL files load-bearing

The single best property of the current repo is that **every figure traces
to a committed `.sql` file** (`analysis/presentation.html` says so in its own
subtitle). Do not re-express those queries as Python string literals. Load
them from `sql/` at request time (or once at import) and return their rows as
JSON.

One mode-agnostic `build_routes() -> FastAPI` with **relative** paths
(`skills/aw-create-app/SKILL.md:446-473`;
`repos/aw-app-template/template_app/routes.py:109-149` is the reference),
registered via `ctx.routes.register(...)` in `plugin.py` exactly as
`repos/aw-app-template/template_app/plugin.py:67` does.

Split by domain from day one — this is the cheap part of not painting the
data layer into a corner:

- `uc_phd_app/routes.py` — the factory; mounts the routers below, then the
  SPA **last**.
- `uc_phd_app/api/projects.py` — the v1 surface, one endpoint per existing
  SQL file plus list/detail:
  - `/api/coverage` → `sql/coverage.sql`
  - `/api/fill-rates` → `sql/fill_rates.sql`
  - `/api/groups` → `sql/projects_per_group.sql`
  - `/api/groups/{code}/top-projects` → `sql/top_projects_per_group.sql`
  - `/api/funding` → `sql/funding_breakdown.sql`
  - `/api/budget/by-group` → `sql/budget_by_group.sql`
  - `/api/budget/by-year` → `sql/budget_by_year.sql`
  - `/api/timeline` → `sql/start_date_timeline.sql`
  - `/api/coordinators` → `sql/top_coordinators.sql`
  - `/api/projects` — paged list, filter by group, free-text title search
  - `/api/projects/{id}` — detail, **including** the `project_fields_raw`
    rows (`scraper/schema.sql:37-46`), which is where `Keywords` and every
    other un-typed field lives
- `uc_phd_app/db.py` — read-only connection + `sql/` loader.
- Later, from the sibling card: `uc_phd_app/api/people.py`,
  `api/publications.py`, `api/graph.py`. Nothing in v1 needs to change for
  those to land.

**Gotcha to write down in the code:** the SPA is mounted with
`StaticFiles(directory=..., html=True)` at `/`, and a Starlette `Mount("/")`
matches *everything*. It must be registered **after** every API router or it
swallows them. Cover this with a test that asserts `/api/coverage` returns
JSON with the static mount present.

`GET /healthz` returning the DB path, row counts and the seed version is
worth 10 lines — it is what QA and `doctor` will actually poke.

**Drop the template's `/ws/echo`.** This app has nothing to stream and an
unused socket is a maintenance liability. If a later feature needs one, the
template's handler is the reference to copy back in.

### Standalone mode

Keep `uc_phd_app/__main__.py` (`python -m uc_phd_app`). It is how the Coder
and the UX iteration loop run the SPA without a workspace, and it mounts the
same sub-app at the same prefix with no `IdentityGuard`
(`skills/aw-create-app/SKILL.md:603-636`). Bind `127.0.0.1` by default.

---

## 7. Frontend — a real SPA, served by the app

`ui/`, Vite + React, built to `ui/dist/`, served by the app's own sub-app.

- **`base: './'` in `vite.config.js`.** Absolute asset paths break on the
  `/api/apps/aw-app-uc-phd/` mount while working fine on the subdomain — and
  the subdomain is the one the window uses, so the breakage is invisible
  until someone opens the prefixed URL.
- The template's `vite.config.js` is dual-mode (lib-mode plugin bundle +
  standalone page). **Delete the plugin/lib mode entirely** — there is no
  `component` bundle here. Keep only the standalone build. Likewise delete
  `ui/src/plugin.js` and the `__AW_PLUGIN_HOST__` externals.
- The built `ui/dist/` **must be committed**, because the release pipeline
  ships the repo as-is and there is no npm build step in the install path.
  (`aw-app-template` itself commits `ui/dist` for this reason.) A stale
  committed `dist/` is the classic failure — add a CI check that a fresh
  `npm run build` leaves the tree clean.
- Charts: pick one library and use it for everything; follow the `dataviz`
  skill for palette/axis/legend rules. The old presentation shipped
  matplotlib PNGs as base64 data URIs — the point of this card is that they
  become real, interactive, filterable views.
- Everything in **English** (code, comments, UI), per this workspace's
  standing convention.

### Coverage floor — what the frontend must at least match

From `analysis/presentation.html`'s own section headings, plus the card's
explicit list. The new UI must cover all of these, and QA should check them
one by one:

1. **Coverage** — 400 total projects, 398 detail pages fetched, 2 with no
   detail page, 0 NULL titles, 400/400 `scrape_targets` terminal, and the
   site's own `totalData` at scrape time.
2. **Field completeness** — per-field fill rate.
3. **Research groups** — projects per group, across all 6 (AC, bAI, CMS, IS,
   NCS, SSE), with the many-to-many honesty caveat (a project in 2 groups
   counts under both — `sql/budget_by_group.sql:1-2`).
4. **Top 10 projects per research group** — all 6 groups, ranked by
   `total_budget_amount DESC`, each row linking to its `detail_url`. The
   ranking metric is a documented proxy, not a given
   (`sql/top_projects_per_group.sql:1-3`) — say so in the UI.
5. **Funding** — funding-source breakdown.
6. **Budget** — by group and by year.
7. **Timeline** — start-date distribution.
8. **Coordinators** — top coordinators.
9. **Project detail** — new, and the thing the static presentation could
   never do: synopsis, dates, budgets, partners, keywords, groups, people,
   and the raw `project_fields_raw` pairs.

Re-scraping from the UI is **out of scope for v1** — that is why
`net:outbound` is not requested. Refresh stays `python -m scraper.run`
against the data-dir DB. If Frederico wants a refresh button, that is a
follow-up card and a new capability, not a silent addition here.

---

## 8. Manifest sketch

Tier-1; `id: aw-app-uc-phd`; `name` and `description` written as **product
copy**, not architecture notes (`skills/aw-create-app/SKILL.md:76-106`) — no
capability slugs, no ADR numbers, no migration history on the card.

- `runtime.entrypoint`: `uc_phd_app.plugin:UcPhdAppPlugin`
- `runtime.pip_requires`: `[]`
- `runtime.standalone`: module `uc_phd_app`, pick a free `default_port`
  (template uses 9400 — do not collide)
- `permissions`: `routes:register`, `fs:workspace-data`
- `contributes.routes`: prefix `/api/apps/aw-app-uc-phd`
- `contributes.windows`: one `managed_app` / `kind: web` / `path: /` window,
  `id` namespaced as `aw-app-uc-phd.main`
  (`repos/aw-app-template/docs/window-contract.md:33-39`)
- `config_schema`: **omit**. The framework injects `auto_start`,
  `auth_required` and `public` automatically for a managed app
  (`src/apps/manifest.py:435-465`), and the app has no knobs of its own.
  Leaving `auth_required` at its `true` default is what keeps the app
  visible only to signed-in workspace users — the runtime half of "privada".
- `contributes.skills`: **omit** for now. Add one only if the app grows a
  surface an agent should drive.
- `requires_ui_refresh: true`

Validate with the template's own generic validator:
`python tests/validate_manifest.py` — the schema is **not** copied into the
repo, it is found in a sibling `aw-marketplace` checkout
(`repos/aw-app-template/README.md:101-106`). Do not vendor it.

---

## 9. Private distribution — the explicit flag the card asked for

**Any GitHub remote created for this repo MUST be `--private`.** The
template's README documents `--public`
(`repos/aw-app-template/README.md:30`) and that default is wrong here.
Frederico said "privada".

```
gh repo create tekflox/aw-app-uc-phd --private --source=. --push
```

The repo has **no remote today** — verified, `git -C repos/uc-dei-phd remote
-v` is empty.

**Do not point the release workflow at the public catalog.** Copy
`repos/aw-app-crispal/.github/workflows/release.yml`, not the template's.
The difference is two lines and the header comment on the crispal file
explains why in detail — the shared `app-release.yml` used to hardcode
`tekflox/aw-marketplace` and auto-merge first-party sync PRs, which came one
granted org secret away from publishing a private store's credentials into
the public marketplace:

- `catalog_repo: tekflox/aw-marketplace-private`
- `secrets: inherit` (not the template's explicit
  `MARKETPLACE_SYNC_TOKEN:` mapping)

That catalog is **already registered and working in this workspace** —
`GET /api/marketplace/sources` returns source `tekflox-private`
(`tekflox/aw-marketplace-private@master`, `auth_type: github_pat`,
`has_credential: true`, enabled), and `GET /api/apps/-/catalog` currently
serves 2 apps from it. So there is nothing to set up, only an entry to add.

First push will still fail on `MARKETPLACE_SYNC_TOKEN is required` because a
brand-new repo is not on that org secret's allowlist — fix it with the
`GH_RUNNERS_ADMIN_TOKEN` PUT documented at
`skills/aw-create-app/SKILL.md:812-833` rather than making Frederico click
through the org-admin UI. 204 = added.

**Installing it into the public catalog instead — rejected.** Listing a
private repo in `tekflox/aw-marketplace` would make the app `signed` (and
therefore re-enable `ui:code`), but it publishes the app's name and
description to every workspace on the platform and opens a public sync PR.
"Privada" rules it out. This is the trade we are making consciously: we give
up high-risk capabilities to stay genuinely private.

---

## 10. Tests and CI

Copy the template's harness and adapt it
(`repos/aw-app-template/README.md:135-148`):

- `tests/validate_manifest.py` — generic, copy verbatim, no edits.
- `tests/test_routes.py` — `TestClient` over `build_routes()` against a
  **temporary fixture SQLite** built from `scraper/schema.sql` with a handful
  of rows. Do not test against the real 400-row DB; the assertions become
  unreadable and the fixture stops proving anything about schema drift.
  Include the route-ordering assertion from §6.
- `tests/test_plugin.py` — `activate()`/`deactivate()` against a lightweight
  `ctx` double, **including the seed-copy logic**: absent target → copies;
  present target → does not clobber; concurrent activate → no partial file.
- `tests/test_main.py`, `tests/test_standalone.py` — adapt from the template.
- `tests/test_parse.py`, `tests/test_detail_parser.py` — keep as-is.
- `tests/standalone_test.sh` — the template's version installs a CLI; this
  app has none. Either delete it or repurpose it to boot standalone mode and
  curl `/healthz`.

**Coverage gate — a deliberate, stated narrowing.** The template runs
`pytest --cov=template_app` with `fail_under = 100`
(`repos/aw-app-template/README.md:266-282`). Keep **100%**, but scope
`--cov` to `uc_phd_app` only. `scraper/` is a network-bound one-shot tool
whose parsers already have fixture-based tests; holding it to 100% would
either produce fake tests or push the floor down for the app code that
actually matters. This narrowing must be written into `pyproject.toml` with
that reason next to it, not left for someone to discover.

---

## 11. Install and verify — via the marketplace, not a sideload

`skills/aw-create-app/SKILL.md:773-810` is emphatic and it is right:
`POST /api/apps/install {package_dir}` wins for a few minutes and then the
reconciler converges back to the catalog, logging nothing a caller sees.

The loop is: commit → push → release CI tags → the `chore(sync)` PR lands in
`tekflox/aw-marketplace-private` → wait until the **workspace's own**
`GET /api/apps/-/catalog` serves the new version (raw-CDN lag is ~5 min, and
polling that endpoint is the check — not GitHub's) →
`aw-workspace-cli marketplace install aw-app-uc-phd --update`.

Then:

- `aw-workspace-cli doctor` — non-zero exit means something is silently
  degraded. Run it *before* debugging anything that looks wrong.
- `GET /api/apps` — confirm the app is listed, and **record what `signed`
  and `refused_permissions` actually say**. If `permissions` came back
  reduced, say so; do not paper over it.
- Open the window from the Apps grid and confirm the body renders (an empty
  body with intact chrome is the §2 failure mode).
- `GET /api/apps/aw-app-uc-phd/healthz` and one data endpoint.

---

## 12. Accommodating the publications graph (sibling card)

The Product Owner's plan is **delivered**: `docs/graph-db-plan.md` in this
repo, commit `a67ce45`, summarised in the comments of card
`3e45bf3b-9510-819b-a2c3-f5ed70ffb5d3`. Its relevant conclusions:

- Graph model **over the existing SQLite**, analysed with NetworkX — not
  Neo4j. ~724 researchers, ~354 publications, ~2k edges.
- Researchers from the live CISUC People feed; areas reuse the existing 6
  `research_groups`; publications from the CISUC feed (calendar 2025+2026).
- Authorship read from a per-person publications endpoint, so no author-name
  matching.

What this plan does to stay compatible, at zero cost today:

1. **One SQLite file, idempotent schema.** `scraper/schema.sql:1-2` already
   applies `CREATE TABLE IF NOT EXISTS` on every run. New tables (`people`
   extensions, `publications`, `publication_authors`, …) append; no
   migration framework needed.
2. **Domain-split routers** (§6), so `api/people.py` / `api/publications.py`
   / `api/graph.py` are additive.
3. **The data dir, not the package dir** (§5) — a graph scrape writes to a
   file that survives app updates.
4. **No `net:outbound` in v1** — the graph scraper runs as a CLI against the
   same DB, exactly as the projects scraper does. It does not need to be an
   app route to land here.

**This card does not block on that build.** Nothing above requires the graph
work to exist.

---

## 13. What this design makes harder later

Name the doors it closes, so nobody is surprised:

- **No `ui:code`, ever, while the app stays private.** The app can never
  contribute a nav pill, a slot component, or anything rendered *inside* the
  host SPA. Everything lives in its own iframe. Going public later is what
  would unlock that, and it is a real decision, not a flag flip.
- **No Tier-2, for the same reason** (`containers:manage` is high-risk). If
  the graph work ever wants a real graph engine, it cannot be a sidecar
  container of this app while the app is private. The Product Owner's plan
  already argues against Neo4j on its own merits, so this is currently free
  — but it stops being free the day that changes.
- **The iframe is cross-origin.** The host cannot inject styles, theme
  variables, or scroll behaviour into it (documented in this workspace for
  Tier-2 app iframes; the mechanism is identical here). The SPA owns its own
  theming and will drift from the workspace's look unless deliberately kept
  in line.
- **Committed `ui/dist/`** makes every frontend change a two-artifact commit
  and makes "the UI is stale" a silent failure mode. The CI clean-tree check
  in §7 is not optional garnish.
- **Committing the 1.9 MB SQLite seed** puts binary data in git history.
  Fine at this size and cadence; it stops being fine if the graph data lands
  as another 20 MB and the file is re-committed on every scrape. If that
  happens, move the seed to a release asset.
- **Keeping this repo's history** means the repo is not byte-identical to a
  fresh template checkout, so "does it match the template?" stays a judgement
  call rather than a diff against an empty tree.

---

## 14. Risks for the Coder — the non-obvious ways this breaks

1. **A refused capability does not raise.** `filter_grants` silently drops
   it and the app activates anyway. The only place you find out is
   `GET /api/apps` (`permissions` / `signed`) and the `capability:denied`
   journal entry (`src/apps/base.py:578-583`). Check it explicitly; no test
   will catch it.
2. **`StaticFiles` mounted at `/` swallows every API route registered after
   it.** Order matters, and the failure looks like "the API returns the
   index page" rather than a 404.
3. **Absolute asset paths work on the subdomain and 404 on the prefixed
   mount.** Since the window uses the subdomain, this ships broken and
   nobody notices. `base: './'`.
4. **The package dir is wiped on update.** Anything written next to the code
   is gone at the next version bump, with no error
   (`src/apps/runtime.py:1466-1472`).
5. **`AW_WORKSPACE_WORKERS>1`: activate runs once per worker.** The seed
   copy must be atomic; a naive copy race yields a truncated DB that opens
   without complaint.
6. **Sideloading lies.** It works, then the reconciler reverts it, silently
   (§11). A green sideload proves nothing about the real install path.
7. **The first push's CI failure is expected**, not a bug in your work —
   the `MARKETPLACE_SYNC_TOKEN` allowlist (§9). Fix it, then
   `gh workflow run release.yml` and confirm green before reporting done.
8. **`config` has been silently lost across a reinstall before**, and every
   route kept answering 200 (`skills/aw-create-app/SKILL.md:802-806`).
   Re-check after install.
9. **The dirty working tree (§4 step 0)** — commit it first or you will lose
   an already-signed-off delivery inside a rename diff.
10. **`repos/` is shared by concurrent agents.** Stage this repo's changes
    by explicit path; a bare `git add .` at the workspace root can pick up
    somebody else's work. (The app repo is its own git repo, so the risk is
    mainly in the workspace-level tree, not here — but the `mv` itself is
    visible to every other session.)
