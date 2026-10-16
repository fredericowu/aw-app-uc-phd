-- The researched identity of a thesis mention nothing can match.
--
-- One row per (handle, name_raw, role) — a MENTION, not a name. Written
-- offline from the curated data/external_people.json; see
-- analysis/external_people.py for why this is display metadata and never
-- matcher input, and scraper/schema.sql for the loader's refusals.
--
-- `evidence` is deliberately NOT selected. It is the reviewable record of why
-- a human is satisfied this is the person — long prose, checked by the
-- validator and read in the repo, not something to ship down the wire on
-- every /api/theses call. `note` IS selected: a caveat on this specific
-- identification (Gonçalo Quadros's unverified middle names) belongs next to
-- the name it qualifies.
SELECT handle,
       name_raw,
       role,
       display_name,
       affiliation,
       source_url,
       note
FROM external_people
ORDER BY handle, role, name_raw;
