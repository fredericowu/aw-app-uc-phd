-- How many distinct works are cited by exactly N theses.
--
-- This is the query that decides the tab's default view, so it is committed
-- rather than computed: ~97% of the corpus's references sit at cited_by = 1,
-- and a ranked list whose tail is 22k works tied at one citation is not a
-- ranking. uc_phd_app/bibliography.py's DEFAULT_MIN_CITED_BY is the answer,
-- and this is the evidence for it, on screen.
SELECT cited_by,
       COUNT(*) AS reference_count
FROM bib_references
GROUP BY cited_by
ORDER BY cited_by;
