-- Every thesis and how many references were parsed out of it, including the
-- ones where that number is zero.
--
-- LEFT JOIN, not JOIN: a thesis with no parseable bibliography is the finding,
-- not a row to hide. 42 of the 181 are metadata-only stubs with no body at
-- all, and a handful more have a body whose references did not survive PDF
-- extraction — the two are different failures and full_text tells them apart.
SELECT t.handle,
       t.title,
       t.year,
       t.full_text,
       COUNT(tr.reference_id) AS reference_count
FROM theses t
LEFT JOIN thesis_references tr ON tr.handle = t.handle
GROUP BY t.handle, t.title, t.year, t.full_text
ORDER BY reference_count DESC, t.handle;
