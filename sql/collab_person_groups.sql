-- Which research group(s) each person's own project memberships touch — any
-- role (coordinator or researcher), any of their projects. Feeds the
-- collaboration graph's cross_group signal: two people who work together
-- despite their own group memberships never overlapping (see
-- uc_phd_app/collab.py). Not grouped by person here — the API folds this
-- into a slug -> set(group_code) map, same shape it needs project_groups in
-- for every other per-group figure.
SELECT DISTINCT pp.person_slug AS person_slug, pg.group_code AS group_code
FROM project_people pp
JOIN project_groups pg ON pg.project_id = pp.project_id;
