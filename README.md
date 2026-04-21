# 👻 Ghost v3.0

> The AI daemon that haunts your machine.

Ghost is a production-grade, local-first AI agent daemon that runs in the background. It synthesizes "tools" (lightweight Python scripts) on demand, tests them in isolation, runs them using POSIX security limits, and coordinates its contextual execution through an asynchronous graph system backing into SQLite.

## ✨ Features

- **Daemon-First Architecture**: Runs silently via Unix Domain Sockets mapping native logic workflows. Single instance enforced via PID.
- **RAG & Context Assembly**: Semantic Vector/Full-Text Search on a Knowledge Graph (Nodes/Edges) utilizing Reciprocal Rank Fusion via `sqlite-vec` internally.
- **Tool Forge & Execution**: Synthesizes PEP 723 isolated scripts natively. Tools execute in memory-capped sandboxes using `uv`. 
- **Resilient Memory**: Built on top of a single-writer concurrent queue bypassing dreaded `database is locked` SQLite concurrency errors.
- **Intelligence Layer**: Native token-aware HTTPX provider endpoints for OpenAI integrations explicitly tracking costs and metrics natively.

## 🚀 Quick Start

1. **Install uv** (Highly recommended for tool sandboxes):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. **Install Ghost**
   To run from source:
   ```bash
   uv run pip install -e .
   ```
3. **Initialize the Environment**
   ```bash
   ghost init
   ```
   This generates the configuration and creates `.env` in your `~/.ghost/` folder.
   Add your OpenAI API key to `~/.ghost/.env`.

4. **Start the Daemon**
   ```bash
   ghost start
   ```

5. **Forge a Tool**
   Tell Ghost what you need, and it synthesizes a tool for you:
   ```bash
   ghost forge "scan current directory for memory leaks"
   ```

## 🛠️ CLI Reference

### Daemon Management
- `ghost start` / `ghost stop` / `ghost restart` / `ghost status`
- `ghost init`: Initialize project integration settings.
- `ghost doctor`: Diagnostics testing API keys, python environment, and system thresholds.

### Tool Management
- `ghost forge "<intent>"`: Synthesizes a new tool and sends it to quarantine.
- `ghost tools run <name>`: Runs an approved tool natively.
- `ghost tools list`: Views all tool scripts natively.
- `ghost approve <tool_id>`: Readies a quarantined tool for live registry executions.

### Memory & Observability
- `ghost memory search "query"`: Triggers contextual rank checks across SQLite graph stores.
- `ghost cost`: Check native API session prices.
- `ghost debug / ghost logs`: Monitor operations directly through web socket/HTTP connections.

## 🗄️ Architecture Topology

Ghost v3 consists of three core architectural layers:
1. **Core Infrastructure**: SQlite memory handlers, EventBus pub/sub, Concurrent queue writer, and structural Data objects.
2. **Brain & Synthesis**: Cost aggregators, Context assemblers via RAG, OpenAI interactions, intent routers, and the Tool quarantine Forge.
3. **Daemon Interface**: The UDS running Uvicorn daemon process mapped to FastAPI syncing natively to the Typer-based synchronizer CLI.

---
**Status**: Ghost v3 Phase 1 completed successfully and all 75 integration unit tests passing. Built primarily for robust Linux/MacOS functionality workflows.
