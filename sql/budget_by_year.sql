-- Only projects with a successfully parsed start_date (ISO) contribute —
-- an unparseable date is excluded here rather than guessed at.
SELECT
    substr(start_date, 1, 4) AS start_year,
    COUNT(*) AS project_count,
    ROUND(SUM(total_budget_amount), 2) AS total_budget_sum
FROM projects
WHERE start_date IS NOT NULL
GROUP BY start_year
ORDER BY start_year;
