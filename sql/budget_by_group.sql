-- A project in 2 groups counts its budget under both — same honesty
-- tradeoff as projects_per_group.sql. Only rows with a parsed amount count.
SELECT
    rg.code,
    rg.name,
    COUNT(DISTINCT p.id) AS project_count,
    ROUND(SUM(p.total_budget_amount), 2) AS total_budget_sum
FROM research_groups rg
JOIN project_groups pg ON pg.group_code = rg.code
JOIN projects p ON p.id = pg.project_id
WHERE p.total_budget_amount IS NOT NULL
GROUP BY rg.code, rg.name
ORDER BY total_budget_sum DESC;
