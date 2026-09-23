-- How much of the app the Partners view actually covers — surfaced next to
-- the chart rather than left as a silent gap, same convention as
-- coverage.sql for the app as a whole.
SELECT
    (SELECT COUNT(*) FROM projects WHERE detail_fetched = 1) AS detail_fetched_ok,
    (SELECT COUNT(*) FROM projects
       WHERE detail_fetched = 1 AND partners_raw IS NOT NULL AND partners_raw != '')
                                                                AS projects_with_partners_raw,
    (SELECT COUNT(DISTINCT project_id) FROM project_partners)  AS projects_with_parsed_partners,
    (SELECT COUNT(*) FROM project_partners)                    AS partner_entries,
    (SELECT COUNT(DISTINCT partner_name) FROM project_partners) AS distinct_partners;
