# Memento

[![Version](https://img.shields.io/badge/version-0.9.1-blue.svg)](pyproject.toml)
[![Python](https://img.shields.io/badge/python-≥3.10-blue.svg)](https://www.python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](pyproject.toml)

[中文说明](README.zh-CN.md)

> Your long-term memory engine for AI Agents — knowledge that accumulates across sessions, decays when stale, and forgets on demand.

Memento is the implementation of the [Engram architecture](Engram：分布式记忆操作系统与协作协议.md): a distributed memory operating system and collaboration protocol for cross-session and cross-project knowledge accumulation.

---

## Table of Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Core Concepts](#core-concepts)
- [Command Reference](#command-reference)
- [Configuration](#configuration)
- [Web Dashboard](#web-dashboard)
- [Agent Integration](#agent-integration)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)

---

## Features

- **Living Memory** — Memories decay when unused, strengthen when recalled. Not a static archive.
- **Auto-Extraction** — Stop hook automatically extracts decisions, preferences, and conventions from AI conversations.
- **Semantic Retrieval** — Vector + graph + full-text triple recall with multiple embedding providers.
- **Epoch Consolidation** — Sleep-like LLM-driven structuring, reconsolidation, and abstraction.
- **Claude Code Integration** — Deep integration via hooks + MCP Server for automatic memory extraction and recall.
- **OpenCode Integration** — Native plugin support with lifecycle hooks, automatic priming, and tool observation.
- **Local-First** — Data stored in local SQLite. Dashboard listens on `127.0.0.1` only.
- **Crypto-Shredding** — Delete the encryption key to mathematically destroy all associated data. Built-in right to be forgotten.

---

## Quick Start

### Prerequisites

- Python >= 3.10
- pip
- Git (for installation from repository)

### Install

```bash
pip install git+ssh://git@github.com:winteriscome/memento.git
```

### Setup

```bash
memento setup
```

The interactive wizard guides you through database initialization, embedding provider selection, LLM configuration, and Claude Code integration.

### Verify

```bash
memento doctor         # check configuration
memento doctor --ping  # verify API connectivity
```

### Try It

```bash
# capture a memory
memento capture "Project uses Python 3.11 + SQLite" --type fact

# recall memories
memento recall "tech stack"

# check system status
memento status
```

Once these work, Memento is ready. If you use Claude Code, it runs automatically in the background — no manual action needed.

---

## Core Concepts

### Memory Lifecycle

```
capture / auto-extraction → L2 buffer → epoch run → Engram (permanent memory)
                                                        ↓
                                                 decay / strengthen / forget
```

1. Memories are written to the L2 buffer (immediate, provisional state)
2. `epoch run` consolidates buffered memories into permanent Engrams (can be triggered automatically by hooks)
3. Engrams participate in ongoing decay and strengthening cycles

### Memory Types

Specified via `--type`, affects retrieval weight and consolidation strategy:

| Type | Purpose | Example |
|------|---------|---------|
| `fact` | Technical facts | "Project uses Python 3.11 + SQLite" |
| `decision` | Architectural decisions | "Chose SQLite over PostgreSQL for single-node deployment" |
| `preference` | User preferences | "Communicate in Chinese, code comments in English" |
| `convention` | Project conventions | "Commit messages in English, scope in lowercase" |
| `insight` | Lessons learned | "Concurrent tests need isolated DB instances" |
| `debugging` | Debugging experience | "Port conflict? Check uvicorn processes first" |

### Trust Model

- Agent-written memories have a strength cap of 0.5 (semi-trusted)
- Users can lift the cap with `memento verify <id>`
- User-written memories have no cap

---

## Command Reference

### Daily Operations

| Command | Description |
|---------|-------------|
| `memento capture <content> --type <type>` | Capture a memory |
| `memento recall <query>` | Semantic search for related memories |
| `memento status` | View system status |
| `memento inspect <id>` | View memory details |
| `memento forget <id>` | Mark for deletion (takes effect after next epoch) |

### Memory Management

| Command | Description |
|---------|-------------|
| `memento verify <id>` | Mark agent memory as trustworthy |
| `memento pin <id> --rigidity 0.8` | Pin memory to prevent decay (0.0-1.0) |
| `memento nexus <id> --depth 2` | View memory association network |
| `memento export --output backup.json` | Export memories |
| `memento import --file data.json` | Import memories |

### Epoch Consolidation

| Command | Description |
|---------|-------------|
| `memento epoch run` | Run consolidation (auto-selects full/light mode) |
| `memento epoch run --mode light` | Math-only mode (decay, strength updates) |
| `memento epoch run --mode full` | LLM-driven mode (structuring, abstraction) |
| `memento epoch status` | View epoch history |
| `memento epoch debt` | View cognitive debt |

### Setup & Maintenance

| Command | Description |
|---------|-------------|
| `memento setup` | Interactive setup wizard |
| `memento doctor [--ping]` | Check config / verify connectivity |
| `memento init` | Initialize database |
| `memento update [--check]` | Update to latest version |
| `memento dashboard` | Launch Web Dashboard |

---

## Configuration

### Using the Setup Wizard (Recommended)

```bash
memento setup
# or non-interactive:
memento setup --yes --embedding-provider zhipu --embedding-api-key "sk-xxx"
```

### Manual Configuration

For fine-grained control, set environment variables directly.

#### Embedding Provider (Semantic Search)

Set one API key — Memento picks the first available by priority:

```bash
# Chinese LLM providers (tried first)
export ZHIPU_API_KEY="your-key"          # Zhipu GLM embedding-3 (2048d)
export MINIMAX_API_KEY="your-key"        # Minimax embo-01 (1536d)
export MOONSHOT_API_KEY="your-key"       # Moonshot/Kimi

# International providers
export OPENAI_API_KEY="your-key"         # OpenAI text-embedding-3-small
export GEMINI_API_KEY="your-key"         # Google Gemini embedding-001 (768d)
```

Priority: Zhipu → Minimax → Moonshot → OpenAI → Gemini → local sentence-transformers → FTS5 fallback.

No API key? Memento falls back to full-text search. For local embeddings (offline):

```bash
pip install memento[local]   # installs sentence-transformers
```

#### LLM Provider (Epoch Consolidation — Optional)

Any OpenAI-compatible API works:

```bash
export MEMENTO_LLM_BASE_URL=https://api.openai.com/v1
export MEMENTO_LLM_API_KEY=sk-xxx
export MEMENTO_LLM_MODEL=gpt-4o-mini
```

| Provider | BASE_URL | MODEL example |
|----------|----------|---------------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Zhipu/GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Ollama (local) | `http://localhost:11434/v1` | `llama3` |
| vLLM | `http://localhost:8000/v1` | `your-model` |
| LM Studio | `http://localhost:1234/v1` | `your-model` |

> **Without LLM:** Memento works fine. `epoch run` auto-degrades to light mode (pure math: decay, strength updates, Nexus adjustments). LLM-dependent operations are deferred as cognitive debt until an LLM is available.

Optional settings:

```bash
export MEMENTO_LLM_TIMEOUT=30          # seconds (default: 30)
export MEMENTO_LLM_MAX_RETRIES=3       # retries (default: 3)
export MEMENTO_LLM_TEMPERATURE=0       # temperature (default: 0)
```

---

## Web Dashboard

Local Web Dashboard for visual memory management. No internet connection required.

```bash
# install dependencies (one-time)
pip install memento[dashboard]

# launch
memento dashboard                # opens http://localhost:8230
memento dashboard --port 9000    # custom port
memento dashboard --no-open      # don't auto-open browser
```

Three views:

- **Memories** — Browse, search, filter, and manage all memories
- **Sessions** — View session history and event statistics
- **System** — Monitor status, epoch history, L2 buffer

Dashboard listens on `127.0.0.1` only — not exposed to the network.

---

## Agent Integration

Memento supports multiple AI coding agents through a runtime adapter architecture. The core memory engine is agent-agnostic; each agent connects through its own integration layer.

### Claude Code (Recommended)

```bash
memento setup    # auto-installs hooks + MCP server
memento doctor   # verify configuration
```

After setup, Claude Code automatically calls Memento at these points:

| Hook | When | Behavior |
|------|------|----------|
| SessionStart | Session begins | Injects most relevant memories into conversation context |
| Stop | After each AI response | Auto-extracts valuable memories from conversation |
| SessionEnd | Session ends | Records session summary |

Place [CLAUDE.md](CLAUDE.md) in your project root so the agent follows the memory protocol.

### OpenCode

OpenCode support is provided by a native JavaScript plugin that hooks into the event system:

| Event | When | Behavior |
|-------|------|----------|
| `session.created` | New session starts | Recalls and caches priming memories |
| `session.idle` | Session becomes idle | Debounced flush + optional epoch trigger |
| `session.deleted` | Session ends | Final flush, close session, shutdown worker |
| `tool.execute.after` | After each tool use | Records observation for context tracking |
| `chat.system.transform` | Before LLM call | Injects cached priming into system prompt |

**Install:**

```bash
./scripts/install-opencode-plugin.sh
```

**Prerequisites:**
- Bun runtime (required — OpenCode's plugin system itself runs on Bun; this plugin uses Bun's `$` shell API and native Unix socket `fetch()`, which OpenCode plugins are designed around)
- Memento Python package installed (`pip install -e .`)
- `memento-worker` CLI on PATH

**Manual setup:**

1. Copy plugin files to `~/.config/opencode/plugins/memento/`:
   ```bash
   mkdir -p ~/.config/opencode/plugins/memento/shared
   cp src/memento/plugins/opencode/*.js ~/.config/opencode/plugins/memento/
   cp src/memento/plugins/shared/bridge.js ~/.config/opencode/plugins/memento/shared/
   cd ~/.config/opencode/plugins/memento && bun install
   ```
2. Add to your `opencode.json`:
   ```json
   {
     "plugin": ["memento"],
     "mcpServers": {
       "memento": {
         "type": "stdio",
         "command": "memento-mcp-server"
       }
     }
   }
   ```

**验证 OpenCode 插件：**

```bash
# 1. 启动 OpenCode
opencode

# 2. 查看插件日志（插件通过 stderr 输出 [memento] 前缀日志）
# 预期行为：
#   - session.created 时：[memento] priming: N memories cached for session xxx
#   - tool.execute.after 时：无输出（静默记录 observation）
#   - session.idle 时：[memento] idle flush complete
#   - session.deleted 时：[memento] session end: flushed and closed
```

**手动验证插件加载：**

| 步骤 | 操作 | 预期行为 |
|------|------|----------|
| 1 | `memento status` | 显示系统状态 |
| 2 | 启动 OpenCode，新会话 | 日志中显示 `[memento] plugin initialized` |
| 3 | 发送一条消息 | 日志显示 `[memento] priming: N memories cached` |
| 4 | 执行工具调用（如 Bash、Read） | 静默记录 observation |
| 5 | 结束会话 | 日志显示 `idle flush complete` + `session end` |

---

## Architecture

Memento shifts memory from static CRUD to a "living memory" paradigm:

- **Living Memory Units (Engrams)** — Core unit with strength, decay rate, emotional valence, and associative network.
- **Three Cognitive Rhythms:**
  - *Awake Track* (milliseconds) — Instant graph/vector recall and memory capture.
  - *Subconscious Track* (minutes) — Background metadata updates, Hebbian reinforcement, noise reduction.
  - *Sleep / Epoch Track* (daily) — LLM-driven heavy consolidation, semantic abstraction, snapshot generation.
- **Immutable Snapshot DAG** — Git-like Merkle DAG for tracking cognitive revisions.
- **Crypto-Shredding** — Delete the Data Encryption Key to mathematically destroy memory and all associated data.

For the full design document, see [Engram: Distributed Memory OS and Collaboration Protocol](Engram：分布式记忆操作系统与协作协议.md).

---

## Project Structure

```
memento/
├── src/memento/
│   ├── cli.py              # CLI entry point (Click framework)
│   ├── api.py              # MementoAPI (LocalAPI)
│   ├── mcp_server.py       # MCP Server
│   ├── worker.py           # Worker service (Unix Socket HTTP server)
│   ├── session.py          # Session lifecycle management
│   ├── epoch.py            # Epoch consolidation logic
│   ├── embedding.py        # Embedding provider integration
│   ├── llm.py              # LLM integration
│   ├── db.py               # Database operations
│   ├── decay.py            # Memory decay calculations
│   ├── hebbian.py          # Hebbian learning
│   ├── plugins/
│   │   ├── shared/         # Runtime-agnostic bridge
│   │   │   └── bridge.js   # Universal Worker client (JS)
│   │   └── opencode/       # OpenCode native plugin
│   │       ├── plugin.js   # Lifecycle hooks entry point
│   │       ├── normalize.js# Event → unified schema
│   │       └── priming.js  # System prompt formatter
│   └── dashboard/          # Web Dashboard
├── plugin/                 # Claude Code plugin (hooks + scripts)
│   ├── hooks/hooks.json    # Claude hook registrations
│   └── scripts/            # Hook handler scripts
├── scripts/
│   ├── memento-agent.sh    # Shared agent helper (multi-agent)
│   └── install-opencode-plugin.sh
├── tests/                  # Test suite
├── docs/                   # Documentation
├── CLAUDE.md               # Claude Code instruction template
└── pyproject.toml          # Project metadata
```

---

## Development

```bash
git clone ssh://git@git@github.com:winteriscome/memento.git
cd memento
pip install -e ".[dev,dashboard]"
pytest
```

---

## Contributing

Issues and Merge Requests are welcome.

1. Fork this repository
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Commit your changes
4. Push and create a Merge Request

---

## License

[MIT](pyproject.toml)

---

<sub>Memento — Making AI agent memory alive, forgettable, and truly cumulative.</sub>
