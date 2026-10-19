"""Harvest UC's per-unit staff directories into `people` + `directory_listings`.

UC runs no institution-wide staff directory. It does not run SIGARRA (that is
Porto's system) and `apps.uc.pt` redirects any university-wide staff listing to
SAML SSO. What exists is one "Docentes" page per Faculty and one "Pessoas" page
per research centre — the same scrapable shape `scraper/people.py` already
reads for CISUC, just one unit at a time.

So this is a *suite*, driven by a committed registry (`units.py`), with one
parser per page SHAPE (`parsers.py`) rather than per unit, and a single
offline one-shot entry point (`run.py`). The three properties it inherits from
`scraper/people.py` and `scraper/run.py` are the ones that matter:

* **additive, never destructive** — `db.upsert_person` semantics, so a person
  who drops off a current page survives, exactly like CISUC's ~182;
* **loud per-unit failure** — a page that changes shape fails ITS unit against
  an `expected_min` floor, the run continues, commits what succeeded, and
  exits non-zero naming every failed unit. A silently short pool quietly
  *narrows* the candidate pool the identity matcher runs against, which is
  worse than not running at all;
* **no app code ever fetches** — the app opens the database `mode=ro`, and the
  committed seed diff is the review artifact.
"""
