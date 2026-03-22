# Memento Agent Instructions

[中文说明](AGENTS.zh-CN.md)

This repository uses Memento as the shared long-term memory layer for agent runtimes such as Codex, Copilot Chat, and other CLI agents.

**You MUST call memento commands in the terminal to read and write memories. This is mandatory, not optional.**

## Mandatory Rules

### 1. Session Start: MUST Load Memories

**Before starting any substantial work, you MUST immediately run:**

```bash
memento recall "项目概况" --format json
```

If no results are returned, this is a new project — proceed normally.

### 2. During Work: MUST Query Before Guessing

When encountering these situations, **MUST recall first, do not guess**:

- Unsure about project conventions → `memento recall "relevant topic" --format json`
- Need prior architectural decisions → `memento recall "architecture" --format json`
- Encountering a bug or anomaly → `memento recall "related error" --format json`

### 3. After Work: MUST Capture Valuable Knowledge

When these events occur, **MUST capture immediately** — do not wait for user to ask:

| Event | Command |
|-------|--------|
| User says "remember/always/never/every time" | `memento capture "content" --type preference --importance critical` |
| Resolved a complex bug | `memento capture "problem and solution (<200 chars)" --type debugging --origin agent` |
| Made an architecture decision | `memento capture "decision and rationale (<200 chars)" --type decision --origin agent` |
| Discovered a project convention | `memento capture "convention" --type convention --origin agent` |
| Found a valuable technical fact | `memento capture "fact" --type fact --origin agent` |

**Principle**: Would deleting this memory cause the same mistake again? **Yes → MUST capture. No → skip.**

**Important**: User-dictated content ("remember XX") must NOT include `--origin agent` — defaults to human, highest trust. Agent-generated summaries MUST include `--origin agent`.

## Trust Model

- Agent memories (`--origin agent`) are capped at strength 0.5 until verified.
- User can run `memento verify <id>` to unlock the cap.
- Never write agent-generated content as human-origin memories.

## Commands

```bash
memento capture <content> [--type TYPE] [--importance IMPORTANCE] [--tags "a,b"] [--origin human|agent]
memento recall <query> [--max 5] [--format json|text]
memento verify <id>
memento forget <id>
memento status
```