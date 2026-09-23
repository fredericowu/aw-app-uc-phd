-- Single source of truth for the DB shape. Applied idempotently via
-- `CREATE TABLE IF NOT EXISTS` on every run — see db.py:apply_schema.

CREATE TABLE IF NOT EXISTS projects (
    id                      INTEGER PRIMARY KEY,
    title                   TEXT NOT NULL,
    title_norm              TEXT NOT NULL UNIQUE,
    detail_url              TEXT,
    slug                    TEXT,
    scope                   TEXT,
    synopsis                TEXT,
    funding_raw             TEXT,
    partners_raw            TEXT,
    keywords_raw            TEXT,
    total_budget_raw        TEXT,
    total_budget_amount     REAL,
    total_budget_currency   TEXT,
    cisuc_budget_raw        TEXT,
    cisuc_budget_amount     REAL,
    cisuc_budget_currency   TEXT,
    start_date_raw          TEXT,
    start_date              TEXT,
    end_date_raw            TEXT,
    end_date                TEXT,
    listing_details         TEXT,
    listing_scope           TEXT,
    detail_fetched          INTEGER NOT NULL DEFAULT 0,
    detail_unavailable_reason TEXT,
    detail_http_status      INTEGER,
    first_seen_at           TEXT NOT NULL,
    last_scraped_at         TEXT
);

-- The catch-all: every (label, value) pair seen on a detail page, verbatim,
-- in document order. Nothing is lost here even if it never gets a typed
-- column — see README "what this makes harder later".
CREATE TABLE IF NOT EXISTS project_fields_raw (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    label       TEXT NOT NULL,
    ordinal     INTEGER NOT NULL,
    value_text  TEXT,
    href        TEXT
);
CREATE INDEX IF NOT EXISTS idx_project_fields_raw_project
    ON project_fields_raw(project_id);

CREATE TABLE IF NOT EXISTS research_groups (
    code TEXT PRIMARY KEY,   -- e.g. 'NCS', from the href /NCS
    name TEXT NOT NULL
);

-- Many-to-many: the site's own facet counts (478 memberships / 400 projects)
-- prove a project can belong to more than one group.
CREATE TABLE IF NOT EXISTS project_groups (
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    group_code  TEXT NOT NULL REFERENCES research_groups(code),
    PRIMARY KEY (project_id, group_code)
);

