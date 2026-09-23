-- How much of Partners and Theses the transitive link actually reaches —
-- surfaced next to the feature rather than left as a silent gap, same
-- convention as partners_coverage.sql and coverage.sql.
SELECT
    (SELECT COUNT(DISTINCT partner_name) FROM project_partners) AS distinct_partners,
    (SELECT COUNT(DISTINCT pp.partner_name)
       FROM project_partners pp
       JOIN project_people ppl ON ppl.project_id = pp.project_id
       JOIN thesis_people tp   ON tp.person_slug = ppl.person_slug)
                                                                 AS partners_with_a_thesis_link,
    (SELECT COUNT(*) FROM theses)                                AS total_theses,
    (SELECT COUNT(DISTINCT th.handle)
       FROM theses th
       JOIN thesis_people tp   ON tp.handle = th.handle
       JOIN project_people ppl ON ppl.person_slug = tp.person_slug
       JOIN project_partners pp ON pp.project_id = ppl.project_id)
                                                                 AS theses_with_a_partner_link;
