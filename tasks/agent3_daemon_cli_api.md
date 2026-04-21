# Agent 3 Task: Daemon + CLI + API

> **Role**: You are building the INTERFACE layer of Ghost — the daemon process, FastAPI app, API routes, and the entire CLI. You are the user-facing surface that ties everything together.
>
> **Working Directory**: `/home/mohit/Coding/ghost v3.0/`
>
> **Do NOT touch files outside your assigned list.** Other agents are building config/, memory/, brain/, and synthesis/ concurrently.

---

## Context: What Is Ghost?

Ghost is a local-first AI daemon. You are building:
1. **The daemon** (`ghostd`) — background process that hosts the FastAPI app on a Unix Domain Socket
2. **The CLI** (`ghost`) — Typer-based CLI that talks to the daemon via sync httpx over UDS
3. **The API** — FastAPI routes that connect CLI requests to the brain/memory/synthesis modules

**Read these files to understand the full spec:**
- `ghost_implementation_plan_v3.md` — Sections 4.3-4.5, 10 (CLI reference) are most relevant
- `final_gaps_analysis.md` — Gaps 1, 5, 6, 8, 9 affect you
- `final_bug_sweep.md` — **Bug #3 (signal handler)** and **Bug #6 (PID PermissionError)** are YOURS. Also Edge Cases 1 (UDS path length) and 2 (zombie processes).

---

## Dependencies From Other Agents

You import FROM Agent 1 and Agent 2's code (treat as available):

```python
# From Agent 1 (Core Infrastructure):
from ghost.config.schema import GhostConfig, SecretConfig, LLMConfig, TierConfig, LLMProvider, SandboxConfig
from ghost.config.loader import load_config, save_config
from ghost.constants import (
    DEFAULT_GHOST_HOME, DEFAULT_SOCKET_NAME, DEFAULT_PID_FILE, DEFAULT_ENV_FILE,
    DEFAULT_CONFIG_FILE, DAEMON_BASE_URL, UDS_PATH_LIMIT_LINUX, UDS_PATH_LIMIT_MACOS,
    QUARANTINE_DIR, TOOLS_DIR, LOGS_DIR, LOG_FILE, VERSION, Topics,
    DEFAULT_SOCKET_POINTER,
)
from ghost.memory.database import get_connection, check_integrity
from ghost.memory.writer import DatabaseWriter
from ghost.memory.migrations.runner import run_migrations
from ghost.memory.entities import EntityStore
from ghost.memory.graph import GraphStore
from ghost.memory.vectors import VectorStore, check_sqlite_vec
from ghost.memory.search import UnifiedSearch
from ghost.memory.audit import AuditLog
from ghost.core.events import EventBus
from ghost.core.tasks import TaskManager
from ghost.core.logging import setup_logging, set_log_level

# From Agent 2 (Brain + Synthesis):
from ghost.brain.router import ModelRouter
from ghost.brain.context import ContextAssembler
from ghost.brain.cost import CostMeter, TokenCounter
from ghost.brain.queue import IntentQueue
from ghost.synthesis.forge import ToolForge
from ghost.synthesis.quarantine import QuarantineManager
from ghost.synthesis.executor import ToolExecutor, ExecutionResult
from ghost.synthesis.registry import ToolRegistry
```

---

## Your Files (21 files)

```
src/ghost/
├── core/
│   ├── __init__.py          # Already exists (empty)
│   ├── daemon.py            # ← YOU BUILD THIS
│   ├── app.py               # ← YOU BUILD THIS
│   ├── lifecycle.py         # ← YOU BUILD THIS
│   └── health.py            # ← YOU BUILD THIS
├── cli/
│   ├── __init__.py          # Already exists (empty)
│   ├── app.py               # ← YOU BUILD THIS
│   ├── client.py            # ← YOU BUILD THIS
│   ├── display.py           # ← YOU BUILD THIS
│   └── commands/
│       ├── __init__.py      # Already exists (empty)
│       ├── init.py          # ← YOU BUILD THIS
│       ├── start.py         # ← YOU BUILD THIS
│       ├── forge.py         # ← YOU BUILD THIS
│       ├── approve.py       # ← YOU BUILD THIS
│       ├── watch.py         # ← YOU BUILD THIS
│       ├── memory.py        # ← YOU BUILD THIS
│       ├── tools.py         # ← YOU BUILD THIS
│       ├── logs.py          # ← YOU BUILD THIS
│       ├── cost.py          # ← YOU BUILD THIS
│       ├── doctor.py        # ← YOU BUILD THIS
│       ├── gc.py            # ← YOU BUILD THIS
│       └── uninstall.py     # ← YOU BUILD THIS
├── api/
│   ├── __init__.py          # Already exists (empty)
│   ├── schemas.py           # ← YOU BUILD THIS
│   └── routes/
│       ├── __init__.py      # Already exists (empty)
│       ├── forge.py         # ← YOU BUILD THIS
│       ├── tools.py         # ← YOU BUILD THIS
│       ├── memory.py        # ← YOU BUILD THIS
│       ├── watch.py         # ← YOU BUILD THIS
│       ├── health.py        # ← YOU BUILD THIS
│       ├── events.py        # ← YOU BUILD THIS
│       └── config.py        # ← YOU BUILD THIS

tests/
├── unit/
│   └── test_suspend.py      # ← YOU BUILD THIS
├── integration/
│   └── test_daemon_lifecycle.py  # ← YOU BUILD THIS
```

---

## File 1: `src/ghost/core/daemon.py` — THE MOST CRITICAL FILE

This is the entry point for the `ghostd` command. It handles:
1. Single-instance enforcement via PID file
2. Stale socket cleanup
3. UDS path length safety (Edge Case 1)
4. Uvicorn launch on Unix Domain Socket

> [!CAUTION]
> **Bug #3**: Do NOT use `signal.signal()` for SIGTERM/SIGINT. It conflicts with uvicorn's signal handling. Use FastAPI lifespan events instead (in `app.py`).
>
> **Bug #6**: `os.kill(pid, 0)` can raise `PermissionError` if the PID belongs to another user. Catch it.
>
> **Edge Case 1**: UDS path can exceed 108 chars (Linux) / 104 chars (macOS). Fall back to `/tmp/ghost_<hash>.sock`.
>
> **Edge Case 2**: Use `os.killpg()` in stop to kill child processes too.

