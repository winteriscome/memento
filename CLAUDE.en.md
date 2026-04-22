# Memento Long-Term Memory — Agent Instruction Template

[中文版本](CLAUDE.md)

## Overview

This project uses Memento to manage cross-session memory. Memento is a long-term memory engine for AI agents based on decay and reinforcement.

## At Session Start

Run the following command to load project context:

```bash
memento recall "项目概况" --format json
```

## During Work

### When To Recall

- If you are unsure about project conventions → `memento recall "相关问题" --format json`
- If you need to recover prior architectural decisions → `memento recall "相关话题" --format json`

### When To Capture

- If the user says “remember / always / don’t forget / every time” → `memento capture “content” --type preference --importance critical`
  User-supplied facts should not use `--origin agent`; they remain human-origin and highest trust.
- If you solved a complex bug → `memento capture “problem and solution” --type debugging --origin agent`
- If you made an architecture decision → `memento capture “decision and rationale” --type decision --origin agent`
- If you discovered a stable project convention → `memento capture “convention” --type convention --origin agent`
- If you discovered a durable fact worth keeping → `memento capture “fact” --type fact --origin agent`

**Note:**
- `capture` writes to L2 buffer, will be consolidated in next epoch run.
- Newly captured memories may appear in `recall` results as provisional (marked `provisional: true`).

### Decision Rule

> If deleting this memory would likely cause the same mistake again later, capture it. Otherwise, do not.

## Important Behavioral Changes (v0.5)

### capture is asynchronous
`memento capture` writes to L2 buffer, not immediately consolidated into long-term memory. Consolidation happens on next `memento epoch run`.

### recall may return provisional results
Newly captured memories may appear in recall results with `provisional: true` status until consolidated.

### forget is mark-for-deletion
`memento forget <id>` marks for deletion. Actual cleanup happens during next epoch consolidation.

### Agent-Written Memory Limits
Memories written with `--origin agent` have a strength cap of 0.5 until a human verifies them.
This prevents agent hallucinations from becoming “indestructible false memories” through repeated recall.
Users can run `memento verify <id>` to mark an agent memory as trustworthy and lift the cap.

## Useful Command Reference

### Core Commands

```bash
# Capture memory (L2 buffer, asynchronous)
memento capture <content> [--type TYPE] [--importance IMPORTANCE] [--tags "a,b"] [--origin human|agent]

# Recall memory (may include provisional results)
memento recall <query> [--max 5] [--format json|text]

# Mark for deletion (takes effect on next epoch)
memento forget <id>

# Verify agent memory (lift strength cap)
memento verify <id>

# Show status
memento status
```

### Epoch Management

```bash
# Trigger consolidation (L2 → L1, execute forgetting/deletion)
memento epoch run [--mode full|light]

# View epoch history
memento epoch status

# View pending cognitive debt
memento epoch debt
```

### Advanced Commands

```bash
# Inspect engram details (nexus + rigidity)
memento inspect <id>

# View connections
memento nexus <id> [--depth 1|2]

# Set rigidity (prevent forgetting)
memento pin <id> --rigidity <value>

# Import/export
memento export [--output file.json]
memento import <file.json> [--source "source name"]
```