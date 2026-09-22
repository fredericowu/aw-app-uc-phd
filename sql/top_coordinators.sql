SELECT
    pe.name AS coordinator,
    COUNT(*) AS project_count
FROM project_people pp
JOIN people pe ON pe.slug = pp.person_slug
WHERE pp.role = 'coordinator'
GROUP BY pe.slug, pe.name
ORDER BY project_count DESC, coordinator
LIMIT 15;
