# Memento + Gemini CLI

[English Version](GEMINI.md)

本仓库通过 Memento 为 Gemini CLI 提供跨会话长期记忆能力。

## 会话启动

每次会话开始时，先执行：

```bash
memento recall "项目概况" --format json
```

如果当前任务涉及项目约定、架构设计或历史调试经验，再补一次有针对性的 recall：

```bash
memento recall "相关问题" --format json
```

## 工作规则

- 不确定时，先 recall，再做判断。
- 只 capture 能长期复用、能减少重复犯错的信息。
- 不要把普通闲聊内容写入记忆。
- Gemini 产出的总结，使用 `--origin agent`。

## Capture 示例

```bash
memento capture "修复 Redis 泄漏需要在 finally 关闭连接池" --type debugging --origin agent
memento capture "该项目使用 snake_case 命名" --type convention --origin agent
memento capture "用户要求 README 同步维护中文版本" --type preference --importance critical
```

## 判断标准

写入前先问自己一个问题：

如果丢掉这条信息，下次是否大概率还会重复犯错、重复分析？

如果答案是“会”，就 capture。

## 推荐 Shell 工作流

建议使用仓库内的辅助脚本：

```bash
source scripts/memento-agent.sh
memento_project_env
memento_session_start
```