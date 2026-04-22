# Documentation Guide

This file defines the current documentation source-of-truth for the Memento repository.

## Source of Truth

When multiple documents disagree, use the following precedence:

1. **Current implementation in `src/memento/` and tests in `tests/`**
2. **Current architecture/specification docs**
3. **Current roadmap**
4. **Historical plans and implementation notes**

## Current Canonical Documents

### System-level architecture and version semantics

- `../Engram：分布式记忆操作系统与协作协议.md`
  - The main architecture document.
  - Canonical for milestone semantics such as `v0.6.0`, `v0.6.1`, `v0.7.0`.
  - Canonical for high-level session / memory / epoch model.

### Current roadmap

- `superpowers/plans/2026-04-02-v06-v07-roadmap.md`
  - Canonical for near-term sequencing and milestone priority.
  - Should stay aligned with the Engram main document.

### Current detailed design references

- `superpowers/specs/2026-04-01-session-lifecycle-design.md`
  - Canonical reference for `session_start`, `session_end`, session summaries, observations, and session event semantics.

- `superpowers/specs/2026-04-01-v03-runtime-integration-design.md`
  - Canonical reference for Worker / MCP runtime integration behavior and response shape.

- `superpowers/specs/2026-04-01-v051a-infrastructure-hardening-design.md`
  - Canonical reference for WorkerClientAPI transport details and dataclass response shaping.

## Historical Plans

The following documents are valuable implementation history, but they are **not the final source of truth** if they conflict with the current implementation or the canonical docs above.

- `superpowers/plans/2026-04-01-v03-runtime-integration.md`
- `superpowers/plans/2026-04-01-v051a-infrastructure-hardening.md`
- `superpowers/plans/2026-04-02-v060-agent-perception.md`
- `superpowers/plans/2026-04-02-v061-ingestion-safety-net.md`
- `superpowers/plans/2026-04-02-v070-llm-epoch.md`

Use these documents for:

- implementation rationale
- task breakdown history
- test planning history
- understanding why a design changed

Do **not** use them as the sole source for current milestone status.

## Reading Guide by Task

### I want to understand the current version roadmap

Read in this order:

1. `../Engram：分布式记忆操作系统与协作协议.md`
2. `superpowers/plans/2026-04-02-v06-v07-roadmap.md`

### I want to understand current `session_end` behavior

Read in this order:

1. `superpowers/specs/2026-04-01-session-lifecycle-design.md`
2. `superpowers/specs/2026-04-01-v03-runtime-integration-design.md`
3. `src/memento/api.py`
4. `src/memento/session.py`
5. `src/memento/mcp_server.py`

### I want to understand v0.6.1 ingestion safety net details

Read in this order:

1. `../Engram：分布式记忆操作系统与协作协议.md` (current semantic placement)
2. `superpowers/plans/2026-04-02-v06-v07-roadmap.md`
3. `superpowers/plans/2026-04-02-v061-ingestion-safety-net.md` (historical implementation plan)
4. `src/memento/api.py`
5. `tests/test_session.py`
6. `tests/test_mcp_server.py`

### I want to understand planned v0.7.0 LLM Epoch work

Read in this order:

1. `../Engram：分布式记忆操作系统与协作协议.md`
2. `superpowers/plans/2026-04-02-v06-v07-roadmap.md`
3. `superpowers/plans/2026-04-02-v070-llm-epoch.md`

## Consistency Rules

### Rule 1: Milestone status

If milestone status differs between files:

- prefer `Engram：分布式记忆操作系统与协作协议.md`
- then confirm with `superpowers/plans/2026-04-02-v06-v07-roadmap.md`
- then confirm against code/tests

### Rule 2: API / runtime behavior

If API behavior differs between docs:

- prefer the current implementation in `src/memento/`
- then align the relevant spec doc
- historical plan docs should be treated as snapshots, not live contracts

### Rule 3: `session_end` semantics

Current expected semantics are:

- `summary` is first stored in `sessions.summary`
- it does **not** directly become an `engram`
- in current implementation, it may trigger a low-trust fallback capture when explicit capture/observation is insufficient
- awake-mode capture writes to `capture_log` and does **not** append `session_events.capture`

### Rule 4: Version naming

Current repo-wide interpretation:

- `v0.6.0` = retrieval fix + agent perception
- `v0.6.1` = ingestion safety net / auto-summary fallback
- `v0.7.0` = LLM Epoch structuring and reconsolidation

Any document that says otherwise should be updated or treated as historical.