```python
"""
Daemon entry point: ghostd.

Handles:
1. Single-instance enforcement via PID file
2. Stale socket cleanup  
3. UDS path length safety
4. SQLite integrity check
5. Uvicorn launch on Unix Domain Socket

NOTE: Signal handling is done via FastAPI lifespan (app.py), NOT signal.signal().
This avoids conflicting with uvicorn's own signal handlers (Bug #3 fix).
"""
import hashlib
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def safe_socket_path(config) -> Path:
    """
    Ensure socket path is within OS kernel limit.
    
    Edge Case 1 fix: UDS path limit is 108 chars on Linux, 104 on macOS.
    If the default path exceeds this, fall back to /tmp/ghost_<hash>.sock
    and write a pointer file so the CLI knows where to find it.
    """
    from ghost.constants import UDS_PATH_LIMIT_LINUX, UDS_PATH_LIMIT_MACOS, DEFAULT_SOCKET_POINTER
    
    resolved = str(config.socket_path.resolve())
    limit = UDS_PATH_LIMIT_MACOS if sys.platform == "darwin" else UDS_PATH_LIMIT_LINUX

    if len(resolved) < limit:
        return config.socket_path

    # Fallback: /tmp/ghost_<hash>.sock
    home_hash = hashlib.md5(str(config.ghost_home).encode()).hexdigest()[:12]
    fallback = Path(f"/tmp/ghost_{home_hash}.sock")

    # Write pointer so CLI can find the socket
    pointer_file = config.ghost_home / DEFAULT_SOCKET_POINTER
    pointer_file.write_text(str(fallback))

    logger.warning(
        f"Socket path too long ({len(resolved)} chars, limit {limit}). "
        f"Using fallback: {fallback}"
    )
    return fallback


def ensure_single_instance(config) -> None:
    """
    Prevent multiple daemon instances. Clean up stale artifacts.
    
    Bug #6 fix: Catches PermissionError from os.kill(pid, 0) which occurs
    when the PID exists but belongs to another user (PID reuse scenario).
    """
    pid_file = config.ghost_home / "ghost.pid"
    sock_file = config.socket_path

    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text().strip())
            os.kill(old_pid, 0)  # Signal 0 = check existence
            # Process exists — another daemon is running
            print(f"👻 Ghost daemon already running (PID {old_pid})", file=sys.stderr)
            print(f"   Run 'ghost stop' first, or 'ghost restart'.", file=sys.stderr)
            sys.exit(1)
        except (ProcessLookupError, PermissionError, ValueError):
            # ProcessLookupError: PID doesn't exist (stale)
            # PermissionError: PID exists but belongs to another user (PID reuse)
            # ValueError: PID file contains garbage
            pid_file.unlink(missing_ok=True)

    # Clean stale socket file (left over from crash)
    if sock_file.exists():
        sock_file.unlink()

    # Write current PID
    pid_file.write_text(str(os.getpid()))


def main():
    """Entry point for `ghostd` command."""
    import uvicorn
    from ghost.config.loader import load_config
    from ghost.memory.database import check_integrity

    config = load_config()
    config.ghost_home.mkdir(parents=True, exist_ok=True)

    # Setup operational logging first
    from ghost.core.logging import setup_logging
    log_listener = setup_logging(config.ghost_home, config.log_level)

    logger.info(f"Ghost daemon starting (v{config.version})")

    # Integrity check on database
    check_integrity(config.db_path)

    # Single instance guard
    ensure_single_instance(config)

    # Resolve safe socket path (Edge Case 1)
    socket_path = safe_socket_path(config)

    # Create FastAPI app (lifespan handles startup/shutdown)
    from ghost.core.app import create_app
    app = create_app(config, log_listener)

    # Launch uvicorn on Unix socket
    # NOTE: uvicorn handles SIGTERM/SIGINT — we piggyback via lifespan (Bug #3 fix)
    try:
        uvicorn.run(
            app,
            uds=str(socket_path),
            log_level=config.log_level.lower(),
            access_log=False,
        )
    finally:
        # Cleanup (in case lifespan didn't run)
        pid_file = config.ghost_home / "ghost.pid"
        pid_file.unlink(missing_ok=True)
        socket_path.unlink(missing_ok=True)
        log_listener.stop()


if __name__ == "__main__":
    main()
```

---

## File 2: `src/ghost/core/app.py` — FastAPI App Factory

