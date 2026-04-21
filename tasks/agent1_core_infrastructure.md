# Agent 1 Task: Core Infrastructure + Memory

> **Role**: You are building the FOUNDATION layer of Ghost — config, database, memory, event bus, task management, and logging. Every other module depends on your work.
>
> **Working Directory**: `/home/mohit/Coding/ghost v3.0/`
>
> **Do NOT touch files outside your assigned list.** Other agents are building brain/, synthesis/, cli/, api/, and core/daemon.py concurrently.

---

## Context: What Is Ghost?

Ghost is a local-first AI daemon that runs as a background process. It watches your projects, maintains a knowledge graph in SQLite, and synthesizes its own tools. You are building the data layer and core infrastructure that everything else plugs into.

**Read these files to understand the full spec:**
- `ghost_implementation_plan_v3.md` — Full architecture and pseudocode
- `final_gaps_analysis.md` — Gaps 1-10 and their solutions
- `final_bug_sweep.md` — 7 bugs found in pseudocode (YOU must fix bugs 1, 2, 5, 7)

---

## Your Files (17 files)

```
src/ghost/
├── config/
│   ├── __init__.py          # Already exists (empty)
│   ├── schema.py            # ← YOU BUILD THIS
│   ├── loader.py            # ← YOU BUILD THIS
│   └── migrations.py        # ← YOU BUILD THIS
├── memory/
│   ├── __init__.py          # Already exists (empty)
│   ├── database.py          # ← YOU BUILD THIS
│   ├── writer.py            # ← YOU BUILD THIS
│   ├── migrations/
│   │   ├── __init__.py      # Already exists (empty)
│   │   ├── runner.py        # ← YOU BUILD THIS
│   │   ├── 001_initial.sql  # ← YOU BUILD THIS
│   │   └── 002_vectors.sql  # ← YOU BUILD THIS
│   ├── entities.py          # ← YOU BUILD THIS
│   ├── graph.py             # ← YOU BUILD THIS
│   ├── vectors.py           # ← YOU BUILD THIS
│   ├── search.py            # ← YOU BUILD THIS
│   └── audit.py             # ← YOU BUILD THIS
├── core/
│   ├── events.py            # ← YOU BUILD THIS
│   ├── tasks.py             # ← YOU BUILD THIS
│   └── logging.py           # ← YOU BUILD THIS

tests/unit/
├── test_config.py           # ← YOU BUILD THIS
├── test_events.py           # ← YOU BUILD THIS
├── test_writer.py           # ← YOU BUILD THIS
├── test_graph.py            # ← YOU BUILD THIS
├── test_circuit_breaker.py  # ← YOU BUILD THIS (yes, test the pattern even though senses/ builds it)
```

---

## File 1: `src/ghost/config/schema.py`

Pydantic v2 models for all Ghost configuration.

```python
"""
Ghost configuration schema — Pydantic v2 models.

Config is loaded from ~/.ghost/config.toml.
API keys are loaded from ~/.ghost/.env via SecretConfig (pydantic-settings).
"""
from enum import Enum
from pathlib import Path
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"


class TierConfig(BaseModel):
    """Configuration for a single LLM tier."""
    provider: LLMProvider = LLMProvider.OPENAI
    model: str
    max_tokens: int = 4096
    temperature: float = 0.3


class LLMConfig(BaseModel):
    """LLM provider and model configuration."""
    default_provider: LLMProvider = LLMProvider.OPENAI
    tier2: TierConfig  # Tool synthesis, triage (mid-range)
    tier3: TierConfig  # Complex analysis (high-end)
    request_timeout: int = 60
    max_retries: int = 3


class WatchConfig(BaseModel):
    """File watching and event processing configuration."""
    debounce_seconds: float = 2.0
    significance_threshold: float = 0.6
    reconcile_interval_minutes: int = 60
    max_watched_dirs: int = 5
    storm_threshold: int = 50
    storm_window_seconds: float = 3.0
    storm_cooldown_seconds: float = 30.0


class SandboxConfig(BaseModel):
    """Tool execution sandbox limits."""
    exec_timeout_seconds: int = 30
    install_timeout_seconds: int = 120  # For uv first-run cold cache
    memory_limit_mb: int = 256
    max_output_bytes: int = 1_048_576
    prefer_uv: bool = True


class GhostConfig(BaseModel):
    """Root configuration model."""
    version: int = 1
    ghost_home: Path = Field(default_factory=lambda: Path.home() / ".ghost")
    socket_path: Path = Field(default_factory=lambda: Path.home() / ".ghost" / "ghost.sock")
    db_path: Path = Field(default_factory=lambda: Path.home() / ".ghost" / "ghost.db")
    llm: LLMConfig
    watch: WatchConfig = WatchConfig()
    sandbox: SandboxConfig = SandboxConfig()
    log_level: str = "INFO"


class SecretConfig(BaseSettings):
    """
    API keys loaded from ~/.ghost/.env (NOT config.toml).
    Uses pydantic-settings for env file + env var loading.
    
    BUG FIX (Bug #4 from final_bug_sweep.md):
    Uses model_config = SettingsConfigDict(...) instead of inner Config class.
    Pydantic v2 deprecated the inner Config class.
    """
    model_config = SettingsConfigDict(
        env_file=str(Path.home() / ".ghost" / ".env"),
        env_file_encoding="utf-8",
    )

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""
```

**Build this EXACTLY as shown.** The other agents import `GhostConfig`, `SecretConfig`, `LLMProvider`, `TierConfig`, `LLMConfig`, `SandboxConfig` from `ghost.config.schema`.

---

## File 2: `src/ghost/config/loader.py`

Loads config from TOML file + env vars, returns a `GhostConfig` instance.

