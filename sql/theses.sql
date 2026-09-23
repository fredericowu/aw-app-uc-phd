-- Every Estudo Geral doctoral thesis in the seed, one row each.
--
-- These rows used to be 18 YAML front matters re-parsed on every request.
-- They are built offline by `python -m analysis.build_thesis_facts` and
-- committed inside data/cisuc.sqlite3, next to the people/project tables they
-- join against. Ordered by handle, which is the order the .md files were read
-- in before, so the dashboard's list does not reshuffle.
SELECT handle,
       slug,
       title,
       date,
       year,
       source_url,
       rights,
       full_text,
       abstract_pt,
       abstract_en
FROM theses
ORDER BY handle;
