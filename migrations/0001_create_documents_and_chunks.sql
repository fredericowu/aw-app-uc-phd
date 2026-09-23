-- 0001 — pgvector store for the Estudo Geral thesis corpus (S3).
--
-- DDL-only, as the division of labour requires: src/apps/migrations.py runs
-- this file under `SET LOCAL search_path TO "<workspace schema>"` — with NO
-- `, public` — so every reference to a type or operator class that lives in
-- `public` must be schema-qualified HERE. A bare `vector(768)` or
-- `vector_cosine_ops` fails with "operator class ... does not exist for
-- access method hnsw" the moment search_path stops including public. Queries
-- go through ctx.db (search_path includes public there), so this is the one
-- place in the app that spells `public.` — do not copy it into a query.
--
-- Table names are unquoted-unsafe (the `app__aw-app-uc-phd__` prefix has
-- hyphens in it), so every reference is double-quoted, same as every other
-- app's migration in this workspace.
--
-- HNSW, not IVFFlat — this runs against an EMPTY table (migrations apply
-- before any row exists), and an IVFFlat index built empty gets degenerate
-- centroids and silently bad recall forever after. HNSW has no such
-- minimum-population requirement.

CREATE TABLE IF NOT EXISTS "app__aw-app-uc-phd__documents" (
    handle       text PRIMARY KEY,
    slug         text NOT NULL,
    title        text NOT NULL,
    year         text,
    source_url   text NOT NULL,
    full_text    boolean NOT NULL DEFAULT false,
    md_sha256    text NOT NULL,
    embed_model  text NOT NULL,
    embed_dim    integer NOT NULL,
    indexed_at   timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS "app__aw-app-uc-phd__documents_slug_key"
    ON "app__aw-app-uc-phd__documents" (slug);

CREATE TABLE IF NOT EXISTS "app__aw-app-uc-phd__chunks" (
    id          bigserial PRIMARY KEY,
    handle      text NOT NULL REFERENCES "app__aw-app-uc-phd__documents" (handle) ON DELETE CASCADE,
    ordinal     integer NOT NULL,
    chunk_text  text NOT NULL,
    -- Qualified on purpose: the `vector` extension lives in `public`, this
    -- table lives in the workspace's own schema.
    embedding   public.vector(768) NOT NULL,
    UNIQUE (handle, ordinal)
);

CREATE INDEX IF NOT EXISTS "app__aw-app-uc-phd__chunks_handle_idx"
    ON "app__aw-app-uc-phd__chunks" (handle);

-- Both the type AND the opclass are `public.` — see the file header.
CREATE INDEX IF NOT EXISTS "app__aw-app-uc-phd__chunks_embedding_hnsw"
    ON "app__aw-app-uc-phd__chunks" USING hnsw (embedding public.vector_cosine_ops);
