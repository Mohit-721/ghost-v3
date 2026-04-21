<div align="center">
  <h1>👻 Ghost v3.0</h1>
  <p><strong>The Autonomous AI Daemon That Haunts Your Machine</strong></p>
  <p>
    A production-grade, local-first intelligence daemon that runs in the background,
    synthesizes Python tools on demand, executes them in secure sandboxes,
    and maintains persistent project memory through a Knowledge Graph.
  </p>
  <p>
    <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+">
    <img src="https://img.shields.io/badge/tests-75%20passed-brightgreen.svg" alt="75 Tests Passed">
    <img src="https://img.shields.io/badge/lint-ruff%20clean-brightgreen.svg" alt="Ruff Clean">
    <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License">
  </p>
</div>

---

## Table of Contents

- [Overview](#-overview)
- [How It Works](#-how-it-works)
- [Installation & Setup](#-installation--setup)
- [CLI Command Reference](#-cli-command-reference)
- [Architecture](#-architecture)
- [Project Structure](#-project-structure)
- [Module Reference](#-module-reference)
- [Configuration](#-configuration)
- [Database Schema](#-database-schema)
- [Security Model](#-security-model)
- [Testing](#-testing)
- [Development](#-development)
- [Roadmap](#-roadmap)

---

## Overview

**Ghost** is not another LLM wrapper or chatbot CLI. It is a fully autonomous background daemon (`ghostd`) that bridges the gap between natural language intents and concrete, repeatable file-system operations.

When you tell Ghost to do something, it:

1. **Understands** your intent using tiered LLM intelligence (cheap models for triage, powerful models for synthesis)
2. **Gathers context** from its persistent Knowledge Graph using RAG (Retrieval-Augmented Generation)
3. **Synthesizes** a standalone Python script with proper dependency declarations (PEP 723)
4. **Quarantines** the script for your review (human-in-the-loop)
5. **Executes** approved tools in memory-capped, time-limited sandboxes via `uv run`
6. **Remembers** everything in a SQLite-backed entity graph for future context

Ghost runs over **Unix Domain Sockets** (no open ports), writes to a **single SQLite database** with WAL mode (no external services), and tracks every dollar spent on API calls.

---

## How It Works

```
┌──────────┐     sync httpx      ┌──────────────────────────────────────┐
│ ghost CLI│◄────── UDS ────────►│             ghostd (daemon)          │
│  (Typer) │                     │                                      │
└──────────┘                     │  FastAPI ─── EventBus ─── TaskManager│
                                 │     │                                │
                                 │  ┌──▼──────┐  ┌──────────────┐      │
                                 │  │  Brain   │  │   Synthesis  │      │
                                 │  │ ─Router  │  │ ─Forge       │      │
                                 │  │ ─Context │  │ ─Quarantine  │      │
                                 │  │ ─Cost    │  │ ─Executor    │      │
                                 │  │ ─Queue   │  │ ─Registry    │      │
                                 │  └──────────┘  └──────────────┘      │
                                 │        │              │              │
                                 │  ┌─────▼──────────────▼──────┐      │
                                 │  │          Memory            │      │
                                 │  │ ─Writer (single-writer Q)  │      │
                                 │  │ ─Entities + Graph + Search │      │
                                 │  │ ─Vectors (sqlite-vec)      │      │
                                 │  │ ─Audit Log                 │      │
                                 │  └────────────┬───────────────┘      │
                                 │               │                      │
                                 │          SQLite (WAL)                │
                                 └──────────────────────────────────────┘
```

### The Tool Lifecycle

```
  "find hardcoded secrets"        LLM generates code        User reviews
         │                              │                        │
    ghost forge ──► Context Assembly ──► Structured Output ──► Quarantine
                    (RAG + token          (json_schema)     ~/.ghost/quarantine/
                     budget)                                     │
                                                            ghost approve
                                                                 │
                                                            Registry ──► Execution
                                                        ~/.ghost/tools/    (uv run)
```

---

## Installation & Setup

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | Uses `tomllib`, `StrEnum`, `X \| Y` syntax |
| OS | Linux or macOS | POSIX APIs (`setrlimit`, `killpg`, UDS) |
| uv | Latest | Recommended for sandboxed tool execution |

### Step 1: Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Step 2: Clone and Install

```bash
git clone https://github.com/Mohit-721/ghost-v3.git
cd ghost-v3
uv pip install -e ".[dev]"
```

### Step 3: Initialize Ghost

```bash
ghost init
```

This creates `~/.ghost/` with the following structure:
```
~/.ghost/
├── config.toml       # Main configuration
├── .env              # API keys (gitignored)
├── ghost.db          # SQLite database
├── quarantine/       # Pending tool review
├── tools/            # Approved tools
└── logs/             # Operational logs
```

### Step 4: Add Your API Key

```bash
echo 'OPENAI_API_KEY=sk-...' >> ~/.ghost/.env
```

### Step 5: Start the Daemon

```bash
ghost start
```

### Step 6: Verify

```bash
ghost doctor    # Checks Python, uv, API keys, DB, disk space
ghost status    # Shows daemon health, memory, active tasks
```

---

## CLI Command Reference

### Daemon Lifecycle

| Command | Description |
|---------|-------------|
| `ghost start` | Start the daemon as a detached background process |
| `ghost stop` | Gracefully shutdown (flushes write queue, closes DB) |
| `ghost restart` | Stop then start |
| `ghost status` | Show PID, uptime, memory, queue depth, session cost |

### Tool Synthesis

| Command | Description |
|---------|-------------|
| `ghost forge "<intent>"` | Synthesize a new tool from natural language |
| `ghost approve <tool_id>` | Promote a quarantined tool to the registry |
| `ghost reject <tool_id>` | Delete a quarantined tool permanently |

### Tool Management

| Command | Description |
|---------|-------------|
| `ghost tools list` | List all tools (filter with `--status`) |
| `ghost tools info <name>` | Show tool details, source code, run history |
| `ghost tools run <name>` | Execute a registered tool in a sandbox |
| `ghost tools delete <name>` | Remove a tool from registry and disk |

### Memory & Search

| Command | Description |
|---------|-------------|
| `ghost memory search "<query>"` | Semantic search across the Knowledge Graph |
| `ghost memory stats` | Entity/edge/project counts |

### Observability

| Command | Description |
|---------|-------------|
| `ghost cost` | API spend breakdown (tokens, USD, per-model) |
| `ghost logs` | Recent audit log entries (semantic events) |
| `ghost debug` | Operational log tail (stack traces, timing) |
| `ghost doctor` | System health diagnostics |

### Maintenance

| Command | Description |
|---------|-------------|
| `ghost gc` | Garbage collect old audit entries |
| `ghost uninstall` | Full removal of `~/.ghost/` and all data |
| `ghost --version` | Print version |

---

## Architecture

Ghost is built in three architectural layers, each with clearly separated concerns:

### Layer 1: Core Infrastructure

The foundation that every other component depends on.

- **`constants.py`** — Single source of truth for all paths, defaults, version, pricing tables, and event topic names
- **`config/`** — Pydantic v2 models for typed configuration, TOML loader with environment variable overrides, and versioned config migrations
- **`core/events.py`** — Async pub/sub EventBus with wildcard topic support (`forge.*`), bounded history (deque, maxlen=500), and fire-and-forget task dispatch
- **`core/tasks.py`** — Concurrency controller using `asyncio.Semaphore` (2 LLM slots, 1 execution slot) with graceful shutdown
- **`core/logging.py`** — Non-blocking operational logging via `QueueHandler` → background thread → `RotatingFileHandler`. The async event loop never touches disk
- **`memory/writer.py`** — The critical single-writer queue. All SQLite writes pass through one `asyncio.Queue` consumer, eliminating `database is locked` errors entirely
- **`memory/database.py`** — SQLite connection with WAL mode, 64MB cache, memory-mapped I/O, and automatic corruption recovery (archives corrupt DB, rebuilds from scratch)

### Layer 2: Brain & Synthesis

The intelligence and tool generation pipeline.

- **`brain/providers/`** — Protocol-based LLM abstraction. Phase 1 ships OpenAI (httpx, no SDK). Each provider implements `complete()`, `structured_complete()` (native JSON schema enforcement), `count_tokens()`, and `embed()`
- **`brain/router.py`** — Tiered model selection. Tier 2 (gpt-4o-mini) for cheap operations like triage. Tier 3 (gpt-4o) for complex synthesis
- **`brain/context.py`** — RAG pipeline: queries the Knowledge Graph, packs results into a token budget using provider-specific tokenizers, with truncation for oversized entities
- **`brain/cost.py`** — Real-time cost tracking. `TokenCounter` uses `tiktoken` for OpenAI, with fallback estimation. `CostMeter` records every API call's USD cost to the database
- **`brain/retry.py`** — Tenacity-based retry with exponential backoff + jitter for 429/503/timeout errors. Falls back to persistent `IntentQueue` when all retries fail
- **`brain/prompts.py`** — Versioned prompt templates. Tools are pinned to the prompt version that generated them, enabling future regeneration when prompts improve
- **`synthesis/forge.py`** — The orchestrator: assembles context → calls LLM with structured output → validates response → writes PEP 723 script to quarantine → publishes events
- **`synthesis/quarantine.py`** — Holds synthesized tools as Python scripts in `~/.ghost/quarantine/`. Tracks status in DB. Supports approve (→ registry) and reject (→ delete)
- **`synthesis/executor.py`** — Runs tools in isolated subprocesses. Prefers `uv run` (automatic PEP 723 dep resolution). Applies POSIX `setrlimit` for memory/CPU caps. Strips API keys from environment
- **`synthesis/registry.py`** — Versioned tool storage. Multiple versions of the same tool name coexist. Current-version pointer for each name. Run counter and last_run tracking

### Layer 3: Daemon Interface

The entry points that users and systems interact with.

- **`core/daemon.py`** — The `ghostd` entry point. Handles single-instance enforcement (PID file), stale socket cleanup, UDS path length safety (fallback to `/tmp/` with pointer file), SQLite integrity check, and uvicorn launch
- **`core/app.py`** — FastAPI application factory. The `lifespan` context manager wires up every service on startup and tears everything down on shutdown. Signal handling piggybacks on uvicorn (no `signal.signal()` conflicts)
- **`core/health.py`** — Health status builder and `SuspendDetector` (monitors monotonic clock drift to catch laptop lid closures, triggering reconciliation on resume)
- **`core/lifecycle.py`** — Graceful shutdown helpers. Uses `os.killpg()` to terminate the entire process group, preventing zombie `uv run` child processes
- **`api/routes/`** — FastAPI routers for health, forge, tools, memory, watch, events (WebSocket), and config
- **`cli/app.py`** — Typer CLI with 18 registered commands and sub-command groups
- **`cli/client.py`** — Synchronous `httpx.Client` communicating with the daemon over UDS. Resolves socket pointer files when paths exceed kernel limits
- **`cli/display.py`** — Rich-powered terminal formatting for tables, tool previews, cost summaries, and status displays

---

## Project Structure

```
ghost-v3/
├── pyproject.toml                    # Project metadata, dependencies, entry points
├── Makefile                          # make test, lint, format, run, stop
├── README.md
│
├── src/ghost/
│   ├── __init__.py                   # Package version
│   ├── __main__.py                   # python -m ghost
│   ├── constants.py                  # All paths, defaults, pricing, event topics
│   │
│   ├── config/
│   │   ├── schema.py                 # GhostConfig, LLMConfig, SecretConfig (Pydantic v2)
│   │   ├── loader.py                 # TOML → GhostConfig, save_config()
│   │   └── migrations.py            # Config version transforms
│   │
│   ├── core/
│   │   ├── daemon.py                 # ghostd entry: PID lock, socket safety, uvicorn
│   │   ├── app.py                    # FastAPI factory, lifespan startup/shutdown
│   │   ├── events.py                 # Async pub/sub EventBus (wildcard, bounded)
│   │   ├── tasks.py                  # TaskManager: semaphore concurrency control
│   │   ├── lifecycle.py              # Process group kill, alive check
│   │   ├── health.py                 # SuspendDetector, health status builder
│   │   └── logging.py               # Non-blocking QueueHandler logging
│   │
│   ├── brain/
│   │   ├── providers/
│   │   │   ├── base.py               # LLMProviderProtocol (runtime_checkable)
│   │   │   └── openai.py             # httpx client, structured output, tiktoken
│   │   ├── router.py                 # Tier 2/3 model routing
│   │   ├── context.py                # RAG: search → token budget → pack
│   │   ├── cost.py                   # TokenCounter + CostMeter
│   │   ├── queue.py                  # Persistent intent queue (SQLite-backed)
│   │   ├── retry.py                  # Tenacity policies, queue fallback
│   │   └── prompts/
│   │       ├── registry.py           # Versioned prompt loader
│   │       └── v1/                   # forge.py, triage.py, analyze.py
│   │
│   ├── memory/
│   │   ├── database.py               # SQLite connection, pragmas, integrity check
│   │   ├── writer.py                 # Single-writer queue (sentinel shutdown)
│   │   ├── migrations/
│   │   │   ├── runner.py             # Sequential .sql migration runner
│   │   │   ├── 001_initial.sql       # Full schema: entities, edges, FTS5, tools, audit
│   │   │   └── 002_vectors.sql       # sqlite-vec (optional, graceful skip)
│   │   ├── entities.py               # Entity CRUD (project-scoped, content-hash upsert)
│   │   ├── graph.py                  # Edge CRUD, N-hop traversal, FTS+graph search
│   │   ├── vectors.py                # sqlite-vec store (no-op if unavailable)
│   │   ├── search.py                 # Unified search: FTS5 + graph + vectors → RRF fusion
│   │   └── audit.py                  # Semantic event log (append-only, prunable)
│   │
│   ├── synthesis/
│   │   ├── forge.py                  # Intent → context → LLM → quarantine pipeline
│   │   ├── quarantine.py             # PEP 723 script generator, approve/reject
│   │   ├── executor.py               # Subprocess execution (uv/python, setrlimit)
│   │   ├── registry.py               # Versioned tool storage, current pointer
│   │   └── templates/
│   │       └── tool_skeleton.py      # PEP 723 tool template
│   │
│   ├── senses/                       # Phase 2: file watching, filtering, reconciliation
│   │   └── __init__.py
│   │
│   ├── cli/
│   │   ├── app.py                    # Typer app, command registration
│   │   ├── client.py                 # Sync httpx over UDS → daemon
│   │   ├── display.py                # Rich formatting helpers
│   │   └── commands/                 # 12 command modules
│   │       ├── init.py               # ghost init
│   │       ├── start.py              # ghost start/stop/restart/status
│   │       ├── forge.py              # ghost forge
│   │       ├── approve.py            # ghost approve/reject
│   │       ├── watch.py              # ghost watch/unwatch/sync
│   │       ├── memory.py             # ghost memory search/stats
│   │       ├── tools.py              # ghost tools list/info/run/delete
│   │       ├── logs.py               # ghost logs + ghost debug
│   │       ├── cost.py               # ghost cost
│   │       ├── doctor.py             # ghost doctor
│   │       ├── gc.py                 # ghost gc
│   │       └── uninstall.py          # ghost uninstall
│   │
│   └── api/
│       ├── schemas.py                # Pydantic request/response models
│       └── routes/
│           ├── health.py             # GET /api/health, POST /api/shutdown
│           ├── forge.py              # POST /api/forge
│           ├── tools.py              # Tools CRUD + execution
│           ├── memory.py             # Search + stats
│           ├── watch.py              # Watch management
│           ├── events.py             # WebSocket stream + audit logs
│           └── config.py             # Dynamic log level
│
├── tests/
│   ├── conftest.py                   # Shared fixtures (in-memory DB, config)
│   ├── unit/                         # 11 test files, 75 tests total
│   │   ├── test_config.py
│   │   ├── test_events.py
│   │   ├── test_writer.py            # 9 tests for single-writer queue
│   │   ├── test_graph.py
│   │   ├── test_cost.py
│   │   ├── test_quarantine.py
│   │   ├── test_registry.py
│   │   ├── test_router.py
│   │   ├── test_circuit_breaker.py
│   │   └── test_suspend.py
│   └── integration/
│       └── test_daemon_lifecycle.py   # PID, socket path, stale cleanup
│
└── tools/                            # Pre-built starter tools (Phase 2)
```

**76 source files. 75 automated tests. 0 lint errors.**

---

## Configuration

### `~/.ghost/config.toml`

```toml
version = 1
log_level = "INFO"

[llm]
default_provider = "openai"
request_timeout = 60
max_retries = 3

[llm.tier2]
provider = "openai"
model = "gpt-4o-mini"
max_tokens = 4096
temperature = 0.3

[llm.tier3]
provider = "openai"
model = "gpt-4o"
max_tokens = 4096
temperature = 0.3

[watch]
debounce_seconds = 2.0
significance_threshold = 0.6
max_watched_dirs = 5

[sandbox]
exec_timeout_seconds = 30
install_timeout_seconds = 120
memory_limit_mb = 256
max_output_bytes = 1048576
prefer_uv = true
```

### `~/.ghost/.env`

```env
OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...    (Phase 3)
# GOOGLE_API_KEY=AI...             (Phase 3)
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GHOST_HOME` | `~/.ghost` | Override the Ghost home directory |
| `GHOST_LOG_LEVEL` | `INFO` | Override log level without config file |

---

## 🗄️ Database Schema

Ghost uses a single SQLite database (`~/.ghost/ghost.db`) with WAL mode.

### Tables

| Table | Purpose |
|-------|---------|
| `projects` | Multi-project isolation (root path, tech stack) |
| `entities` | Knowledge Graph nodes (files, functions, classes, insights) |
| `edges` | Knowledge Graph relationships (typed, weighted) |
| `entities_fts` | FTS5 full-text search index (auto-synced via triggers) |
| `entity_vectors` | Optional sqlite-vec embeddings for semantic search |
| `tools` | Tool registry (versioned, with status lifecycle) |
| `tool_current` | Current version pointer per tool name |
| `audit_log` | Append-only semantic event log |
| `cost_records` | Per-call LLM cost tracking (model, tokens, USD) |
| `intent_queue` | Persistent buffer for failed LLM requests |
| `file_hashes` | File change detection cache for reconciler |
| `watched_dirs` | Scoped directory watch list |
| `schema_version` | Migration tracking |

---

## Security Model

### Sandbox Isolation

Every tool runs in a restricted subprocess:
- **Memory cap**: `setrlimit(RLIMIT_AS)` — default 256 MB
- **CPU cap**: `setrlimit(RLIMIT_CPU)` — default 30 seconds
- **Working directory**: Temporary directory (`/tmp/ghost_*`), not the project
- **Environment stripping**: API keys are **never** passed to tools. Only `PATH`, `HOME=/tmp`, `LANG`, and `GHOST_PROJECT_DIR` are set
- **Dependency isolation**: `uv run` creates ephemeral virtual environments per-execution

### Human-in-the-Loop

All synthesized tools must pass through quarantine. No LLM-generated code executes without explicit `ghost approve`.

### Daemon Security

- **No open ports**: Communication exclusively over Unix Domain Sockets
- **Single instance**: PID file prevents duplicate daemons
- **PID reuse protection**: `PermissionError` from `os.kill()` is caught (handles PID belonging to another user)

---

## Testing

```bash
# Run all tests
make test

# With coverage
make test-cov

# Lint
make lint

# Format
make format

# Type check
make typecheck
```

### Test Coverage

| Module | Tests | Key Scenarios |
|--------|-------|---------------|
| `writer` | 9 | Sequential writes, sentinel shutdown, exception propagation, concurrent serialization |
| `events` | 5 | Pub/sub, wildcards, error isolation, drain |
| `graph` | 5 | Edge CRUD, N-hop traversal, FTS+graph search |
| `config` | 5 | TOML loading, defaults, validation, secret loading |
| `quarantine` | 4 | File creation, DB registration, approve, reject |
| `registry` | 5 | Register, current pointer, list, run tracking, delete |
| `router` | 4 | Provider init, tier routing, missing API key, invalid tier |
| `cost` | 3 | Token counting, pricing calculation, session tracking |
| `circuit_breaker` | 6 | Storm detection, cooldown, threshold tuning |
| `suspend` | 1 | Monotonic clock drift detection |
| `daemon_lifecycle` | 5 | PID lock, stale cleanup, UDS path fallback, PermissionError |

---

## Development

### Local Development

```bash
# Install in dev mode
make dev

# Run the daemon in foreground (useful for debugging)
uv run ghostd

# Or start as background process
ghost start

# Watch logs
tail -f ~/.ghost/logs/ghostd.log
```

### Entry Points (from `pyproject.toml`)

| Command | Module | Description |
|---------|--------|-------------|
| `ghost` | `ghost.cli.app:main` | CLI frontend |
| `ghostd` | `ghost.core.daemon:main` | Daemon process |

### Key Design Decisions

1. **Single-Writer Queue**: All DB writes go through one `asyncio.Queue` consumer. This eliminates SQLite lock contention without requiring external databases
2. **Lifespan-Only Cleanup**: All shutdown logic is in FastAPI's `lifespan` context manager, not `signal.signal()`. This prevents conflicts with uvicorn's internal signal handlers
3. **Sentinel Shutdown**: The writer queue uses `None` as a sentinel to break the consumer loop, avoiding the race condition in `while running or not queue.empty()`
4. **UDS Path Fallback**: If `~/.ghost/ghost.sock` exceeds the kernel's 108-char UDS path limit, Ghost falls back to `/tmp/ghost_<hash>.sock` and writes a pointer file
5. **Provider-Specific Tokenizers**: Token counting uses `tiktoken` for OpenAI (local, fast), with a `len(text) // 4` fallback for unknown providers

---

## Roadmap

### Phase 1 ✅ (Current)
Core infrastructure, brain, synthesis, daemon, CLI, and API — all implemented and tested.

### Phase 2 (Planned)
- **Senses layer**: File watcher (`watchfiles`), signal filter pipeline, circuit breaker (storm detection), and periodic reconciler
- **Pre-built starter tools**: project scanner, git analyzer, TODO finder
- **CI/CD**: GitHub Actions for lint + test on push

### Phase 3 (Planned)
- **Additional LLM providers**: Anthropic (tool_use structured output), Google Gemini (response_schema)
- **Embeddings**: Integration with `sentence-transformers` for local vector generation
- **systemd/launchd**: Auto-start templates for Linux and macOS

---

<div align="center">
  <sub>Built with obsessive attention to edge cases. 4 rounds of adversarial design review. 36 architectural gaps resolved.</sub>
</div>
