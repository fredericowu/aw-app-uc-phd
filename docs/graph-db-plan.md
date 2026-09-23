# Graph DB plan — researchers × research areas × publications (last 2 years)

Status: **plan awaiting Frederico's approval**. Nothing here is built yet.

Scope of this document: where each entity comes from, what the graph looks
like, what technology to use, and the sequenced collection steps. Every
source claim below was **probed live against cisuc.uc.pt on 2026-09-23**,
not assumed — the numbers are real responses.

---

## 0. The headline finding

The CISUC site exposes everything needed, in structured JSON, behind the
same Laravel + Vue + CSRF recipe the projects scraper already uses. Most
importantly:

**Authorship does not have to be inferred from author-name strings.**

The publications listing only gives a pre-formatted citation with
abbreviated authors (`"J. Alves, P. Sousa, T. Cruz and J. Mendes, <i>A
Multi-Agent...</i>, 2026"`). Matching `J. Alves` back to one of 724 people
would be guesswork, and it is the single thing that would have wrecked the
data quality of this graph.

It turns out each **person page carries a numeric id** and there is a
**per-person publications endpoint** that returns exactly that person's
publications, using the **same publication ids** as the global feed. So the
`AUTHORED` edge is read directly from the source, authoritatively, with zero
name disambiguation.

This finding is what makes the rest of the plan cheap and trustworthy.

---

## 1. Where each entity comes from

### Researchers → the live People feed (**not** the existing `people` table)

`POST https://www.cisuc.uc.pt/en/people` (CSRF recipe, `length: 1000`, not
capped) returns **724 rows in one request**, each with:

| field | use |
|---|---|
| `slug` | stable identity key (`/en/people/<slug>`) |
| `name` | display name |
| `membership` | Student / Integrated PhD Student / Integrated Researcher / Collaborator / Group Leader |
| `research_acronym` | **the area edge, free** — CMS/AC/NCS/SSE/IS/bAI |
| `formerMember`, `photo`, `url` | status + display |

**Recommendation: the live People feed is the Researcher spine. The existing
`people` table (475 rows) is a historical overlay, not a substitute.**

Trade-off, measured: only **293 of the 475** existing slugs appear in the
live feed. 182 are in our DB but not live (former members, or slug drift),
and 418 live people were never seen by the projects scraper. Reusing the
existing table alone would miss more than half the researchers; ignoring it
would throw away project participation history for 182 people. So: **join
on `slug`, keep both**, and flag each researcher as live / historical-only.

Two data-quality facts the build must handle rather than discover:
- 724 rows but **711 unique slugs** — there are duplicate rows; dedupe on slug.
- `formerMember` is **not a clean boolean**: values seen are `'false'` (413)
  and `'active'` (311). Do not write `if formerMember:` against it.
- **183 of 724 people (~25%) have no `research_acronym`** (empty or null).
  A quarter of researchers will have no `IN_AREA` edge from this source.
  That is a real coverage gap, not a bug — see §5.

### Research areas → reuse the 6 groups, already in the DB

