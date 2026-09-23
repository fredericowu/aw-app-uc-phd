-- Same person keyed by slug, not display name — the site has people who
-- share a name under different profiles/slugs. Ranking and project_count
-- use COUNT(DISTINCT project_id) over the coordinator-role rows ALONE
-- (coordinator_projects/totals, below), before the join to project_groups:
-- project_people's composite PK lets one person hold both coordinator and
-- researcher roles on the same project, and group membership is
-- many-to-many like every other per-group figure in this app (see
-- projects_per_group.sql) — joining it multiplies rows per project, which
-- would inflate the ranking for anyone with a multi-group project if it ran
-- before this split.
--
-- Output is long-format, one row per (coordinator, group): the API pivots
-- it into one stacked-bar series per coordinator. A project with no listed
-- research group is counted under the synthetic 'UNGROUPED' code rather
-- than silently dropping that coordinator's segment.
WITH coordinator_projects AS (
    SELECT DISTINCT pp.person_slug, pp.project_id
    FROM project_people pp
    WHERE pp.role = 'coordinator'
),
totals AS (
    SELECT person_slug, COUNT(*) AS project_count
    FROM coordinator_projects
    GROUP BY person_slug
    ORDER BY project_count DESC, person_slug
    LIMIT 15
)
SELECT
    pe.slug AS coordinator_slug,
    pe.name AS coordinator,
    t.project_count,
    COALESCE(rg.code, 'UNGROUPED') AS group_code,
    rg.name AS group_name,
    COUNT(DISTINCT cp.project_id) AS group_project_count
FROM totals t
JOIN people pe ON pe.slug = t.person_slug
JOIN coordinator_projects cp ON cp.person_slug = t.person_slug
LEFT JOIN project_groups pg ON pg.project_id = cp.project_id
LEFT JOIN research_groups rg ON rg.code = pg.group_code
GROUP BY pe.slug, pe.name, t.project_count, group_code, rg.name
ORDER BY t.project_count DESC, pe.name, group_code;
