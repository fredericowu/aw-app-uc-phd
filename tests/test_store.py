"""Tests for uc_phd_app/store.py.

Same convention as tests/test_index_chunking.py (the P0 prototype's own
tests) for the pure chunking functions. ``VectorStore`` itself needs the
workspace Postgres, which does not exist in this environment — every method
is exercised against a fake db double (``_RecordingDb``) instead, same
technique as ``tests/test_search_routes.py``. ``embed_*``/``load_model`` need
the real 520 MB fastembed/ONNX model, which this repo also does not install
in CI — the ``fake_fastembed`` fixture (``tests/conftest.py``) stands in for
the ONNX runtime only, so the actual prefixing/batching/SQL-building logic in
this file still runs for real.
"""
import os

from uc_phd_app import store


def test_table_names_are_the_real_hyphenated_ones():
    """A test against ``app__test__chunks`` would prove nothing about the
    thing that actually breaks — the prefix has hyphens in it
    (``app__aw-app-uc-phd__``), which is exactly what makes the identifier
    quoting in migrations/0001 and every store.py query load-bearing."""
    assert store.DOCUMENTS_TABLE == "app__aw-app-uc-phd__documents"
    assert store.CHUNKS_TABLE == "app__aw-app-uc-phd__chunks"


def test_chunk_text_empty_body_yields_no_chunks():
    assert store.chunk_text("   \n  ") == []


def test_chunk_text_short_body_is_one_chunk():
    assert store.chunk_text("a short thesis abstract") == ["a short thesis abstract"]


def test_chunk_text_strips_nul_bytes():
    """PDF-extracted checkbox glyphs land as literal NUL bytes in some
    theses (real: 10316/119444) — Postgres text columns reject them
    outright, so they must never reach a chunk."""
    assert store.chunk_text("Nada \x00 Muito \x00") == ["Nada Muito"]


def test_chunk_text_respects_the_size_cap_and_never_splits_a_word():
    body = " ".join(f"word{i:04d}" for i in range(2000))
    chunks = store.chunk_text(body)
    assert len(chunks) > 1
    assert all(len(c) <= store.CHUNK_CHARS for c in chunks)
    originals = set(body.split())
    assert all(tok in originals for c in chunks for tok in c.split())


def test_chunk_text_overlaps_so_a_sentence_on_a_boundary_survives():
    body = " ".join(f"word{i:04d}" for i in range(2000))
    chunks = store.chunk_text(body)
    first_tail = chunks[0].split()[-3:]
    assert all(tok in chunks[1] for tok in first_tail)


def test_vec_literal_is_a_pgvector_literal():
    assert store.vec_literal([1.0, -0.5, 0.25]) == "[1,-0.5,0.25]"


# ── document_content: the embargoed-thesis case ───────────────────────────


def test_document_content_full_text_thesis_includes_title_abstracts_and_body():
    front = {"title": "T", "abstract_en": "EN abstract.", "abstract_pt": "PT abstract.",
              "full_text": True}
    content = store.document_content(front, "The extracted body text.")
    assert "T" in content
    assert "EN abstract." in content
    assert "PT abstract." in content
    assert "The extracted body text." in content


def test_document_content_embargoed_thesis_is_metadata_only():
    """The embargoed thesis (full_text: false) has no body — its content is
    exactly title + abstracts, which is still real, substantial text to
    search over (S3 acceptance criterion #2)."""
    front = {"title": "Deep Learning in Drug Development",
              "abstract_en": "The discovery of new drugs is complex.",
              "abstract_pt": "A descoberta de novos fármacos é complexa.",
              "full_text": False}
    content = store.document_content(front, "*(full text not available)*")
    assert "Deep Learning in Drug Development" in content
    assert "The discovery of new drugs is complex." in content
    assert "full text not available" not in content


def test_document_content_handles_missing_abstracts():
    content = store.document_content({"title": "Bare Title", "full_text": False}, "")
    assert content == "Bare Title"


# ── embeddings (ONNX faked, everything else real) ─────────────────────────


def test_model_loaded_is_false_until_load_model_succeeds(fake_fastembed):
    assert store.model_loaded() is False
    store.load_model()
    assert store.model_loaded() is True


def test_load_model_points_fastembed_cache_at_the_data_dir(fake_fastembed, isolated_data_dir):
    store.load_model()
    assert os.environ["FASTEMBED_CACHE_PATH"] == str(isolated_data_dir / "fastembed_cache")


