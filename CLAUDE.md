# ═══ Memento 长期记忆 — Agent 指令模板 ═══

## 概述

本项目使用 Memento 管理跨会话记忆。Memento 是一个基于衰减+强化机制的 AI Agent 长期记忆引擎。

## 会话开始时

运行以下命令获取项目背景知识：

```bash
memento recall "项目概况" --format json
```

## 工作期间

### 何时查询记忆

- 遇到不确定的项目约定 → `memento recall "相关问题" --format json`
- 需要回忆之前的架构决策 → `memento recall "相关话题" --format json`

### 何时写入记忆

- 用户说"记住/总是/不要再/每次" → `memento capture "内容" --type preference --importance critical`
  （用户明确指示的内容不加 `--origin agent`，默认为 human，可信度最高）
- 解决了复杂 bug → `memento capture "过程和解法" --type debugging --origin agent`
- 做了架构决策 → `memento capture "决策及原因" --type decision --origin agent`
- 发现项目约定 → `memento capture "约定内容" --type convention --origin agent`
- 发现了有价值的事实 → `memento capture "事实" --type fact --origin agent`

### 判断原则

> 删掉这条记忆，下次会犯同样的错误吗？是 → capture，否 → 不 capture。

## 重要：Agent 写入的记忆限制

Agent 通过 `--origin agent` 写入的记忆有 strength 上限（0.5）。
这防止 Agent 幻觉通过反复 recall 自我强化成"坚不可摧的假记忆"。
用户可以通过 `memento verify <id>` 来确认 Agent 记忆为可信并解除限制。

## 可用命令速查

```bash
memento capture <content> [--type TYPE] [--importance IMPORTANCE] [--tags "a,b"] [--origin human|agent]
memento recall <query> [--max 5] [--format json|text]
memento verify <id>
memento forget <id>
memento status
memento export [--output file.json]
memento import <file.json> [--source "来源名"]
```
