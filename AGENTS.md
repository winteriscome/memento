# Memento Agent Instructions

[中文说明](AGENTS.zh-CN.md)

This repository uses Memento as the shared long-term memory layer for agent runtimes such as Codex, Copilot Chat, and other CLI agents.

## Session Start

Before starting substantial work in this repository, load the project context:

```bash
memento recall "项目概况" --format json
```

## During Work

Use recall when:

- You are unsure about project conventions.
- You need to recover prior architectural decisions.
- You need to check whether a bug or tradeoff has been documented before.

Useful patterns:

```bash
memento recall "相关问题" --format json
memento recall "架构决策" --format json
memento recall "调试经验" --format json
```

## When To Capture

Write to Memento only when the information is likely to prevent repeated mistakes later.

- User explicit preferences:

```bash
memento capture "内容" --type preference --importance critical
```

- Complex bug resolution:

```bash
memento capture "过程和解法" --type debugging --origin agent
```

- Architecture decisions:

```bash
memento capture "决策及原因" --type decision --origin agent
```

- Stable project conventions:

```bash
memento capture "约定内容" --type convention --origin agent
```

- Durable facts:

```bash
memento capture "事实" --type fact --origin agent
```

## Trust Model

- Do not write agent-generated memories as human memories.
- Use `--origin agent` for agent summaries.
- User-supplied statements should remain human-origin memories.
- Unverified agent memories are capped at strength 0.5 until explicitly verified.

## Practical Rule

If deleting the memory would likely cause the same mistake to happen again, capture it.

## Useful Commands

```bash
memento recall <query> [--max 5] [--mode A|B] [--format json|text]
memento capture <content> [--type TYPE] [--importance IMPORTANCE] [--tags "a,b"] [--origin human|agent]
memento verify <id>
memento status
```