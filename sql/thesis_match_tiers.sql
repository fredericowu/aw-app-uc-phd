-- How the name matcher did, counted over DISTINCT names.
--
-- COUNT(DISTINCT name_raw), not COUNT(*): a supervisor on three theses is one
-- identity decision, not three, and the row grain would inflate the confident
-- tiers over the unmatched ones — flattering the number that matters least.
-- Same reason COUNT(DISTINCT project_id) is the rule over project_people.
SELECT match_status,
       COUNT(DISTINCT name_raw) AS name_count
FROM thesis_people
GROUP BY match_status
ORDER BY name_count DESC, match_status;
