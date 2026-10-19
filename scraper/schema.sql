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

-- Where a `people` row came from, when it did NOT come from CISUC's own
-- directory: one row per (person, publishing unit).
--
-- Written offline by `python -m scraper.uc_directories.run` from the
-- committed per-unit registry (scraper/uc_directories/units.py). UC runs no
-- institution-wide staff directory — what exists is a per-Faculty "Docentes"
-- page and a per-centre "Pessoas" page, one unit at a time — so a UC
-- academic who is not a CISUC member reaches `people` through here.
--
-- **This table is what makes scope derivable rather than asserted twice.** A
-- `people` row with NO row here is a CISUC-directory person, exactly as
-- before (only the harvester above writes listings); a row with one is a
-- UC-unit-directory person. Nothing adds a column to `people`: one person
-- can hold listings in several units, which is a table and not a column, and
-- `people` is applied with CREATE TABLE IF NOT EXISTS over the committed
-- seed, where SQLite has no ADD COLUMN IF NOT EXISTS to lean on.
--
-- Slugs live in a disjoint, prefixed namespace (`uc--<source>--<name-slug>`)
-- and the harvester REFUSES to write a slug that already exists in `people`
-- outside it, so collision with CISUC's arbitrary URL-tail slugs is both
-- structurally impossible and checked.
--
-- `listing_url` is the live page the row was read off, and it is the whole
-- point: every match this pool buys has to be checkable by a human against
-- the source. `person_url` is the unit's own per-person page where it
-- publishes one, and it is also the ONLY evidence cross-unit duplicates are
-- ever collapsed on — never the name, which is this corpus's core trap. A
-- same-human pair with no shared person URL is surfaced for review and
-- settled the house way, by a `person_aliases` verdict with evidence.
--
-- PK (person_slug, source): one person, one row per unit. Boaventura de
-- Sousa Santos on FEUC's Docentes page and CES's Pessoas page is one slug
-- and two rows, which is exactly the fact the grain exists to record.
CREATE TABLE IF NOT EXISTS directory_listings (
    person_slug       TEXT NOT NULL REFERENCES people(slug),
    source            TEXT NOT NULL,   -- unit code: 'feuc', 'fduc', 'ces', ...
    unit_name         TEXT NOT NULL,   -- 'Faculdade de Economia (FEUC)'
    listing_url       TEXT NOT NULL,   -- the directory page the row was read off
    person_url        TEXT,            -- per-person page, when the unit publishes one
    name_as_published TEXT NOT NULL,   -- verbatim, before any display normalisation
    role_as_published TEXT,            -- 'Professor Catedrático', when the page carries it
    fetched_at        TEXT NOT NULL,
    PRIMARY KEY (person_slug, source)
);
CREATE INDEX IF NOT EXISTS idx_directory_listings_source ON directory_listings(source);

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
-- claimant with a note; what follows is the backstop that makes a re-merge
-- impossible to commit even if that pass is ever bypassed.
--
-- It used to be a partial UNIQUE index, `idx_one_thesis_per_resolved_author`
-- ON thesis_people(person_slug) WHERE role = 'author' AND person_slug IS NOT
-- NULL. It stopped being able to be one when the invariant acquired a
-- reviewed exception: a graduate whose MSc dissertation AND doctoral thesis
-- are both deposited here is one person with two authored theses
-- (data/multi_thesis_authors.json, analysis/multi_thesis_authors.py), and
-- SQLite's partial-index predicate cannot subquery, so it cannot ask whether
-- a pair has been reviewed. A BEFORE INSERT trigger can, and it keeps the
-- guarantee at the same strength rather than downgrading the backstop to
-- "the build pass and the tests" — which is what simply dropping the index
-- would have done.
--
-- DROP INDEX, not a comment: `build()` applies this file over the COMMITTED
-- seed with `executescript`, and every statement here is IF NOT EXISTS, so a
-- rebuild in place would otherwise keep the stale index alive in the shipped
-- file and fail on the very row the exemption exists to allow.
DROP INDEX IF EXISTS idx_one_thesis_per_resolved_author;

