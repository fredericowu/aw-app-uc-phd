-- The site exposes a funder NAME, not a funding "type" category — no
-- category is invented here (DESIGN.md: no LLM-derived/enriched fields).
-- Top funders by number of projects funded; long tail collapsed into Other.
--
-- funding_raw is free text (239 distinct values), and the same funder shows
-- up under several spellings — worst offender is FCT (Fundação para a
-- Ciência e a Tecnologia, Portugal's main science agency), split across the
-- 27 variants canonicalized below: plain "FCT", its Portuguese/English full
-- name in various spellings, and "FCT" followed by its own grant code or
-- internal programme name (PTDC/…, POCI-…, PRAXIS, Sapiens). Without this,
-- the chart undercounts FCT (46 instead of its true count) and inflates the
-- long tail with duplicate near-identical rows.
--
-- Values that name FCT alongside a genuinely distinct co-funder (e.g.
-- "FCT/CAPES", "FCT and DAAD", "FCT-CMU, Portugal2020, COMPETE2020, FEDER")
-- are deliberately left as their own funder — collapsing those into plain
-- "FCT" would misrepresent a joint funding arrangement as FCT-only.
-- funding_raw itself is untouched; this canonicalization only affects this
-- aggregate view.
WITH normalized AS (
    SELECT
        CASE funding_raw
            WHEN 'FCT' THEN 'FCT'
            WHEN 'FCT - Fundação para a Ciência e Tecnologia' THEN 'FCT'
            WHEN 'Fundação para a Ciência e Tecnologia' THEN 'FCT'
            WHEN 'Fundação para a Ciência e a Tecnologia' THEN 'FCT'
            WHEN 'Portuguese Science Foundation' THEN 'FCT'
            WHEN 'Fundação para Ciência e Tecnologia' THEN 'FCT'
            WHEN 'Fundação da Ciência e Tecnologia' THEN 'FCT'
            WHEN 'Fundação para a Ciência e a Tecnologia (FCT)' THEN 'FCT'
            WHEN 'FCT- Fundação para a Ciência e a Tecnologia' THEN 'FCT'
            WHEN 'FCT - Fundação para a Ciência e a Tecnologia' THEN 'FCT'
            WHEN 'FCT - Portuguese Science Foundation' THEN 'FCT'
            WHEN 'FCT (POCI-01-0145-FEDER-029297)' THEN 'FCT'
            WHEN 'FCT-Fundação para a Ciência e a Tecnologia (POC-Conhecimento)' THEN 'FCT'
            WHEN 'FCT: PTDC/EIA-EIA/102185/2008' THEN 'FCT'
            WHEN 'FCT: PTDC/CCI-COM/3171/2021' THEN 'FCT'
            WHEN 'FCT- Grid Initiative' THEN 'FCT'
            WHEN 'FCT Sapiens 33572/99' THEN 'FCT'
            WHEN 'FCT PTDC/EIA-EIA/100752/2008' THEN 'FCT'
            WHEN 'FCT PRAXIS' THEN 'FCT'
            WHEN 'FCT POCI-01-0145-FEDER-032504' THEN 'FCT'
            WHEN 'FCT /POSI/SRI/41234/2001, 2002-2005.' THEN 'FCT'
            WHEN 'FCT - project PTDC/EEI-SCR/2072/2014' THEN 'FCT'
            WHEN 'FCT - PTDC/GES/70168/2006' THEN 'FCT'
            WHEN 'FCT - PTDC/EEI-TEL/3684/2014' THEN 'FCT'
            WHEN 'FCT - PTDC/ECM-TRA/1898/2012' THEN 'FCT'
            WHEN 'FCT - PRAXIS/C/EEI/11223/1998' THEN 'FCT'
            WHEN 'FCT - PRAXIS/C/EEI/10168/1998' THEN 'FCT'
            ELSE funding_raw
        END AS funder_normalized
    FROM projects
    WHERE detail_fetched = 1
),
ranked AS (
    SELECT
        COALESCE(funder_normalized, '(no funding listed)') AS funder,
        COUNT(*) AS project_count
    FROM normalized
    GROUP BY funder
),
top15 AS (
    SELECT * FROM ranked ORDER BY project_count DESC LIMIT 15
),
other AS (
    SELECT 'Other' AS funder, SUM(project_count) AS project_count
    FROM ranked
    WHERE funder NOT IN (SELECT funder FROM top15)
)
SELECT funder, project_count FROM top15
UNION ALL
SELECT funder, project_count FROM other WHERE project_count > 0
ORDER BY project_count DESC;
