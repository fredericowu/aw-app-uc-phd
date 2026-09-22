-- The site exposes a funder NAME, not a funding "type" category — no
-- category is invented here (DESIGN.md: no LLM-derived/enriched fields).
-- Top funders by number of projects funded; long tail collapsed into Other.
WITH ranked AS (
    SELECT
        COALESCE(funding_raw, '(no funding listed)') AS funder,
        COUNT(*) AS project_count
    FROM projects
    WHERE detail_fetched = 1
    GROUP BY funder
),
top15 AS (
    SELECT * FROM ranked ORDER BY project_count DESC LIMIT 15
),
other AS (
    SELECT 'Other' AS funder, SUM(project_count) AS project_count
    FROM ranked
    WHERE funder NOT IN (SELECT funder FROM top15)
)
SELECT funder, project_count FROM top15
UNION ALL
SELECT funder, project_count FROM other WHERE project_count > 0
ORDER BY project_count DESC;