-- The reviewed exceptions, one row per exempted (person, thesis) claim.
--
-- Written offline by `python -m analysis.build_thesis_facts` from the
-- curated, human-reviewed data/multi_thesis_authors.json — see
-- analysis/multi_thesis_authors.py for why a reviewed per-person fact is the
-- only acceptable shape for this, and why the rule version of it ("claims
-- that are byte-identical are safe") was weighed and rejected.
--
-- The build writes this table BEFORE thesis_people, because the trigger
-- below reads it. That is an ordering fact, stated in `build()`'s docstring.
CREATE TABLE IF NOT EXISTS multi_thesis_authors (
    person_slug TEXT NOT NULL REFERENCES people(slug),
    handle      TEXT NOT NULL REFERENCES theses(handle),
    source_url  TEXT NOT NULL,   -- the citable page the review was read off.
    evidence    TEXT NOT NULL,   -- why a human is satisfied it is one person. Not optional.
    PRIMARY KEY (person_slug, handle)
);

-- Two resolved author rows may share a person_slug only when both of their
-- (person_slug, handle) pairs are reviewed above AND they are on different
-- theses. With the table empty this is exactly the old index: the first
-- condition fails, so any second resolved author row on a slug aborts.
--
-- The same-thesis case stays forbidden in both directions, which the old
-- index also forbade: two author names on ONE thesis both resolving to one
-- person is a double-counted student, not a multi-thesis author, and the
-- build pass demotes it.
CREATE TRIGGER IF NOT EXISTS trg_one_thesis_per_resolved_author
BEFORE INSERT ON thesis_people
WHEN NEW.role = 'author' AND NEW.person_slug IS NOT NULL
BEGIN
    -- One string literal, not three adjacent ones: SQLite has no implicit
    -- string concatenation, and three would be a syntax error in every
    -- `executescript` that applies this file.
    SELECT RAISE(ABORT, 'one person authors at most one thesis in this corpus: this person_slug already carries a resolved author row, and data/multi_thesis_authors.json does not review both claims as the same human on two different theses')
    WHERE EXISTS (
        SELECT 1
        FROM thesis_people existing
        WHERE existing.role = 'author'
          AND existing.person_slug = NEW.person_slug
          AND NOT (
              existing.handle <> NEW.handle
              AND EXISTS (
                  SELECT 1 FROM multi_thesis_authors m
                  WHERE m.person_slug = NEW.person_slug AND m.handle = NEW.handle
              )
              AND EXISTS (
                  SELECT 1 FROM multi_thesis_authors m
                  WHERE m.person_slug = existing.person_slug AND m.handle = existing.handle
              )
          )
    );
END;

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

-- One physical thesis that Estudo Geral deposited twice, reviewed by a human.
--
-- Written offline by `python -m analysis.build_thesis_facts` from the curated
-- data/duplicate_theses.json — see analysis/duplicate_theses.py for why a
-- reviewed per-record fact is the only acceptable shape for this, and why the
-- rule version of it ("byte-identical abstracts are the same thesis") was
-- weighed and rejected: a false positive here silently deletes a real thesis.
--
-- The build drops the duplicate's front matter immediately after reconcile()
-- and before any row is derived, so this table exists to make the reason a
-- handle is ABSENT from `theses` queryable rather than only readable in git.
-- "2690 .md files, 2689 theses" is a discrepancy anyone auditing the corpus
-- will hit, and these rows are the answer to it.
--
-- The build writes this table BEFORE theses, because the trigger below reads
-- it. That is an ordering fact, stated in `build()`'s docstring.
CREATE TABLE IF NOT EXISTS duplicate_theses (
    -- The record the build drops. Deliberately NOT `REFERENCES theses(handle)`:
    -- its absence from that table is the entire point of the row, so the
    -- foreign key every other handle column here carries would be exactly
    -- backwards and would refuse every row this table is for.
    duplicate_handle TEXT PRIMARY KEY,
    -- The record that stays, and it IS in theses — which is what makes the
    -- claim falsifiable: an entry asserts a pair, not a lone deletion, and a
    -- survivor that went away upstream must break the build rather than let
    -- the exclusion erase the thesis entirely.
    kept_handle      TEXT NOT NULL REFERENCES theses(handle),
    source_url       TEXT NOT NULL,   -- the citable record the review was read off.
    evidence         TEXT NOT NULL    -- why a human is satisfied it is one deposit. Not optional.
);

-- The backstop, not the mechanism: `build()`'s filter is what keeps the
-- duplicate out, and this refuses any OTHER writer — or a future refactor that
-- drops the filter — putting a reviewed-out record back into `theses`. Same
-- defense-in-depth move as trg_one_thesis_per_resolved_author above, and the
-- same reason it is a trigger rather than a constraint: only a trigger can ask
-- whether a row has been reviewed.
CREATE TRIGGER IF NOT EXISTS trg_no_excluded_thesis
BEFORE INSERT ON theses
WHEN EXISTS (SELECT 1 FROM duplicate_theses d WHERE d.duplicate_handle = NEW.handle)
BEGIN
    -- One string literal, not several adjacent ones: SQLite has no implicit
    -- string concatenation, and two would be a syntax error in every
    -- `executescript` that applies this file.
    SELECT RAISE(ABORT, 'this handle is a reviewed duplicate record (data/duplicate_theses.json) and must not enter theses');
END;

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

-- Which OAI sets Estudo Geral lists each thesis under — communities AND
-- collections, exactly as the harvest's record headers carried them.
--
-- Many-to-many because membership genuinely is: one thesis here sits in three
-- communities at once, so a single "origin" column would have had to pick
-- one, and which one it picked would be an artifact of harvest order rather
-- than a fact about the thesis. Grouping by category is therefore a join plus
-- `WHERE set_spec IN (...)`, the same shape thesis_keywords already uses.
--
-- The RAW spec is stored, never a label: membership we did not plan for (the
-- UC-wide `col_10316_15519`, say) stays queryable without re-harvesting, and
-- the community -> label map lives next to the harvester that defines the
-- scope, in estudo_geral_extractor/oai.py's HARVEST_SETS.
--
-- Snapshot-at-harvest, like every other column here: if UC re-maps an item's
-- communities, these rows are stale until the next harvest run.
CREATE TABLE IF NOT EXISTS thesis_sets (
    handle   TEXT NOT NULL REFERENCES theses(handle),
    set_spec TEXT NOT NULL,
    PRIMARY KEY (handle, set_spec)
);
CREATE INDEX IF NOT EXISTS idx_thesis_sets_set_spec ON thesis_sets(set_spec);

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
