-- How the name matcher did, counted over DISTINCT names, SPLIT BY ROLE.
--
-- COUNT(DISTINCT name_raw), not COUNT(*): a supervisor on three theses is one
-- identity decision, not three, and the row grain would inflate the confident
-- tiers over the unmatched ones — flattering the number that matters least.
-- Same reason COUNT(DISTINCT project_id) is the rule over project_people.
--
-- Split by role because pooling the two hides the finding. An author is a
-- doctoral student and an unmatched one is the CORRECT answer (`people` is
-- current CISUC staff); an unmatched supervisor is a hole in the advisor view.
-- One pooled unmatched rate describes neither — see the header of
-- sql/thesis_attribution_coverage.sql, which carries the edge- and
-- thesis-grain figures these per-name tiers cannot express.
--
-- A name appearing in both roles (24 of 283 at time of writing) is counted
-- once under each, so these counts sum to more than the corpus's distinct-name
-- total. That is the price of the split and it is the right one: "how many
-- supervisor names failed" must not be diluted by the same human's author row.
SELECT role,
       match_status,
       COUNT(DISTINCT name_raw) AS name_count
FROM thesis_people
GROUP BY role, match_status
ORDER BY role, name_count DESC, match_status;
