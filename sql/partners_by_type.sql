-- Academic vs industry, at a glance: distinct partners and the projects
-- they touch, per type. project_count is COUNT(DISTINCT project_id) within
-- each type alone — a project with both an academic and an industry
-- partner is counted under both types, same many-to-many honesty rule as
-- projects_per_group.sql.
SELECT
    partner_type,
    COUNT(DISTINCT partner_name) AS distinct_partners,
    COUNT(DISTINCT project_id) AS project_count
FROM project_partners
GROUP BY partner_type
ORDER BY partner_type;