def test_embed_docs_returns_one_vector_per_text(fake_fastembed):
    vecs = store.embed_docs(["first chunk", "second chunk"])
    assert len(vecs) == 2
    assert len(vecs[0]) == store.VECTOR_DIM
    assert all(isinstance(x, float) for x in vecs[0])


def test_embed_query_returns_a_single_vector(fake_fastembed):
    vec = store.embed_query("a search query")
    assert len(vec) == store.VECTOR_DIM


# ── VectorStore against a fake db double ───────────────────────────────────


class _RecordingDb:
    """Duck-types ctx.db's execute/execute_multi. Records every call for
    assertions and answers just enough to drive VectorStore's real logic."""

    def __init__(self, extension_present=True, table_present=True,
                 table_probe_error=None):
        self.extension_present = extension_present
        self.table_present = table_present
        self.table_probe_error = table_probe_error
        self.calls: list[tuple] = []
        self.md_sha256_by_handle: dict[str, str] = {}

    def execute(self, name, sql, params=None):
        self.calls.append((name, sql, params))
        if "pg_extension" in sql:
            return [(1,)] if self.extension_present else []
        if "to_regclass" in sql:
            if self.table_probe_error:
                raise self.table_probe_error
            return [(self.table_present,)]
        if "count(*)" in sql:
            return [(0,)]
        if "SELECT md_sha256" in sql:
            sha = self.md_sha256_by_handle.get(params["h"])
            return [(sha,)] if sha else []
        return None

    def execute_multi(self, sql, names, params=None):
        self.calls.append(("__multi__", sql, params))
        return []


def test_probe_state_reports_unavailable_when_the_table_probe_raises():
    """The second of probe_state()'s two try/except blocks — the extension
    check passes but the table check itself errors (e.g. a lock timeout)."""
    db = _RecordingDb(table_probe_error=RuntimeError("statement timeout"))
    state = store.VectorStore(db).probe_state()
    assert state["state"] == "unavailable"
    assert "table probe failed" in state["reason"]
    assert "statement timeout" in state["reason"]


def test_document_md_sha256_returns_none_for_an_unknown_handle():
    db = _RecordingDb()
    assert store.VectorStore(db).document_md_sha256("10316/000001") is None


def test_document_md_sha256_returns_the_stored_hash():
    db = _RecordingDb()
    db.md_sha256_by_handle["10316/000001"] = "abc123"
    assert store.VectorStore(db).document_md_sha256("10316/000001") == "abc123"


def test_stats_reports_zero_on_an_empty_store():
    db = _RecordingDb()
    assert store.VectorStore(db).stats() == {"documents": 0, "chunks": 0}


def test_replace_document_upserts_the_document_then_replaces_its_chunks(fake_fastembed):
    db = _RecordingDb()
    vs = store.VectorStore(db)

    written = vs.replace_document(
        handle="10316/000001", slug="10316-000001", title="A Thesis", year="2024",
        source_url="https://estudogeral.uc.pt/handle/10316/000001",
        full_text=True, md_sha256="deadbeef", chunks=["chunk one", "chunk two"],
    )

    assert written == 2
    kinds = [sql.split(None, 1)[0] for _, sql, _ in db.calls if isinstance(sql, str)]
    # document upsert (pending sha), delete-old-chunks, the batch insert,
    # then the final UPDATE that stamps the real sha — in that order, which
    # is what keeps a re-run idempotent (see the docstring: deleting first
    # is what drops stale tail chunks) AND makes a mid-batch crash safe (see
    # test_replace_document_leaves_a_pending_sha_if_chunk_insert_raises).
    assert kinds == ["INSERT", "DELETE", "INSERT", "UPDATE"]
    chunk_insert_params = db.calls[-2][2]
    assert chunk_insert_params["c0"] == "chunk one"
    assert chunk_insert_params["c1"] == "chunk two"
    assert chunk_insert_params["o0"] == 0 and chunk_insert_params["o1"] == 1
    final_update_params = db.calls[-1][2]
    assert final_update_params == {"sha": "deadbeef", "h": "10316/000001"}


