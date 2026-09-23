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
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SCHEMA = ROOT / "scraper" / "schema.sql"


def build_fixture_db(path: Path) -> Path:
    """A handful of rows covering every shape the queries care about:
    two research groups, a project in both, a project with no detail page, a
    project with no parsed budget, coordinators and researchers, keywords,
    one academic and one industry partner, a completed scrape run with its
    manifest, and the thesis-facts corpus below."""
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

        -- 'grace' is on no project at all: a name can resolve to a real
        -- person and still carry zero groups, which is not the same thing as
        -- failing to resolve.
        --
        -- 'grace-1' carries the SAME display name as 'grace' under a second
        -- slug. Three such pairs exist in the real snapshot (joao-bicker /
        -- joao-bicker-1, nuno-seco / nuno-seco-1, teresa-pessoa /
        -- teresa-pessoa-1) and this app has no evidence whether they are the
        -- same human — nothing merges them, and the profile page has to say
        -- so rather than silently present one of them as "the" person.
        INSERT INTO people (slug, name) VALUES
            ('ada', 'Ada Lovelace'), ('alan', 'Alan Turing'),
            ('grace', 'Grace Hopper'), ('grace-1', 'Grace Hopper');
        -- 'ada' holds BOTH roles on Beta. project_people's primary key is
        -- (project_id, person_slug, role), so that is a legal pair of rows
        -- describing ONE membership — and every per-person count in this app
        -- has to be COUNT(DISTINCT project_id) to survive it. The real
        -- snapshot happens to contain zero such rows today, so without this
        -- fixture row a regression from DISTINCT back to COUNT(*) would pass
        -- the whole suite.
        INSERT INTO project_people (project_id, person_slug, role, ordinal) VALUES
            (1, 'ada',  'coordinator', 0),
            (1, 'alan', 'researcher',  1),
            (2, 'ada',  'coordinator', 0),
            (2, 'ada',  'researcher',  1);

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

        -- The thesis facts the offline builder writes (analysis/
        -- build_thesis_facts.py). Three theses covering every shape the
        -- runtime join has to stay honest about: a supervisor who resolves
        -- and carries groups, one who resolves and carries none, an author
        -- who does not resolve at all, a person who is only ever a
        -- *researcher* (the coordinator-then-researcher fallback), and a
        -- thesis where nothing resolves.
        INSERT INTO theses
            (handle, slug, title, date, year, source_url, rights, full_text,
             abstract_pt, abstract_en)
        VALUES
            ('10316/000001', '10316-000001', 'Thesis A', '2024-05-01', '2024',
             'https://estudogeral.uc.pt/handle/10316/000001', 'openAccess', 1,
             'Resumo A.', 'Abstract A.'),
            ('10316/000002', '10316-000002', 'Thesis B', '2025-01-01', '2025',
             'https://estudogeral.uc.pt/handle/10316/000002', 'embargoedAccess', 0,
             NULL, NULL),
            ('10316/000003', '10316-000003', 'Thesis C', '2023-11-20', '2023',
             'https://estudogeral.uc.pt/handle/10316/000003', 'openAccess', 1,
             NULL, NULL);

        INSERT INTO thesis_people
            (handle, name_raw, role, person_slug, match_status, match_confidence,
             match_note, ordinal)
        VALUES
            ('10316/000001', 'Author, Ada Unresolved', 'author', NULL,
             'unmatched', 0.0, 'no row in people carries that surname', 0),
            ('10316/000001', 'Lovelace, Ada', 'supervisor', 'ada',
             'exact', 1.0, 'every token matches', 0),
            ('10316/000001', 'Hopper, Grace', 'supervisor', 'grace',
             'exact', 1.0, 'every token matches', 1),
            ('10316/000002', 'Turing, Alan', 'author', 'alan',
             'exact', 1.0, 'every token matches', 0),
            ('10316/000003', 'Nobody, At All', 'author', NULL,
             'unmatched', 0.0, 'no row in people carries that surname', 0),
            ('10316/000003', 'Ambiguous, Two People', 'supervisor', NULL,
             'ambiguous', 0.4, 'two rows fit and nothing separates them', 0);

        INSERT INTO thesis_keywords (handle, keyword, ordinal) VALUES
            ('10316/000001', 'graphs', 0),
            ('10316/000001', 'graphs', 1);
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


