-- Migration 002: Vector storage for semantic search
-- Only applied if sqlite-vec extension is available.
-- If this migration fails, Ghost gracefully continues with FTS5-only search.

CREATE VIRTUAL TABLE IF NOT EXISTS entity_vectors USING vec0(
    entity_id TEXT,
    embedding FLOAT[384]
);