def test_replace_document_leaves_a_pending_sha_if_chunk_insert_raises(fake_fastembed):
    """Real incident (10316/117187, /119468, /119520): the loader was killed
    mid-batch, leaving a document row whose md_sha256 already matched its
    real content but with 0 chunks written — so every later resume saw the
    hash match and skipped it forever, permanently losing that thesis from
    search. The document row must only be stamped with the REAL hash after
    every chunk batch has committed; until then it must carry a hash that
    can never match, so a resume reprocesses it instead of treating a
    half-written document as done."""
    db = _RecordingDb()
    orig_execute = db.execute

    def _execute(name, sql, params=None):
        if name == store.CHUNKS_TABLE and sql.strip().startswith("INSERT"):
            db.calls.append((name, sql, params))
            raise RuntimeError("killed mid-batch")
        return orig_execute(name, sql, params)

    db.execute = _execute
    vs = store.VectorStore(db)

    try:
        vs.replace_document(
            handle="10316/000002", slug="10316-000002", title="A Thesis", year="2024",
            source_url="https://estudogeral.uc.pt/handle/10316/000002",
            full_text=True, md_sha256="deadbeef", chunks=["chunk one"],
        )
        assert False, "expected the chunk insert to raise"
    except RuntimeError:
        pass

    document_upserts = [c for c in db.calls if c[0] == store.DOCUMENTS_TABLE and "INSERT" in c[1]]
    assert len(document_upserts) == 1
    assert document_upserts[0][2]["md_sha256"] != "deadbeef"
    # No UPDATE ever ran to stamp the real hash.
    assert not any(c[0] == store.DOCUMENTS_TABLE and c[1].strip().startswith("UPDATE")
                   for c in db.calls)


def test_replace_document_batches_inserts_past_insert_batch_size(fake_fastembed, monkeypatch):
    monkeypatch.setattr(store, "INSERT_BATCH", 2)
    db = _RecordingDb()
    vs = store.VectorStore(db)

    written = vs.replace_document(
        handle="h", slug="h", title="T", year=None,
        source_url="https://estudogeral.uc.pt/handle/h",
        full_text=False, md_sha256="s", chunks=["a", "b", "c"],
    )

    assert written == 3
    chunk_inserts = [c for c in db.calls
                     if isinstance(c[1], str) and "INSERT INTO {table} (handle, ordinal" in c[1]]
    assert len(chunk_inserts) == 2  # 2 + 1, not one 3-row insert
    first_batch_params, second_batch_params = chunk_inserts[0][2], chunk_inserts[1][2]
    assert set(k for k in first_batch_params if k.startswith("o")) == {"o0", "o1"}
    assert set(k for k in second_batch_params if k.startswith("o")) == {"o0"}
    assert second_batch_params["o0"] == 2  # continues the ordinal sequence


def test_search_carries_handle_and_source_url_for_every_result(fake_fastembed):
    db = _RecordingDb()
    db.execute_multi = lambda sql, names, params=None: [
        ("10316/117599", "Audiovisual Metaphors",
         "https://estudogeral.uc.pt/handle/10316/117599", True, 0,
         "some chunk text", 0.12),
    ]
    result = store.VectorStore(db).search("audiovisual metaphors", k=3)
    assert result["results"][0]["handle"] == "10316/117599"
    assert result["results"][0]["source_url"].startswith("https://estudogeral.uc.pt")
    assert result["results"][0]["full_text"] is True
    assert "embed_ms" in result and "db_ms" in result


# ── per-thesis abstract embedding (migrations/0002) ──────────────────────


def test_abstract_content_is_title_plus_abstracts_and_never_the_body():
    """One vector per thesis has to mean the same thing for every thesis —
    folding the full body in for the 17 non-embargoed ones and not the 18th
    would make its distance incomparable."""
    front = {"title": "T", "abstract_en": "EN", "abstract_pt": "PT", "full_text": True}
    assert store.abstract_content(front) == "T\n\nEN\n\nPT"
    assert "BODY" not in store.abstract_content(front)


def test_abstract_content_tolerates_missing_abstracts():
    assert store.abstract_content({"title": "T"}) == "T"


