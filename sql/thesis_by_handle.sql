-- One Estudo Geral doctoral thesis by handle — same columns as theses.sql,
-- scoped to a single row for uc_phd_app/mcp's get_phd_thesis tool (S4), which
-- needs the abstracts theses.list_theses() does not surface.
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
WHERE handle = :handle;
