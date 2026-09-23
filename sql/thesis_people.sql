-- Every author/supervisor edge, with the identity the matcher resolved it to.
--
-- LEFT JOIN, never INNER: an unresolved name is a real row carrying its
-- name_raw and its tier, and an inner join would silently delete exactly the
-- 14 names (of 50) this app is most honest about. person_slug IS NULL is the
-- unmatched/ambiguous case.
--
-- A name can carry two rows when `people` itself holds duplicate rows for one
-- human (joao-bicker / joao-bicker-1) — see scraper/schema.sql.
SELECT tp.handle,
       tp.name_raw,
       tp.role,
       tp.person_slug,
       tp.match_status,
       tp.match_confidence,
       tp.match_note,
       tp.ordinal,
       p.name AS person_name
FROM thesis_people tp
LEFT JOIN people p ON p.slug = tp.person_slug
ORDER BY tp.handle, tp.role, tp.ordinal, tp.person_slug;
