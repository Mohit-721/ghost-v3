# Ghost — Final Gaps Analysis (v2.0 Addendum)

> **Status:** This is the last review pass. After addressing these, the spec is ready for execution.
>
> These gaps were discovered through targeted research of every technology choice in the plan, cross-referencing with known failure modes in production Python daemons.

---

## Research Findings: Technology Validation

Before the gaps — here's what the research **confirmed works** as specified:

| Technology | Status | Notes |
|-----------|--------|-------|
| **FastAPI + Uvicorn on UDS** | ✅ Confirmed | `uvicorn app:main --uds /path/to/sock` works. Socket cleanup on crash requires explicit handling. |
| **watchfiles** | ✅ Confirmed | Rust-based, fast. BUT: still subject to inotify queue overflow on Linux. Supports `force_polling=True` fallback. |
| **sqlite-vec** | ⚠️ Confirmed with risk | C extension — pre-built wheels may not exist for all platforms. Graceful fallback is mandatory. |
| **PEP 723 + uv** | ✅ Confirmed | `uv run script.py` reads inline `# /// script` metadata, auto-installs deps, runs in isolation. This is the RIGHT answer for tool dependencies. |
| **OpenAI Structured Output** | ✅ Confirmed | `response_format: { type: "json_schema", strict: true }` is production-grade. Model literally cannot produce schema-violating tokens. |
| **aiosqlite WAL mode** | ✅ Confirmed | Works. Must tune pragmas on connection open. Single-writer pattern is essential for correctness. |

---

## Gap 1: Stale Socket & Multiple Instance Prevention (Critical)

**What's missing:** The plan doesn't address what happens when Ghost crashes (kill -9, power loss, OOM-killed) and the `.sock` file remains on disk. The next `ghost start` gets "Address already in use" and the user is stuck.

Also: nothing prevents running two daemon instances simultaneously, which would corrupt the database (two writers to the same SQLite file).

**Fix:**

```python
# On daemon startup:
def ensure_single_instance(config: GhostConfig) -> None:
    pid_file = config.ghost_home / "ghost.pid"
    sock_file = config.socket_path

    # 1. Check PID file
    if pid_file.exists():
        old_pid = int(pid_file.read_text().strip())
        if _process_alive(old_pid):
            raise GhostAlreadyRunning(f"Ghost daemon already running (PID {old_pid})")
        else:
            # Stale PID file — old process is dead
            pid_file.unlink()

    # 2. Clean stale socket
    if sock_file.exists():
        sock_file.unlink()

    # 3. Write current PID
    pid_file.write_text(str(os.getpid()))

    # 4. Register cleanup
    atexit.register(lambda: _cleanup(pid_file, sock_file))

def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)  # Signal 0: check existence, don't kill
        return True
    except ProcessLookupError:
        return False
```

**Impact on plan:** Add `pid_file` path to `GhostConfig`. Add `ensure_single_instance()` call at the top of `daemon.py:main()`. Add PID file cleanup to `lifecycle.py` signal handlers.

---

## Gap 2: Tool Dependency Management via PEP 723 (Critical)

**What's missing:** The plan assumes synthesized tools only use the standard library. In practice, LLMs will generate `import pandas`, `import requests`, `import matplotlib` etc. The tool will crash with `ModuleNotFoundError`, the user will think Ghost is broken, and they'll uninstall it.

**Fix:** Use PEP 723 inline script metadata + `uv run` for tool execution.

The forge prompt instructs the LLM to include a PEP 723 header:
```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "requests>=2.31",
# ]
# ///

import requests

def main():
    ...
```

The executor changes from:
```python
subprocess.run(["python", str(tool_path)], ...)
```
to:
```python
subprocess.run(["uv", "run", str(tool_path)], ...)
```

`uv run` automatically reads the inline metadata, creates an isolated virtual environment, installs the declared deps, and runs the script. Zero configuration. The tool is fully self-contained.

**Fallback:** If `uv` is not installed, fall back to bare `python` execution with a warning: "Tool may fail if it requires third-party packages. Install `uv` for automatic dependency management."

