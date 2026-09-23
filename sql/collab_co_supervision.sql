-- Co-supervision edges: two people supervised the same thesis together.
-- weight = COUNT(DISTINCT handle) of theses they share, restricted to
-- supervisor rows with a resolved person_slug — an unmatched name_raw is
-- not a graph node (see thesis_people.match_status). Person pairs are keyed
-- by slug, never display name, same as every other person-pair query in
-- this app.
WITH supervision AS (
    SELECT DISTINCT handle, person_slug
    FROM thesis_people
    WHERE role = 'supervisor' AND person_slug IS NOT NULL
)
SELECT
    a.person_slug AS person_a,
    b.person_slug AS person_b,
    COUNT(DISTINCT a.handle) AS weight
FROM supervision a
JOIN supervision b ON a.handle = b.handle AND a.person_slug < b.person_slug
GROUP BY a.person_slug, b.person_slug
ORDER BY weight DESC, a.person_slug, b.person_slug;
