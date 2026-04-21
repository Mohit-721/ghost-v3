-- Ghost v3.0 initial schema
-- Migration 001: Full initial schema

-- Metadata
CREATE TABLE IF NOT EXISTS ghost_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Projects (multi-project isolation)
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL UNIQUE,
    tech_stack TEXT DEFAULT '{}',
    file_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Entity Graph: Nodes (project-scoped)
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    content TEXT,
    content_hash TEXT,
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_entities_project ON entities(project_id);
CREATE INDEX IF NOT EXISTS idx_entities_kind ON entities(kind);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_entities_hash ON entities(content_hash);

-- Entity Graph: Edges
CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES entities(id),
    target_id TEXT NOT NULL REFERENCES entities(id),
    relation TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);

-- FTS5 full-text search (external content mode)
-- External content mode = FTS index references the entities table directly
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
    name, content, content='entities', content_rowid='rowid'
);

-- BUG FIX (Bug #1 from final_bug_sweep.md):
-- FTS5 external content mode does NOT auto-sync with the main table.
-- Without these triggers, the FTS index is never populated and searches
-- always return empty results. These triggers are MANDATORY.

CREATE TRIGGER IF NOT EXISTS entities_ai AFTER INSERT ON entities BEGIN
    INSERT INTO entities_fts(rowid, name, content)
    VALUES (new.rowid, new.name, new.content);
END;

CREATE TRIGGER IF NOT EXISTS entities_ad AFTER DELETE ON entities BEGIN
    INSERT INTO entities_fts(entities_fts, rowid, name, content)
    VALUES('delete', old.rowid, old.name, old.content);
END;

CREATE TRIGGER IF NOT EXISTS entities_au AFTER UPDATE ON entities BEGIN
    INSERT INTO entities_fts(entities_fts, rowid, name, content)
    VALUES('delete', old.rowid, old.name, old.content);
    INSERT INTO entities_fts(rowid, name, content)
    VALUES (new.rowid, new.name, new.content);
END;

-- Tool Registry (versioned)
CREATE TABLE IF NOT EXISTS tools (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    description TEXT,
    file_path TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'quarantined',
    capabilities TEXT DEFAULT '[]',
    prompt_version TEXT,
    ghost_api_version TEXT,
    runs INTEGER DEFAULT 0,
    last_run_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(name, version)
);

CREATE INDEX IF NOT EXISTS idx_tools_name ON tools(name);
CREATE INDEX IF NOT EXISTS idx_tools_status ON tools(status);

-- Current version pointer for each tool name
CREATE TABLE IF NOT EXISTS tool_current (
    name TEXT PRIMARY KEY,
    current_version_id TEXT NOT NULL REFERENCES tools(id)
);

-- Audit Log (append-only semantic event log)
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    payload TEXT DEFAULT '{}',
    causation_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_topic ON audit_log(topic);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);

-- Cost Tracking
CREATE TABLE IF NOT EXISTS cost_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    purpose TEXT NOT NULL,
    session_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Intent Queue (for LLM unavailability / backpressure)
CREATE TABLE IF NOT EXISTS intent_queue (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

-- File hash cache (for reconciler — change detection)
CREATE TABLE IF NOT EXISTS file_hashes (
    path TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    hash TEXT NOT NULL,
    size_bytes INTEGER,
    scanned_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Watched directories (scoping for senses)
CREATE TABLE IF NOT EXISTS watched_dirs (
    path TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_reconcile_at TEXT
);
