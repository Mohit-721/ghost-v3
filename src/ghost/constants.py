"""
Ghost constants — shared across all modules.

This file is the SINGLE SOURCE OF TRUTH for paths, defaults, and version info.
All modules import from here. Never hardcode these values elsewhere.
"""

from pathlib import Path

# ─── Version ────────────────────────────────────────────────────────────────
VERSION = "0.1.0"
CONFIG_VERSION = 1
SCHEMA_VERSION = 1  # Bump when adding new migrations

# ─── Paths ──────────────────────────────────────────────────────────────────
DEFAULT_GHOST_HOME = Path.home() / ".ghost"
DEFAULT_SOCKET_NAME = "ghost.sock"
DEFAULT_DB_NAME = "ghost.db"
DEFAULT_PID_FILE = "ghost.pid"
DEFAULT_CONFIG_FILE = "config.toml"
DEFAULT_ENV_FILE = ".env"
DEFAULT_SOCKET_POINTER = "socket_path"  # Written when UDS path is too long

# Subdirectories under GHOST_HOME
QUARANTINE_DIR = "quarantine"
TOOLS_DIR = "tools"
LOGS_DIR = "logs"
LOG_FILE = "ghostd.log"

# ─── Daemon ─────────────────────────────────────────────────────────────────
DAEMON_BASE_URL = "http://ghostd"  # Placeholder host for UDS transport
UDS_PATH_LIMIT_LINUX = 108
UDS_PATH_LIMIT_MACOS = 104

# ─── Database ───────────────────────────────────────────────────────────────
DB_PRAGMAS = {
    "journal_mode": "WAL",
    "synchronous": "NORMAL",
    "cache_size": -64000,  # 64MB
    "foreign_keys": True,
    "temp_store": "MEMORY",
    "mmap_size": 268435456,  # 256MB
}

# ─── Concurrency ────────────────────────────────────────────────────────────
MAX_CONCURRENT_LLM_CALLS = 2
MAX_CONCURRENT_EXEC = 1

# ─── Sandbox Defaults ───────────────────────────────────────────────────────
DEFAULT_EXEC_TIMEOUT = 30  # seconds
DEFAULT_INSTALL_TIMEOUT = 120  # seconds (for uv first-run)
DEFAULT_MEMORY_LIMIT_MB = 256
DEFAULT_MAX_OUTPUT_BYTES = 1_048_576  # 1MB

# ─── Logging ────────────────────────────────────────────────────────────────
LOG_MAX_BYTES = 5_000_000  # 5MB per log file
LOG_BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

# ─── Watch / Senses ────────────────────────────────────────────────────────
DEFAULT_DEBOUNCE_SECONDS = 2.0
DEFAULT_SIGNIFICANCE_THRESHOLD = 0.6
DEFAULT_RECONCILE_INTERVAL_MINUTES = 60
DEFAULT_MAX_WATCHED_DIRS = 5
DEFAULT_STORM_THRESHOLD = 50
DEFAULT_STORM_WINDOW = 3.0
DEFAULT_STORM_COOLDOWN = 30.0

# ─── LLM ────────────────────────────────────────────────────────────────────
DEFAULT_REQUEST_TIMEOUT = 60
DEFAULT_MAX_RETRIES = 3
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 4096
TOKEN_FALLBACK_CHARS_PER_TOKEN = 4  # len(text) // 4

# ─── Cost Tracking ──────────────────────────────────────────────────────────
# Pricing per 1M tokens (USD) — updated as of 2026-04
MODEL_PRICING = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku-3.5": {"input": 0.80, "output": 4.00},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
}

# ─── Tier Defaults ──────────────────────────────────────────────────────────
# Tier 2: Tool synthesis, triage (mid-range model)
# Tier 3: Complex analysis (high-end model)
DEFAULT_TIER2_MODEL = "gpt-4o-mini"
DEFAULT_TIER3_MODEL = "gpt-4o"

# ─── Hardcoded Ignore Patterns ──────────────────────────────────────────────
ALWAYS_IGNORE = {
    ".ghost",
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    "Thumbs.db",
}


# ─── Event Topics ───────────────────────────────────────────────────────────
# Namespaced event topics for the EventBus
class Topics:
    # File system
    FILE_CHANGED = "fs.changed"
    FILE_CREATED = "fs.created"
    FILE_DELETED = "fs.deleted"

    # Forge
    FORGE_REQUESTED = "forge.requested"
    FORGE_COMPLETED = "forge.completed"
    FORGE_FAILED = "forge.failed"

    # Tools
    TOOL_APPROVED = "tool.approved"
    TOOL_REJECTED = "tool.rejected"
    TOOL_EXECUTED = "tool.executed"
    TOOL_FAILED = "tool.failed"

    # System
    DAEMON_STARTED = "system.started"
    DAEMON_STOPPING = "system.stopping"
    RESUME_DETECTED = "system.resume"
    STORM_DETECTED = "system.storm"
    RECONCILE_STARTED = "system.reconcile.start"
    RECONCILE_COMPLETED = "system.reconcile.done"

    # Memory
    ENTITY_CREATED = "memory.entity.created"
    ENTITY_UPDATED = "memory.entity.updated"
