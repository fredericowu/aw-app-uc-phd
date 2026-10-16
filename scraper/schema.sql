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

-- The person-alias "de x para": CISUC's own directory lists some humans under
-- TWO person rows, and this is which of them is which.
--
-- Written offline by `python -m analysis.build_thesis_facts` from the curated,
-- human-reviewed data/person_aliases.json — see analysis/person_aliases.py for
-- why the decision cannot be automated (the same name shape that proves
-- simao-paredes/s-paredes are one person, via a shared ORCID, is carried by
-- nuno-silva-1/nuno-silva-4, who are two different people).
--
-- `people` rows are NOT merged or deleted. scraper/people.py re-serves both
-- slugs on every sync, so a deleted row would simply come back; both CISUC
-- pages are live URLs; and project_people/project_fields_raw provenance hangs
-- off both slugs. The indirection is the mechanism, not a migration step.
--
-- from_slug is the PRIMARY KEY, which is also what makes resolution exactly
-- one hop: a slug can be an alias of at most one canonical, and the loader
-- additionally refuses a to_slug that is itself a from_slug (a chain), so no
-- consumer ever has to loop.
CREATE TABLE IF NOT EXISTS person_aliases (
    from_slug TEXT PRIMARY KEY REFERENCES people(slug),
    to_slug   TEXT NOT NULL REFERENCES people(slug),
    evidence  TEXT NOT NULL   -- why a human ruled these one person. Not optional.
);
CREATE INDEX IF NOT EXISTS idx_person_aliases_to ON person_aliases(to_slug);

