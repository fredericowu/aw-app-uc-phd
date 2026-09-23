-- The content signal: how much each thesis's own text looks like each
-- research group's project text, built offline by
-- `python -m analysis.build_group_affinity`.
--
-- Ordered by rank so the first row per handle is the argmax and
-- uc_phd_app/theses.py never has to re-sort. A handle with no rows at all has
-- no content signal — no title tokens, no keywords, no abstract — which is a
-- real state the tier logic reports as `people-only`, not an error.
SELECT handle,
       group_code,
       score,
       "rank"
FROM thesis_group_affinity
ORDER BY handle, "rank";