#: One thesis in S1's real front-matter shape, for the offline builder's
#: tests (tests/test_build_thesis_facts.py). The names are chosen against the
#: fixture `people` rows above: "Lovelace, Ada" resolves, the other two do
#: not — so one run covers both the matched and the preserved-unmatched path.
#: `graphs` appears twice on purpose: 9 of the 18 real theses repeat a
#: keyword, which is why thesis_keywords is keyed on ordinal.
THESIS_MD = """---
handle: 10316/000001
title: Fixture Thesis
authors:
- Lovelace, Ada
supervisors:
- Curie, Marie Sklodowska
- Nobody, At All
date: '2024-05-01'
keywords:
- graphs
- graphs
abstract_pt: Um resumo em portugues.
abstract_en: An abstract in English.
rights: openAccess
full_text: true
source_url: https://estudogeral.uc.pt/handle/10316/000001
---

# Fixture Thesis
"""


class _FakeTextEmbedding:
    """Stands in for ``fastembed.TextEmbedding`` — no ONNX runtime, no
    ~520 MB download (fastembed is not installed in this environment; that
    absence is itself one of S3's real findings, see
    ``uc_phd_app/store.py``'s ``model_loaded``). Returns a fixed-length
    vector per input, so the REAL prefixing/batching/float-conversion logic
    in ``store.embed_docs``/``embed_query`` still runs — only the ONNX
    inference itself is faked."""

    def __init__(self, model_name, **kwargs):
        self.model_name = model_name

    def embed(self, texts, batch_size=1):
        for _ in texts:
            yield [0.01] * 768


@pytest.fixture()
def fake_fastembed(monkeypatch):
    """Installs a fake ``fastembed`` module in ``sys.modules`` so
    ``uc_phd_app.store``'s ``from fastembed import TextEmbedding`` succeeds.
    Also resets store's lazy model singleton before/after so tests don't leak
    state into each other via the module-level cache."""
    from uc_phd_app import store as store_mod

    fake_module = types.ModuleType("fastembed")
    fake_module.TextEmbedding = _FakeTextEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", fake_module)
    monkeypatch.setattr(store_mod, "_model", None)
    # load_model() sets this via os.environ.setdefault (a real env mutation,
    # not monkeypatch) — pre-clearing it through monkeypatch means its
    # teardown un-sets it again afterwards, regardless of what the code under
    # test wrote, so it can never leak into an unrelated later test.
    monkeypatch.delenv("FASTEMBED_CACHE_PATH", raising=False)
    yield
    monkeypatch.setattr(store_mod, "_model", None)


@pytest.fixture()
def theses_env(tmp_path, monkeypatch):
    """Redirects the app's theses-related paths to a tiny fixture, the same
    way ``isolated_data_dir`` redirects the database — for route tests that
    exercise ``uc_phd_app/api/theses.py`` through the real env-based
    resolution in ``paths.py`` rather than by passing explicit paths."""
    import json

    estudo_geral = tmp_path / "estudo_geral"
    estudo_geral.mkdir()
    (estudo_geral / "10316-000001.md").write_text(THESIS_FIXTURE_MD, encoding="utf-8")
    monkeypatch.setenv("AW_APP_UC_PHD_ESTUDO_GERAL_DIR", str(estudo_geral))

    attribution = tmp_path / "thesis-attribution.json"
    attribution.write_text(json.dumps(THESIS_FIXTURE_ATTRIBUTION), encoding="utf-8")
    monkeypatch.setenv("AW_APP_UC_PHD_ATTRIBUTION_PATH", str(attribution))

    return {"estudo_geral_dir": estudo_geral, "attribution_path": attribution}
