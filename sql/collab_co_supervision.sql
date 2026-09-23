-- Long-form co-supervision facts: one row per (unordered person pair, shared
-- thesis handle). The API aggregates this into per-pair weight (# theses two
-- people supervised together) and the list of handles behind it — the same
-- long-form shape collab_co_project.sql has always had, and for the same
-- reason: an aggregate here would throw away the per-edge identity the graph
-- needs to say WHICH theses an edge stands for.
--
-- Restricted to supervisor rows with a resolved person_slug — an unmatched
-- name_raw is not a graph node (see thesis_people.match_status). The
-- DISTINCT (handle, person_slug) CTE is what makes one row per pair per
-- thesis exact, so the row count IS the weight the previous
-- COUNT(DISTINCT handle) computed. Person pairs are keyed by slug, never
-- display name, same as every other person-pair query in this app.
WITH supervision AS (
    SELECT DISTINCT handle, person_slug
    FROM thesis_people
    WHERE role = 'supervisor' AND person_slug IS NOT NULL
)
SELECT
    a.person_slug AS person_a,
    b.person_slug AS person_b,
    a.handle      AS handle
FROM supervision a
JOIN supervision b ON a.handle = b.handle AND a.person_slug < b.person_slug
ORDER BY a.person_slug, b.person_slug, a.handle;