-- A person's full legal name, where CISUC's published short form is not a
-- truncation of it but drops the real surname ('António Dourado' for António
-- Dourado Pereira Correia) or prefers a later given name ('Penousal Machado'
-- for Fernando Jorge Penousal Martins Machado). The thesis form and the
-- display form then share no surname token at all, and analysis/name_match.py's
-- `_fits()` rejects them in both directions.
--
-- Written offline by `python -m analysis.build_thesis_facts` from the curated,
-- human-reviewed data/person_full_names.json — see analysis/person_full_names.py
-- for why this is a reviewed fact and not a rule, and why `_fits_full()` (the
-- one matcher direction this table unlocks) must stay unreachable for a slug
-- with no row here: the same comparison against an UNREVIEWED display name is
-- exactly the relaxation this repo measured and rejected ("Cruz, Luís Alberto
-- da Silva" -> "Luís Silva", docs/thesis-attribution.md "Two rejected
-- relaxations", B).
--
-- What this must never become: a thesis-name lookup. The key is a slug — a
-- row is a fact about a person, upstream of any thesis, exactly like the alias
-- table above. A `name_raw` column here would be the hand-written attribution
-- table the Product Owner rejected (option C in the same document).
--
-- Nothing renders this. `people.name` stays what the app displays, because
-- that is what CISUC publishes; the only reader is name_match._fits_full().
CREATE TABLE IF NOT EXISTS person_full_names (
    slug      TEXT PRIMARY KEY REFERENCES people(slug),
    full_name TEXT NOT NULL,
    evidence  TEXT NOT NULL   -- the citable source a human read it off. Not optional.
);

-- One row per HUMAN, where `people` is one row per CISUC directory entry.
--
-- `people.slug` stopped meaning "one human" the moment the table above
-- existed, and every count over people is wrong by the number of aliases
-- unless it resolves through it. This view is the one obvious place to do
-- that, so a future consumer has something to join to instead of
-- rediscovering the problem — see uc_phd_app/collab.py:summary().
CREATE VIEW IF NOT EXISTS people_canonical AS
SELECT slug, name FROM people
WHERE slug NOT IN (SELECT from_slug FROM person_aliases);

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

-- One resolved person authors at most one thesis in this corpus.
--
-- A unique *student slug* was never missing: people.slug is already that
-- table's PRIMARY KEY, so two rows could never share one. The defect this
-- guards is the other direction and invisible to that key — a wrong
-- many-real-people -> one-slug MAPPING, which is how "Martins, Pedro" (2014,
-- computer vision) and "Martins, Pedro Miguel de Oliveira" (2016, ETL) both
-- landed on `pedro-martins` and turned 181 theses into 180 students.
--
-- Partial on both counts, deliberately: unresolved names are kept as rows
-- with a NULL slug and there are many of them, and one supervisor on many
-- theses is the normal case, not a conflict. The invariant is enforced at
-- build time by analysis/build_thesis_facts.py, which demotes the losing
-- claimant with a note; this index is the backstop that makes a re-merge
-- impossible to commit even if that pass is ever bypassed.
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_thesis_per_resolved_author
    ON thesis_people(person_slug) WHERE role = 'author' AND person_slug IS NOT NULL;

-- A researched identity for a thesis mention that will never get a slug.
--
-- The two reviewed-fact tables above correct a defect in CISUC's directory.
-- This one is for the names where the directory is RIGHT to be silent: an
-- ISEP professor who co-supervised one thesis, a CERN project leader, a
-- Critical Software founder, a graduate who left in 2015. They stay
-- `unmatched` forever, and the only thing that was wrong is that the app
-- printed a bare "(unattributed)" next to a person whose name, affiliation
-- and source are known.
--
-- Written offline by `python -m analysis.build_thesis_facts` from the
-- curated, human-reviewed data/external_people.json — see
-- analysis/external_people.py for why this is NOT the thesis-name lookup the
-- Product Owner rejected (option C, docs/thesis-attribution.md).
--
-- What keeps it on the right side of that line, enforced by the loader and
-- not merely intended:
--
--  * NO person_slug column, and no path to one. This table cannot override,
--    shadow or second-guess a matcher verdict, and `identity_coverage` does
--    not move when a row is added — an external person is correctly
--    unresolved, not newly resolved.
--  * The loader REFUSES an entry whose thesis_people row is anything other
--    than match_status='unmatched'. A future matcher improvement that
--    resolves one of these names breaks the build until the obsolete entry
--    is removed, instead of leaving a stale external claim next to a real
--    CISUC person.
--  * The key is a MENTION — (handle, name_raw, role) — not a name. Option C
--    mapped a name to a person and so applied to every thesis forever,
--    which is this corpus's core trap ("Martins, Pedro" is two different
--    people two years apart). A future thesis carrying the same string
--    inherits nothing from here. The cost is duplication, and it is
--    accepted: Torsten Braun supervises two theses, so he has two rows.
--
-- analysis/name_match.py must never import the loader. A name this table
-- describes is still an unresolved name to every count, join and tier here.
CREATE TABLE IF NOT EXISTS external_people (
    handle       TEXT NOT NULL REFERENCES theses(handle),
    name_raw     TEXT NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('author', 'supervisor')),
    display_name TEXT NOT NULL,   -- how the person is actually published
    affiliation  TEXT NOT NULL,   -- where they work. Rendered, so not optional.
    source_url   TEXT NOT NULL,   -- the citable page the above was read off.
    note         TEXT,            -- a caveat on THIS identification, when there is one
    evidence     TEXT NOT NULL,   -- why a human is satisfied this is the person. Not optional.
    PRIMARY KEY (handle, name_raw, role)
);
CREATE INDEX IF NOT EXISTS idx_external_people_handle ON external_people(handle);

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