CREATE TABLE IF NOT EXISTS people (
    slug TEXT PRIMARY KEY,   -- from /en/people/<slug>
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_people (
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    person_slug TEXT NOT NULL REFERENCES people(slug),
    role        TEXT NOT NULL CHECK (role IN ('coordinator', 'researcher')),
    ordinal     INTEGER NOT NULL,
    PRIMARY KEY (project_id, person_slug, role)
);

CREATE TABLE IF NOT EXISTS project_keywords (
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    keyword     TEXT NOT NULL,
    ordinal     INTEGER NOT NULL,
    PRIMARY KEY (project_id, keyword)
);

-- partners_raw, parsed and classified. scraper/parse.py:split_partners
-- splits the free-text field; classify_partner() flags each as academic or
-- industry by a keyword heuristic (not verified per partner — see its
-- docstring). ordinal is the primary-key differentiator, not partner_name,
-- because the same partner name can legitimately repeat within one raw
-- string (e.g. mentioned in a role note and again plainly).
CREATE TABLE IF NOT EXISTS project_partners (
    project_id   INTEGER NOT NULL REFERENCES projects(id),
    partner_name TEXT NOT NULL,
    partner_type TEXT NOT NULL CHECK (partner_type IN ('academic', 'industry')),
    ordinal      INTEGER NOT NULL,
    PRIMARY KEY (project_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_project_partners_project ON project_partners(project_id);

-- === Estudo Geral thesis facts ==============================================
-- The identity spine: the thesis corpus promoted from 18 YAML front matters
-- re-parsed on every request into tables that sit next to the people /
-- project_people / project_groups rows they actually join against. Built
-- offline by `python -m analysis.build_thesis_facts` and committed inside the
-- seed, the same way the projects data is; the app opens this database
-- mode=ro and never writes it.

CREATE TABLE IF NOT EXISTS theses (
    handle      TEXT PRIMARY KEY,   -- '10316/116663', Estudo Geral's own id
    slug        TEXT NOT NULL,      -- '10316-116663', the estudo_geral/ filename stem
    title       TEXT NOT NULL,
    date        TEXT,
    year        TEXT,
    source_url  TEXT NOT NULL,      -- provenance is not optional: NOT NULL enforces
                                    -- what was previously only a convention
    rights      TEXT,               -- 'openAccess' / 'embargoedAccess'
    full_text   INTEGER NOT NULL DEFAULT 0,
    abstract_pt TEXT,
    abstract_en TEXT
);

-- One row per (thesis, raw name, role, candidate person).
--
-- `person_slug` is NULLABLE and `name_raw` is the key, not the other way
-- round: a name the matcher cannot resolve is a preserved row carrying its
-- tier, never a dropped one. 14 of today's 50 names are unmatched and the
-- corpus is about to grow 10x, so the schema has to hold that honestly.
--
-- `role` is part of the key because one person is legitimately the author of
-- one thesis and the supervisor of another — the same shape that makes
-- COUNT(*) over project_people over-count, which is dormant there (0 rows
-- today) and must not be re-introduced here.
--
-- `person_slug` is in the key too, because one name can resolve to several
-- `people` rows when the scraped source itself holds duplicates of one human
-- (joao-bicker / joao-bicker-1). A PRIMARY KEY cannot enforce that over NULLs
-- in SQLite, so the unique index below does it properly.
CREATE TABLE IF NOT EXISTS thesis_people (
    handle           TEXT NOT NULL REFERENCES theses(handle),
    name_raw         TEXT NOT NULL,
    role             TEXT NOT NULL CHECK (role IN ('author', 'supervisor')),
    person_slug      TEXT REFERENCES people(slug),
    match_status     TEXT NOT NULL
                     CHECK (match_status IN ('exact', 'confident', 'ambiguous', 'unmatched')),
    match_confidence REAL NOT NULL,
    match_note       TEXT,          -- why the matcher decided this, in words
    ordinal          INTEGER NOT NULL,
    PRIMARY KEY (handle, name_raw, role, person_slug)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_thesis_people_identity
    ON thesis_people(handle, name_raw, role, COALESCE(person_slug, ''));
CREATE INDEX IF NOT EXISTS idx_thesis_people_person ON thesis_people(person_slug);
CREATE INDEX IF NOT EXISTS idx_thesis_people_role ON thesis_people(role);

-- Keyed on ordinal, not keyword, for the same reason project_partners is: a
-- thesis legitimately repeats a keyword (9 of 18 do — case variants, and a
-- literal '-' the source publishes as a separator). Kept verbatim, in
-- document order; normalising is a query's job, not this table's.
CREATE TABLE IF NOT EXISTS thesis_keywords (
    handle  TEXT NOT NULL REFERENCES theses(handle),
    keyword TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    PRIMARY KEY (handle, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_thesis_keywords_keyword ON thesis_keywords(keyword);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id              INTEGER PRIMARY KEY,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    site_total_data INTEGER,
    listing_rows    INTEGER,
    detail_ok       INTEGER,
    detail_failed   INTEGER,
    notes           TEXT
);

-- THE MANIFEST (criterion 3). Written before the detail fetches, one row
-- per listing row, then updated as each completes — makes "did we get all
-- of them?" a query instead of an act of faith.
CREATE TABLE IF NOT EXISTS scrape_targets (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES scrape_runs(id),
    title       TEXT NOT NULL,
    url         TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'ok', 'no_detail_url', 'http_error', 'parse_error')),
    http_status INTEGER,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_scrape_targets_run ON scrape_targets(run_id);
