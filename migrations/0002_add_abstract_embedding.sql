-- 0002 — one embedding per THESIS, for the Fit screen's theme matching.
--
-- Same schema-qualification rules as 0001, and for the same reason:
-- src/apps/migrations.py runs this file under `SET LOCAL search_path TO
-- "<workspace schema>"` with NO `, public`, so the `vector` type and the
-- `vector_cosine_ops` opclass must both be spelled `public.` HERE. Queries go
-- through ctx.db, whose search_path DOES include public — do not copy the
-- qualification into uc_phd_app/store.py. Table names stay double-quoted
-- because the enforced `app__aw-app-uc-phd__` prefix contains hyphens.
--
-- WHY A SECOND VECTOR, NEXT TO `chunks.embedding`
-- ------------------------------------------------
-- `chunks` ranks PASSAGES and is what /api/search is built on; it stays
-- untouched. It cannot rank THESES: the corpus is 6609 chunks across 18
-- theses, from 858 (Computational Graphic Design) down to 8 (the embargoed
-- one), and the top 3 theses hold 29.6% of all chunks. No `k` over chunks
-- guarantees 5 distinct theses, and max-over-chunks hands a long thesis ~100x
-- more lottery tickets than a short one. One vector per thesis — over title +
-- abstract_en + abstract_pt — makes ">=5 distinct theses" structural rather
-- than probabilistic.
--
-- NULLABLE ON PURPOSE, AND THE TRAP THAT COMES WITH IT
-- -----------------------------------------------------
-- The column has to be nullable: this runs against a table that already holds
-- 18 fully-indexed rows, and there is no value to backfill it with from SQL —
-- the embedding only exists once the ONNX model has run. That makes the
-- loader's resume check the sharp edge: it skipped any thesis whose
-- `md_sha256` already matched, which after this migration is ALL of them, so
-- every abstract_embedding would stay NULL and the Fit screen would answer
-- "no matches" forever while looking perfectly healthy. The skip condition in
-- estudo_geral_extractor/pgvector_index.py is therefore "sha matches AND
-- abstract_embedding IS NOT NULL" — see `needs_abstract_embedding` in
-- uc_phd_app/store.py.

ALTER TABLE "app__aw-app-uc-phd__documents"
    ADD COLUMN IF NOT EXISTS abstract_embedding public.vector(768);

-- HNSW, not IVFFlat — same reasoning as 0001: this index is created against a
-- column that is entirely NULL at migration time, and an IVFFlat index built
-- with no populated rows gets degenerate centroids and silently bad recall
-- forever after. HNSW has no minimum-population requirement.
--
-- Both the type AND the opclass are `public.` — see the file header.
CREATE INDEX IF NOT EXISTS "app__aw-app-uc-phd__documents_abstract_hnsw"
    ON "app__aw-app-uc-phd__documents" USING hnsw (abstract_embedding public.vector_cosine_ops);
