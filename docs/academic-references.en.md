# Academic Research References for Engram/Memento

This document maps frontier academic research to the Memento system design across six dimensions.

---

## 1. Memory Decay & Reinforcement — Core Mechanism

Memento's `effective_strength = strength × 0.5^(hours / half_life)` and spaced reinforcement directly correspond to:

### 1.1 FSRS (Free Spaced Repetition Scheduler)

- **Authors**: Jarrett Ye et al.
- **Venue**: KDD 2022
- **Contribution**: DSR (Difficulty-Stability-Retrievability) model, framing spaced repetition as a stochastic shortest-path problem (MDP)
- **Mapping**: `reinforcement_boost` interval effects are equivalent to FSRS's stability growth function. FSRS v6 is integrated into Anki with large-scale validation data, reducing review count by 20-30% vs SM-2
- **Actionable**: The current half-life decay formula can be replaced with FSRS's parameterized model for more precise individualized decay rates

### 1.2 MemoryBank

- **Authors**: Zhong et al.
- **Venue**: AAAI 2024
- **Contribution**: First work to explicitly apply the Ebbinghaus forgetting curve to LLM memory. Decay by time + reinforcement by relative importance
- **Mapping**: Nearly isomorphic to Memento's design; `importance_factor` corresponds to their relative significance weight

### 1.3 ARM: Adaptive RAG Memory

- **Venue**: arXiv 2025
- **Contribution**: Replaces RAG's static vector index with a dynamic memory substrate. High-frequency items are consolidated; low-frequency items decay
- **Mapping**: Explicitly cites Ebbinghaus and Atkinson-Shiffrin dual-store theory; highly consistent with `recall` read-as-reinforcement design

### 1.4 Human-like Forgetting Curves in Deep Neural Networks

- **Venue**: arXiv 2025
- **Contribution**: Demonstrates that MLPs exhibit human-like forgetting curves; knowledge becomes increasingly stable through periodic review
- **Mapping**: Provides neural-network-level theoretical support for the "decay + reinforcement > pure vector search" hypothesis

### 1.5 CVPR 2025 "Respacing"

- **Venue**: CVPR 2025
- **Contribution**: Applies Ebbinghaus theory to continual learning; finds that moderate forgetting actually protects long-term memory
- **Mapping**: Perfectly aligns with the "forgetting is a feature, not a bug" philosophy

---

## 2. Agent Memory Architecture — Primary Use Case

### 2.1 Generative Agents

- **Authors**: Park et al.
- **Venue**: UIST 2023
- **Contribution**: Memory stream architecture with recency × importance × relevance tri-factor retrieval
- **Mapping**: `effective_strength × similarity` ranking is a decay-enhanced version of this approach

### 2.2 MemGPT → Letta

- **Authors**: Packer et al.
- **Venue**: NeurIPS 2023
- **Contribution**: Virtual context management inspired by OS memory hierarchy (RAM vs disk). Letta V1 introduces "context compilation"—agents autonomously edit memory blocks
- **Mapping**: STM/LTM dual-layer + Epoch consolidation parallels MemGPT's paging mechanism

### 2.3 A-Mem

- **Authors**: Xu et al.
- **Venue**: NeurIPS 2025
- **Contribution**: Agents self-organize memory using Zettelkasten-style dynamic indexing and linking; 192% improvement over MemGPT
- **Mapping**: Nexus associative network aligns with interconnected knowledge nodes

### 2.4 Mem0

- **Authors**: Chhikara et al.
- **Venue**: ECAI 2025
- **Contribution**: Production-grade agent memory: dynamic extraction, consolidation, retrieval + graph memory variant. 26% improvement over OpenAI memory, 91% latency reduction
- **Mapping**: Closest positioning to Memento, but Memento adds decay as a key differentiator

### 2.5 EM-LLM

- **Authors**: Fountas et al.
- **Venue**: ICLR 2025
- **Contribution**: Integrates human episodic memory and event cognition into LLMs using Bayesian surprise for event segmentation; retrieval across 10M tokens
- **Mapping**: Related to episodic → semantic abstraction pathway

### 2.6 Focus: Active Context Compression

- **Author**: Verma
- **Venue**: arXiv 2026
- **Contribution**: Agent autonomously decides when to compress learnings into persistent "knowledge chunks" and prune interaction history; 22.7% token reduction with no accuracy loss
- **Mapping**: Consistent with Epoch abstraction goals

---

## 3. Cognitive Architecture — Theoretical Foundation

### 3.1 CoALA: Cognitive Architectures for Language Agents

- **Authors**: Sumers et al.
- **Venue**: TMLR 2024
- **Contribution**: The most important theoretical framework—departing from ACT-R/Soar cognitive science to propose modular agent architecture. Defines working memory, episodic memory, semantic memory, and procedural memory modules. LLMs replace hand-crafted production rules
- **Mapping**: Engram type system (episodic/semantic/procedural) directly corresponds to CoALA categories

### 3.2 Soar + LLM Series

