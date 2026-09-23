-- Top partners by number of projects they appear on, each carrying the
-- academic/industry flag project_partners was classified with (scraper/
-- parse.py:classify_partner — a keyword heuristic, not verified per
-- partner). Long tail collapsed into an 'Other' row per type, same pattern
-- as funding_breakdown.sql.
--
-- classify_partner() is a pure function of the name, so every row sharing a
-- partner_name string already carries the same partner_type — MIN() is just
-- the aggregate GROUP BY requires, not a tie-break. A different spelling of
-- the same real-world entity is still a distinct partner_name here and can
-- end up on both sides; that is a partners_raw free-text limitation, not
-- something this query resolves.
WITH ranked AS (
    SELECT
        partner_name,
        MIN(partner_type) AS partner_type,
        COUNT(DISTINCT project_id) AS project_count
    FROM project_partners
    GROUP BY partner_name
),
top20 AS (
    SELECT * FROM ranked ORDER BY project_count DESC, partner_name LIMIT 20
),
other AS (
    SELECT
        'Other academic' AS partner_name, 'academic' AS partner_type,
        SUM(project_count) AS project_count
    FROM ranked
    WHERE partner_type = 'academic' AND partner_name NOT IN (SELECT partner_name FROM top20)
    UNION ALL
    SELECT
        'Other industry' AS partner_name, 'industry' AS partner_type,
        SUM(project_count) AS project_count
    FROM ranked
    WHERE partner_type = 'industry' AND partner_name NOT IN (SELECT partner_name FROM top20)
)
SELECT partner_name, partner_type, project_count FROM top20
UNION ALL
SELECT partner_name, partner_type, project_count FROM other WHERE project_count > 0
ORDER BY project_count DESC, partner_name;
