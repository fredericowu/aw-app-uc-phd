-- Long-form co-project facts: one row per (unordered person pair, shared
-- project), plus that project's own team size (distinct people on it). The
-- API aggregates this into per-pair weight (# shared projects — the card's
-- co_project(person_a, person_b) definition) and a size-normalised weight
-- (each project's contribution divided by team_size - 1, so a 30-person
-- project does not inflate a pair the same as two people working alone —
-- see uc_phd_app/collab.py). Membership is DISTINCT (project_id,
-- person_slug) first: project_people's composite PK lets one person hold
-- both coordinator and researcher roles on the same project, which would
-- otherwise count as two memberships of the same project. Person pairs are
-- keyed by slug, never display name — 3 of 475 people share a name across
-- different profiles.
WITH membership AS (
    SELECT DISTINCT project_id, person_slug FROM project_people
),
project_size AS (
    SELECT project_id, COUNT(*) AS team_size FROM membership GROUP BY project_id
)
SELECT
    a.person_slug AS person_a,
    b.person_slug AS person_b,
    a.project_id  AS project_id,
    ps.team_size  AS team_size
FROM membership a
JOIN membership b ON a.project_id = b.project_id AND a.person_slug < b.person_slug
JOIN project_size ps ON ps.project_id = a.project_id
ORDER BY a.person_slug, b.person_slug, a.project_id;
