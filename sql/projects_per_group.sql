-- Many-to-many by design (DESIGN.md §1b): the sum across groups exceeds
-- total project count because a project can belong to more than one group.
SELECT
    rg.code,
    rg.name,
    COUNT(pg.project_id) AS project_count
FROM research_groups rg
JOIN project_groups pg ON pg.group_code = rg.code
GROUP BY rg.code, rg.name
ORDER BY project_count DESC;
