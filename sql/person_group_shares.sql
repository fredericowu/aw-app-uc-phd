-- One person's research groups, as weights rather than a flat set.
--
-- This replaces the coordinator-first / researcher-fallback rule that
-- uc_phd_app/theses.py used to express as two SQL literals. The fallback was
-- not wrong, it was just too blunt: a prolific coordinator genuinely
-- coordinates projects in five groups, so taking all of them union'd a
-- supervisor's whole CV onto every one of their students' theses — 35 of 181
-- theses came out tagged with all six groups (S7).
--
-- The weight is how much of the person's project history sits in each group,
-- not whether any of it does. A coordinator role counts 1.0 and a researcher
-- role 0.4: coordinating is the stronger claim on a group, but being on ten
-- of its projects as a researcher is still a stronger claim than coordinating
-- nothing there. The two roles are summed instead of one excluding the other,
-- which is the actual behaviour change.
--
-- The inner query collapses to ONE row per project before any summing, and
-- takes MAX of the role weight rather than the sum. project_people's key is
-- (project_id, person_slug, role), so one person legitimately holds BOTH
-- roles on one project — that is a single membership described twice, not
-- 1.0 + 0.4 of evidence. Same class of double-count as the two-`people`-rows
-- case below, one level down, and the same rule the rest of this app follows
-- with COUNT(DISTINCT project_id).
--
-- Normalisation to sum 1 is deliberately NOT done here: the caller has to
-- normalise per *name*, not per slug, because one human can hold two rows in
-- `people` (joao-bicker / joao-bicker-1) and normalising per slug would let
-- that person count twice. See _person_group_shares / _resolve_person_rows.
--
-- Still derived live on every request, never frozen into the seed: a group is
-- a live fact about a career, and a new project must move it without a seed
-- rebuild.
SELECT pg.group_code,
       SUM(membership.weight) AS weight
FROM (
    SELECT pp.project_id,
           MAX(CASE pp.role WHEN 'coordinator' THEN 1.0 ELSE 0.4 END) AS weight
    FROM project_people pp
    WHERE pp.person_slug = :slug
    GROUP BY pp.project_id
) AS membership
JOIN project_groups pg ON pg.project_id = membership.project_id
GROUP BY pg.group_code
ORDER BY weight DESC, pg.group_code;