**Impact on plan:**
- Add `uv` as a recommended (not required) system dependency in README
- Update `synthesis/executor.py` to prefer `uv run` over bare `python`
- Update `synthesis/forge.py` — the forge prompt must instruct the LLM to include PEP 723 headers
- Update `synthesis/templates/tool_skeleton.py` to include the PEP 723 template
- Add a `ghost doctor` command that checks if `uv` is installed

---

## Gap 3: Structured Output Strategy Per Provider (Important)

**What's missing:** The plan uses `httpx` directly to call LLM APIs and mentions Pydantic for validation, but doesn't address HOW to get reliably structured responses from each provider. They all have different mechanisms:

| Provider | Structured Output Mechanism | Reliability |
|---------|---------------------------|-------------|
| OpenAI | `response_format: { type: "json_schema", json_schema: {...}, strict: true }` | Very high — token-level constraint |
| Anthropic | Tool use (define a "tool" that returns structured data) | High — but different API shape |
| Google Gemini | `response_mime_type: "application/json"` + `response_schema` | Medium — less strict than OpenAI |

**Fix:** Each provider implementation in `brain/providers/` must implement a `structured_complete()` method that uses the provider-native mechanism:

```python
class LLMProvider(Protocol):
    async def complete(self, messages: list[Message], **kwargs) -> Completion: ...
    async def structured_complete(
        self, messages: list[Message], schema: type[BaseModel], **kwargs
    ) -> BaseModel: ...
```

The `structured_complete()` method:
1. Derives a JSON schema from the Pydantic model
2. Passes it through the provider-specific structured output API
3. Validates the response against the Pydantic model
4. Returns a typed Python object, not raw JSON

If validation fails (which should be rare with strict mode), retry once with a "please fix this JSON" follow-up prompt before raising an error.

**Impact on plan:** Add `structured_complete()` to the provider protocol. Each provider implementation handles the translation to its native format.

---

## Gap 4: Multi-Project Isolation (Important)

**What's missing:** The current schema has a flat `entities` table. If a user watches `/home/user/project-a` and `/home/user/project-b`, all entities are mixed together. The Context Assembler might pull files from project-a when analyzing a change in project-b. This produces confusing, irrelevant LLM responses.

**Fix:** Add a `project_id` column to `entities`, `edges`, and `entity_vectors`:

```sql
-- Add to entities table
ALTER TABLE entities ADD COLUMN project_id TEXT REFERENCES projects(id);

-- New table
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,          -- User-friendly name (derived from directory name)
    root_path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

The Context Assembler accepts a `project_id` parameter and scopes all queries:
```python
async def assemble(self, query: str, project_id: str, budget: int | None = None):
    structural = await self.graph.search_related(query, project_id=project_id, limit=20)
    ...
```

Cross-project queries (e.g., "find similar patterns across all my projects") remain possible but must be explicitly requested.

**Impact on plan:** Add `projects` table to `001_initial.sql`. Add `project_id` column to `entities` and `edges`. Update `entity CRUD`, `graph.py`, `search.py`, and `context.py` to accept project scoping. Each `ghost watch <path>` invocation creates/associates a project.

---

## Gap 5: Operational Logging vs Audit Logging (Important)

**What's missing:** The plan has an `audit_log` table for semantic events ("tool forged", "insight generated"). But there's no strategy for **operational logging** — the Python `logging` module output that captures stack traces, timing, asyncio warnings, httpx request/response logs, and database query timing.

When Ghost misbehaves, the user needs `ghost debug` not `ghost logs`.

**Fix:** Two separate log streams:

| Stream | Purpose | Destination | Rotation |
|--------|---------|-------------|----------|
| **Audit log** | Semantic events (what Ghost did) | SQLite `audit_log` table | Prune entries > 30 days old via scheduled task |
| **Operational log** | Python logging (how Ghost did it) | `~/.ghost/logs/ghostd.log` | `RotatingFileHandler`, 5MB per file, 3 backups |

```python
# In daemon startup
import logging
from logging.handlers import RotatingFileHandler