Creates the FastAPI app with lifespan events. The lifespan handles ALL startup and shutdown logic (Bug #3 fix — no raw signal handlers).

```python
"""
FastAPI application factory.

The lifespan context manager handles:
- Startup: DB connection, writer, migrations, all service initialization
- Shutdown: Graceful cleanup of all resources

Bug #3 fix: ALL cleanup is in the lifespan shutdown, not in signal.signal() handlers.
This piggybacks on uvicorn's signal handling instead of fighting it.
"""
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from ghost.config.schema import GhostConfig, SecretConfig
from ghost.constants import VERSION

logger = logging.getLogger(__name__)


def create_app(config: GhostConfig, log_listener=None) -> FastAPI:
    """Create and configure the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Startup and shutdown lifecycle."""
        logger.info("Ghost daemon starting up...")

        # ─── Startup ────────────────────────────────────────────────────

        # 1. Database connection
        from ghost.memory.database import get_connection
        db = await get_connection(config.db_path)
        app.state.db = db

        # 2. Database writer (single-writer queue)
        from ghost.memory.writer import DatabaseWriter
        writer = DatabaseWriter(db)
        await writer.start()
        app.state.writer = writer

        # 3. Run migrations
        from ghost.memory.migrations.runner import run_migrations
        await run_migrations(writer)

        # 4. Core services
        from ghost.core.events import EventBus
        from ghost.core.tasks import TaskManager

        event_bus = EventBus()
        task_manager = TaskManager()
        app.state.event_bus = event_bus
        app.state.task_manager = task_manager

        # 5. Memory services
        from ghost.memory.entities import EntityStore
        from ghost.memory.graph import GraphStore
        from ghost.memory.vectors import VectorStore
        from ghost.memory.search import UnifiedSearch
        from ghost.memory.audit import AuditLog

        entities = EntityStore(db, writer)
        graph = GraphStore(db, writer)
        vectors = VectorStore(db, writer)
        search = UnifiedSearch(db, graph, vectors)
        audit = AuditLog(db, writer)

        app.state.entities = entities
        app.state.graph = graph
        app.state.vectors = vectors
        app.state.search = search
        app.state.audit = audit

        # 6. Brain services
        secrets = SecretConfig()
        from ghost.brain.router import ModelRouter
        from ghost.brain.cost import CostMeter, TokenCounter
        from ghost.brain.context import ContextAssembler
        from ghost.brain.queue import IntentQueue

        router = ModelRouter(config, secrets)
        session_id = str(uuid.uuid4())
        cost_meter = CostMeter(writer, session_id=session_id)

        # Token counter for context assembly (use default provider)
        try:
            default_provider = router.get_provider(tier=2)
            token_counter = TokenCounter(
                config.llm.default_provider.value,
                config.llm.tier2.model,
            )
        except RuntimeError:
            # No provider configured — use fallback counter
            from ghost.constants import TOKEN_FALLBACK_CHARS_PER_TOKEN
            token_counter = TokenCounter("fallback", "none")

        context_assembler = ContextAssembler(search, token_counter)
        intent_queue = IntentQueue(db, writer)

        app.state.router = router
        app.state.cost_meter = cost_meter
        app.state.context_assembler = context_assembler
        app.state.intent_queue = intent_queue

        # 7. Synthesis services
        from ghost.synthesis.quarantine import QuarantineManager
        from ghost.synthesis.executor import ToolExecutor
        from ghost.synthesis.registry import ToolRegistry
        from ghost.synthesis.forge import ToolForge

        quarantine = QuarantineManager(config.ghost_home, writer)
        executor = ToolExecutor(config.sandbox)
        registry = ToolRegistry(config.ghost_home, db, writer)
        forge = ToolForge(
            router=router,
            context_assembler=context_assembler,
            cost_meter=cost_meter,
            quarantine=quarantine,
            event_bus=event_bus,
            audit_log=audit,
            task_manager=task_manager,
        )

        app.state.quarantine = quarantine
        app.state.executor = executor
        app.state.registry = registry
        app.state.forge = forge

        # 8. Health / suspend detection
        from ghost.core.health import SuspendDetector
        suspend_detector = SuspendDetector()
        app.state.suspend_detector = suspend_detector

        # Store config and log listener for shutdown
        app.state.config = config
        app.state.log_listener = log_listener
        app.state.session_id = session_id

        # Publish startup event
        await event_bus.publish("system.started", {
            "version": VERSION,
            "session_id": session_id,
            "pid": __import__("os").getpid(),
        })
        audit.log("system.started", {"version": VERSION, "session_id": session_id})

        logger.info(f"Ghost daemon ready (session: {session_id[:8]})")

        yield  # ← App is running here

        # ─── Shutdown ───────────────────────────────────────────────────
        logger.info("Ghost daemon shutting down...")

        # Cancel active tasks
        await task_manager.shutdown()

        # Drain event bus
        await event_bus.drain()

        # Log shutdown
        audit.log("system.stopped", {"session_id": session_id})

        # Stop database writer (drains pending writes)
        await writer.stop()

        # Close database
        await db.close()

        # Close LLM provider connections
        await router.close()

        # Cleanup PID and socket files
        pid_file = config.ghost_home / "ghost.pid"
        pid_file.unlink(missing_ok=True)
        config.socket_path.unlink(missing_ok=True)

        # Stop log listener
        if log_listener:
            log_listener.stop()

        logger.info("Ghost daemon stopped cleanly")

    # ─── Create App ─────────────────────────────────────────────────────

    app = FastAPI(
        title="Ghost Daemon",
        version=VERSION,
        lifespan=lifespan,
    )

    # Register API routes
    from ghost.api.routes import health, forge, tools, memory, watch, events, config as config_routes
    app.include_router(health.router, prefix="/api")
    app.include_router(forge.router, prefix="/api")
    app.include_router(tools.router, prefix="/api")
    app.include_router(memory.router, prefix="/api")
    app.include_router(watch.router, prefix="/api")
    app.include_router(events.router, prefix="/api")
    app.include_router(config_routes.router, prefix="/api")

    return app
```

---

## File 3: `src/ghost/core/lifecycle.py`

Graceful shutdown utilities.

```python
"""
Lifecycle management — graceful shutdown helpers.

Edge Case 2 fix: Uses os.killpg() to kill the entire process group,
preventing zombie child processes (uv run, reconciler threads, etc.).
"""
import logging
import os
import signal

logger = logging.getLogger(__name__)


def stop_daemon_by_pid(pid: int) -> bool:
    """
    Stop a daemon by PID. Kills entire process group.
    
    Edge Case 2 fix: os.killpg() reaches child processes spawned by the daemon
    (uv run subprocesses, etc.) preventing zombies.
    
    Returns True if signal was sent successfully.
    """
    try:
        # Kill entire process group
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
        logger.info(f"Sent SIGTERM to process group {pgid} (PID {pid})")
        return True
    except ProcessLookupError:
        logger.info(f"Process {pid} not found (already stopped)")
        return False
    except PermissionError:
        # Try just the main process
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info(f"Sent SIGTERM to PID {pid} (couldn't reach group)")
            return True
        except (ProcessLookupError, PermissionError):
            return False
    except OSError as e:
        logger.error(f"Failed to stop PID {pid}: {e}")
        return False


def is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False
```

---

## File 4: `src/ghost/core/health.py`

Health monitoring and suspend detection.

```python
"""
Health endpoint logic and suspend detection.

The SuspendDetector monitors monotonic clock drift to detect system
suspend/resume (the laptop lid problem). When resume is detected,
it triggers a reconciliation scan.
"""
import asyncio
import logging
import os
import time

from ghost.constants import VERSION

logger = logging.getLogger(__name__)


class SuspendDetector:
    """Detects system suspend/resume by monitoring monotonic clock drift."""

    def __init__(self, check_interval: float = 10.0, threshold: float = 30.0):
        self.check_interval = check_interval
        self.threshold = threshold
        self._last_check = time.monotonic()
        self._resume_count = 0
        self._task: asyncio.Task | None = None

    async def start(self, on_resume) -> None:
        """Start the background detection loop."""
        self._task = asyncio.create_task(self._run(on_resume), name="suspend-detector")

    async def stop(self) -> None:
        """Stop the detection loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self, on_resume) -> None:
        """Background loop. Calls on_resume() when suspend is detected."""
        while True:
            await asyncio.sleep(self.check_interval)
            now = time.monotonic()
            elapsed = now - self._last_check
            self._last_check = now

            if elapsed > self.threshold:
                gap = elapsed - self.check_interval
                logger.warning(f"System resume detected (gap: {gap:.0f}s)")
                self._resume_count += 1
                try:
                    await on_resume(gap_seconds=gap)
                except Exception:
                    logger.exception("Resume handler failed")

    @property
    def resume_count(self) -> int:
        return self._resume_count


def get_health_status(app) -> dict:
    """Build health status response."""
    import psutil  # Optional, graceful fallback

    status = {
        "status": "healthy",
        "version": VERSION,
        "pid": os.getpid(),
        "uptime_seconds": time.monotonic(),  # Approximate
        "session_id": getattr(app.state, "session_id", None),
    }

    # Memory usage (optional)
    try:
        process = psutil.Process()
        status["memory_mb"] = round(process.memory_info().rss / 1024 / 1024, 1)
    except Exception:
        # psutil not installed or error — skip
        pass

    # Writer queue status
    if hasattr(app.state, "writer"):
        status["writer_pending"] = app.state.writer.pending_count

    # Task manager status
    if hasattr(app.state, "task_manager"):
        tm = app.state.task_manager
        status["active_tasks"] = tm.active_count
        status["llm_slots_available"] = tm.llm_available
        status["exec_slots_available"] = tm.exec_available

    # Intent queue
    if hasattr(app.state, "intent_queue"):
        # Note: this is async, so we report last known value
        status["intent_queue_pending"] = "check /api/health/detailed"

    # Cost
    if hasattr(app.state, "cost_meter"):
        status["session_cost"] = app.state.cost_meter.session_summary

    return status
```

> [!NOTE]
> `psutil` is optional. Wrap its usage in try/except. Do NOT add it to dependencies. If the user has it installed, great; if not, the health endpoint still works.

---

## File 5: `src/ghost/cli/app.py` — Main CLI Entry Point

The Typer app that registers all commands.

```python
"""
Ghost CLI — main entry point.

All commands communicate with the daemon via sync httpx over UDS.
The CLI is fully synchronous (Typer is sync).
"""
import typer
from rich.console import Console

from ghost.constants import VERSION

app = typer.Typer(
    name="ghost",
    help="👻 Ghost — The AI daemon that haunts your machine.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()

# Import and register command groups
from ghost.cli.commands import (
    init, start, forge, approve, watch,
    memory, tools, logs, cost, doctor, gc, uninstall,
)

# Register individual commands
app.command(name="init", help="Initialize Ghost in the current directory")(init.init_cmd)
app.command(name="start", help="Start the Ghost daemon")(start.start_cmd)
app.command(name="stop", help="Stop the Ghost daemon")(start.stop_cmd)
app.command(name="restart", help="Restart the Ghost daemon")(start.restart_cmd)
app.command(name="status", help="Show daemon status")(start.status_cmd)
app.command(name="forge", help="Synthesize a new tool")(forge.forge_cmd)
app.command(name="approve", help="Approve a quarantined tool")(approve.approve_cmd)
app.command(name="reject", help="Reject a quarantined tool")(approve.reject_cmd)
app.command(name="sync", help="Force a reconciliation scan")(watch.sync_cmd)

# Register sub-command groups (typer sub-apps)
app.add_typer(watch.watch_app, name="watch", help="Manage watched directories")
app.add_typer(tools.tools_app, name="tools", help="Manage registered tools")
app.add_typer(memory.memory_app, name="memory", help="Search and manage memory")
app.add_typer(logs.logs_app, name="logs", help="View audit logs")
app.add_typer(cost.cost_app, name="cost", help="View API costs")
app.command(name="debug", help="View operational logs")(logs.debug_cmd)
app.command(name="doctor", help="Run system health checks")(doctor.doctor_cmd)
app.command(name="gc", help="Garbage collect old data")(gc.gc_cmd)
app.command(name="uninstall", help="Remove Ghost completely")(uninstall.uninstall_cmd)


@app.callback(invoke_without_command=True)
def version_callback(
    version: bool = typer.Option(False, "--version", "-v", help="Show version"),
):
    if version:
        console.print(f"👻 Ghost v{VERSION}")
        raise typer.Exit()


def main():
    """Entry point for the `ghost` CLI."""
    app()
```

---

## File 6: `src/ghost/cli/client.py` — CLI ↔ Daemon Communication

Sync httpx client over Unix Domain Socket.

```python
"""
CLI → Daemon communication over Unix Domain Socket.

Uses SYNC httpx (NOT async) because Typer is synchronous.
httpx.Client supports UDS via HTTPTransport(uds=...).
"""
import logging
from pathlib import Path
from typing import Any

import httpx

from ghost.constants import DAEMON_BASE_URL, DEFAULT_SOCKET_POINTER

logger = logging.getLogger(__name__)


class GhostClient:
    """Synchronous HTTP client that talks to the Ghost daemon over UDS."""

    def __init__(self, socket_path: Path, ghost_home: Path | None = None):
        self.socket_path = self._resolve_socket(socket_path, ghost_home)
        self._base_url = DAEMON_BASE_URL

    def _resolve_socket(self, default_path: Path, ghost_home: Path | None) -> Path:
        """
        Resolve the actual socket path.
        
        Edge Case 1: If the socket path was too long, the daemon writes a pointer
        file at ~/.ghost/socket_path. Check there first.
        """
        if ghost_home:
            pointer = ghost_home / DEFAULT_SOCKET_POINTER
            if pointer.exists():
                actual = Path(pointer.read_text().strip())
                if actual.exists():
                    return actual
        return default_path

    def _client(self) -> httpx.Client:
        transport = httpx.HTTPTransport(uds=str(self.socket_path))
        return httpx.Client(transport=transport, base_url=self._base_url)

    def is_daemon_running(self) -> bool:
        """Check if the daemon is alive."""
        try:
            with self._client() as c:
                r = c.get("/api/health", timeout=2.0)
                return r.status_code == 200
        except (httpx.ConnectError, FileNotFoundError, ConnectionRefusedError):
            return False

    def get_health(self) -> dict:
        """Get full health status."""
        with self._client() as c:
            r = c.get("/api/health", timeout=5.0)
            r.raise_for_status()
            return r.json()

    def forge(self, intent: str, project_id: str | None = None) -> dict:
        """Request tool synthesis."""
        with self._client() as c:
            r = c.post(
                "/api/forge",
                json={"intent": intent, "project_id": project_id},
                timeout=120.0,  # LLM calls can be slow
            )
            r.raise_for_status()
            return r.json()

    def approve_tool(self, tool_id: str) -> dict:
        """Approve a quarantined tool."""
        with self._client() as c:
            r = c.post(f"/api/tools/{tool_id}/approve", timeout=60.0)
            r.raise_for_status()
            return r.json()

    def reject_tool(self, tool_id: str) -> dict:
        """Reject a quarantined tool."""
        with self._client() as c:
            r = c.post(f"/api/tools/{tool_id}/reject", timeout=10.0)
            r.raise_for_status()
            return r.json()

    def list_tools(self, status: str | None = None) -> list[dict]:
        """List tools."""
        params = {}
        if status:
            params["status"] = status
        with self._client() as c:
            r = c.get("/api/tools", params=params, timeout=10.0)
            r.raise_for_status()
            return r.json()

    def run_tool(self, name: str, args: list[str] | None = None,
                 project_dir: str | None = None) -> dict:
        """Run a registered tool."""
        with self._client() as c:
            r = c.post(
                f"/api/tools/{name}/run",
                json={"args": args or [], "project_dir": project_dir},
                timeout=180.0,
            )
            r.raise_for_status()
            return r.json()

    def search_memory(self, query: str, project_id: str | None = None) -> list[dict]:
        """Search the knowledge graph."""
        with self._client() as c:
            r = c.post(
                "/api/memory/search",
                json={"query": query, "project_id": project_id},
                timeout=10.0,
            )
            r.raise_for_status()
            return r.json()

    def get_cost(self, detail: bool = False) -> dict:
        """Get cost summary."""
        with self._client() as c:
            r = c.get("/api/health", timeout=5.0)
            r.raise_for_status()
            data = r.json()
            return data.get("session_cost", {})

    def get_audit_logs(self, topic: str | None = None, limit: int = 50) -> list[dict]:
        """Get audit log entries."""
        params = {"limit": limit}
        if topic:
            params["topic"] = topic
        with self._client() as c:
            r = c.get("/api/logs", params=params, timeout=10.0)
            r.raise_for_status()
            return r.json()

    def shutdown(self) -> bool:
        """Request graceful daemon shutdown."""
        try:
            with self._client() as c:
                r = c.post("/api/shutdown", timeout=5.0)
                return r.status_code == 200
        except Exception:
            return False

    def watch_dir(self, path: str, project_name: str | None = None) -> dict:
        """Start watching a directory."""
        with self._client() as c:
            r = c.post(
                "/api/watch",
                json={"path": path, "project_name": project_name},
                timeout=10.0,
            )
            r.raise_for_status()
            return r.json()

    def unwatch_dir(self, path: str) -> dict:
        """Stop watching a directory."""
        with self._client() as c:
            r = c.delete(f"/api/watch", params={"path": path}, timeout=10.0)
            r.raise_for_status()
            return r.json()

    def set_log_level(self, level: str) -> dict:
        """Change the daemon's log level."""
        with self._client() as c:
            r = c.post("/api/config/log-level", json={"level": level}, timeout=5.0)
            r.raise_for_status()
            return r.json()

    def get_pending_tools(self) -> list[dict]:
        """Get quarantined tools pending approval."""
        with self._client() as c:
            r = c.get("/api/tools", params={"status": "quarantined"}, timeout=10.0)
            r.raise_for_status()
            return r.json()
```

---

## File 7: `src/ghost/cli/display.py` — Rich Formatting Helpers

```python
"""Rich terminal display helpers for the Ghost CLI."""

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()


def print_success(message: str) -> None:
    console.print(f"✅ {message}", style="green")


def print_error(message: str) -> None:
    console.print(f"❌ {message}", style="red bold")


def print_warning(message: str) -> None:
    console.print(f"⚠️  {message}", style="yellow")


def print_info(message: str) -> None:
    console.print(f"ℹ️  {message}", style="blue")


def print_ghost(message: str) -> None:
    console.print(f"👻 {message}", style="bold")


def print_tool_code(code: str, title: str = "Generated Tool") -> None:
    """Display tool source code with syntax highlighting."""
    syntax = Syntax(code, "python", theme="monokai", line_numbers=True)
    console.print(Panel(syntax, title=f"🔧 {title}", border_style="cyan"))


def print_tool_table(tools: list[dict]) -> None:
    """Display tools in a table."""
    table = Table(title="🔧 Ghost Tools", box=box.ROUNDED)
    table.add_column("Name", style="cyan")
    table.add_column("Version", justify="center")
    table.add_column("Status", justify="center")
    table.add_column("Runs", justify="right")
    table.add_column("Description")

    for tool in tools:
        status_style = {
            "quarantined": "yellow",
            "approved": "green",
            "registered": "green bold",
        }.get(tool.get("status", ""), "white")

        table.add_row(
            tool.get("name", "?"),
            str(tool.get("version", "?")),
            Text(tool.get("status", "?"), style=status_style),
            str(tool.get("runs", 0)),
            (tool.get("description", "")[:60] + "...") if len(tool.get("description", "")) > 60 else tool.get("description", ""),
        )

    console.print(table)


def print_cost_summary(cost: dict) -> None:
    """Display cost summary."""
    table = Table(title="💰 API Cost Summary", box=box.ROUNDED)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Total Cost", f"${cost.get('total_cost_usd', 0):.6f}")
    table.add_row("Input Tokens", f"{cost.get('total_input_tokens', 0):,}")
    table.add_row("Output Tokens", f"{cost.get('total_output_tokens', 0):,}")
    table.add_row("API Calls", str(cost.get("total_calls", 0)))
    table.add_row("Session", cost.get("session_id", "?")[:8])

    console.print(table)


def print_health(health: dict) -> None:
    """Display health status."""
    table = Table(title="👻 Ghost Daemon Status", box=box.ROUNDED)
    table.add_column("Property", style="cyan")
    table.add_column("Value")

    for key, value in health.items():
        if isinstance(value, dict):
            value = str(value)
        table.add_row(key, str(value))

    console.print(table)


def print_search_results(results: list[dict]) -> None:
    """Display memory search results."""
    if not results:
        print_info("No results found.")
        return

    for i, r in enumerate(results, 1):
        kind = r.get("kind", "?")
        name = r.get("name", "?")
        content = r.get("content", "")
        preview = content[:200] + "..." if len(content) > 200 else content

        console.print(f"\n[cyan]{i}.[/cyan] [{kind}] [bold]{name}[/bold]")
        if preview:
            console.print(f"   {preview}", style="dim")


def print_audit_logs(logs: list[dict]) -> None:
    """Display audit log entries."""
    table = Table(title="📋 Audit Log", box=box.ROUNDED)
    table.add_column("Time", style="dim")
    table.add_column("Topic", style="cyan")
    table.add_column("Details")

    for entry in logs:
        table.add_row(
            entry.get("created_at", "?"),
            entry.get("topic", "?"),
            str(entry.get("payload", {}))[:80],
        )

    console.print(table)


def confirm_action(message: str) -> bool:
    """Prompt for confirmation."""
    return console.input(f"\n{message} [y/N]: ").strip().lower() in ("y", "yes")
```

---

## Files 8-18: CLI Commands

Each command is a thin wrapper that calls `GhostClient` and displays results with Rich.

### `src/ghost/cli/commands/init.py`

```python
"""ghost init — First-run setup wizard."""
import os
from pathlib import Path
import typer
from ghost.cli.display import console, print_success, print_info, print_ghost, print_warning
from ghost.constants import DEFAULT_GHOST_HOME, DEFAULT_CONFIG_FILE, DEFAULT_ENV_FILE


def init_cmd(
    path: str = typer.Argument(".", help="Project directory to initialize"),
):
    """Initialize Ghost for a project directory."""
    project_dir = Path(path).resolve()
    ghost_home = Path(os.environ.get("GHOST_HOME", str(DEFAULT_GHOST_HOME)))

    print_ghost("Initializing Ghost...")
    console.print(f"   Project: {project_dir}")
    console.print(f"   Ghost home: {ghost_home}")

    # Create ghost home directory structure
    ghost_home.mkdir(parents=True, exist_ok=True)
    (ghost_home / "quarantine").mkdir(exist_ok=True)
    (ghost_home / "tools").mkdir(exist_ok=True)
    (ghost_home / "logs").mkdir(exist_ok=True)

    # Create default config if it doesn't exist
    config_file = ghost_home / DEFAULT_CONFIG_FILE
    if not config_file.exists():
        from ghost.config.loader import load_config, save_config
        config = load_config()
        save_config(config)
        print_success(f"Created config at {config_file}")
    else:
        print_info(f"Config already exists at {config_file}")

    # Create .env template if it doesn't exist
    env_file = ghost_home / DEFAULT_ENV_FILE
    if not env_file.exists():
        env_file.write_text(
            "# Ghost API Keys\n"
            "# At least one provider key is required.\n"
            "OPENAI_API_KEY=\n"
            "ANTHROPIC_API_KEY=\n"
            "GOOGLE_API_KEY=\n"
        )
        env_file.chmod(0o600)
        print_success(f"Created .env at {env_file} (chmod 600)")
        print_warning("Edit ~/.ghost/.env and add your API key(s)")
    else:
        print_info(f".env already exists at {env_file}")

    # Create .ghostignore in project dir if doesn't exist
    ignore_file = project_dir / ".ghostignore"
    if not ignore_file.exists():
        ignore_file.write_text(
            "# Ghost ignore patterns (gitignore syntax)\n"
            "node_modules/\n"
            ".venv/\n"
            "venv/\n"
            "__pycache__/\n"
            "*.pyc\n"
            ".git/\n"
            "dist/\n"
            "build/\n"
        )
        print_success(f"Created .ghostignore in {project_dir}")

    print_ghost("Ghost initialized! Next steps:")
    console.print("   1. Add your API key: [cyan]nano ~/.ghost/.env[/cyan]")
    console.print("   2. Start the daemon: [cyan]ghost start[/cyan]")
    console.print("   3. Forge your first tool: [cyan]ghost forge \"find all TODO comments\"[/cyan]")
```

### `src/ghost/cli/commands/start.py`

```python
"""ghost start / stop / restart / status commands."""
import os
import shutil
import signal
import subprocess
import sys
import time
import typer
from pathlib import Path

from ghost.cli.display import console, print_success, print_error, print_ghost, print_health
from ghost.constants import DEFAULT_GHOST_HOME


def _get_client():
    from ghost.config.loader import load_config
    from ghost.cli.client import GhostClient
    config = load_config()
    return GhostClient(config.socket_path, config.ghost_home), config


def start_cmd():
    """Start the Ghost daemon as a background process."""
    client, config = _get_client()
    
    if client.is_daemon_running():
        print_ghost("Ghost daemon is already running")
        return

    # Find ghostd binary
    ghostd_path = shutil.which("ghostd")
    if ghostd_path:
        cmd = [ghostd_path]
    else:
        cmd = [sys.executable, "-m", "ghost.core.daemon"]

    # Launch detached
    proc = subprocess.Popen(
        cmd,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )

    # Wait up to 5s for daemon to be ready
    for _ in range(50):
        time.sleep(0.1)
        if client.is_daemon_running():
            print_ghost(f"Ghost daemon started (PID {proc.pid})")
            console.print(f"   Socket: {client.socket_path}")
            return

    print_error("Daemon failed to start. Check `ghost debug` for logs.")
    raise typer.Exit(code=1)


def stop_cmd():
    """Stop the Ghost daemon gracefully."""
    client, config = _get_client()

    if not client.is_daemon_running():
        print_ghost("Ghost daemon is not running")
        return

    # Try graceful shutdown via API
    if client.shutdown():
        # Wait for process to exit
        for _ in range(30):
            time.sleep(0.1)
            if not client.is_daemon_running():
                print_success("Daemon stopped")
                return
    
    # Fallback: SIGTERM via PID file
    from ghost.core.lifecycle import stop_daemon_by_pid
    pid_file = config.ghost_home / "ghost.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            stop_daemon_by_pid(pid)
        except (ValueError, OSError):
            pass

    # Clean up artifacts
    pid_file.unlink(missing_ok=True)
    config.socket_path.unlink(missing_ok=True)
    print_success("Daemon stopped")


def restart_cmd():
    """Restart the Ghost daemon."""
    stop_cmd()
    time.sleep(0.5)
    start_cmd()


def status_cmd():
    """Show Ghost daemon status."""
    client, config = _get_client()
    
    if not client.is_daemon_running():
        print_ghost("Ghost daemon is [red]not running[/red]")
        console.print("   Run [cyan]ghost start[/cyan] to start it.")
        return

    try:
        health = client.get_health()
        print_health(health)
    except Exception as e:
        print_error(f"Could not get status: {e}")
```

### `src/ghost/cli/commands/forge.py`

```python
"""ghost forge — Synthesize a tool from natural language."""
import typer
from ghost.cli.display import console, print_ghost, print_error, print_tool_code, print_success


def forge_cmd(
    intent: str = typer.Argument(..., help="What you want the tool to do"),
    project: str = typer.Option(None, "--project", "-p", help="Project ID for context"),
):
    """Synthesize a new tool from natural language intent."""
    from ghost.cli.commands.start import _get_client
    client, config = _get_client()

    if not client.is_daemon_running():
        print_error("Ghost daemon is not running. Run `ghost start` first.")
        raise typer.Exit(code=1)

    print_ghost(f"Forging tool: \"{intent}\"")
    console.print("   This may take a moment...", style="dim")

    try:
        result = client.forge(intent, project_id=project)

        console.print()
        print_success(f"Tool '{result['name']}' synthesized!")
        console.print(f"   ID: {result['id']}")
        console.print(f"   Description: {result.get('description', 'N/A')}")
        console.print(f"   Status: [yellow]quarantined[/yellow]")

        if result.get("code_preview"):
            print_tool_code(result["code_preview"], title=result["name"])

        console.print()
        console.print("   To approve and run: [cyan]ghost approve " + result['id'][:8] + "[/cyan]")
        console.print("   To reject: [cyan]ghost reject " + result['id'][:8] + "[/cyan]")

    except Exception as e:
        print_error(f"Forge failed: {e}")
        raise typer.Exit(code=1)
```

### `src/ghost/cli/commands/approve.py`

```python
"""ghost approve / reject — Manage quarantined tools."""
import typer
from ghost.cli.display import console, print_success, print_error, print_ghost


def approve_cmd(
    tool_id: str = typer.Argument(..., help="Tool ID (or prefix) to approve"),
):
    """Approve a quarantined tool for execution."""
    from ghost.cli.commands.start import _get_client
    client, config = _get_client()

    if not client.is_daemon_running():
        print_error("Ghost daemon is not running.")
        raise typer.Exit(code=1)

    try:
        result = client.approve_tool(tool_id)
        print_success(f"Tool '{result.get('name', tool_id)}' approved!")
        console.print(f"   Run it with: [cyan]ghost tools run {result.get('name', tool_id)}[/cyan]")
    except Exception as e:
        print_error(f"Approve failed: {e}")
        raise typer.Exit(code=1)


def reject_cmd(
    tool_id: str = typer.Argument(..., help="Tool ID (or prefix) to reject"),
):
    """Reject and delete a quarantined tool."""
    from ghost.cli.commands.start import _get_client
    client, config = _get_client()

    if not client.is_daemon_running():
        print_error("Ghost daemon is not running.")
        raise typer.Exit(code=1)

    try:
        result = client.reject_tool(tool_id)
        print_ghost(f"Tool rejected and removed.")
    except Exception as e:
        print_error(f"Reject failed: {e}")
        raise typer.Exit(code=1)
```

### `src/ghost/cli/commands/watch.py`

```python
"""ghost watch — Manage watched directories."""
import typer
from ghost.cli.display import console, print_success, print_error

watch_app = typer.Typer(no_args_is_help=True)


@watch_app.command("add")
def watch_add(
    path: str = typer.Argument(".", help="Directory to watch"),
    name: str = typer.Option(None, "--name", "-n", help="Project name"),
):
    """Start watching a directory."""
    from pathlib import Path
    from ghost.cli.commands.start import _get_client
    client, _ = _get_client()
    resolved = str(Path(path).resolve())
    try:
        result = client.watch_dir(resolved, project_name=name)
        print_success(f"Now watching: {resolved}")
    except Exception as e:
        print_error(f"Failed: {e}")


@watch_app.command("remove")
def watch_remove(
    path: str = typer.Argument(".", help="Directory to stop watching"),
):
    """Stop watching a directory."""
    from pathlib import Path
    from ghost.cli.commands.start import _get_client
    client, _ = _get_client()
    resolved = str(Path(path).resolve())
    try:
        result = client.unwatch_dir(resolved)
        print_success(f"Stopped watching: {resolved}")
    except Exception as e:
        print_error(f"Failed: {e}")


def sync_cmd():
    """Force a reconciliation scan now."""
    from ghost.cli.commands.start import _get_client
    client, _ = _get_client()
    console.print("🔄 Forcing reconciliation scan...")
    # This would call a /api/sync endpoint
    print_success("Reconciliation scan triggered.")
```

### `src/ghost/cli/commands/memory.py`

```python
"""ghost memory — Search and manage the knowledge graph."""
import typer
from ghost.cli.display import console, print_error, print_search_results, print_info

memory_app = typer.Typer(no_args_is_help=True)


@memory_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Search query"),
    project: str = typer.Option(None, "--project", "-p", help="Scope to project"),
):
    """Search the knowledge graph."""
    from ghost.cli.commands.start import _get_client
    client, _ = _get_client()
    try:
        results = client.search_memory(query, project_id=project)
        print_search_results(results)
    except Exception as e:
        print_error(f"Search failed: {e}")


@memory_app.command("stats")
def memory_stats():
    """Show memory statistics."""
    from ghost.cli.commands.start import _get_client
    client, _ = _get_client()
    try:
        health = client.get_health()
        print_info(f"Status: see `ghost status` for full details")
    except Exception as e:
        print_error(f"Failed: {e}")
```

### `src/ghost/cli/commands/tools.py`

```python
"""ghost tools — Manage registered tools."""
import typer
from ghost.cli.display import console, print_error, print_success, print_tool_table, print_tool_code

tools_app = typer.Typer(no_args_is_help=True)


@tools_app.command("list")
def tools_list(
    status: str = typer.Option(None, "--status", "-s", help="Filter by status"),
):
    """List all tools."""
    from ghost.cli.commands.start import _get_client
    client, _ = _get_client()
    try:
        tools = client.list_tools(status=status)
        if tools:
            print_tool_table(tools)
        else:
            console.print("No tools found. Forge one with: [cyan]ghost forge \"...\"[/cyan]")
    except Exception as e:
        print_error(f"Failed: {e}")


@tools_app.command("run")
def tools_run(
    name: str = typer.Argument(..., help="Tool name to run"),
    project_dir: str = typer.Option(None, "--project-dir", "-d", help="Project directory"),
    args: list[str] = typer.Argument(None, help="Arguments to pass to the tool"),
):
    """Run a registered tool."""
    from ghost.cli.commands.start import _get_client
    client, _ = _get_client()
    try:
        result = client.run_tool(name, args=args, project_dir=project_dir)
        if result.get("stdout"):
            console.print(result["stdout"])
        if result.get("stderr"):
            console.print(result["stderr"], style="red")
        if result.get("timed_out"):
            print_error("Tool execution timed out")
    except Exception as e:
        print_error(f"Failed: {e}")


@tools_app.command("info")
def tools_info(
    name: str = typer.Argument(..., help="Tool name"),
):
    """Show detailed info about a tool."""
    from ghost.cli.commands.start import _get_client
    client, _ = _get_client()
    try:
        tools = client.list_tools()
        match = [t for t in tools if t.get("name") == name]
        if not match:
            print_error(f"Tool '{name}' not found")
            return
        tool = match[0]
        for key, val in tool.items():
            console.print(f"  [cyan]{key}[/cyan]: {val}")
    except Exception as e:
        print_error(f"Failed: {e}")


@tools_app.command("delete")
def tools_delete(
    name: str = typer.Argument(..., help="Tool name to delete"),
):
    """Delete a tool."""
    from ghost.cli.display import confirm_action
    if not confirm_action(f"Delete tool '{name}'?"):
        return
    console.print(f"Tool '{name}' deleted.", style="yellow")
```

### `src/ghost/cli/commands/logs.py`

```python
"""ghost logs / ghost debug — View logs."""
import typer
from ghost.cli.display import console, print_error, print_audit_logs

logs_app = typer.Typer(no_args_is_help=False, invoke_without_command=True)


@logs_app.callback(invoke_without_command=True)
def logs_default(
    topic: str = typer.Option(None, "--topic", "-t", help="Filter by topic"),
    limit: int = typer.Option(50, "--limit", "-n", help="Number of entries"),
):
    """View audit log (semantic events)."""
    from ghost.cli.commands.start import _get_client
    client, _ = _get_client()
    try:
        logs = client.get_audit_logs(topic=topic, limit=limit)
        print_audit_logs(logs)
    except Exception as e:
        print_error(f"Failed: {e}")


def debug_cmd(
    level: str = typer.Option(None, "--level", "-l", help="Set log level (DEBUG/INFO/WARNING)"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
):
    """View operational log (Python debug output)."""
    from ghost.constants import DEFAULT_GHOST_HOME, LOGS_DIR, LOG_FILE
    from pathlib import Path
    import os

    ghost_home = Path(os.environ.get("GHOST_HOME", str(DEFAULT_GHOST_HOME)))
    log_file = ghost_home / LOGS_DIR / LOG_FILE

    # Set log level on running daemon
    if level:
        from ghost.cli.commands.start import _get_client
        client, _ = _get_client()
        try:
            client.set_log_level(level.upper())
            console.print(f"Log level set to [cyan]{level.upper()}[/cyan]")
        except Exception as e:
            print_error(f"Could not set log level: {e}")
        return

    if not log_file.exists():
        print_error(f"No log file at {log_file}")
        console.print("   Is the daemon running? Try: [cyan]ghost start[/cyan]")
        return

    if follow:
        # Tail -f equivalent
        import subprocess
        try:
            subprocess.run(["tail", "-f", str(log_file)])
        except KeyboardInterrupt:
            pass
    else:
        # Show last N lines
        content = log_file.read_text()
        last_lines = content.strip().split("\n")[-lines:]
        for line in last_lines:
            console.print(line, style="dim")
```

### `src/ghost/cli/commands/cost.py`

```python
"""ghost cost — View API spend."""
import typer
from ghost.cli.display import console, print_error, print_cost_summary

cost_app = typer.Typer(no_args_is_help=False, invoke_without_command=True)


@cost_app.callback(invoke_without_command=True)
def cost_default(
    detail: bool = typer.Option(False, "--detail", "-d", help="Show detailed breakdown"),
):
    """View API cost summary."""
    from ghost.cli.commands.start import _get_client
    client, _ = _get_client()
    try:
        cost = client.get_cost(detail=detail)
        if cost:
            print_cost_summary(cost)
        else:
            console.print("No cost data yet. Forge a tool to see costs.")
    except Exception as e:
        print_error(f"Failed: {e}")
```

### `src/ghost/cli/commands/doctor.py`

```python
"""ghost doctor — System health check."""
import shutil
import sys
from pathlib import Path
import typer
from ghost.cli.display import console, print_success, print_warning, print_error, print_ghost


def doctor_cmd():
    """Run system health checks."""
    print_ghost("Running diagnostics...\n")
    all_ok = True

    # Python version
    py_ver = sys.version_info
    if py_ver >= (3, 11):
        print_success(f"Python {py_ver.major}.{py_ver.minor}.{py_ver.micro}")
    else:
        print_error(f"Python {py_ver.major}.{py_ver.minor} (need >=3.11)")
        all_ok = False

    # uv installed?
    if shutil.which("uv"):
        print_success("uv is installed (tools can auto-install dependencies)")
    else:
        print_warning("uv not found. Install it for automatic tool dependency management.")
        console.print("   [dim]curl -LsSf https://astral.sh/uv/install.sh | sh[/dim]")

    # Ghost home exists?
    from ghost.constants import DEFAULT_GHOST_HOME
    import os
    ghost_home = Path(os.environ.get("GHOST_HOME", str(DEFAULT_GHOST_HOME)))
    if ghost_home.exists():
        print_success(f"Ghost home: {ghost_home}")
    else:
        print_warning(f"Ghost home not found: {ghost_home}")
        console.print("   Run [cyan]ghost init[/cyan] first.")
        all_ok = False

    # API keys configured?
    env_file = ghost_home / ".env"
    if env_file.exists():
        content = env_file.read_text()
        has_key = any(
            line.strip() and not line.startswith("#") and "=" in line and line.split("=", 1)[1].strip()
            for line in content.split("\n")
            if "API_KEY" in line
        )
        if has_key:
            print_success("API key(s) configured in .env")
        else:
            print_warning("No API keys found in .env")
            console.print("   Edit [cyan]~/.ghost/.env[/cyan] and add at least one API key.")
    else:
        print_warning(".env file not found")

    # sqlite-vec available?
    try:
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        conn.load_extension("vec0")
        conn.close()
        print_success("sqlite-vec extension available (vector search enabled)")
    except Exception:
        print_warning("sqlite-vec not available (vector search disabled, FTS5 fallback)")

    # Daemon running?
    try:
        from ghost.cli.commands.start import _get_client
        client, _ = _get_client()
        if client.is_daemon_running():
            print_success("Ghost daemon is running")
        else:
            print_warning("Ghost daemon is not running")
    except Exception:
        print_warning("Cannot check daemon status")

    # Disk space
    import shutil as shutil_mod
    total, used, free = shutil_mod.disk_usage(str(ghost_home.parent))
    free_gb = free / (1024 ** 3)
    if free_gb > 1:
        print_success(f"Disk space: {free_gb:.1f} GB free")
    else:
        print_warning(f"Low disk space: {free_gb:.2f} GB free")

    console.print()
    if all_ok:
        print_ghost("All checks passed! Ghost is ready.")
    else:
        print_ghost("Some issues found. See warnings above.")
```

### `src/ghost/cli/commands/gc.py`

```python
"""ghost gc — Garbage collection."""
import typer
from ghost.cli.display import console, print_success, print_ghost


def gc_cmd(
    days: int = typer.Option(30, "--days", "-d", help="Prune entries older than N days"),
):
    """Garbage collect old audit logs and retired tools."""
    print_ghost(f"Garbage collecting entries older than {days} days...")
    # This would call /api/gc on the daemon
    # For now, placeholder
    console.print("   Audit log pruning: [dim]not yet implemented (Phase 4)[/dim]")
    console.print("   Retired tool cleanup: [dim]not yet implemented (Phase 4)[/dim]")
    print_success("Done.")
```

### `src/ghost/cli/commands/uninstall.py`

```python
"""ghost uninstall — Full removal."""
import shutil
import os
from pathlib import Path
import typer
from ghost.cli.display import console, print_success, print_warning, print_ghost, confirm_action


def uninstall_cmd():
    """Remove Ghost completely (daemon + data + config)."""
    from ghost.constants import DEFAULT_GHOST_HOME
    
    ghost_home = Path(os.environ.get("GHOST_HOME", str(DEFAULT_GHOST_HOME)))

    console.print()
    print_warning("This will:")
    console.print("   1. Stop the Ghost daemon (if running)")
    console.print("   2. Delete ~/.ghost/ (database, tools, config, logs)")
    console.print()
    console.print("   [red]Your synthesized tools and knowledge graph will be permanently deleted.[/red]")
    console.print()

    if not confirm_action("Proceed with uninstall?"):
        console.print("Cancelled.")
        return

    # Stop daemon
    try:
        from ghost.cli.commands.start import stop_cmd
        stop_cmd()
    except Exception:
        pass

    # Delete ghost home
    if ghost_home.exists():
        size = sum(f.stat().st_size for f in ghost_home.rglob("*") if f.is_file())
        size_mb = size / (1024 * 1024)
        shutil.rmtree(str(ghost_home))
        print_success(f"Deleted {ghost_home} ({size_mb:.1f} MB)")

    console.print()
    print_ghost("Ghost has been fully removed.")
    console.print("   Run [cyan]pip uninstall ghost-ai[/cyan] to remove the Python package.")
```

---

## File 19: `src/ghost/api/schemas.py` — API Request/Response Models

```python
"""Pydantic models for API request and response bodies."""
from pydantic import BaseModel, Field


class ForgeRequest(BaseModel):
    intent: str = Field(..., description="Natural language description of the tool")
    project_id: str | None = Field(None, description="Project ID for context")


class ForgeResponse(BaseModel):
    id: str
    name: str
    description: str
    file_path: str
    source_hash: str
    status: str
    capabilities: list[str] = []
    code_preview: str = ""


class ToolRunRequest(BaseModel):
    args: list[str] = []
    project_dir: str | None = None


class ToolRunResponse(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    used_uv: bool


class ToolResponse(BaseModel):
    id: str
    name: str
    version: int
    description: str | None = None
    status: str
    runs: int = 0
    capabilities: str = "[]"


class MemorySearchRequest(BaseModel):
    query: str
    project_id: str | None = None
    limit: int = 20


class WatchRequest(BaseModel):
    path: str
    project_name: str | None = None


class LogLevelRequest(BaseModel):
    level: str


class HealthResponse(BaseModel):
    status: str
    version: str
    pid: int


class ShutdownResponse(BaseModel):
    message: str = "Shutting down..."
```

---

## Files 20-26: API Routes

Each route is a FastAPI router that accesses services via `request.app.state`.

### `src/ghost/api/routes/health.py`

```python
"""Health and status endpoints."""
import asyncio
import os
from fastapi import APIRouter, Request

from ghost.core.health import get_health_status

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request):
    """Get daemon health status."""
    return get_health_status(request.app)


@router.post("/shutdown")
async def shutdown(request: Request):
    """Initiate graceful shutdown."""
    # Schedule shutdown after responding
    loop = asyncio.get_event_loop()
    loop.call_later(0.5, lambda: os.kill(os.getpid(), __import__("signal").SIGTERM))
    return {"message": "Shutting down..."}
```

### `src/ghost/api/routes/forge.py`

```python
"""Tool synthesis endpoints."""
from fastapi import APIRouter, Request, HTTPException
from ghost.api.schemas import ForgeRequest, ForgeResponse

router = APIRouter(tags=["forge"])


@router.post("/forge", response_model=ForgeResponse)
async def forge_tool(req: ForgeRequest, request: Request):
    """Synthesize a new tool from natural language."""
    try:
        result = await request.app.state.forge.forge(
            intent=req.intent,
            project_id=req.project_id,
        )
        return ForgeResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### `src/ghost/api/routes/tools.py`

```python
"""Tool management endpoints."""
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException
from ghost.api.schemas import ToolRunRequest, ToolRunResponse

router = APIRouter(tags=["tools"])


@router.get("/tools")
async def list_tools(request: Request, status: str | None = None):
    """List tools, optionally filtered by status."""
    if status == "quarantined":
        return await request.app.state.quarantine.list_pending()
    return await request.app.state.registry.list_all(status=status)


@router.post("/tools/{tool_id}/approve")
async def approve_tool(tool_id: str, request: Request):
    """Approve a quarantined tool."""
    result = await request.app.state.quarantine.approve(tool_id)
    if not result:
        raise HTTPException(status_code=404, detail="Tool not found or not quarantined")
    # Register it
    registered = await request.app.state.registry.register(tool_id)
    return registered or result


@router.post("/tools/{tool_id}/reject")
async def reject_tool(tool_id: str, request: Request):
    """Reject a quarantined tool."""
    success = await request.app.state.quarantine.reject(tool_id)
    if not success:
        raise HTTPException(status_code=404, detail="Tool not found or not quarantined")
    return {"status": "rejected", "tool_id": tool_id}


@router.post("/tools/{name}/run", response_model=ToolRunResponse)
async def run_tool(name: str, req: ToolRunRequest, request: Request):
    """Run a registered tool."""
    tool = await request.app.state.registry.get_current(name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")

    project_dir = Path(req.project_dir) if req.project_dir else None
    
    async def _execute():
        return await request.app.state.executor.execute(
            tool_path=Path(tool["file_path"]),
            args=req.args,
            project_dir=project_dir,
        )
    
    result = await request.app.state.task_manager.submit_exec_task(_execute())
    
    # Record the run
    await request.app.state.registry.record_run(tool["id"])
    
    return ToolRunResponse(
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        timed_out=result.timed_out,
        used_uv=result.used_uv,
    )
```

### `src/ghost/api/routes/memory.py`

```python
"""Memory/knowledge graph endpoints."""
from fastapi import APIRouter, Request
from ghost.api.schemas import MemorySearchRequest

router = APIRouter(tags=["memory"])


@router.post("/memory/search")
async def search_memory(req: MemorySearchRequest, request: Request):
    """Search the knowledge graph."""
    results = await request.app.state.search.search(
        query=req.query,
        project_id=req.project_id or "",
        limit=req.limit,
    )
    return results


@router.get("/memory/stats")
async def memory_stats(request: Request):
    """Get memory statistics."""
    db = request.app.state.db
    
    entity_count = (await (await db.execute("SELECT COUNT(*) FROM entities WHERE deleted_at IS NULL")).fetchone())[0]
    edge_count = (await (await db.execute("SELECT COUNT(*) FROM edges")).fetchone())[0]
    project_count = (await (await db.execute("SELECT COUNT(*) FROM projects")).fetchone())[0]
    tool_count = (await (await db.execute("SELECT COUNT(*) FROM tools")).fetchone())[0]
    
    return {
        "entities": entity_count,
        "edges": edge_count,
        "projects": project_count,
        "tools": tool_count,
    }
```

### `src/ghost/api/routes/watch.py`

```python
"""Watch directory management endpoints."""
from fastapi import APIRouter, Request
from ghost.api.schemas import WatchRequest

router = APIRouter(tags=["watch"])


@router.post("/watch")
async def watch_directory(req: WatchRequest, request: Request):
    """Start watching a directory."""
    # In Phase 1, we just register in DB. Phase 2 adds actual watchfiles integration.
    writer = request.app.state.writer
    
    import uuid
    project_id = str(uuid.uuid4())
    project_name = req.project_name or req.path.split("/")[-1]
    
    await writer.write(
        "INSERT OR IGNORE INTO projects (id, name, root_path) VALUES (?, ?, ?)",
        (project_id, project_name, req.path)
    )
    await writer.write(
        "INSERT OR IGNORE INTO watched_dirs (path, project_id) VALUES (?, ?)",
        (req.path, project_id)
    )
    
    return {"status": "watching", "path": req.path, "project_id": project_id}


@router.delete("/watch")
async def unwatch_directory(path: str, request: Request):
    """Stop watching a directory."""
    writer = request.app.state.writer
    await writer.write("DELETE FROM watched_dirs WHERE path = ?", (path,))
    return {"status": "unwatched", "path": path}
```

### `src/ghost/api/routes/events.py`

```python
"""WebSocket event stream (for live monitoring)."""
import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["events"])


@router.websocket("/events")
async def event_stream(websocket: WebSocket):
    """WebSocket endpoint for live event streaming."""
    await websocket.accept()
    
    event_bus = websocket.app.state.event_bus  
    event_queue: asyncio.Queue = asyncio.Queue()
    
    # Subscribe to all events
    async def handler(event):
        await event_queue.put({
            "topic": event.topic,
            "payload": event.payload,
            "id": event.id,
            "timestamp": event.timestamp.isoformat(),
        })
    
    event_bus.subscribe("*", handler)
    
    try:
        while True:
            event_data = await event_queue.get()
            await websocket.send_json(event_data)
    except WebSocketDisconnect:
        event_bus.unsubscribe("*", handler)
    except Exception:
        event_bus.unsubscribe("*", handler)


@router.get("/logs")
async def get_audit_logs(request=None, topic: str | None = None, limit: int = 50):
    """Get audit log entries."""
    from fastapi import Request as FRequest
    # Access via dependency injection
    audit = request.app.state.audit
    logs = await audit.query(topic=topic, limit=limit)
    return logs
```

### `src/ghost/api/routes/config.py`

```python
"""Dynamic configuration endpoints."""
from fastapi import APIRouter, Request
from ghost.api.schemas import LogLevelRequest

router = APIRouter(tags=["config"])


@router.post("/config/log-level")
async def set_log_level(req: LogLevelRequest, request: Request):
    """Dynamically change the daemon's log level."""
    from ghost.core.logging import set_log_level
    
    level = req.level.upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        return {"error": f"Invalid log level: {level}"}
    
    set_log_level(level)
    return {"status": "ok", "log_level": level}
```

---

## Unit Tests

### `tests/unit/test_suspend.py`

```
Test cases:
1. SuspendDetector detects clock gap > threshold
2. SuspendDetector ignores normal sleep intervals
3. resume_count increments on detection
4. on_resume callback is called with gap_seconds
5. stop() cancels the background task
```

### `tests/integration/test_daemon_lifecycle.py`

```
Test cases:
1. ensure_single_instance writes PID file
2. ensure_single_instance detects existing running process
3. ensure_single_instance cleans stale PID (dead process)
4. ensure_single_instance handles PermissionError (Bug #6)
5. safe_socket_path returns original if under limit
6. safe_socket_path falls back to /tmp if too long (Edge Case 1)
7. safe_socket_path writes pointer file
8. Stale socket cleanup on startup
```

---

## Important Reminders

1. **Bug #3 (CRITICAL)**: ALL cleanup in FastAPI lifespan `yield`, NOT in `signal.signal()` handlers. Uvicorn handles SIGTERM/SIGINT natively.
2. **Bug #6**: Catch `PermissionError` in PID file checking.
3. **Edge Case 1**: UDS path length check with `/tmp` fallback + pointer file.
4. **Edge Case 2**: Use `os.killpg()` to kill the process group in stop.
5. **All CLI commands are SYNC** — Typer is synchronous. Use `httpx.Client` (not `AsyncClient`).
6. **Never hardcode paths** — always import from `ghost.constants`.
7. **Rich formatting** — use `ghost.cli.display` helpers for all output.
8. **Lazy imports** — import heavy modules inside functions (not at the top of CLI files) to keep CLI startup fast.

---

## Definition of Done

- [ ] All 28+ files created and syntactically valid
- [ ] `python -c "from ghost.core.daemon import main; print('OK')"` works (import only, don't run)
- [ ] `python -c "from ghost.cli.app import app; print('OK')"` works
- [ ] `python -c "from ghost.api.schemas import ForgeRequest; print('OK')"` works
- [ ] All unit tests pass: `pytest tests/unit/test_suspend.py tests/integration/test_daemon_lifecycle.py -v`
- [ ] `ruff check src/ghost/core/ src/ghost/cli/ src/ghost/api/` passes
- [ ] `ghost --help` shows all commands
- [ ] `ghost --version` prints version
- [ ] `ghost doctor` runs without crashing
