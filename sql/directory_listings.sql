-- Where a non-CISUC `people` row came from, one row per (person, unit).
--
-- Read whole and once per request (uc_phd_app/theses.py), the same call
-- sql/external_people.sql gets and for the same reason: the table is a few
-- thousand rows against a 2690-thesis payload, so the round trip costs more
-- than the rows do.
--
-- Ordered by source so a person listed by two units has a stable "primary"
-- listing — the badge shows one unit and the profile lists them all, and a
-- rebuild must not reshuffle which one the badge shows.
SELECT person_slug,
       source,
       unit_name,
       listing_url,
       person_url,
       name_as_published,
       role_as_published
FROM directory_listings
ORDER BY person_slug, source;
