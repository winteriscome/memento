# Memento + Gemini CLI

[中文说明](GEMINI.zh-CN.md)

This repository integrates Gemini CLI with Memento for cross-session memory.

## Startup Routine

At the beginning of a session, run:

```bash
memento recall "项目概况" --format json
```

If the current task is about conventions, architecture, or prior debugging work, also run a focused recall:

```bash
memento recall "相关问题" --format json
```

## Working Rules

- Prefer recall before guessing.
- Prefer capture only for durable, reusable knowledge.
- Do not capture ordinary conversational filler.
- Use `--origin agent` for Gemini-generated summaries.

## Capture Examples

```bash
memento capture "修复 Redis 泄漏需要在 finally 关闭连接池" --type debugging --origin agent
memento capture "该项目使用 snake_case 命名" --type convention --origin agent
memento capture "用户要求 README 同步维护中文版本" --type preference --importance critical
```

## Decision Filter

Ask one question before writing memory:

Would losing this note likely cause the same mistake or repeated analysis later?

If yes, capture it.

## Suggested Shell Workflow

Use the helper script in `scripts/memento-agent.sh`:

```bash
source scripts/memento-agent.sh
memento_project_env
memento_session_start
```