The site's own publication filter uses exactly the 6 groups already in our
`research_groups` table (CMS=2, AC=3, SSE=4, NCS=5, IS=6, bAI=7 — note the
numeric ids are the site's filter values, worth storing alongside the codes).

**Recommendation: areas = the 6 CISUC research groups. No topic modelling.**

This is a deliberate decision, not a default. The alternative — deriving
fine-grained topics via keywords or NLP over titles — is a much larger piece
of work whose output is fuzzy and unverifiable. The 6 groups are
authoritative, free, and directly filterable on the server. We already have
919 rows in `project_keywords` if a second, finer layer is ever wanted; that
is explicitly deferred (see §6).

### Publications → the CISUC publications feed. **Not** an external API.

`POST https://www.cisuc.uc.pt/en/publications` — same recipe. Live numbers:

- **7,676 publications** all-time
- server-side filters: **`research-group`**, **`type`** (9 kinds), **`year`** (1979–2026)
- `length: 1000` is **not capped** — each slice returns in one request

Year volumes, measured: **2026 → 110, 2025 → 244**, 2024 → 304.

**Recommendation: use the CISUC feed as the sole publication source for v1;
do not add DBLP/OpenAlex/Scopus/Scholar now.** The card flagged an external
bibliographic API as an open question — here is the answer. An external
source buys citation counts and richer metadata, but costs a second
identity-resolution problem (matching CISUC publications to external records
by fuzzy title), and every external source has its own coverage gaps for
Portuguese venues. The CISUC feed already gives authoritative area and
authorship links, which is precisely what a *correlation* graph needs.
DOIs are present on many records and are the clean join key **if** enrichment
is wanted later — so v1 should store `doiLink` verbatim to keep that door open.

### What "last 2 years" concretely means

**The source only has year granularity — there is no month/date field.** A
rolling 24-month window (Sep 2024 → Sep 2026) is therefore *not possible*
from this source.

**Recommendation: "last 2 years" = calendar years 2025 + 2026 = 354
publications.** Adding 2024 is one extra filter call (→ 658 total) if
Frederico prefers a wider window; the collector should take the year list as
a parameter so this is a config change, not a code change.

---

## 2. Graph schema

### Nodes

| Node | Key | Main attributes | Source |
|---|---|---|---|
| `Researcher` | `slug` | name, membership, is_active, is_live, cisuc_user_id | People feed (+ existing `people`) |
| `Area` | `code` (CMS/AC/…) | name, site_filter_id | existing `research_groups` |
| `Publication` | `id` (site's own) | title, year, type, venue, doi, pdf_link, headline_raw | Publications feed |
| `Venue` | normalised name | — | parsed from headline (low confidence — see §5) |
| `Project` | existing `projects.id` | already populated | existing DB |

### Edges

| Edge | From → To | Source | Confidence |
|---|---|---|---|
| `AUTHORED` | Researcher → Publication | **per-person endpoint** | **authoritative** |
| `MEMBER_OF` | Researcher → Area | `research_acronym` | authoritative (75% coverage) |
| `PUB_IN_AREA` | Publication → Area | `research-group` filter | authoritative, **many-to-many** |
| `CO_AUTHORED` | Researcher ↔ Researcher | **derived** from shared publications | derived, weighted by count |
| `WORKED_ON` | Researcher → Project | existing `project_people` (coordinator/researcher) | authoritative |
| `PROJECT_IN_AREA` | Project → Area | existing `project_groups` | authoritative |
| `PUBLISHED_IN` | Publication → Venue | parsed | low |

`CO_AUTHORED` is deliberately **derived, not stored as a source fact** — it
is a projection over `AUTHORED`, and materialising it is a build decision,
not a collection one.

**Publications belong to multiple areas.** Measured: the six per-group counts
for 2025 sum to 270 against a true total of 244. Anything that sums per-group
counts to get a total will over-count by ~10%. Same many-to-many shape the
projects data already has.

---

## 3. Technology: a graph model over the existing SQLite. Not Neo4j.

**Recommendation: extend the existing `data/cisuc.sqlite3` with `nodes` and
`edges` tables, and do analysis/visualisation in NetworkX, exporting to
GraphML/GEXF for Gephi if a visual is wanted.**

Reasoning:

- **The graph is tiny.** ~724 researchers, ~354 publications, roughly 1.5–2k
  edges. This is four orders of magnitude below where a graph engine starts
  paying for itself. NetworkX holds it in memory without noticing.
- **This repo is a single-user, offline artefact** — the README says so
  explicitly: no deploy, no scheduling, own `.venv`. Neo4j means a container,
  a port, a volume, a backup story and a service to keep alive, for a dataset
  that fits in a spreadsheet. That cost is real and recurring; the benefit is
  zero at this size.
- **Consistency beats novelty here.** The projects data, the SQL analysis
  files and the presentation pipeline are all already SQLite-based. A second
  datastore would split the data and mean no single query can join
  publications to projects.
- Recursive/path queries — the one thing Cypher genuinely does better — are
  available via SQLite recursive CTEs, and at this size, simply doing it in
  NetworkX is easier still.

*This is a recommendation with its reasoning, and a genuine product
constraint (stay single-file and offline). The final call on table layout
and library choice is the Architect's.*

---

## 4. Collection steps, sequenced

Each step is independently runnable and idempotent, following the existing
scraper's pattern (its `scrape_runs` / `scrape_targets` bookkeeping should be
reused so coverage is provable rather than asserted).

1. **Extend the schema** — add publication/node/edge tables alongside the
   existing ones. No change to existing tables beyond additive columns.
2. **Collect people** (1 request). `POST /en/people`, `length:1000` → 724
   rows. Dedupe to 711 slugs. Upsert into `people`, marking which slugs are
   live vs historical-only. Writes `Researcher` nodes and `MEMBER_OF` edges.
3. **Resolve person → numeric id** (711 requests). `GET /en/people/<slug>`,
   regex out `params.userFilter = '<digits>'`. Store `cisuc_user_id`.
   *This is the step that unlocks authorship — it must run before step 5.*
   Politely rate-limited; expect some 404s (verified: `/en/people/penousal`
   404s, so slugs in our DB are not all resolvable) — record them as
   `scrape_targets` failures rather than crashing.
4. **Collect publications for the target years** (1 request per year, plus
   6 per year for group attribution = ~14 requests). `POST /en/publications`
   with `year` filter → `Publication` nodes; then once per
   `(year, research-group)` → `PUB_IN_AREA` edges.
5. **Collect authorship** (~711 requests). `POST /en/people/publications`
   with `userFilter=<id>` → that person's publications. Keep only the
   publication ids already collected in step 4; that intersection is the
   `AUTHORED` edge set.
6. **Derive `CO_AUTHORED`** (no network). Self-join `AUTHORED` on publication
   id, weight = shared publication count.
7. **Reconcile and report coverage.** Cross-checks that must be run and
   published, not skipped:
   - count of `Publication` nodes == sum of the per-year `totalData` (354)
   - every `AUTHORED` publication id exists as a `Publication` node
   - how many of the 354 publications have **zero** CISUC author resolved
     (see §5) — report the number, do not hide it
   - how many researchers have no `MEMBER_OF` edge (expect ~183)

Total network cost: **~1,450 requests**, nearly all of them the two
per-person loops. At a polite 1 req/sec that is ~25 minutes. No browser, no
Playwright.

---

## 5. Known risks and gaps — stated up front

1. **Orphan publications.** Authorship is collected person-by-person, so a
   publication whose CISUC authors are all former/unlisted members will end
   up with no `AUTHORED` edge. The size of this set is unknown until step 7
   measures it. It is a *coverage number to report*, not a failure — but if
   it turns out to be large, the graph's co-authorship layer is weaker than
   it looks and Frederico should know that before relying on it.
2. **~25% of researchers have no area.** Partial mitigation available at no
   extra cost: infer a researcher's area from the areas of their publications
   and projects. Recommended as a clearly-labelled *derived* edge
   (`MEMBER_OF_INFERRED`), never merged into the authoritative one.
3. **Venue parsing is unreliable.** The venue sits inside a free-text
   citation string with no consistent delimiter. Treat `Venue` as
   best-effort; keep `headline_raw` verbatim so it can be re-parsed later
   without re-scraping. (This mirrors the `project_fields_raw` decision the
   existing scraper already got right.)
4. **The site can change.** The projects scraper already hit one nasty
   surprise here. Every endpoint above is a private JSON API, not a
   contract — the collector should fail loudly on shape changes.
5. **2026 is a partial year.** It has 110 publications with the year still
   running, some likely forthcoming/in-press. Any "publications per year"
   trend chart must not present 2026 as a complete year.

---

## 6. Explicitly out of scope for v1

- **No external bibliographic enrichment** (DBLP / OpenAlex / Scopus /
  Google Scholar) — no citation counts, no h-index. `doiLink` is stored so
  this stays possible later.
- **No topic modelling / NLP-derived research areas.** Areas are the 6 groups.
- **No Neo4j or any separate graph service.**
- **No web UI, no API, no scheduling.** One-shot collector + queries, like
  the existing scraper.
- **No publications before the target years** — the other ~7,300 are
  reachable by one filter change, but collecting them is not this task.
- **No author-name string matching as an authorship source.** The per-person
  endpoint replaces it; fuzzy name matching must not silently creep back in
  as a "fallback", because it would pollute authoritative edges with guesses.
- **No analysis/presentation deliverable.** This card collects and models.
  What to *show* is a separate piece of work.

---

## 7. One open question for Frederico — non-blocking

Everything above is buildable as written; this only affects what gets
*emphasised*, not whether the plan works.

**How do you intend to use this graph?** The working assumption is
**PhD positioning**: finding who at CISUC is actively publishing in a given
area, who co-publishes with whom, and who would make a plausible supervisor
or collaborator. That assumption is what drives the emphasis on
`CO_AUTHORED`, on researcher `membership`, and on recency.

If instead the goal is, say, **institutional/bibliometric reporting**
(productivity per group, output trends), then citation counts matter a lot
more and the "no external enrichment" decision in §6 is the wrong call and
should be revisited before building.

If no answer comes, build to the PhD-positioning assumption.
