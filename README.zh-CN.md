# Memento

[English README](README.md)

**面向 AI Agent 的长期记忆引擎。**

Memento 是 **Engram** 架构的实现。它是一个分布式记忆操作系统与协作协议，目标是解决 AI Agent 与个人在跨会话、跨项目场景下的知识积累与检索问题。

## 🌟 核心理念

传统知识库（如 Notion、Obsidian）和向量数据库通常把记忆视为静态文件。Memento 则把记忆视为一种活体系统，并建立在三个基本原则之上：

1. **记忆是活的**：记忆不是档案，而是会随着使用不断变化的组织。长期不用会衰减，每次被召回都会强化。Memento 会自动降低过时信息的排序权重，并提升高频知识的权重，让检索结果的信噪比随使用持续改善。
2. **认知是可共享的**：人类文明本质上就是记忆的分叉与合并。Memento 支持认知层面的 Fork / PR / Merge 工作流，让记忆库（Vault）能够在联邦网络中安全共享、同步和演化。
3. **遗忘是特性**：无限记忆会导致决策瘫痪。选择性遗忘是智能系统的核心能力之一。

## 🏗️ 关键架构

Memento 试图从传统 CRUD 模式切换到“活记忆”模式：

- **活性记忆单元（Engram）**：系统中的核心单位，具备强度、衰减速率、情绪标记和关联网络等属性。
- **三种认知节律**：
  - *Awake Track*（毫秒级）：用于即时图检索、向量检索和记忆捕获。
  - *Subconscious Track*（分钟级）：用于后台元数据更新、Hebbian 强化与降噪。
  - *Sleep / Epoch Track*（天级）：用于重型整合、语义抽象和快照生成。
- **不可变快照 DAG**：Memento 使用类似 Git 的 Merkle DAG 跟踪认知修订历史，并通过 tombstone 机制实现可遗忘而不断链的存储压缩。
- **严格隐私与密码粉碎**：遗忘权直接内建在存储层。删除数据加密密钥（DEK）后，记忆、向量、摘要及相关元数据都可被数学意义上立即销毁。

## 🚀 v0.1 快速开始

Memento v0.1 当前以 CLI 工具形式提供，既可直接使用，也可以嵌入 Claude Code、Gemini CLI、Codex 等 AI Agent 的工作流中。

### 安装

```bash
# Clone the repository
git clone https://github.com/winteriscome/memento.git
cd memento

# Install as an editable package (requires Python 3.10+)
pip install -e .
```

### 配置

Memento 默认使用 Gemini 生成高质量语义向量；如果不可用，会回退到本地模型或 FTS5。先设置 API Key：

```bash
export GEMINI_API_KEY="your-gemini-api-key"
```

### 基本用法

```bash
# 初始化数据库（~/.memento/default.db）
memento init

# 写入一条记忆（Agent 自动写入建议带上 --origin agent）
memento capture "JWT authentication uses RS256, keys are in /config/keys/" --type fact --importance high

# 检索上下文（自动应用衰减与强化权重）
memento recall "auth" --format json

# 生成一套实验种子数据和标注查询集
memento seed-experiment --db eval_mode_a.db --queries-output examples/eval_queries.generated.json

# 一次性初始化 Mode A / Mode B 两份实验数据库
memento setup-experiment --db-a eval_mode_a.db --db-b eval_mode_b.db --queries-output examples/eval_queries.generated.json --manifest-output examples/experiment_manifest.generated.json

# 运行不带强化副作用的基线检索
memento recall "auth" --mode B --format json

# 对标注查询集执行只读评估
memento eval --queries eval_queries.json --mode A --format json

# 直接比较两份数据库快照
memento eval --queries eval_queries.json --db eval_mode_a.db --mode A --compare-db eval_mode_b.db --compare-mode B --format json

# 将完整评估报告保存到文件
memento eval --queries eval_queries.json --db eval_mode_a.db --mode A --compare-db eval_mode_b.db --compare-mode B --report-output reports/week2.json --format json

# 状态与导出
memento status
memento export --output team_memory.json
```

`memento recall --mode A` 是实验组排序器，公式为 `effective_strength × similarity`。
`memento recall --mode B` 是基线排序器，公式为 `similarity × recency_bonus`，且不会写入强化副作用。
`memento seed-experiment` 会生成一小套包含冷记忆、温记忆、高频记忆和过时记忆的标注数据，方便直接启动 v0.1 实验。
`memento setup-experiment` 会创建 A/B 数据库对、生成查询集，并写出推荐的 eval 命令清单。
`memento eval` 始终以只读方式运行，便于对隔离快照做对比评估。
可以使用 `--report-output` 将完整 JSON 评估报告保存下来，便于周中和周末留档。
查询集格式可参考 `examples/eval_queries.sample.json`。

如果你通过 AI Agent 使用 Memento，可参考 [CLAUDE.md](CLAUDE.md) 中的指令模板，自动化完成知识共建。

## Agent 自动化接入

Memento 最适合通过固定时机调用来接入 agent，而不是靠手工临时记忆管理。

仓库里建议配套使用这些文件：

- [CLAUDE.md](CLAUDE.md)：用于 Claude Code
- [GEMINI.md](GEMINI.md)：用于 Gemini CLI
- [AGENTS.md](AGENTS.md)：用于 Codex 和其他通用 agent
- [scripts/memento-agent.sh](scripts/memento-agent.sh)：统一 shell 辅助脚本

推荐启动方式：

```bash
source scripts/memento-agent.sh
memento_project_env
memento_session_start
```

这样所有 agent runtime 会共享同一个项目级数据库：

```bash
export MEMENTO_DB="$PWD/.memento/project.db"
```

推荐的固定节律：

1. 会话开始：`memento recall "项目概况" --format json`
2. 遇到不确定问题：`memento recall "相关问题" --format json`
3. 完成重要任务后：`memento capture "总结" --type debugging --origin agent`

为了方便，脚本中也提供了包装命令：

```bash
claude_memento
gemini_memento
codex_memento
```

## 📖 深入阅读

如果你想进一步了解数据模型、记忆生命周期和联邦协议，请阅读完整设计文档：

👉 [Engram：分布式记忆操作系统与协作协议](Engram：分布式记忆操作系统与协作协议.md)

---
*Memento：让 AI Agent 的记忆变得可生长、可遗忘、可持续积累。*