"""Shared fixtures.

Every test runs against a **small fixture database built from
``scraper/schema.sql``**, never the real 400-row snapshot. Two reasons, both
learned the hard way elsewhere:

* Assertions against the real data read as magic numbers (``== 117``) that
  nobody can check, and they break whenever the site is re-scraped — so the
  suite starts failing for a reason that has nothing to do with the code.
* Building the fixture from the shipped ``schema.sql`` means a schema change
  the app has not caught up with fails these tests immediately, which is the
  one thing a hand-rolled ``CREATE TABLE`` in a test file can never do.

``AW_APP_UC_PHD_DATA_DIR`` is redirected to a tmp dir for the whole session so
nothing here can touch the real workspace data directory.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SCHEMA = ROOT / "scraper" / "schema.sql"


def build_fixture_db(path: Path) -> Path:
    """A handful of rows covering every shape the queries care about:
    two research groups, a project in both, a project with no detail page, a
    project with no parsed budget, coordinators and researchers, keywords,
    one academic and one industry partner, and a completed scrape run with
    its manifest."""
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executescript(
        """
        INSERT INTO research_groups (code, name) VALUES
            ('NCS', 'Networks, Communications and Security'),
            ('AC',  'Adaptive Computation');

        INSERT INTO projects
            (id, title, title_norm, detail_url, scope, synopsis, funding_raw,
             partners_raw, total_budget_amount, total_budget_currency,
             cisuc_budget_amount, cisuc_budget_currency,
             start_date, end_date, detail_fetched, detail_unavailable_reason,
             first_seen_at, last_scraped_at)
        VALUES
            (1, 'Alpha Project', 'alpha project', 'https://example.test/alpha',
             'International', 'Alpha solves A.', 'FCT', 'Partner One',
             1000.0, 'EUR', 400.0, 'EUR',
             '2020-01-01', '2023-01-01', 1, NULL,
             '2026-01-01T00:00:00+00:00', '2026-01-02T00:00:00+00:00'),
            (2, 'Beta Project', 'beta project', 'https://example.test/beta',
             'National', 'Beta solves B.', 'FCT', NULL,
             500.0, 'EUR', NULL, NULL,
             '2021-06-01', NULL, 1, NULL,
             '2026-01-01T00:00:00+00:00', '2026-01-02T00:00:00+00:00'),
            (3, 'Gamma Stub', 'gamma stub', NULL,
             NULL, NULL, NULL, NULL,
             NULL, NULL, NULL, NULL,
             NULL, NULL, 0, 'no detail url published by site',
             '2026-01-01T00:00:00+00:00', NULL);

        -- Alpha belongs to BOTH groups: the many-to-many case every per-group
        -- figure has to keep being honest about.
        INSERT INTO project_groups (project_id, group_code) VALUES
            (1, 'NCS'), (1, 'AC'), (2, 'NCS');

        INSERT INTO people (slug, name) VALUES
            ('ada', 'Ada Lovelace'), ('alan', 'Alan Turing');
        INSERT INTO project_people (project_id, person_slug, role, ordinal) VALUES
            (1, 'ada',  'coordinator', 0),
            (1, 'alan', 'researcher',  1),
            (2, 'ada',  'coordinator', 0);

        INSERT INTO project_keywords (project_id, keyword, ordinal) VALUES
            (1, 'networks', 0), (1, 'security', 1);

        INSERT INTO project_partners (project_id, partner_name, partner_type, ordinal) VALUES
            (1, 'University of Testcoimbra', 'academic', 0),
            (1, 'Partner Industries Lda', 'industry', 1);

        INSERT INTO project_fields_raw (project_id, label, ordinal, value_text, href) VALUES
            (1, 'Scope',    0, 'International', NULL),
            (1, 'Keywords', 1, 'networks, security', NULL),
            (1, 'coordinator', 2, 'Ada Lovelace', 'https://example.test/people/ada'),
            (2, 'Scope',    0, 'National', NULL);

        INSERT INTO scrape_runs
            (id, started_at, finished_at, site_total_data, listing_rows, detail_ok, detail_failed)
        VALUES (1, '2026-01-01T00:00:00+00:00', '2026-01-01T01:00:00+00:00', 3, 3, 2, 0);

        INSERT INTO scrape_targets (id, run_id, title, url, status) VALUES
            (1, 1, 'Alpha Project', 'https://example.test/alpha', 'ok'),
            (2, 1, 'Beta Project',  'https://example.test/beta',  'ok'),
            (3, 1, 'Gamma Stub',    NULL,                          'no_detail_url');
        """
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirect the app's data dir per test. Autouse so no test can reach the
    real one by forgetting to ask."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("AW_APP_UC_PHD_DATA_DIR", str(d))
    return d


@pytest.fixture()
def fixture_db(tmp_path):
    return build_fixture_db(tmp_path / "fixture.sqlite3")


@pytest.fixture()
def live_db(isolated_data_dir):
    """A fixture database installed where the app expects to find the live
    one, so route tests exercise the real resolution path."""
    return build_fixture_db(isolated_data_dir / "cisuc.sqlite3")
