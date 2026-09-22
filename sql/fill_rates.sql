-- Criterion 4: per-field fill rate, driven entirely by project_fields_raw —
-- the label universe that exists on the site, not a hardcoded list. A field
-- the parser never knew to look for (e.g. Keywords) still shows up here.
SELECT
    label,
    COUNT(DISTINCT project_id) AS projects_with_field,
    (SELECT COUNT(*) FROM projects WHERE detail_fetched = 1) AS total_fetched,
    ROUND(
        100.0 * COUNT(DISTINCT project_id) /
        (SELECT COUNT(*) FROM projects WHERE detail_fetched = 1),
        1
    ) AS fill_rate_pct
FROM project_fields_raw
WHERE value_text IS NOT NULL AND value_text != ''
GROUP BY label
ORDER BY fill_rate_pct DESC, label;
