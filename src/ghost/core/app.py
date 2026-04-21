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
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from ghost.config.schema import GhostConfig, SecretConfig
from ghost.constants import VERSION

logger = logging.getLogger(__name__)


def create_app(config: GhostConfig, log_listener: Any = None) -> FastAPI:
    """Create and configure the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
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
        from ghost.memory.audit import AuditLog
        from ghost.memory.entities import EntityStore
        from ghost.memory.graph import GraphStore
        from ghost.memory.search import UnifiedSearch
        from ghost.memory.vectors import VectorStore

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
        from ghost.brain.context import ContextAssembler
        from ghost.brain.cost import CostMeter, TokenCounter
        from ghost.brain.queue import IntentQueue
        from ghost.brain.router import ModelRouter

        router = ModelRouter(config, secrets)
        session_id = str(uuid.uuid4())
        cost_meter = CostMeter(writer, session_id=session_id)

        # Token counter for context assembly (use default provider)
        try:
            router.get_provider(tier=2)
            token_counter = TokenCounter(
                config.llm.default_provider.value,
                config.llm.tier2.model,
            )
        except RuntimeError:
            # No provider configured — use fallback counter
            token_counter = TokenCounter("fallback", "none")

        context_assembler = ContextAssembler(search, token_counter)
        intent_queue = IntentQueue(db, writer)

        app.state.router = router
        app.state.cost_meter = cost_meter
        app.state.context_assembler = context_assembler
        app.state.intent_queue = intent_queue

        # 7. Synthesis services
        from ghost.synthesis.executor import ToolExecutor
        from ghost.synthesis.forge import ToolForge
        from ghost.synthesis.quarantine import QuarantineManager
        from ghost.synthesis.registry import ToolRegistry

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
        await event_bus.publish(
            "system.started",
            {
                "version": VERSION,
                "session_id": session_id,
                "pid": __import__("os").getpid(),
            },
        )
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
    from ghost.api.routes import config as config_routes
    from ghost.api.routes import events, forge, health, memory, tools, watch

    app.include_router(health.router, prefix="/api")
    app.include_router(forge.router, prefix="/api")
    app.include_router(tools.router, prefix="/api")
    app.include_router(memory.router, prefix="/api")
    app.include_router(watch.router, prefix="/api")
    app.include_router(events.router, prefix="/api")
    app.include_router(config_routes.router, prefix="/api")

    return app
