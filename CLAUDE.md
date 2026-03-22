# ═══ Memento 长期记忆 — Agent 指令模板 ═══

[English Version](CLAUDE.en.md)

## 概述

本项目使用 Memento 管理跨会话记忆。**你必须在终端调用 memento 命令来读写记忆，这是强制行为，不是可选建议。**

## 强制规则（MUST）

### 1. 会话开始：必须加载记忆

**每次会话开始实质性工作前，你必须立即在终端运行：**

```bash
memento recall "项目概况" --format json
```

如果返回结果为空，说明是新项目，继续工作即可。如果有结果，将其作为项目背景上下文。

### 2. 工作中：必须查询记忆

遇到以下情况时，**必须先 recall 再行动**，不要凭猜测回答：

- 不确定项目约定 → `memento recall "相关问题" --format json`
- 需要回忆架构决策 → `memento recall "架构决策" --format json`
- 遇到 bug 或异常 → `memento recall "相关错误" --format json`

### 3. 完成工作后：必须写入有价值的记忆

在以下场景发生时，**必须立即执行 capture**，不要等用户要求：

| 场景 | 命令 |
|------|------|
| 用户说"记住/总是/不要再/每次" | `memento capture "内容" --type preference --importance critical` |
| 解决了复杂 bug | `memento capture "问题描述和解法（<200字）" --type debugging --origin agent` |
| 做了架构决策 | `memento capture "决策及原因（<200字）" --type decision --origin agent` |
| 发现项目约定或模式 | `memento capture "约定内容" --type convention --origin agent` |
| 发现有价值的技术事实 | `memento capture "事实" --type fact --origin agent` |

**判断原则**：删掉这条记忆，下次会犯同样的错误吗？**是 → 必须 capture。否 → 不 capture。**

**注意**：用户明确指示的内容（"记住XX"）不加 `--origin agent`，默认为 human，可信度最高。Agent 自主总结的内容必须加 `--origin agent`。

### 4. capture 内容规范

- 内容精炼，控制在 200 字以内
- 包含足够上下文使未来检索有意义
- 使用 `--tags` 标记关键词以提高检索命中率
- 不要 capture 临时性、一次性的信息

## Agent 记忆的信任限制

Agent 通过 `--origin agent` 写入的记忆 strength 上限为 0.5。
这防止 Agent 幻觉通过反复 recall 自我强化。
用户可通过 `memento verify <id>` 确认后解除限制。

## 命令速查

```bash
memento capture <content> [--type TYPE] [--importance IMPORTANCE] [--tags "a,b"] [--origin human|agent]
memento recall <query> [--max 5] [--format json|text]
memento verify <id>
memento forget <id>
memento status
memento export [--output file.json]
memento import <file.json> [--source "来源名"]
```
