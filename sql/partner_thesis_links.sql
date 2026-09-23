-- Every renderable path from a project partner to an Estudo Geral thesis.
--
-- There is no partner<->thesis edge in any source. Every row here is
-- transitive: partner -> project (project_partners) -> person
-- (project_people, their role on that project) -> thesis (thesis_people,
-- their role on that thesis), riding the same person_slug the identity
-- spine (bd0da89) already resolves theses' authors/supervisors to. This is
-- NOT "this company funded this thesis" — it is "this company shares a
-- project with someone who wrote or supervised this thesis" — so every row
-- keeps both intermediate hops (project, person) rather than collapsing to
-- a bare partner/thesis pair.
--
-- match_confidence is the only uncertain step in the chain: project_partners
-- and project_people are both scraped, authoritative facts, not
-- name-matched guesses, so they contribute no confidence of their own.
--
-- INNER JOIN throughout, deliberately: an unmatched/ambiguous thesis name
-- has no person_slug (see thesis_people.sql), so it has nothing to join a
-- partner through — dropping those rows here is correct, not a leak.
SELECT
    pp.partner_name,
    pp.partner_type,
    pr.id                AS project_id,
    pr.title              AS project_title,
    ppl.person_slug       AS via_person_slug,
    pe.name               AS via_person_name,
    ppl.role              AS via_project_role,
    th.handle             AS thesis_handle,
    th.title              AS thesis_title,
    th.source_url         AS thesis_source_url,
    tp.role               AS thesis_role,
    tp.match_status,
    tp.match_confidence
FROM project_partners pp
JOIN projects pr        ON pr.id = pp.project_id
JOIN project_people ppl ON ppl.project_id = pp.project_id
JOIN people pe          ON pe.slug = ppl.person_slug
JOIN thesis_people tp   ON tp.person_slug = ppl.person_slug
JOIN theses th          ON th.handle = tp.handle
ORDER BY pp.partner_name, th.handle, ppl.person_slug, tp.role;