def setup_logging(config: GhostConfig):
    log_dir = config.ghost_home / "logs"
    log_dir.mkdir(exist_ok=True)

    handler = RotatingFileHandler(
        log_dir / "ghostd.log",
        maxBytes=5_000_000,    # 5MB
        backupCount=3,
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    root = logging.getLogger("ghost")
    root.setLevel(logging.DEBUG if config.log_level == "DEBUG" else logging.INFO)
    root.addHandler(handler)
```

CLI commands:
- `ghost logs` — tail the audit log (semantic events)
- `ghost debug` — tail the operational log (Python logging)
- `ghost debug --level DEBUG` — set log level to DEBUG on the running daemon (via API call)

**Impact on plan:** Add `setup_logging()` to daemon startup. Add `logs/` directory to `~/.ghost/`. Add `ghost debug` CLI command. Add `POST /api/config/log-level` API endpoint for dynamic log level changes.

---

## Gap 6: System Suspend / Resume (The Laptop Lid Problem)

**What's missing:** User closes laptop lid. System suspends. User opens laptop 8 hours later. The daemon's asyncio event loop was frozen. Consequences:

- `asyncio.sleep()` timers for the reconciler/scheduler think only seconds have passed — they don't fire when expected
- watchfiles may have missed events during suspend (inotify queue was not being drained)
- The cost meter's "session" time is inflated by 8 hours of sleep
- Any pending HTTP requests to the LLM API timed out during sleep

**Fix:** Suspend detection + recovery:

```python
import time

class SuspendDetector:
    """Detects system suspend/resume by monitoring monotonic clock drift."""

    def __init__(self, threshold_seconds: float = 30.0):
        self.threshold = threshold_seconds
        self._last_check = time.monotonic()

    async def check(self) -> bool:
        """Call this periodically (every 10s). Returns True if suspend was detected."""
        now = time.monotonic()
        elapsed = now - self._last_check
        self._last_check = now

        # If more than threshold+check_interval has passed,
        # the system was likely suspended
        if elapsed > self.threshold:
            return True
        return False
```

When suspend is detected:
1. Log "System resume detected after ~X hours of sleep"
2. Force a reconciliation scan (filesystem may have changed while suspended)
3. Reset all scheduler timers
4. Re-establish any broken WebSocket/HTTP connections
5. Drain the intent queue (API should be available again)

**Impact on plan:** Add `SuspendDetector` to `core/`. Add periodic check in the daemon's main loop. Wire resume events to the reconciler and scheduler.

---

## Gap 7: Database Corruption Recovery (Defensive)

**What's missing:** SQLite is robust, but not immune to corruption — especially if the daemon is kill -9'd during a write, or the disk has errors. If `ghost.db` is corrupt, the daemon crashes on startup and the user is stuck.

**Fix:** Integrity check on startup with automatic recovery:

```python
async def check_database_integrity(db_path: Path) -> bool:
    """Run PRAGMA integrity_check. If corrupt, archive and recreate."""
    try:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("PRAGMA integrity_check;") as cursor:
                result = await cursor.fetchone()
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
        # Can't even open the file
        logger.error(f"Cannot open database: {e}")
        db_path.rename(db_path.with_suffix(f".corrupt.{int(time.time())}"))
        return False
```

The user loses their history but Ghost continues to function. Show a clear CLI message: "⚠️ Database was corrupted and has been archived. Ghost is starting fresh."

**Impact on plan:** Add integrity check before migration runner in `memory/database.py`.

---

## Gap 8: The `ghost uninstall` Command (UX)

**What's missing:** Ghost creates a daemon, a systemd service, a `~/.ghost/` directory with databases and tools, and potentially a PID file. If the user wants to remove Ghost, `pip uninstall ghost-ai` only removes the Python package — everything else stays behind.

**Fix:** `ghost uninstall` command:

```
$ ghost uninstall

⚠️  This will:
  1. Stop the Ghost daemon (if running)
  2. Remove the systemd service (if installed)
  3. Delete ~/.ghost/ (database, tools, config, logs)

Your synthesized tools and knowledge graph will be permanently deleted.

? Proceed? [y/N]: y

✓ Daemon stopped (PID 48291)
✓ Removed systemd service
✓ Deleted /home/mohit/.ghost/ (23 MB)

Ghost has been fully removed.
Run `pip uninstall ghost-ai` to remove the Python package.
```

**Impact on plan:** Add `ghost uninstall` to CLI commands. Add `scripts/uninstall.sh` for users who can't run the CLI.

---

## Gap 9: Windows Non-Support Declaration (Scope)

**What's missing:** The entire plan uses Linux-specific technologies:
- Unix Domain Sockets (doesn't exist on Windows)
- `systemd --user` (Linux only)
- `inotify` via watchfiles (Windows uses `ReadDirectoryChangesW`)
- `resource.setrlimit()` in the sandbox (POSIX only)
- PID files with `os.kill(pid, 0)` (different semantics on Windows)

The plan never explicitly addresses this. If a Windows user tries to install Ghost, it will fail in confusing ways.

**Fix:** Declare the scope explicitly:

```markdown
## Platform Support

| Platform | Status |
|----------|--------|
| Linux (Ubuntu 22.04+, Fedora 38+, Arch) | ✅ Fully supported |
| macOS (13+) | ✅ Supported (launchd instead of systemd) |
| Windows | ❌ Not supported in v1 |
| WSL2 | ✅ Supported (treated as Linux) |
```

For macOS, the differences are:
- `launchctl` / `launchd` instead of `systemd` — generate a `.plist` file instead of `.service`
- `fsevents` instead of `inotify` — watchfiles handles this transparently
- `resource.setrlimit()` may have different limits — test and document

**Impact on plan:**
- Add platform declaration to README
- Add macOS `launchd` plist generator alongside the systemd service generator
- Gate systemd-specific code behind platform checks
- Add platform detection to `ghost init`

---

## Gap 10: Concurrent Request Handling & Task Serialization (Correctness)

**What's missing:** What happens when:
1. User runs `ghost forge "tool A"` and immediately `ghost forge "tool B"` — two LLM calls in parallel, two tools being quarantined simultaneously
2. The file watcher triggers a triage event WHILE a forge is in progress — the Context Assembler is reading the graph while the forge is writing to it
3. Two forge requests generate a tool with the same name

FastAPI handles concurrent requests natively, but the downstream modules (forge, registry, database writes) may not be safe under concurrency.

**Fix:** Task queue with controlled concurrency:

```python
class TaskManager:
    """Manages concurrent Ghost operations with controlled parallelism."""

    def __init__(self, max_concurrent_llm: int = 2, max_concurrent_exec: int = 1):
        self._llm_semaphore = asyncio.Semaphore(max_concurrent_llm)
        self._exec_semaphore = asyncio.Semaphore(max_concurrent_exec)
        self._active_tasks: set[asyncio.Task] = set()

    async def submit_llm_task(self, coro):
        """LLM calls: allow 2 concurrent (for parallel forge + triage)."""
        async with self._llm_semaphore:
            return await coro

    async def submit_exec_task(self, coro):
        """Tool execution: allow 1 at a time (prevent resource contention)."""
        async with self._exec_semaphore:
            return await coro
```

For name collisions: The registry auto-appends a short hash if a tool name already exists (`log_analyzer` → `log_analyzer_b7f2`). The user can rename it via `ghost tools rename`.

For database concurrency: SQLite in WAL mode supports concurrent reads with a single writer. Use a dedicated writer connection (never shared) and multiple reader connections. All writes go through a single async queue.

**Impact on plan:** Add `TaskManager` to `core/`. Wire forge and executor through semaphores. Add a write-serialization layer in `memory/database.py`.

---

## Summary: Complete Gap Registry

Combining all reviews (v1.0 critique → v2.0 corrections → your additional fixes → this final analysis):

### Previously Addressed (19 items) ✅

| # | Gap | Resolution |
|---|-----|-----------|
| 1 | AST sandbox illusion | HITL only, no AST security |
| 2 | Custom IPC reinvention | FastAPI + Uvicorn on UDS |
| 3 | Event loop blocking | ProcessPoolExecutor + sqlite-vec |
| 4 | File watcher drift | Reconciliation scan |
| 5 | Event sourcing complexity | DB is state, log is audit |
| 6 | LLM cost | Tiered intelligence router |
| 7 | Daemon stability | systemd + subprocess isolation |
| 8 | Knowledge graph schema | Semi-structured entities in SQLite |
| 9 | Signal vs noise | 4-stage filter pipeline |
| 10 | Context window management | Context Assembly Pipeline (RAG) |
| 11 | Cost transparency | Cost Meter |
| 12 | Cold start | `ghost init` project scan |
| 13 | Prompt versioning | Tools pinned to prompt versions |
| 14 | LLM unavailability | Intent queue |
| 15 | sqlite-vec distribution | Graceful fallback to Python cosine |
| 16 | Triage configurability | `triage_policy.toml` / configurable |
| 17 | Tool versioning | Semantic versioning with `current_version` pointer |
| 18 | Exclusion zones | `~/.ghost/` hardcoded in ignore list |
| 19 | Cold start API bill | Tiered indexing (grep/AST at Tier 0) |

### Newly Identified in This Analysis (10 items)

| # | Gap | Severity | Resolution |
|---|-----|----------|-----------|
| 20 | Stale socket / multiple instances | **Critical** | PID file + lock + stale socket cleanup on startup |
| 21 | Tool dependency management | **Critical** | PEP 723 inline metadata + `uv run` execution |
| 22 | Structured output per provider | **Important** | `structured_complete()` method using provider-native mechanisms |
| 23 | Multi-project isolation | **Important** | `project_id` column + `projects` table + scoped queries |
| 24 | Operational logging vs audit logging | **Important** | Two streams: SQLite audit log + RotatingFileHandler for Python logging |
| 25 | System suspend/resume | **Medium** | `SuspendDetector` via monotonic clock drift + forced reconciliation |
| 26 | Database corruption recovery | **Medium** | `PRAGMA integrity_check` on boot + archive corrupt + recreate |
| 27 | `ghost uninstall` command | **Medium** | Stop daemon + remove service + delete `~/.ghost/` + guide pip uninstall |
| 28 | Windows non-support | **Medium** | Explicit platform table in README + macOS launchd support |
| 29 | Concurrent request serialization | **Important** | Semaphores for LLM/exec + write-serialized DB + name collision handling |

### Additional items from your analysis (already endorsed)

| # | Gap | Resolution |
|---|-----|-----------|
| 30 | Tool environment deps (ModuleNotFoundError) | Covered by #21 (PEP 723 + `uv run`) |
| 31 | Git checkout storm | Circuit breaker: >50 files in 3s → drop insights, schedule reconciler |
| 32 | 429 rate limiting | Exponential backoff + jitter (tenacity library) + CLI status |
| 33 | Mega-file context overflow | Dynamic truncation + token budgeting + `read_file_chunk` tool for LLM |

---

## Competitive Differentiation (Research Finding)

From the competitive landscape research, the top AI agent frameworks in 2026 are:

| Framework | Stars | What It Is |
|-----------|-------|-----------|
| LangGraph/LangChain | ~120k+ | Library you import into your code |
| CrewAI | ~50k+ | Multi-agent orchestration framework |
| AutoGen | ~40k+ | Microsoft's async agent chat |
| Dify | ~100k+ | Low-code visual agent builder |

**Ghost's killer differentiator: None of these are daemons.**

Every single competitor is a framework you `import` and run inside your application. Ghost is fundamentally different — it's a **persistent background intelligence** that runs on your machine, remembers across sessions, and grows its own capabilities.

The README positioning should be:

> *"CrewAI, LangGraph, and AutoGen are agent frameworks you build WITH. Ghost is an agent that builds FOR you. It runs as a daemon on your machine, watches your projects, remembers everything, and synthesizes its own tools — while you sleep."*

This is the hook. This is what makes people star the repo.

---

## Final Verdict

**Total gaps identified across all review rounds: 33**
**All 33 have documented resolutions.**

The spec is now ready for execution. No remaining architectural ambiguity.

> [!IMPORTANT]
> The next step is to incorporate gaps 20-29 into the v2.0 implementation plan and begin Phase 1: Skeleton + Brain + Memory.
