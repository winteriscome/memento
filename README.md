# Memento

[中文说明](README.zh-CN.md)

**Your long-term memory engine for AI Agents.**

Memento is the implementation of the **Engram** architecture—a distributed memory operating system and collaboration protocol designed to solve the problem of cross-session and cross-project knowledge accumulation and retrieval for AI agents and individuals.

## 🌟 Core Philosophy

Traditional knowledge bases (like Notion or Obsidian) and vector databases treat memory as static files. Memento treats memory as a living organism based on three fundamental principles:

1. **Memory is Alive**: Memory is not an archive, but a living tissue. It decays if unused, and strengthens each time it is recalled. Memento automatically deranks outdated information and boosts frequently used knowledge, continuously improving the signal-to-noise ratio.
2. **Cognition is Shareable**: Human civilization is essentially a process of forking and merging memories. Memento supports a cognitive Fork/PR/Merge workflow, allowing memory vaults (Vaults) to be safely shared, synchronized, and evolved across a federated network.
3. **Forgetting is a Feature**: Infinite memory leads to decision paralysis. Selective forgetting is at the core of intelligence.

## 🏗️ Key Architectures

Memento introduces a paradigm shift from traditional CRUD approaches:

- **Living Memory Units (Engrams)**: The core unit of memory, complete with strength, decay rates, emotional valence, and associative network connections (Nexus).
- **Three Cognitive Rhythms**: 
  - *Awake Track* (Milliseconds): For instant graph/vector recall and capturing memory buffers.
  - *Subconscious Track* (Minutes): Silent background metadata updates, Hebbian learning reinforcement, and noise reduction.
  - *Sleep/Epoch Track* (Daily): Heavy LLM-driven consolidation, semantic abstraction, and snapshot generation.
- **Immutable Snapshot DAG**: Memento uses a Git-like Merkle DAG to track cognitive revisions. Memory space compression utilizes a tombstone mechanism to allow selective forgetting without breaking the cryptographic hash chain.
- **Strict Privacy & Crypto-Shredding**: The "Right to be forgotten" is built directly into the storage engine. Deleting the Data Encryption Key (DEK) mathematically shreds the memory, its embeddings, its abstracts, and all associated metadata instantly.

## 🚀 v0.1 Quick Start

Memento v0.1 is available as a CLI tool designed to be integrated into AI Agent loops (like Claude Code, Gemini CLI, or Codex), or used directly.

### Installation

```bash
# Clone the repository
git clone https://github.com/winteriscome/memento.git
cd memento

# Install as an editable package (requires Python 3.10+)
pip install -e .
```

### Configuration

Memento uses Gemini for high-quality semantic embeddings (falling back to local FTS5 if not available). Set your API key:

```bash
export GEMINI_API_KEY="your-gemini-api-key"
```

### Basic Usage

```bash
# Initialize the database (~/.memento/default.db)
memento init

# Capture a memory (Agent auto-captured memories should use --origin agent)
memento capture "JWT authentication uses RS256, keys are in /config/keys/" --type fact --importance high

# Recall context (automatically applies decay & reinforcement weights)
memento recall "auth" --format json

# Generate a starter experiment dataset and labeled queries
memento seed-experiment --db eval_mode_a.db --queries-output examples/eval_queries.generated.json

# One-shot setup for both Mode A and Mode B databases
memento setup-experiment --db-a eval_mode_a.db --db-b eval_mode_b.db --queries-output examples/eval_queries.generated.json --manifest-output examples/experiment_manifest.generated.json

# Run the baseline scorer without reinforcement side effects
memento recall "auth" --mode B --format json

# Evaluate a labeled query set in read-only mode
memento eval --queries eval_queries.json --mode A --format json

# Compare two database snapshots directly
memento eval --queries eval_queries.json --db eval_mode_a.db --mode A --compare-db eval_mode_b.db --compare-mode B --format json

# Save the full evaluation report to a file
memento eval --queries eval_queries.json --db eval_mode_a.db --mode A --compare-db eval_mode_b.db --compare-mode B --report-output reports/week2.json --format json

# Status & Sync
memento status
memento export --output team_memory.json
```

`memento recall --mode A` is the experimental scorer (`effective_strength × similarity`).
`memento recall --mode B` is the baseline scorer (`similarity × recency_bonus`) and does not write reinforcement side effects.
`memento seed-experiment` writes a small labeled dataset with cold, warm, hot, and stale memories so you can start the v0.1 experiment immediately.
`memento setup-experiment` creates the A/B database pair, generated query set, and a manifest with the recommended eval command.
`memento eval` always runs in read-only mode so you can compare isolated database snapshots during the v0.1 experiment.
Use `--report-output` to save the full JSON report for review history.
See `examples/eval_queries.sample.json` for the expected query-set format.

For AI Agents, refer to the [CLAUDE.md](./CLAUDE.md) instruction template to automate knowledge co-building.

## Agent Automation

Memento works best when the agent runtime calls it at fixed points rather than relying on manual memory management.

Recommended repository files:

- [CLAUDE.md](CLAUDE.md) for Claude Code
- [GEMINI.md](GEMINI.md) for Gemini CLI
- [AGENTS.md](AGENTS.md) for Codex and other generic agents
- [scripts/memento-agent.sh](scripts/memento-agent.sh) for shared shell helpers

Recommended workflow:

```bash
source scripts/memento-agent.sh
memento_project_env
memento_session_start
```

This gives all agent runtimes the same project-local database:

```bash
export MEMENTO_DB="$PWD/.memento/project.db"
```

Suggested usage pattern:

1. Session start: `memento recall "项目概况" --format json`
2. On uncertainty: `memento recall "相关问题" --format json`
3. On completion of substantial work: `memento capture "总结" --type debugging --origin agent`

Wrapper helpers are provided for convenience:

```bash
claude_memento
gemini_memento
codex_memento
```

## 📖 Deep Dive

For a comprehensive dive into the data models, memory lifecycles, and federation protocols, please read the complete design document:

👉 [Engram：分布式记忆操作系统与协作协议](./Engram：分布式记忆操作系统与协作协议.md)

---
*Memento: Making AI agent memory alive, forgettable, and truly cumulative.*
