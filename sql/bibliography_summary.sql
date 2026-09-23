-- Headline counts for the Bibliography tab.
--
-- COUNT(DISTINCT handle) over thesis_references, not COUNT(*): a thesis
-- citing 400 works is one thesis. Same rule COUNT(DISTINCT project_id) obeys
-- over project_people, and COUNT(DISTINCT name_raw) over thesis_people.
SELECT
    (SELECT COUNT(*) FROM bib_references)                         AS references_total,
    (SELECT COUNT(*) FROM thesis_references)                      AS citations_total,
    (SELECT COUNT(DISTINCT handle) FROM thesis_references)        AS theses_with_references,
    (SELECT COUNT(*) FROM theses)                                 AS theses_total,
    (SELECT COUNT(*) FROM theses WHERE full_text = 1)             AS theses_with_body,
    (SELECT COUNT(*) FROM bib_references WHERE cited_by >= 2)     AS shared_references,
    (SELECT MAX(cited_by) FROM bib_references)                    AS max_cited_by,
    (SELECT MAX(matcher_version) FROM bib_references)             AS matcher_version;
