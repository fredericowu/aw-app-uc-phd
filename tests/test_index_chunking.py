"""Fixture-based tests for estudo_geral_extractor.index's pure functions.

Same convention as tests/test_estudo_geral_extractor.py: only the pure
chunking/parsing/serialisation logic is tested here. Everything that talks to
Postgres or loads the ONNX model (`db`, `create_table`, `insert_batch`,
`search`, `get_model`, `embed_*`) is deliberately untested — it needs the
workspace Postgres and a 520 MB model download, neither of which exists on a
GitHub-hosted runner. Importing the module is safe on CI precisely because
those imports are lazy, inside the functions that need them.
"""
from estudo_geral_extractor.index import (
    CHUNK_CHARS,
    chunk_text,
    split_front_matter,
    vec_literal,
)

DOC = """---
handle: 10316/117599
title: Audiovisual Metaphors
full_text: true
---

# Audiovisual Metaphors

body text here
"""


def test_split_front_matter_returns_mapping_and_body():
    front, body = split_front_matter(DOC)
    assert front["handle"] == "10316/117599"
    assert front["full_text"] is True
    assert body.startswith("# Audiovisual Metaphors")


def test_split_front_matter_passes_through_when_absent():
    front, body = split_front_matter("no front matter here")
    assert front == {}
    assert body == "no front matter here"


def test_split_front_matter_passes_through_on_unterminated_block():
    raw = "---\nhandle: 10316/1\n"
    assert split_front_matter(raw) == ({}, raw)


def test_chunk_text_empty_body_yields_no_chunks():
    assert chunk_text("   \n  ") == []


def test_chunk_text_short_body_is_one_chunk():
    assert chunk_text("a short thesis abstract") == ["a short thesis abstract"]


def test_chunk_text_respects_the_size_cap_and_never_splits_a_word():
    body = " ".join(f"word{i:04d}" for i in range(2000))
    chunks = chunk_text(body)
    assert len(chunks) > 1
    assert all(len(c) <= CHUNK_CHARS for c in chunks)
    # Every token is intact: a mid-word cut would produce a fragment that is
    # not one of the originals.
    originals = set(body.split())
    assert all(tok in originals for c in chunks for tok in c.split())


def test_chunk_text_overlaps_so_a_sentence_on_a_boundary_survives():
    body = " ".join(f"word{i:04d}" for i in range(2000))
    chunks = chunk_text(body)
    first_tail = chunks[0].split()[-3:]
    assert all(tok in chunks[1] for tok in first_tail)


def test_chunk_text_collapses_whitespace():
    assert chunk_text("a\n\n  b\tc") == ["a b c"]


def test_chunk_text_strips_nul_and_other_control_bytes():
    # A NUL anywhere in the text makes the INSERT fail outright — Postgres
    # `text` cannot hold one — so it has to be gone before the chunk is
    # embedded, not caught at insert time.
    out = chunk_text("clean\x00 te\x01xt\x7f here")
    assert out == ["clean text here"]
    assert "\x00" not in out[0]


def test_vec_literal_is_a_pgvector_literal():
    assert vec_literal([1.0, -0.5, 0.25]) == "[1,-0.5,0.25]"