**Requirements:**
- Load from `~/.ghost/config.toml` if it exists
- Fall back to sensible defaults if no config file exists
- Merge environment variable overrides (e.g., `GHOST_LOG_LEVEL=DEBUG`)
- Return a fully populated `GhostConfig` instance

```python
"""
Config loader: TOML file → GhostConfig.

Priority: config.toml → environment variables → defaults.
"""
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def load_config(config_path: Path | None = None) -> "GhostConfig":
    """
    Load Ghost configuration.
    
    Args:
        config_path: Optional explicit path to config.toml.
                     Defaults to ~/.ghost/config.toml.
    
    Returns:
        Fully populated GhostConfig instance.
    """
    from ghost.config.schema import GhostConfig, LLMConfig, TierConfig, LLMProvider
    from ghost.constants import DEFAULT_GHOST_HOME, DEFAULT_CONFIG_FILE
    
    ghost_home = Path(os.environ.get("GHOST_HOME", str(DEFAULT_GHOST_HOME)))
    
    if config_path is None:
        config_path = ghost_home / DEFAULT_CONFIG_FILE
    
    if config_path.exists():
        # Load from TOML
        # Use tomllib (Python 3.11+) or tomli for <3.12
        import sys
        if sys.version_info >= (3, 12):
            import tomllib
        else:
            import tomli as tomllib
        
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        
        # Apply config version migration if needed
        from ghost.config.migrations import migrate_config
        data = migrate_config(data)
        
        return GhostConfig(**data)
    else:
        # Return defaults
        logger.info(f"No config file at {config_path}, using defaults")
        return GhostConfig(
            ghost_home=ghost_home,
            socket_path=ghost_home / "ghost.sock",
            db_path=ghost_home / "ghost.db",
            llm=LLMConfig(
                tier2=TierConfig(provider=LLMProvider.OPENAI, model="gpt-4o-mini"),
                tier3=TierConfig(provider=LLMProvider.OPENAI, model="gpt-4o"),
            ),
            log_level=os.environ.get("GHOST_LOG_LEVEL", "INFO"),
        )


def save_config(config: "GhostConfig", config_path: Path | None = None) -> None:
    """Save current config to TOML file."""
    import tomli_w
    from ghost.constants import DEFAULT_CONFIG_FILE
    
    if config_path is None:
        config_path = config.ghost_home / DEFAULT_CONFIG_FILE
    
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    data = config.model_dump(mode="json")
    # Convert Path objects to strings for TOML
    for key in ("ghost_home", "socket_path", "db_path"):
        if key in data:
            data[key] = str(data[key])
    
    with open(config_path, "wb") as f:
        tomli_w.dump(data, f)
```

Don't forget `import os` at the top.

---

## File 3: `src/ghost/config/migrations.py`

Simple config version migration system.

```python
"""Config version transforms. Handles upgrading old config.toml formats."""

import logging

logger = logging.getLogger(__name__)

def migrate_config(data: dict) -> dict:
    """Apply sequential config migrations based on version field."""
    version = data.get("version", 0)
    
    if version < 1:
        data = _migrate_v0_to_v1(data)
    
    # Future: if version < 2: data = _migrate_v1_to_v2(data)
    
    return data


def _migrate_v0_to_v1(data: dict) -> dict:
    """Initial migration: ensure all required fields exist with defaults."""
    data.setdefault("version", 1)
    data.setdefault("log_level", "INFO")
    logger.info("Migrated config from v0 to v1")
    return data
```

---

## File 4: `src/ghost/memory/database.py`

Database connection management with SQLite pragmas.

**Requirements:**
- `get_connection(db_path)` → returns configured aiosqlite connection with WAL mode + pragmas from `constants.py`
- `check_integrity(db_path)` → runs `PRAGMA integrity_check`, archives corrupt DB (see final_gaps_analysis.md Gap 7)
- All pragmas from `constants.DB_PRAGMAS` applied on every connection

```python
"""
SQLite connection management.

Key design decisions:
- WAL mode for concurrent reads with single writer
- All pragmas applied on connection open
- Integrity check on startup with automatic recovery
"""
import aiosqlite
import logging
import time
from pathlib import Path

from ghost.constants import DB_PRAGMAS

logger = logging.getLogger(__name__)


async def get_connection(db_path: Path) -> aiosqlite.Connection:
    """
    Open a configured SQLite connection.
    
    Applies all pragmas from constants.DB_PRAGMAS.
    WAL mode allows concurrent reads while DatabaseWriter handles all writes.
    """
    db = await aiosqlite.connect(str(db_path))
    db.row_factory = aiosqlite.Row
    
    for pragma, value in DB_PRAGMAS.items():
        if isinstance(value, bool):
            value = int(value)
        await db.execute(f"PRAGMA {pragma} = {value};")
    
    return db


def check_integrity(db_path: Path) -> bool:
    """
    Synchronous integrity check. Run BEFORE async operations start.
    
    If corrupt: archives the DB file and returns False.
    Caller should proceed with fresh DB creation.
    """
    import sqlite3
    
    if not db_path.exists():
        return True  # No DB yet, will be created by migrations
    
    try:
        conn = sqlite3.connect(str(db_path))
        result = conn.execute("PRAGMA integrity_check;").fetchone()
        conn.close()
        
        if result[0] == "ok":
            return True
        
        # Corruption detected
        corrupt_path = db_path.with_suffix(f".corrupt.{int(time.time())}")
        db_path.rename(corrupt_path)
        logger.error(
            f"Database corruption detected. "
            f"Corrupt file archived to {corrupt_path}. "
            f"Ghost will rebuild from scratch."
        )
        return False
        
    except Exception as e:
        logger.error(f"Cannot open database: {e}")
        try:
            corrupt_path = db_path.with_suffix(f".corrupt.{int(time.time())}")
            db_path.rename(corrupt_path)
        except Exception:
            pass
        return False
```