-- How much each thesis's own text looks like each research group's project
-- text — TF-IDF cosine, built offline by `python -m
-- analysis.build_group_affinity`.
--
-- This is the *content* half of group attribution, and the only half that is
-- frozen. The people half (a person's group from their project history) stays
-- derived live on every request in uc_phd_app/theses.py, deliberately. The two
-- halves therefore run on two clocks, and a re-scrape moves one and not the
-- other until this builder re-runs.
--
-- A pair scoring 0.0 is absent, not stored as a zero row: "no rows for this
-- handle" is how the reader tells a thesis with no usable text from one that
-- was simply scored low, and a stored six-way tie at zero would let an argmax
-- invent a group out of nothing.
CREATE TABLE IF NOT EXISTS thesis_group_affinity (
    handle     TEXT NOT NULL REFERENCES theses(handle),
    group_code TEXT NOT NULL REFERENCES research_groups(code),
    score      REAL NOT NULL,      -- cosine in [0, 1]
    rank       INTEGER NOT NULL,   -- 1 = best, dense within the handle
    PRIMARY KEY (handle, group_code)
);
CREATE INDEX IF NOT EXISTS idx_thesis_group_affinity_rank
    ON thesis_group_affinity(handle, rank);

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

-- ── Bibliography (analysis/build_bibliography.py) ────────────────────────
--
-- One row per DISTINCT work cited anywhere in the corpus, and one row per
-- (thesis, work) citation. Built offline from estudo_geral/*.md and committed
-- into the seed for the same reason thesis facts are (see
-- analysis/build_thesis_facts.py's "Why the seed and not Postgres"): every
-- join partner is already in this file, and Postgres has no seed mechanism.
--
-- `bib_references`, not `references`. SQLite reserves REFERENCES, so a table
-- of that name is a syntax error unless every single statement that touches
-- it double-quotes it — forever, in every query, including ones written by
-- someone who has not read this comment. The design note that named the table
-- `references` did not know that; the prefix is the whole deviation from it.
CREATE TABLE IF NOT EXISTS bib_references (
    id              INTEGER PRIMARY KEY,
    -- The tier-2 identity: '<normalised first author>|<normalised title>',
    -- or a 'doi:<doi>' key when tier 1 resolved it. NULL is not allowed —
    -- a reference with no derivable key gets a per-row 'raw:<id>' key so it
    -- still counts exactly once instead of collapsing with every other
    -- unparseable entry into one meaningless bucket.
    normalised_key  TEXT NOT NULL UNIQUE,
    -- The longest raw entry string seen for this work, kept verbatim. Longest
    -- rather than first: the corpus corrupts entries by dropping characters,
    -- so the longest surviving copy is the most readable one, and the reader
    -- needs SOMETHING quotable next to a count.
    display_string  TEXT NOT NULL,
    doi             TEXT,
    year            TEXT,
    first_author    TEXT,
    -- How this work's identity was established. 'doi' is exact; 'title' is
    -- the normalised author+title key, measured at 52.6% recall against DOI
    -- ground truth (analysis/reference_parse.py's module docstring);
    -- 'unmatched' means no key could be derived and the row is a singleton by
    -- construction. Stored per row so the UI can say which is which instead
    -- of presenting one confidence for all of them.
    match_tier      TEXT NOT NULL CHECK (match_tier IN ('doi', 'title', 'unmatched')),
    -- analysis/reference_parse.py's MATCHER_VERSION at build time. The key is
    -- frozen into a committed seed, so improving the matcher needs a rebuild
    -- and a version bump; this column is what makes a stale seed visible.
    matcher_version INTEGER NOT NULL,
    cited_by        INTEGER NOT NULL  -- distinct theses citing it; denormalised
);
CREATE INDEX IF NOT EXISTS idx_bib_references_cited_by ON bib_references(cited_by);
CREATE INDEX IF NOT EXISTS idx_bib_references_doi ON bib_references(doi);

-- One row per (thesis, work). `entry_raw` is that thesis's own wording, kept
-- because two theses citing one work with different strings IS the evidence
-- the match tier is claiming something about — discarding it would make the
-- claim uncheckable.
CREATE TABLE IF NOT EXISTS thesis_references (
    handle       TEXT NOT NULL REFERENCES theses(handle),
    reference_id INTEGER NOT NULL REFERENCES bib_references(id),
    entry_raw    TEXT NOT NULL,
    ordinal      INTEGER NOT NULL,
    PRIMARY KEY (handle, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_thesis_references_ref ON thesis_references(reference_id);
CREATE INDEX IF NOT EXISTS idx_thesis_references_handle ON thesis_references(handle);
