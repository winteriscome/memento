# Memento

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

# Status & Sync
memento status
memento export --output team_memory.json
```

For AI Agents, refer to the [CLAUDE.md](./CLAUDE.md) instruction template to automate knowledge co-building.

## 📖 Deep Dive

For a comprehensive dive into the data models, memory lifecycles, and federation protocols, please read the complete design document:

👉 [Engram：分布式记忆操作系统与协作协议](./Engram：分布式记忆操作系统与协作协议.md)

---
*Memento: Making AI agent memory alive, forgettable, and truly cumulative.*