---

## File 5: `src/ghost/memory/writer.py`

**THIS IS THE MOST CRITICAL MODULE.** Single-writer queue for SQLite.

> [!CAUTION]
> You MUST apply Bug #2 fix from `final_bug_sweep.md`.
> The consumer loop MUST use `while True` + sentinel exit, NOT `while self._running or not self._queue.empty()`.

```python
"""
Single-writer pattern for SQLite.

ALL writes to the database go through this queue.
Readers can read directly (WAL mode allows concurrent reads).
This eliminates lock contention entirely.

Architecture:
- Any module can call writer.write() or writer.enqueue()
- All writes are processed sequentially by a single consumer coroutine
- writer.write() returns the result (awaits completion)
- writer.enqueue() is fire-and-forget (no result needed)
- writer.stop() sends a sentinel None and waits for drain
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WriteOp:
    """A single database write operation."""
    sql: str
    params: tuple[Any, ...] = ()
    many: bool = False                          # If True, use executemany
    future: asyncio.Future | None = None        # For callers that need the result


class DatabaseWriter:
    """
    Single async consumer that processes all DB writes sequentially.
    
    Usage:
        writer = DatabaseWriter(db)
        await writer.start()
        
        # From any module (concurrency-safe):
        result = await writer.write("INSERT INTO ... RETURNING id", (val1, val2))
        
        # Or fire-and-forget:
        writer.enqueue("INSERT INTO audit_log ...", (val1,))
        
        # Shutdown:
        await writer.stop()  # Drains queue first
    """
    
    def __init__(self, db):
        self.db = db
        self._queue: asyncio.Queue[WriteOp | None] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._started = False
    
    async def start(self) -> None:
        """Start the writer consumer loop."""
        if self._started:
            return
        self._started = True
        self._task = asyncio.create_task(self._consumer(), name="db-writer")
    
    async def stop(self) -> None:
        """Drain queue and stop. Blocks until all pending writes complete."""
        if not self._started:
            return
        self._started = False
        # Send sentinel to unblock the consumer
        await self._queue.put(None)
        if self._task:
            await self._task
            self._task = None
    
    async def write(self, sql: str, params: tuple = (), many: bool = False) -> Any:
        """Write with result (awaits completion)."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await self._queue.put(WriteOp(sql=sql, params=params, many=many, future=future))
        return await future
    
    def enqueue(self, sql: str, params: tuple = (), many: bool = False) -> None:
        """Fire-and-forget write (no result needed)."""
        try:
            self._queue.put_nowait(WriteOp(sql=sql, params=params, many=many))
        except asyncio.QueueFull:
            logger.error(f"Write queue full, dropping: {sql[:80]}")
    
    async def execute_script(self, sql: str) -> None:
        """Execute a multi-statement SQL script (for migrations)."""
        future = asyncio.get_running_loop().create_future()
        # Use a special sentinel to indicate script execution
        op = WriteOp(sql=sql, params=(), many=False, future=future)
        op._is_script = True  # type: ignore
        await self._queue.put(op)
        return await future
    
    async def _consumer(self) -> None:
        """
        Process writes until sentinel None is received.
        
        BUG FIX (Bug #2 from final_bug_sweep.md):
        Uses `while True` + sentinel-only exit instead of
        `while self._running or not self._queue.empty()` which has a race condition.
        """
        while True:
            op = await self._queue.get()
            if op is None:
                break
            try:
                if getattr(op, '_is_script', False):
                    await self.db.executescript(op.sql)
                    await self.db.commit()
                    if op.future:
                        op.future.set_result(None)
                elif op.many:
                    await self.db.executemany(op.sql, op.params)
                    await self.db.commit()
                    if op.future:
                        op.future.set_result(None)
                else:
                    cursor = await self.db.execute(op.sql, op.params)
                    result = await cursor.fetchall()
                    await self.db.commit()
                    if op.future:
                        op.future.set_result(result)
            except Exception as e:
                if op.future and not op.future.done():
                    op.future.set_exception(e)
                else:
                    logger.exception(f"Write failed: {op.sql[:100]}")
            finally:
                self._queue.task_done()
    
    @property
    def pending_count(self) -> int:
        """Number of writes waiting in queue."""
        return self._queue.qsize()
```

---

## File 6: `src/ghost/memory/migrations/runner.py`

Schema migration runner.

```python
"""
Database schema migration runner.

Reads .sql files from the migrations directory and applies them
in order, tracking which have been applied via the schema_version table.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent


async def run_migrations(writer) -> None:
    """
    Apply pending migrations.
    
    1. Ensure schema_version table exists
    2. Find all ###_*.sql files in migrations dir
    3. Apply any that haven't been applied yet (by version number)
    
    Args:
        writer: DatabaseWriter instance (all writes go through it)
    """
    # Bootstrap: create schema_version if it doesn't exist
    await writer.write("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    
    # Get current version
    # Read directly from db (reads don't need to go through writer)
    cursor = await writer.db.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_version"
    )
    row = await cursor.fetchone()
    current_version = row[0]
    
    # Find and sort migration files
    migration_files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    
    for migration_file in migration_files:
        version = int(migration_file.name.split("_")[0])
        if version <= current_version:
            continue
        
        logger.info(f"Applying migration {migration_file.name}...")
        sql = migration_file.read_text()
        
        try:
            await writer.execute_script(sql)
            await writer.write(
                "INSERT INTO schema_version (version) VALUES (?)",
                (version,)
            )
            logger.info(f"Migration {migration_file.name} applied successfully")
        except Exception as e:
            logger.error(f"Migration {migration_file.name} FAILED: {e}")
            raise
```

