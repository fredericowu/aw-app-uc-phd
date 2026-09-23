-- How each distinct work's identity was established.
--
-- 'doi' is exact. 'title' is the normalised author+title key, whose recall
-- against DOI ground truth is measured on every build (52.6% at matcher
-- version 1 — analysis/build_bibliography.py prints it). 'unmatched' is a
-- reference no key could be derived from, and is a singleton by construction.
-- Reported next to the data because a count of 3 at tier 'title' means
-- something weaker than a count of 3 at tier 'doi'.
SELECT match_tier,
       COUNT(*)        AS reference_count,
       SUM(cited_by)   AS citation_count
FROM bib_references
GROUP BY match_tier
ORDER BY reference_count DESC, match_tier;
