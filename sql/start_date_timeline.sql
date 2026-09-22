SELECT
    substr(start_date, 1, 4) AS start_year,
    COUNT(*) AS project_count
FROM projects
WHERE start_date IS NOT NULL
GROUP BY start_year
ORDER BY start_year;
