<div align="center">
  <h1>👻 Ghost v3.0</h1>
  <p><strong>The Autonomous AI Daemon That Haunts Your Machine</strong></p>
  <p>A production-grade, local-first intelligence agent running seamlessly in the background, designed to synthesize, sandbox, and execute contextual Python tools on demand.</p>
</div>

---

## Overview

**Ghost** is not just another LLM wrapper or static CLI tool. It is a fully autonomous, local-first daemon (`ghostd`) that operates continuously in the background of your operating system. Ghost acts as an ambient intelligent agent, bridging the gap between natural language requests and concrete file-system execution.

When you ask Ghost to accomplish a task, it doesn't just give you a code snippet to copy-paste. Instead, Ghost leverages a dynamic pipeline to **synthesize**, **sandbox**, **quarantine**, and **execute** standalone Python tools customized exactly for your current operational context. 

By heavily relying on `uv` for seamless, ephemeral dependency management (PEP 723) and utilizing a robust SQLite-backed Knowledge Graph for persistent memory, Ghost effectively learns your environment and handles repetitive engineering tasks securely and autonomously.

## Core Capabilities

### Autonomous Tool Forging
Ghost interprets natural language intents into fully functional, rigorously typed Python scripts. Through its internal "Brain" hierarchy, it leverages tier-based routing (e.g., using `gpt-4o-mini` for triage and `gpt-4o` for complex analysis) to generate context-aware executable tools on the fly. 

### Secure Execution & Sandboxing
Security is paramount when allowing an AI to execute code on your machine. Ghost utilizes POSIX resource limits (`setrlimit`) to strict-bind CPU and memory allocation. All synthesized tools are run within isolated, ephemeral directories via `uv run`, completely stripping ambient API keys and environmental variables to prevent supply-chain leakage.

### The Quarantine Lifecycle
Ghost employs a stringent human-in-the-loop safety mechanism. Newly minted tools are placed in **Quarantine**. They cannot be executed until explicitly reviewed and approved by the user. Once approved, they are promoted to the active Registry and can be executed synchronously.

### Semantic Memory & Knowledge Graph
Ghost persistently records its actions and context. Utilizing `sqlite-vec` alongside Full-Text Search (FTS5), Ghost builds a highly interconnected Knowledge Graph. Entities and edges map out your file system and workflows, allowing Ghost to assemble rich context payloads through Reciprocal Rank Fusion (RRF) before it ever talks to an external LLM.

### Resilient Asynchronous Architecture
The daemon operates via Unix Domain Sockets (UDS) to prevent external port bindings. To safely guarantee SQLite concurrency without encountering `database is locked` states, Ghost processes all writes through a strictly sequential Single-Writer concurrent queue.

---

## System Architecture

Ghost v3.0 is constructed across three primary internal layers:

### 1. Core Infrastructure (`ghost.core` & `ghost.memory`)
* **UDS Daemon Lifecycle**: The background process guarantees a single instantiation via strict PID file bindings and Unix Domain Sockets constraint resolutions.
* **Database Writer Queue**: A multi-producer, single-consumer `asyncio.Queue` that serializes all SQLite transactions efficiently.
* **Event Bus**: A live pub/sub mechanism broadcasting system state changes and audit logs internally and over WebSockets.

### 2. Brain & Synthesis (`ghost.brain` & `ghost.synthesis`)
* **Model Router & Cost Meter**: Dynamically routes requests to appropriate LLM providers based on cognitive complexity, tracking exact API usage and dollar costs in real-time.
* **Context Assembler**: Calculates strict token budgets utilizing `tiktoken` fallbacks, actively fetching semantically relevant context from the Knowledge Graph.
* **Tool Forge**: The orchestration engine enforcing Pydantic validations on LLM structured JSON output, translating raw logic into PEP-723 compliant Python script skeletons.

### 3. Daemon Interface (`ghost.api` & `ghost.cli`)
* **FastAPI Routers**: Exposes native internal endpoints connecting the daemon's internal state machine over Unix Sockets.
* **Typer CLI**: The synchronous terminal frontend for the user (`ghost start`, `ghost forge`, `ghost doctor`), abstracting HTTPX requests securely back to the host daemon.

---

##  Installation & Setup

### Prerequisites
- Operating System: Linux or macOS (Ghost utilizes POSIX-specific APIs).
- Python: Version 3.11 or higher.
- Dependency Manager: **[uv](https://github.com/astral-sh/uv)** (Highly recommended for instantaneous sandbox resolving).
- Database Extension: `sqlite-vec` (Dynamically loaded).

### Step 1: Install `uv` (Recommended)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Step 2: Install Ghost CLI
Clone the repository and install it directly via `pip` or `uv`:
```bash
uv run pip install -e .
```

### Step 3: Initialization
Navigate to a directory where you want Ghost to operate and initialize its configuration structures:
```bash
ghost init
```
*This places structural folders in `~/.ghost/` (such as `quarantine`, `tools`, and `logs`) and generates your initial `.env` file.*

### Step 4: Authentication
Ghost requires access to an external LLM provider. Open the newly generated environment file:
```bash
nano ~/.ghost/.env
```
And supply exactly one (or more) active API keys:
```text
OPENAI_API_KEY=sk-xxxx...
```

---

## Operational Guide

### Managing the Background Daemon
Ghost functions asynchronously. The CLI endpoints communicate with the daemon, which must be running to process requests.
```bash
ghost start     # Starts the daemon in a detached process group
ghost status    # Print current memory, uptime, and queue state
ghost stop      # Gracefully terminates all ongoing tasks and closes DB connections
```

### Forging New Capabilities
When you need functionality, instruct Ghost natively via the `forge` command:
```bash
ghost forge "scan the src directory for files containing hardcoded secrets"
```
*Ghost will parse the context, generate a standalone Python script, and place it directly into the Quarantine vault.*

### Tool Flow: Approval & Execution
Check your quarantined tools, review the code, and promote them:
```bash
ghost tools list --status quarantined
ghost approve <tool_id>
```
Once approved, the tool is now registered and available for immediate localized execution:
```bash
ghost tools run <tool_name> --project-dir ./my_repo
```

### Semantic Memory Search
Interact with what Ghost has mapped and remembered regarding your development habits:
```bash
ghost memory search "Where did we last define the Uvicorn lifespan logic?"
```

### Telemetry & Diagnostics
Ghost tracks your API costs and internal health metrics automatically:
```bash
ghost doctor    # Comprehensive system requirement sweep
ghost cost      # Tabular rundown of Token utilization and USD spend
ghost logs      # View live stream of all audit events
```

---

## Developer Extensibility

Because Ghost isolates tool execution, developers can directly write and place their own `PEP 723` scripts into the `~/.ghost/tools/` registry directory. Ghost will automatically index and parse inline dependencies `/// script requires = ["requests"] ///` allowing infinite user-generated extensibilities outside of the LLM pipeline.

## Security Best Practices
Ghost is designed with guardrails; however, you are executing AI-generated logic directly on your file system. 
1. **Always physically review** code when it sits in `ghost tools list --status quarantined`.
2. Do not run Ghost as a `root` user or under `sudo`. 
3. Rely on `uv` to handle dependencies, preventing your global python namespace from becoming cluttered with arbitrary packages fetched by the LLM.

---
<div align="center">
  <i>"Ghost v3.0: Intelligence at the Kernel Level"</i>
</div>