class _ReindexDb:
    """Answers the needs_reindex probe with a canned (sha, has_abstract)."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, name, sql, params=None):
        self.calls.append((name, sql, params))
        return self.rows


def test_needs_reindex_is_true_for_a_document_that_does_not_exist():
    assert store.VectorStore(_ReindexDb([])).needs_reindex("h", "sha") is True


def test_needs_reindex_is_true_when_the_content_changed():
    assert store.VectorStore(_ReindexDb([("other", True)])).needs_reindex("h", "sha") is True


def test_needs_reindex_is_true_when_the_abstract_vector_is_missing():
    """THE TRAP. migrations/0002 adds abstract_embedding as NULL to 18 rows
    that are already fully indexed. Resuming on md_sha256 alone skips every
    one of them, leaves every abstract_embedding NULL, and the Fit screen
    answers "no theses matched" — indistinguishable from a real zero-match,
    with nothing logged anywhere."""
    assert store.VectorStore(_ReindexDb([("sha", False)])).needs_reindex("h", "sha") is True


def test_needs_reindex_is_false_only_when_both_hold():
    assert store.VectorStore(_ReindexDb([("sha", True)])).needs_reindex("h", "sha") is False


def test_set_abstract_embedding_writes_one_vector_for_the_handle():
    db = _ReindexDb([])
    store.VectorStore(db).set_abstract_embedding("h", [0.5] * store.VECTOR_DIM)
    name, sql, params = db.calls[0]
    assert name == store.DOCUMENTS_TABLE
    assert "abstract_embedding = CAST(:e AS public.vector)" in sql
    assert params["h"] == "h"
    assert params["e"].startswith("[0.5,")


def test_abstract_coverage_counts_theses_against_matchable_ones():
    cov = store.VectorStore(_ReindexDb([(18, 16)])).abstract_coverage()
    assert cov == {"theses": 18, "matchable": 16}


def test_abstract_coverage_of_an_empty_table_is_zero():
    assert store.VectorStore(_ReindexDb([])).abstract_coverage() == {
        "theses": 0, "matchable": 0}


class _MatchDb:
    """Serves the three queries match_theses issues, keyed on SQL shape."""

    def __init__(self, match_rows, evidence_rows=(), coverage=(18, 18)):
        self.match_rows = match_rows
        self.evidence_rows = evidence_rows
        self.coverage = coverage
        self.sql = []

    def execute(self, name, sql, params=None):
        self.sql.append(sql)
        if "count(abstract_embedding)" in sql:
            return [self.coverage]
        if "CROSS JOIN LATERAL" in sql:
            return list(self.evidence_rows)
        return list(self.match_rows)


def test_match_theses_orders_by_the_best_facet_not_the_average():
    rows = [
        ("a", "A", "u", True, 0.40, 0.90),   # best 0.40
        ("b", "B", "u", True, 0.90, 0.20),   # best 0.20 — lower mean loses, max wins
    ]
    # The fake db returns rows in the order given; ORDER BY is Postgres's job,
    # so this asserts the fusion arithmetic and rank assignment, not the sort.
    out = store.VectorStore(_MatchDb(rows)).match_theses([[0.0], [1.0]], k=5)
    assert [r["distance"] for r in out["results"]] == [0.40, 0.20]
    assert [r["facet_index"] for r in out["results"]] == [0, 1]
    assert [r["rank"] for r in out["results"]] == [1, 2]


def test_match_theses_builds_one_bound_parameter_per_facet():
    db = _MatchDb([])
    store.VectorStore(db).match_theses([[0.1], [0.2], [0.3]], k=5)
    sql = db.sql[0]
    assert "LEAST(d0, d1, d2)" in sql
    assert sql.count("CAST(:f") == 3
    assert "WHERE abstract_embedding IS NOT NULL" in sql


def test_match_theses_attaches_the_best_chunk_for_the_winning_facet():
    rows = [("a", "A", "u", True, 0.9, 0.2)]
    db = _MatchDb(rows, evidence_rows=[("a", 7, "the   real  passage")])
    out = store.VectorStore(db).match_theses([[0.0], [1.0]], k=5)
    r = out["results"][0]
    assert r["snippet"] == "the real passage"
    assert r["ordinal"] == 7
    # The evidence query asks for the facet that actually won this thesis.
    assert "CROSS JOIN LATERAL" in db.sql[1]


def test_match_theses_with_no_results_skips_the_evidence_query():
    db = _MatchDb([])
    out = store.VectorStore(db).match_theses([[0.1]], k=5)
    assert out["results"] == []
    assert not any("CROSS JOIN LATERAL" in s for s in db.sql)


def test_match_theses_reports_coverage_alongside_the_results():
    out = store.VectorStore(_MatchDb([], coverage=(18, 17))).match_theses([[0.1]], k=5)
    assert out["coverage"] == {"theses": 18, "matchable": 17}
