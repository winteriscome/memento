# ═══ Memento 长期记忆 — Agent 指令模板 ═══

[English Version](CLAUDE.en.md)

## 概述

本项目使用 Memento 管理跨会话记忆。系统通过 Stop hook 自动从对话中提取有价值的记忆（v0.9），你不需要主动 capture 大部分内容。

## 自动记忆提取（v0.9）

Memento 会在每次你回复后自动分析对话，提取用户偏好、项目约定、架构决策和重要事实。你**不需要**为以下内容手动 capture：

- 对话中自然产生的决策和结论
- 用户表达的偏好和习惯
- 项目约定和规范
- 重要的技术事实

系统会自动处理，写入 L2 缓冲区，经 epoch 整合为长期记忆。

## 自动 Priming（v0.9）

SessionStart hook 会自动从 Memento 检索最相关的记忆（convention、preference、decision 等），并注入对话上下文。你会在会话开头看到 `# $CMEM memento ...` 块，这些就是自动注入的 priming 记忆。

**你不需要在开局手动 recall。** 如果 priming 块存在，说明记忆已经生效。

## 你仍需手动做的事

### 1. Priming 不足时：补充 recall（fallback）

如果会话开头没有 `# $CMEM memento` 块，或者 priming 内容不足以覆盖当前任务，手动 recall：

```bash
memento recall "相关主题" --format json
```

### 2. 工作中：不确定时先查询

遇到以下情况时，**先 recall 再行动**：

- 不确定项目约定 → `memento recall "相关问题" --format json`
- 需要回忆架构决策 → `memento recall "架构决策" --format json`
- 遇到 bug 或异常 → `memento recall "相关错误" --format json`

### 3. 用户明确要求记住时：手动 capture

只在用户明确说"记住/总是/不要再/每次"时，才需要手动 capture：

```bash
memento capture "内容" --type preference --importance critical
```

**注意**：用户明确指示的内容不加 `--origin agent`，默认为 human，可信度最高。

## 不要 capture 的内容

系统自动提取已经覆盖了高价值信息。你**不应**手动 capture：

- 调试过程和修复细节（git log 里有）
- 代码结构和文件路径（可从 codebase 推导）
- 临时任务状态和进度
- 一次性操作记录
- CLAUDE.md 中已有的内容

## 关键行为

### capture 是异步的
`memento capture` 写入 L2 缓冲区，下次 `memento epoch run` 时才整合到长期记忆。

### recall 可能返回临时结果
新写入的记忆在整合前可能以 `provisional: true` 状态出现。

### forget 是标记删除
`memento forget <id>` 仅标记为待删除，下次 epoch 整合时才真正清理。

### Agent 记忆的信任限制
Agent 写入的记忆（包括自动提取的）strength 上限为 0.5。用户可通过 `memento verify <id>` 解除限制。

## 命令速查

```bash
# 检索记忆
memento recall <query> [--max 5] [--format json|text]

# 手动写入（仅用户明确要求时）
memento capture <content> [--type TYPE] [--importance IMPORTANCE] [--tags "a,b"]

# 标记删除
memento forget <id>

# 验证 agent 记忆
memento verify <id>

# 查看状态
memento status

# Epoch 管理
memento epoch run [--mode full|light]
memento epoch status
memento epoch debt

# 高级命令
memento inspect <id>
memento pin <id> --rigidity <value>
```