---

## File 7: `src/ghost/memory/migrations/001_initial.sql`

The initial schema. This is the complete database schema.

> [!CAUTION]
> You MUST include FTS5 sync triggers (Bug #1 from `final_bug_sweep.md`).
> Without these triggers, FTS search returns stale/empty results forever.

```sql
-- Ghost v3.0 initial schema

-- Metadata
CREATE TABLE IF NOT EXISTS ghost_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Projects (multi-project isolation — Gap #4)
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
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
    name, content, content='entities', content_rowid='rowid'
);

-- BUG FIX (Bug #1 from final_bug_sweep.md):
-- FTS5 external content mode does NOT auto-sync. These triggers are REQUIRED.
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

-- Audit Log (append-only)
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

-- Intent Queue (for LLM unavailability)
CREATE TABLE IF NOT EXISTS intent_queue (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

-- File hash cache (for reconciler)
CREATE TABLE IF NOT EXISTS file_hashes (
    path TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    hash TEXT NOT NULL,
    size_bytes INTEGER,
    scanned_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Watched directories
CREATE TABLE IF NOT EXISTS watched_dirs (
    path TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_reconcile_at TEXT
);
```

---

## File 8: `src/ghost/memory/migrations/002_vectors.sql`

Only applied if sqlite-vec is available.

```sql
-- Vector storage for semantic search
-- Only applied if sqlite-vec extension is available

CREATE VIRTUAL TABLE IF NOT EXISTS entity_vectors USING vec0(
    entity_id TEXT,
    embedding FLOAT[384]
);
```

---

## File 9: `src/ghost/memory/entities.py`

Entity CRUD operations. All entities are project-scoped.

**Requirements:**
- All writes go through `DatabaseWriter`
- All reads use the `db` connection directly (WAL mode allows concurrent reads)
- Every entity has a UUID id, project_id, kind, name, content, content_hash
- Soft delete via `deleted_at` column
- `content_hash` is SHA-256 of content (for dedup / change detection)

```python
"""
Entity CRUD — project-scoped nodes in the knowledge graph.

Entity kinds: "file", "function", "class", "module", "insight", "tool", "project"

All writes go through the DatabaseWriter.
Reads happen directly on the db connection (WAL allows this).
"""
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class EntityStore:
    def __init__(self, db, writer):
        self.db = db
        self.writer = writer
    
    async def create(self, project_id: str, kind: str, name: str,
                     content: str | None = None,
                     metadata: dict | None = None) -> str:
        """Create entity, return its ID."""
        entity_id = str(uuid.uuid4())
        content_hash = hashlib.sha256(content.encode()).hexdigest() if content else None
        meta_json = json.dumps(metadata or {})
        
        await self.writer.write(
            """INSERT INTO entities (id, project_id, kind, name, content, content_hash, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (entity_id, project_id, kind, name, content, content_hash, meta_json)
        )
        return entity_id
    
    async def get(self, entity_id: str) -> dict | None:
        """Get entity by ID. Returns None if not found or soft-deleted."""
        cursor = await self.db.execute(
            "SELECT * FROM entities WHERE id = ? AND deleted_at IS NULL",
            (entity_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    async def get_by_name(self, project_id: str, kind: str, name: str) -> dict | None:
        """Get entity by project + kind + name. Returns None if not found."""
        cursor = await self.db.execute(
            """SELECT * FROM entities 
               WHERE project_id = ? AND kind = ? AND name = ? AND deleted_at IS NULL""",
            (project_id, kind, name)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    async def update(self, entity_id: str, content: str | None = None,
                     metadata: dict | None = None) -> None:
        """Update entity content and/or metadata."""
        parts = ["updated_at = datetime('now')"]
        params = []
        
        if content is not None:
            parts.append("content = ?")
            parts.append("content_hash = ?")
            params.extend([content, hashlib.sha256(content.encode()).hexdigest()])
        
        if metadata is not None:
            parts.append("metadata = ?")
            params.append(json.dumps(metadata))
        
        params.append(entity_id)
        
        await self.writer.write(
            f"UPDATE entities SET {', '.join(parts)} WHERE id = ?",
            tuple(params)
        )
    
    async def soft_delete(self, entity_id: str) -> None:
        """Soft delete — sets deleted_at timestamp."""
        await self.writer.write(
            "UPDATE entities SET deleted_at = datetime('now') WHERE id = ?",
            (entity_id,)
        )
    
    async def list_by_project(self, project_id: str, kind: str | None = None,
                               limit: int = 100) -> list[dict]:
        """List entities for a project, optionally filtered by kind."""
        if kind:
            cursor = await self.db.execute(
                """SELECT * FROM entities 
                   WHERE project_id = ? AND kind = ? AND deleted_at IS NULL
                   ORDER BY updated_at DESC LIMIT ?""",
                (project_id, kind, limit)
            )
        else:
            cursor = await self.db.execute(
                """SELECT * FROM entities 
                   WHERE project_id = ? AND deleted_at IS NULL
                   ORDER BY updated_at DESC LIMIT ?""",
                (project_id, limit)
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    
    async def upsert_by_hash(self, project_id: str, kind: str, name: str,
                              content: str, metadata: dict | None = None) -> str:
        """
        Insert or update based on content hash.
        If an entity with the same project/kind/name exists and content changed, update it.
        If content is the same (same hash), skip the write.
        Returns the entity ID.
        """
        existing = await self.get_by_name(project_id, kind, name)
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        
        if existing:
            if existing["content_hash"] == content_hash:
                return existing["id"]  # No change
            await self.update(existing["id"], content=content, metadata=metadata)
            return existing["id"]
        else:
            return await self.create(project_id, kind, name, content, metadata)
```

---

## File 10: `src/ghost/memory/graph.py`

Edge CRUD and graph traversal.

```python
"""
Edge CRUD and graph traversal.

Edges connect entities with typed relationships.
All edges are project-scoped implicitly (through their connected entities).
"""
import json
import logging
import uuid

logger = logging.getLogger(__name__)


class GraphStore:
    def __init__(self, db, writer):
        self.db = db
        self.writer = writer
    
    async def add_edge(self, source_id: str, target_id: str,
                       relation: str, weight: float = 1.0,
                       metadata: dict | None = None) -> str:
        """Create an edge between two entities. Returns edge ID."""
        edge_id = str(uuid.uuid4())
        await self.writer.write(
            """INSERT OR REPLACE INTO edges (id, source_id, target_id, relation, weight, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (edge_id, source_id, target_id, relation, weight, json.dumps(metadata or {}))
        )
        return edge_id
    
    async def get_edges_from(self, entity_id: str, relation: str | None = None) -> list[dict]:
        """Get all outgoing edges from an entity."""
        if relation:
            cursor = await self.db.execute(
                "SELECT * FROM edges WHERE source_id = ? AND relation = ?",
                (entity_id, relation)
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM edges WHERE source_id = ?",
                (entity_id,)
            )
        return [dict(r) for r in await cursor.fetchall()]
    
    async def get_edges_to(self, entity_id: str, relation: str | None = None) -> list[dict]:
        """Get all incoming edges to an entity."""
        if relation:
            cursor = await self.db.execute(
                "SELECT * FROM edges WHERE target_id = ? AND relation = ?",
                (entity_id, relation)
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM edges WHERE target_id = ?",
                (entity_id,)
            )
        return [dict(r) for r in await cursor.fetchall()]
    
    async def get_neighbors(self, entity_id: str, depth: int = 1,
                            limit: int = 50) -> list[dict]:
        """
        Get neighboring entities up to N hops away.
        Returns entities (not edges) with their shortest distance.
        """
        visited = {entity_id}
        current_layer = [entity_id]
        results = []
        
        for d in range(depth):
            next_layer = []
            for eid in current_layer:
                # Get outgoing neighbors
                cursor = await self.db.execute(
                    """SELECT e.*, ed.relation, ed.weight
                       FROM entities e
                       JOIN edges ed ON e.id = ed.target_id
                       WHERE ed.source_id = ? AND e.deleted_at IS NULL""",
                    (eid,)
                )
                for row in await cursor.fetchall():
                    row_dict = dict(row)
                    if row_dict["id"] not in visited:
                        visited.add(row_dict["id"])
                        row_dict["_distance"] = d + 1
                        results.append(row_dict)
                        next_layer.append(row_dict["id"])
                
                # Get incoming neighbors
                cursor = await self.db.execute(
                    """SELECT e.*, ed.relation, ed.weight
                       FROM entities e
                       JOIN edges ed ON e.id = ed.source_id
                       WHERE ed.target_id = ? AND e.deleted_at IS NULL""",
                    (eid,)
                )
                for row in await cursor.fetchall():
                    row_dict = dict(row)
                    if row_dict["id"] not in visited:
                        visited.add(row_dict["id"])
                        row_dict["_distance"] = d + 1
                        results.append(row_dict)
                        next_layer.append(row_dict["id"])
            
            current_layer = next_layer
            if len(results) >= limit:
                break
        
        return results[:limit]
    
    async def remove_edges_for(self, entity_id: str) -> int:
        """Remove all edges involving an entity. Returns count removed."""
        result = await self.writer.write(
            "DELETE FROM edges WHERE source_id = ? OR target_id = ?",
            (entity_id, entity_id)
        )
        return len(result) if result else 0
    
    async def search_related(self, query: str, project_id: str,
                             limit: int = 20) -> list[dict]:
        """
        Find entities related to a query using FTS5 + graph expansion.
        1. FTS5 search for matching entities
        2. Expand via graph neighbors (1-hop)
        3. Return combined, deduplicated results
        """
        # Step 1: FTS5 search
        cursor = await self.db.execute(
            """SELECT e.*, rank
               FROM entities_fts fts
               JOIN entities e ON e.rowid = fts.rowid
               WHERE entities_fts MATCH ? AND e.project_id = ? AND e.deleted_at IS NULL
               ORDER BY rank
               LIMIT ?""",
            (query, project_id, limit)
        )
        fts_results = [dict(r) for r in await cursor.fetchall()]
        
        # Step 2: Expand via 1-hop neighbors
        all_results = {r["id"]: r for r in fts_results}
        for r in fts_results[:5]:  # Only expand top 5
            neighbors = await self.get_neighbors(r["id"], depth=1, limit=10)
            for n in neighbors:
                if n["id"] not in all_results:
                    all_results[n["id"]] = n
        
        return list(all_results.values())[:limit]
```

---

## File 11: `src/ghost/memory/vectors.py`

sqlite-vec with graceful fallback.

```python
"""
Vector storage and similarity search.

Uses sqlite-vec if available, gracefully falls back to no vector search.
When sqlite-vec is unavailable, search.py falls back to FTS5-only.
"""
import logging
import json

logger = logging.getLogger(__name__)

_HAS_SQLITE_VEC = False


def check_sqlite_vec(db_path) -> bool:
    """Check if sqlite-vec extension is available."""
    global _HAS_SQLITE_VEC
    import sqlite3
    try:
        conn = sqlite3.connect(str(db_path))
        conn.enable_load_extension(True)
        conn.load_extension("vec0")
        conn.close()
        _HAS_SQLITE_VEC = True
        logger.info("sqlite-vec extension loaded successfully")
        return True
    except Exception as e:
        logger.info(f"sqlite-vec not available: {e}. Vector search disabled.")
        _HAS_SQLITE_VEC = False
        return False


class VectorStore:
    """Vector storage with sqlite-vec. All methods are no-ops if extension unavailable."""
    
    def __init__(self, db, writer):
        self.db = db
        self.writer = writer
        self.available = _HAS_SQLITE_VEC
    
    async def store(self, entity_id: str, embedding: list[float]) -> None:
        """Store a vector embedding for an entity."""
        if not self.available:
            return
        
        await self.writer.write(
            "INSERT OR REPLACE INTO entity_vectors (entity_id, embedding) VALUES (?, ?)",
            (entity_id, json.dumps(embedding))
        )
    
    async def search(self, query_embedding: list[float], limit: int = 20) -> list[dict]:
        """Find nearest neighbors by cosine similarity."""
        if not self.available:
            return []
        
        cursor = await self.db.execute(
            """SELECT entity_id, distance
               FROM entity_vectors
               WHERE embedding MATCH ?
               ORDER BY distance
               LIMIT ?""",
            (json.dumps(query_embedding), limit)
        )
        return [dict(r) for r in await cursor.fetchall()]
    
    async def delete(self, entity_id: str) -> None:
        """Remove vector for an entity."""
        if not self.available:
            return
        await self.writer.write(
            "DELETE FROM entity_vectors WHERE entity_id = ?",
            (entity_id,)
        )
```

---

## File 12: `src/ghost/memory/search.py`

Unified search: FTS5 + graph + optional vectors.

```python
"""
Unified search combining FTS5, graph traversal, and optional vector search.

Uses Reciprocal Rank Fusion (RRF) to merge results from different sources.
"""
import logging

logger = logging.getLogger(__name__)

# RRF constant (standard value)
RRF_K = 60


class UnifiedSearch:
    def __init__(self, db, graph_store, vector_store=None):
        self.db = db
        self.graph = graph_store
        self.vectors = vector_store
    
    async def search(self, query: str, project_id: str,
                     limit: int = 20,
                     query_embedding: list[float] | None = None) -> list[dict]:
        """
        Multi-source search with RRF fusion.
        
        1. FTS5 text search
        2. Graph-based related entity search
        3. Vector similarity search (if available + embedding provided)
        4. Fuse with Reciprocal Rank Fusion
        """
        # Source 1: FTS5
        fts_results = await self._fts_search(query, project_id, limit=limit * 2)
        
        # Source 2: Graph
        graph_results = await self.graph.search_related(query, project_id, limit=limit * 2)
        
        # Source 3: Vectors (optional)
        vector_results = []
        if self.vectors and self.vectors.available and query_embedding:
            vector_results = await self.vectors.search(query_embedding, limit=limit * 2)
        
        # Fuse results with RRF
        scores: dict[str, float] = {}
        entity_data: dict[str, dict] = {}
        
        for rank, result in enumerate(fts_results):
            eid = result["id"]
            scores[eid] = scores.get(eid, 0) + 1.0 / (RRF_K + rank + 1)
            entity_data[eid] = result
        
        for rank, result in enumerate(graph_results):
            eid = result["id"]
            scores[eid] = scores.get(eid, 0) + 1.0 / (RRF_K + rank + 1)
            entity_data[eid] = result
        
        for rank, result in enumerate(vector_results):
            eid = result.get("entity_id", result.get("id"))
            scores[eid] = scores.get(eid, 0) + 1.0 / (RRF_K + rank + 1)
            # Vector results might not have full entity data
        
        # Sort by fused score
        sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)[:limit]
        
        results = []
        for eid in sorted_ids:
            if eid in entity_data:
                entry = entity_data[eid].copy()
                entry["_rrf_score"] = scores[eid]
                results.append(entry)
        
        return results
    
    async def _fts_search(self, query: str, project_id: str,
                          limit: int = 40) -> list[dict]:
        """Full-text search via FTS5."""
        try:
            cursor = await self.db.execute(
                """SELECT e.*, rank as _fts_rank
                   FROM entities_fts fts
                   JOIN entities e ON e.rowid = fts.rowid
                   WHERE entities_fts MATCH ? AND e.project_id = ? AND e.deleted_at IS NULL
                   ORDER BY rank
                   LIMIT ?""",
                (query, project_id, limit)
            )
            return [dict(r) for r in await cursor.fetchall()]
        except Exception as e:
            logger.warning(f"FTS search failed: {e}")
            return []
```

---

## File 13: `src/ghost/memory/audit.py`

Append-only audit log.

```python
"""
Audit log — semantic event logging.

Records WHAT Ghost did (not HOW — that's the operational log).
Examples: "tool forged", "entity created", "insight generated".

All writes go through DatabaseWriter (fire-and-forget).
"""
import json
import logging
import uuid

logger = logging.getLogger(__name__)


class AuditLog:
    def __init__(self, db, writer):
        self.db = db
        self.writer = writer
    
    def log(self, topic: str, payload: dict | None = None,
            causation_id: str | None = None) -> None:
        """
        Record an audit event. Fire-and-forget (non-blocking).
        
        Args:
            topic: Dotted event topic (e.g., "forge.completed")
            payload: Event data as dict
            causation_id: ID of the event that caused this one
        """
        event_id = str(uuid.uuid4())
        self.writer.enqueue(
            """INSERT INTO audit_log (id, topic, payload, causation_id)
               VALUES (?, ?, ?, ?)""",
            (event_id, topic, json.dumps(payload or {}), causation_id)
        )
    
    async def query(self, topic: str | None = None,
                    limit: int = 50, offset: int = 0) -> list[dict]:
        """Query audit log entries."""
        if topic:
            cursor = await self.db.execute(
                """SELECT * FROM audit_log
                   WHERE topic = ?
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (topic, limit, offset)
            )
        else:
            cursor = await self.db.execute(
                """SELECT * FROM audit_log
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset)
            )
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
            results.append(d)
        return results
    
    async def prune(self, days: int = 30) -> int:
        """Delete audit entries older than N days. Returns count deleted."""
        result = await self.writer.write(
            "DELETE FROM audit_log WHERE created_at < datetime('now', ?)",
            (f"-{days} days",)
        )
        count = len(result) if result else 0
        if count:
            logger.info(f"Pruned {count} audit log entries older than {days} days")
        return count
    
    async def count(self) -> int:
        """Total number of audit entries."""
        cursor = await self.db.execute("SELECT COUNT(*) FROM audit_log")
        row = await cursor.fetchone()
        return row[0]
```

---

## File 14: `src/ghost/core/events.py`

Async pub/sub event bus.

> [!CAUTION]
> Bug #7 from `final_bug_sweep.md`: Use `deque(maxlen=500)` for history, NOT an unbounded list.

```python
"""
Async pub/sub event bus.

Central nervous system of Ghost. All modules communicate via events.
Handlers are async and run as tasks (non-blocking).
"""
import asyncio
import logging
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """An event in the Ghost system."""
    topic: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    causation_id: str | None = None


# Type alias for event handlers
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """
    Async pub/sub event bus with topic-based routing.
    
    BUG FIX (Bug #7 from final_bug_sweep.md):
    Uses deque(maxlen=500) instead of unbounded list to prevent
    memory spikes during event storms.
    """
    
    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._history: deque[Event] = deque(maxlen=500)
        self._active_tasks: set[asyncio.Task] = set()
    
    def subscribe(self, topic: str, handler: EventHandler) -> None:
        """Register a handler for a topic. Supports wildcards: 'forge.*'"""
        self._handlers[topic].append(handler)
        logger.debug(f"Subscribed {handler.__name__} to '{topic}'")
    
    def unsubscribe(self, topic: str, handler: EventHandler) -> None:
        """Remove a handler from a topic."""
        if topic in self._handlers:
            self._handlers[topic] = [h for h in self._handlers[topic] if h != handler]
    
    async def publish(self, topic: str, payload: dict | None = None,
                      causation_id: str | None = None) -> Event:
        """
        Publish an event. Matching handlers run as concurrent tasks.
        Returns the created Event.
        """
        event = Event(
            topic=topic,
            payload=payload or {},
            causation_id=causation_id,
        )
        self._history.append(event)
        
        # Find matching handlers (exact match + wildcard)
        handlers = list(self._handlers.get(topic, []))
        
        # Check wildcard subscriptions (e.g., "forge.*" matches "forge.completed")
        for pattern, pattern_handlers in self._handlers.items():
            if pattern.endswith(".*"):
                prefix = pattern[:-2]
                if topic.startswith(prefix + ".") and pattern != topic:
                    handlers.extend(pattern_handlers)
        
        # Run handlers as tasks
        for handler in handlers:
            task = asyncio.create_task(
                self._safe_invoke(handler, event),
                name=f"event-{topic}-{handler.__name__}"
            )
            self._active_tasks.add(task)
            task.add_done_callback(self._active_tasks.discard)
        
        return event
    
    async def _safe_invoke(self, handler: EventHandler, event: Event) -> None:
        """Invoke handler with error catching."""
        try:
            await handler(event)
        except Exception:
            logger.exception(
                f"Handler {handler.__name__} failed for event {event.topic}"
            )
    
    async def drain(self) -> None:
        """Wait for all active handler tasks to complete."""
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
    
    @property
    def history(self) -> list[Event]:
        """Recent event history (up to 500)."""
        return list(self._history)
    
    @property
    def handler_count(self) -> dict[str, int]:
        """Number of handlers per topic."""
        return {topic: len(handlers) for topic, handlers in self._handlers.items()}
```

---

## File 15: `src/ghost/core/tasks.py`

Task manager with semaphore-based concurrency control.

```python
"""
Task manager — controlled concurrency for Ghost operations.

Limits:
- LLM calls: max 2 concurrent (parallel forge + triage)
- Tool execution: max 1 at a time (prevent resource contention)
"""
import asyncio
import logging
from typing import Any, Coroutine, TypeVar

from ghost.constants import MAX_CONCURRENT_LLM_CALLS, MAX_CONCURRENT_EXEC

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TaskManager:
    """Manages concurrent Ghost operations with controlled parallelism."""
    
    def __init__(self, max_llm: int = MAX_CONCURRENT_LLM_CALLS,
                 max_exec: int = MAX_CONCURRENT_EXEC):
        self._llm_semaphore = asyncio.Semaphore(max_llm)
        self._exec_semaphore = asyncio.Semaphore(max_exec)
        self._active_tasks: set[asyncio.Task] = set()
    
    async def submit_llm_task(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run an LLM call with concurrency limiting."""
        async with self._llm_semaphore:
            logger.debug(f"LLM task acquired semaphore")
            return await coro
    
    async def submit_exec_task(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run a tool execution with concurrency limiting (max 1)."""
        async with self._exec_semaphore:
            logger.debug(f"Exec task acquired semaphore")
            return await coro
    
    def spawn(self, coro: Coroutine, name: str | None = None) -> asyncio.Task:
        """Spawn a fire-and-forget background task."""
        task = asyncio.create_task(coro, name=name)
        self._active_tasks.add(task)
        task.add_done_callback(self._task_done)
        return task
    
    def _task_done(self, task: asyncio.Task) -> None:
        self._active_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.exception(f"Background task {task.get_name()} failed", exc_info=exc)
    
    async def shutdown(self) -> None:
        """Cancel all active tasks and wait for completion."""
        for task in self._active_tasks:
            task.cancel()
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
        self._active_tasks.clear()
    
    @property
    def active_count(self) -> int:
        return len(self._active_tasks)
    
    @property
    def llm_available(self) -> int:
        """Number of available LLM slots."""
        # Semaphore._value is the current count (not public API but useful for status)
        return self._llm_semaphore._value
    
    @property
    def exec_available(self) -> int:
        """Number of available exec slots."""
        return self._exec_semaphore._value
```

---

## File 16: `src/ghost/core/logging.py`

Non-blocking operational logger.

> [!IMPORTANT]
> Bug #4 edge case from `final_bug_sweep.md`: Use `QueueHandler` + `QueueListener` to avoid blocking the event loop during log rotation.

```python
"""
Non-blocking operational logging.

Uses QueueHandler → background thread → RotatingFileHandler.
The event loop never touches disk. All log formatting and file I/O
happens in the QueueListener's background thread.

This is different from the audit log (which is in SQLite).
- Operational log: HOW Ghost did things (stack traces, timing, debug info)
- Audit log: WHAT Ghost did (semantic events like "tool forged")
"""
import logging
import queue
from logging.handlers import RotatingFileHandler, QueueHandler, QueueListener
from pathlib import Path

from ghost.constants import LOG_MAX_BYTES, LOG_BACKUP_COUNT, LOG_FORMAT, LOGS_DIR, LOG_FILE


def setup_logging(ghost_home: Path, log_level: str = "INFO") -> QueueListener:
    """
    Configure non-blocking logging.
    
    Returns the QueueListener, which MUST be stopped on shutdown:
        listener = setup_logging(config.ghost_home)
        # ... on shutdown:
        listener.stop()
    """
    log_dir = ghost_home / LOGS_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # The actual file handler (runs in background thread)
    file_handler = RotatingFileHandler(
        log_dir / LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    
    # Console handler for development
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    console_handler.setLevel(logging.WARNING)  # Only warnings+ on stderr
    
    # Queue bridges async → sync
    log_queue: queue.Queue = queue.Queue(-1)  # Unbounded
    queue_handler = QueueHandler(log_queue)
    
    # Root ghost logger gets the non-blocking QueueHandler
    root = logging.getLogger("ghost")
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root.addHandler(queue_handler)
    root.addHandler(console_handler)
    
    # QueueListener drains the queue in a background thread
    listener = QueueListener(log_queue, file_handler, respect_handler_level=True)
    listener.start()
    
    return listener


def set_log_level(level: str) -> None:
    """Dynamically change the log level of the ghost logger."""
    root = logging.getLogger("ghost")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
```

---

## Unit Tests

### `tests/unit/test_config.py`

```
Test cases:
1. GhostConfig default values are correct
2. SecretConfig loads from env vars
3. LLMProvider enum values
4. SandboxConfig defaults match constants
5. GhostConfig with custom values
6. Config serialization round-trip (model_dump → GhostConfig)
```

### `tests/unit/test_events.py`

```
Test cases:
1. Subscribe + publish → handler called with correct event
2. Publish to topic with no subscribers → no error
3. Wildcard subscription (forge.*) matches forge.completed
4. Handler exception doesn't crash the bus
5. History is bounded (deque maxlen=500)
6. drain() waits for all handlers
7. Unsubscribe removes handler
8. Event has auto-generated UUID and timestamp
```

### `tests/unit/test_writer.py`

```
Test cases:
1. write() returns result
2. enqueue() is fire-and-forget
3. Multiple concurrent writes are serialized
4. stop() drains pending writes before exiting
5. Exception in write sets future exception
6. Exception in enqueue is logged, not raised
7. Sentinel None stops the consumer (Bug #2 fix)
8. pending_count reflects queue size
```

### `tests/unit/test_graph.py`

```
Test cases:
1. Create entity → get entity → matches
2. Entity soft_delete → get returns None
3. Add edge → get_edges_from returns it
4. get_neighbors returns 1-hop entities
5. upsert_by_hash skips write if hash unchanged
6. list_by_project filters by kind
7. FTS search returns matching entities
8. search_related expands via graph edges
```

---

## Important Reminders

1. **All reads use `self.db` directly.** Only writes go through `self.writer`.
2. **Import constants from `ghost.constants`**, never hardcode values.
3. **Use `logging.getLogger(__name__)` in every module.**
4. **Pydantic v2 only** — use `model_dump()` not `dict()`, `model_validate()` not `parse_obj()`.
5. **Apply all 4 bugs assigned to you**: Bug #1 (FTS triggers), Bug #2 (writer consumer), Bug #5 (token fallback in constants.py is already // 4), Bug #7 (deque maxlen).
6. **Run `ruff check` and `ruff format`** before considering yourself done.

---

## Definition of Done

- [ ] All 17 files created and syntactically valid
- [ ] `python -c "from ghost.config.schema import GhostConfig; print('OK')"` works
- [ ] `python -c "from ghost.memory.writer import DatabaseWriter; print('OK')"` works
- [ ] `python -c "from ghost.core.events import EventBus; print('OK')"` works
- [ ] All unit tests pass: `pytest tests/unit/test_config.py tests/unit/test_events.py tests/unit/test_writer.py tests/unit/test_graph.py -v`
- [ ] `ruff check src/ghost/config/ src/ghost/memory/ src/ghost/core/events.py src/ghost/core/tasks.py src/ghost/core/logging.py` passes
