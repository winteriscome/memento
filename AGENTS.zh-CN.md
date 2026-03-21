# Memento Agent 指南

[English Version](AGENTS.md)

本仓库使用 Memento 作为共享长期记忆层，适用于 Codex、Copilot Chat 以及其他通用 CLI Agent。

## 会话开始

在开始较大任务前，先加载项目背景：

```bash
memento recall "项目概况" --format json
```

## 工作过程中

以下场景优先使用 recall：

- 不确定项目约定时
- 需要回忆历史架构决策时
- 需要确认某个 bug 或权衡是否已经记录过时

常用查询模式：

```bash
memento recall "相关问题" --format json
memento recall "架构决策" --format json
memento recall "调试经验" --format json
```

## 什么时候 capture

只有在这些信息能显著减少未来重复犯错时，才写入 Memento。

- 用户明确偏好：

```bash
memento capture "内容" --type preference --importance critical
```

- 复杂 bug 的解决过程：

```bash
memento capture "过程和解法" --type debugging --origin agent
```

- 架构决策：

```bash
memento capture "决策及原因" --type decision --origin agent
```

- 稳定项目约定：

```bash
memento capture "约定内容" --type convention --origin agent
```

- 可长期复用的事实：

```bash
memento capture "事实" --type fact --origin agent
```

## 可信度规则

- 不要把 agent 生成的信息写成 human 记忆。
- agent 的总结使用 `--origin agent`。
- 用户直接给出的信息保留为 human 来源。
- 未验证的 agent 记忆在显式 verify 前，强度上限为 0.5。

## 实用判断标准

如果删除这条记忆后，下次很可能会再次犯同样错误，就应该 capture。

## 常用命令

```bash
memento recall <query> [--max 5] [--mode A|B] [--format json|text]
memento capture <content> [--type TYPE] [--importance IMPORTANCE] [--tags "a,b"] [--origin human|agent]
memento verify <id>
memento status
```