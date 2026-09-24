-- How far the name -> person spine reaches, at the three grains the advisor
-- and collaboration views actually consume.
--
-- WHY NOT ONE NUMBER. sql/thesis_match_tiers.sql answers "how did the matcher
-- do", over distinct names, and that is the wrong question for these views:
-- it pools authors with supervisors. The two populations have OPPOSITE
-- expected outcomes. An author is a doctoral student, so absence from
-- `people` (current CISUC staff) is the correct answer, not a defect; a
-- supervisor is usually staff, and an unresolved one is a real hole in the
-- advisor view. Pooled, the two produce a single unmatched rate that
-- describes neither — 93 of 283 names (32.9%) reads as a third of the graph
-- missing when the supervision graph is 80% resolved.
--
-- `edge` is one row per (thesis, name, role), NOT per thesis_people row. One
-- human can hold two rows in `people` (joao-bicker / joao-bicker-1, see
-- scraper/schema.sql), so a name resolving to both carries two rows there and
-- counting rows would inflate every resolved figure below. Same reason
-- sql/thesis_match_tiers.sql counts DISTINCT name_raw.
--
-- `resolved` is `person_slug IS NOT NULL`, which is exactly what
-- sql/collab_co_supervision.sql filters on — that is what makes these numbers
-- describe the graph that ships rather than a near-miss of it. It agrees with
-- theses.RESOLVED_TIERS by construction: analysis/build_thesis_facts.py's
-- people_rows() only writes slugs for the exact/confident tiers and writes
-- exactly one NULL-slug row otherwise.
WITH edge AS (
    SELECT handle, name_raw, role,
           MAX(person_slug IS NOT NULL) AS resolved
    FROM thesis_people
    GROUP BY handle, name_raw, role
),
sup AS (
    SELECT handle, name_raw, resolved FROM edge WHERE role = 'supervisor'
)
SELECT
    -- Name grain, split by role. A name supervising three theses is one
    -- identity decision; a name appearing in both roles is counted under
    -- each, so these two do not sum to the corpus's distinct-name count.
    (SELECT COUNT(DISTINCT name_raw) FROM edge WHERE role = 'author')
        AS author_names,
    (SELECT COUNT(DISTINCT name_raw) FROM edge WHERE role = 'author' AND resolved)
        AS author_names_resolved,
    (SELECT COUNT(DISTINCT name_raw) FROM sup)
        AS supervisor_names,
    (SELECT COUNT(DISTINCT name_raw) FROM sup WHERE resolved)
        AS supervisor_names_resolved,

    -- Edge grain: the honest headline for the advisor view. A supervisor who
    -- appears on ten theses is ten edges, because ten theses lose their
    -- advisor when that one name fails to resolve.
    (SELECT COUNT(*) FROM sup)                  AS supervision_edges,
    (SELECT COUNT(*) FROM sup WHERE resolved)   AS supervision_edges_resolved,

    -- Thesis grain. `theses_listing_a_supervisor` is the denominator that
    -- matters: a thesis whose front matter names no supervisor at all is an
    -- EXTRACTION gap, not a matching one, and holding the matcher to it
    -- understates it (24 of 181 at time of writing, all 1997-2013).
    (SELECT COUNT(*) FROM theses)               AS theses_total,
    (SELECT COUNT(DISTINCT handle) FROM sup)    AS theses_listing_a_supervisor,
    (SELECT COUNT(DISTINCT handle) FROM sup WHERE resolved)
        AS theses_with_a_resolved_supervisor,
    (SELECT COUNT(*) FROM (
        SELECT handle FROM sup GROUP BY handle HAVING MIN(resolved) = 1
     ))                                         AS theses_fully_resolved,

    -- Pair grain: what the co-supervision graph is built out of. One row per
    -- (thesis, name_a, name_b) — a pair co-supervising two theses is two
    -- occurrences, because each is an edge weight the graph would carry.
    -- Keyed on name, not slug, deliberately: an unresolved name has no slug,
    -- so a slug-keyed count cannot see the pairs it costs.
    (SELECT COUNT(*) FROM sup a JOIN sup b
        ON a.handle = b.handle AND a.name_raw < b.name_raw)
        AS co_supervision_pairs,
    (SELECT COUNT(*) FROM sup a JOIN sup b
        ON a.handle = b.handle AND a.name_raw < b.name_raw
      WHERE a.resolved AND b.resolved)
        AS co_supervision_pairs_resolved,

    -- The aliasing the resolved side already does and no ranking exploits
    -- yet: resolved supervisor NAMES collapse to fewer PEOPLE (91 -> 64 at
    -- time of writing; Edmundo Monteiro is 15 theses under 2 name variants
    -- while the busiest single name is 10). Reported so a future advisor
    -- ranking keyed on name_raw is visibly wrong rather than quietly low.
    (SELECT COUNT(DISTINCT person_slug) FROM thesis_people
      WHERE role = 'supervisor' AND person_slug IS NOT NULL)
        AS supervisor_people;
