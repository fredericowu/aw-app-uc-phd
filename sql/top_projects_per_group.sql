-- Top 10 projects per research group, ranked by total_budget_amount DESC
-- (ranking metric not specified by the request — total budget is the most
-- objective available proxy for a project's size/relevance, so it's used
-- explicitly and labelled as such wherever this query is rendered).
-- Many-to-many (project_groups): a project in 2+ groups can appear in more
-- than one group's top 10, same honesty tradeoff as projects_per_group.sql.
-- Only rows with a parsed budget and a synopsis are eligible — a project
-- can't be ranked without an amount, and can't get a grounded problem
-- summary without a synopsis to ground it in.
WITH ranked AS (
    SELECT
        rg.code,
        rg.name,
        p.id AS project_id,
        p.title,
        p.detail_url,
        p.total_budget_amount,
        p.total_budget_currency,
        p.synopsis,
        ROW_NUMBER() OVER (
            PARTITION BY rg.code
            ORDER BY p.total_budget_amount DESC, p.title
        ) AS rank_in_group
    FROM research_groups rg
    JOIN project_groups pg ON pg.group_code = rg.code
    JOIN projects p ON p.id = pg.project_id
    WHERE p.total_budget_amount IS NOT NULL
      AND p.synopsis IS NOT NULL
      AND TRIM(p.synopsis) != ''
)
SELECT * FROM ranked
WHERE rank_in_group <= 10
ORDER BY code, rank_in_group;
