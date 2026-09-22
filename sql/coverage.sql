-- Criterion 3 (amended). Three different correct numbers — name which one
-- you mean. Query against the LATEST scrape run.
WITH latest_run AS (
    SELECT id FROM scrape_runs ORDER BY id DESC LIMIT 1
)
SELECT
    (SELECT COUNT(*) FROM projects)                                   AS total_projects,
    (SELECT COUNT(*) FROM projects WHERE detail_fetched = 1)          AS detail_fetched_ok,
    (SELECT COUNT(*) FROM projects WHERE detail_unavailable_reason IS NOT NULL)
                                                                        AS detail_unavailable,
    (SELECT COUNT(*) FROM projects WHERE title IS NULL)                AS null_titles,
    (SELECT site_total_data FROM scrape_runs WHERE id = (SELECT id FROM latest_run))
                                                                        AS site_total_data,
    (SELECT COUNT(*) FROM scrape_targets WHERE run_id = (SELECT id FROM latest_run))
                                                                        AS scrape_targets_rows,
    (SELECT COUNT(*) FROM scrape_targets
       WHERE run_id = (SELECT id FROM latest_run) AND status != 'pending')
                                                                        AS scrape_targets_terminal;