- **Authors**: Wray, Kirk, Laird (University of Michigan)
- **Venue**: AGI 2025 / Cognitive Systems Research 2025
- **Contribution**: Migrates Soar cognitive design patterns to general LLM agents; proposes "LLM-Modulo" systems where LLMs complement rather than replace cognitive architecture mechanisms

### 3.3 Brain-Inspired Agentic Architecture

- **Venue**: Nature Communications 2025
- **Contribution**: Explicitly departs from cognitive architecture tradition, using pretrained language models to replace symbolic program components

---

## 4. Memory Reconsolidation Models — Layer A/B Mechanism

### 4.1 Complementary Learning Systems (CLS)

- **Authors**: Sun et al.
- **Venue**: Nature Neuroscience 2023
- **Contribution**: Hippocampus as Hebbian learning notebook (fast encoding), cortex as student network (slow consolidation). Consolidation optimizes future generalization, not simple retention
- **Mapping**: STM(hippocampus) → Epoch consolidation → LTM(cortex) pipeline is an engineering implementation of this theory

### 4.2 Engram Neural Network (ENN)

- **Author**: Szelogowski
- **Venue**: arXiv 2025
- **Contribution**: Named after engrams; uses differentiable memory matrices + Hebbian plasticity + sparse attention retrieval. Operationalizes neuroscience engram formation and reactivation as trainable deep learning
- **Mapping**: Nexus Hebbian learning (co-activated memories strengthen each other) directly corresponds to ENN's Hebbian trace

### 4.3 Memory Consolidation from RL Perspective

- **Authors**: Lee & Jung
- **Venue**: Frontiers 2025
- **Contribution**: Models hippocampal replay as Dyna-style offline learning; value-based selection determines which memories get replayed and consolidated
- **Mapping**: Epoch batch consolidation is essentially an offline replay process

### 4.4 Synaptic Scaling as Destabilization

- **Authors**: Amorim et al.
- **Venue**: Learning & Memory 2021
- **Contribution**: Computational model showing synaptic scaling as a destabilization mechanism during reconsolidation. Brief re-exposure → memory update (Layer B); prolonged exposure → extinction
- **Mapping**: `rigidity` parameter controlling reconsolidation depth analogizes this model's protein synthesis blockade experiments

---

## 5. Federated Knowledge Sharing — v0.5/v1.0 Roadmap

### 5.1 FedR

- **Authors**: Zhang et al.
- **Venue**: arXiv 2022-2023
- **Contribution**: Aggregates only relation embeddings (not entities) using Private Set Union + Secure Aggregation. Privacy leakage drops to zero; communication costs reduced by two orders of magnitude
- **Mapping**: Export Projection + topological noise approach is more aggressive but directionally aligned

### 5.2 DP-Flames

- **Authors**: Hu et al.
- **Venue**: 2023
- **Contribution**: Gradient-level differential privacy + adaptive privacy budget. Attack success rate drops from 83.1% to 59.4%
- **Mapping**: Reference defense baseline

### 5.3 FPKS

- **Venue**: ACM Transactions 2025
- **Contribution**: Privacy-preserving personal knowledge sharing designed for IoT environments
- **Mapping**: Highly relevant to "personal Vault with limited sharing" scenario

---

## 6. Protocols & Standards — Agent Infrastructure Stack

### 6.1 MCP (Model Context Protocol)

- **Publisher**: Anthropic
- **Year**: 2024
- **Contribution**: Open standard for Agent-to-Tool communication, adopted by OpenAI/Google/Microsoft
- **Mapping**: v0.5 plans MCP Server support, directly leveraging this ecosystem

### 6.2 A2A (Agent2Agent Protocol)

- **Publisher**: Google
- **Year**: 2025
- **Contribution**: Agent-to-Agent communication protocol based on JSON-RPC 2.0 + HTTP(S). Agents are opaque to each other (no shared internal memory/logic); supports long tasks and streaming
- **Mapping**: EFP federation protocol can reference A2A's design philosophy, but A2A does not handle memory semantics

### 6.3 MCP + A2A + Engram: The Complete Stack

| Protocol Layer | Problem Solved | Standard |
|----------------|---------------|----------|
| **Tool Access** | How agents access tools and data | MCP |
| **Agent Communication** | How agents collaborate | A2A |
| **Memory Persistence** | How agents manage and share persistent memory | **Engram (this project)** |

---

## Key Insight: Memento's Differentiated Position

From the full research landscape, Memento is uniquely positioned at three intersection points:

1. **Decay as First-Class Citizen** — Mem0, MemGPT, and A-Mem have no decay mechanism; MemoryBank has decay but no federated sharing
2. **Memory Protocol Layer** — MCP solves tool invocation, A2A solves agent communication; no one is building a standard protocol for memory sharing
3. **Cognitive Science Rigor** — Most agent memory systems are engineering-driven; Memento's design explicitly aligns with CLS theory, Hebbian learning, and dual-layer reconsolidation models

---

*Last updated: 2026-03-27*
