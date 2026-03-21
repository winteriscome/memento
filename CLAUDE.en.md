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

- If the user says “remember / always / don’t forget / every time” → `memento capture "内容" --type preference --importance critical`
  User-supplied facts should not use `--origin agent`; they remain human-origin and highest trust.
- If you solved a complex bug → `memento capture "过程和解法" --type debugging --origin agent`
- If you made an architecture decision → `memento capture "决策及原因" --type decision --origin agent`
- If you discovered a stable project convention → `memento capture "约定内容" --type convention --origin agent`
- If you discovered a durable fact worth keeping → `memento capture "事实" --type fact --origin agent`

### Decision Rule

> If deleting this memory would likely cause the same mistake again later, capture it. Otherwise, do not.

## Important: Agent-Written Memory Limits

Memories written with `--origin agent` have a strength cap of 0.5 until a human verifies them.
This prevents agent hallucinations from becoming “indestructible false memories” through repeated recall.
Users can run `memento verify <id>` to mark an agent memory as trustworthy and lift the cap.

## Useful Command Reference

```bash
memento capture <content> [--type TYPE] [--importance IMPORTANCE] [--tags "a,b"] [--origin human|agent]
memento recall <query> [--max 5] [--mode A|B] [--format json|text]
memento seed-experiment [--db file.db] [--queries-output file.json] [--format json|text]
memento setup-experiment [--db-a file.db] [--db-b file.db] [--queries-output file.json] [--manifest-output file.json] [--force] [--format json|text]
memento eval --queries <file.json> [--mode A|B] [--compare-db other.db] [--compare-mode A|B] [--report-output file.json] [--format json|text]
memento verify <id>
memento forget <id>
memento status
memento export [--output file.json]
memento import <file.json> [--source "来源名"]
```