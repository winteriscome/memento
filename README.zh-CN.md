# Memento

[![Version](https://img.shields.io/badge/version-0.9.1-blue.svg)](pyproject.toml)
[![Python](https://img.shields.io/badge/python-≥3.10-blue.svg)](https://www.python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](pyproject.toml)

[English](README.md)

> 面向 AI Agent 的长期记忆引擎 — 让 AI 跨会话积累知识、自动衰减过时信息、选择性遗忘噪声。

Memento 是 [Engram 架构](Engram：分布式记忆操作系统与协作协议.md) 的实现：一个分布式记忆操作系统与协作协议，解决 AI Agent 在跨会话、跨项目场景下的知识积累与检索问题。

---

## 目录

- [特性](#特性)
- [快速开始](#快速开始)
- [核心概念](#核心概念)
- [命令参考](#命令参考)
- [配置](#配置)
- [Web Dashboard](#web-dashboard)
- [Agent 接入](#agent-接入)
- [架构](#架构)
- [项目结构](#项目结构)
- [参与贡献](#参与贡献)
- [许可证](#许可证)

---

## 特性

- **活性记忆** — 记忆会衰减、会强化，不是静态存档。长期不用自动降权，频繁召回自动增强。
- **自动提取** — Stop hook 自动从 AI 对话中提取决策、偏好、约定，无需手动操作。
- **语义检索** — 基于向量 + 图 + 全文三路召回，支持多种 Embedding 提供商。
- **Epoch 整合** — 类似睡眠整合，LLM 驱动的记忆结构化、再巩固和抽象化。
- **Claude Code 深度集成** — 通过 hooks + MCP Server 实现自动记忆提取与召回。
- **OpenCode 原生插件** — JavaScript 原生插件，支持生命周期钩子、自动注入和工具观察。
- **本地优先** — 数据存储在本地 SQLite，Dashboard 仅监听 `127.0.0.1`。
- **密码粉碎** — 删除加密密钥即可数学意义上销毁记忆，内建遗忘权。

---

## 快速开始

### 环境要求

- Python ≥ 3.10
- pip
- Git（用于从仓库安装）

### 安装

```bash
pip install git+ssh://git@github.com:winteriscome/memento.git
```

### 初始化

```bash
memento setup
```

交互式向导会引导你完成数据库初始化、Embedding 提供商选择、LLM 配置和 Claude Code 集成。

### 验证

```bash
memento doctor         # 检查配置
memento doctor --ping  # 验证 API 连通性
```

### 试一试

```bash
# 写入一条记忆
memento capture "项目使用 Python 3.11 + SQLite" --type fact

# 检索记忆
memento recall "技术栈"

# 查看系统状态
memento status
```

完成以上步骤后，Memento 已就绪。如果你通过 Claude Code 使用，它会在后台自动工作 — 无需手动操作。

---

## 核心概念

### 记忆生命周期

```
capture / 自动提取 → L2 缓冲区 → epoch run → 正式记忆（Engram）
                                                  ↓
                                          衰减 / 强化 / 遗忘
```

1. 记忆写入 L2 缓冲区（即时，临时状态）
2. `epoch run` 将缓冲记忆整合为正式 Engram（可由 hook 自动触发）
3. 正式记忆持续参与衰减和强化循环

### 记忆类型

通过 `--type` 指定，影响检索权重和整合策略：

| 类型 | 用途 | 示例 |
|------|------|------|
| `fact` | 技术事实 | "项目使用 Python 3.11 + SQLite" |
| `decision` | 架构决策 | "选择 SQLite 而非 PostgreSQL，因为单机部署" |
| `preference` | 用户偏好 | "用中文交流，代码注释用英文" |
| `convention` | 项目约定 | "commit message 用英文，scope 用小写模块名" |
| `insight` | 经验总结 | "并发测试需要独立数据库实例" |
| `debugging` | 调试经验 | "端口冲突时先检查 uvicorn 进程" |

### 信任机制

- Agent 写入的记忆强度上限为 0.5（半信任）
- 用户可通过 `memento verify <id>` 解除限制
- 用户直接写入的记忆无此限制

---

## 命令参考

### 日常操作

| 命令 | 说明 |
|------|------|
| `memento capture <内容> --type <类型>` | 写入一条记忆 |
| `memento recall <查询>` | 语义检索相关记忆 |
| `memento status` | 查看系统状态 |
| `memento inspect <id>` | 查看某条记忆的详细信息 |
| `memento forget <id>` | 标记删除（下次 epoch 生效） |

### 记忆管理

| 命令 | 说明 |
|------|------|
| `memento verify <id>` | 验证 Agent 记忆为可信 |
| `memento pin <id> --rigidity 0.8` | 钉住记忆防止衰减（0.0-1.0） |
| `memento nexus <id> --depth 2` | 查看记忆关联网络 |
| `memento export --output backup.json` | 导出记忆 |
| `memento import --file data.json` | 导入记忆 |

### Epoch 整合

| 命令 | 说明 |
|------|------|
| `memento epoch run` | 运行整合（自动选择 full/light 模式） |
| `memento epoch run --mode light` | 纯数学模式（衰减、强度更新） |
| `memento epoch run --mode full` | LLM 驱动模式（结构化、抽象化） |
| `memento epoch status` | 查看 Epoch 历史 |
| `memento epoch debt` | 查看认知债务 |

### 安装与维护

| 命令 | 说明 |
|------|------|
| `memento setup` | 交互式安装向导 |
| `memento doctor [--ping]` | 检查配置 / 验证连通性 |
| `memento init` | 初始化数据库 |
| `memento update [--check]` | 更新到最新版本 |
| `memento dashboard` | 启动 Web Dashboard |

---

## 配置

### 使用 Setup 向导（推荐）

```bash
memento setup
# 或非交互模式：
memento setup --yes --embedding-provider zhipu --embedding-api-key "sk-xxx"
```

### 手动配置

如果需要精细控制，可直接设置环境变量。

#### Embedding 提供商（语义检索）

设置其中一个 API Key 即可，Memento 按优先级自动选择：

```bash
# 国内大模型（优先）
export ZHIPU_API_KEY="your-key"          # 智谱 GLM embedding-3 (2048维)
export MINIMAX_API_KEY="your-key"        # Minimax embo-01 (1536维)
export MOONSHOT_API_KEY="your-key"       # Moonshot/Kimi

# 国际服务商
export OPENAI_API_KEY="your-key"         # OpenAI text-embedding-3-small
export GEMINI_API_KEY="your-key"         # Google Gemini embedding-001 (768维)
```

优先级：智谱 → Minimax → Moonshot → OpenAI → Gemini → 本地 sentence-transformers → FTS5 全文检索。

不设置 API Key 也能用，会回退到全文检索。如需本地 Embedding（离线）：

```bash
pip install memento[local]   # 安装 sentence-transformers
```

#### LLM 提供商（Epoch 整合 — 可选）

支持任何 OpenAI 兼容接口：

```bash
export MEMENTO_LLM_BASE_URL=https://api.openai.com/v1
export MEMENTO_LLM_API_KEY=sk-xxx
export MEMENTO_LLM_MODEL=gpt-4o-mini
```

| 提供商 | BASE_URL | MODEL 示例 |
|--------|----------|-----------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| 智谱/GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Ollama（本地） | `http://localhost:11434/v1` | `llama3` |
| vLLM | `http://localhost:8000/v1` | `your-model` |
| LM Studio | `http://localhost:1234/v1` | `your-model` |

> **不配 LLM 也能用。** `epoch run` 自动降级为 light 模式（纯数学：衰减、强度更新、Nexus 调整）。LLM 相关操作会记为认知债务，等 LLM 可用后再处理。

可选参数：

```bash
export MEMENTO_LLM_TIMEOUT=30          # 超时秒数（默认 30）
export MEMENTO_LLM_MAX_RETRIES=3       # 重试次数（默认 3）
export MEMENTO_LLM_TEMPERATURE=0       # 温度（默认 0）
```

---

## Web Dashboard

本地 Web Dashboard，可视化浏览和管理记忆，无需网络连接。

```bash
# 安装依赖（一次性）
pip install memento[dashboard]

# 启动
memento dashboard                # 打开 http://localhost:8230
memento dashboard --port 9000    # 自定义端口
memento dashboard --no-open      # 不自动打开浏览器
```

三个视图：

- **记忆** — 浏览、搜索、过滤和管理所有记忆
- **会话** — 查看会话历史和事件统计
- **系统** — 监控状态、Epoch 历史、L2 缓冲区

Dashboard 仅监听 `127.0.0.1`，不暴露到网络。

---

## Agent 接入

### Claude Code（推荐）

```bash
memento setup    # 自动安装 hooks + MCP server
memento doctor   # 验证配置
```

安装后 Claude Code 自动在以下时机调用 Memento：

| Hook | 时机 | 行为 |
|------|------|------|
| SessionStart | 会话开始 | 注入最相关的记忆到对话上下文 |
| Stop | 每次 AI 回复后 | 自动从对话中提取有价值的记忆 |
| SessionEnd | 会话结束 | 记录会话摘要 |

将 [CLAUDE.md](CLAUDE.md) 放入项目根目录，Agent 即可按规范读写记忆。

### OpenCode

通过原生 JavaScript 插件接入，利用 OpenCode 的事件系统实现自动化记忆管理：

| 事件 | 时机 | 行为 |
|-------|------|------|
| `session.created` | 新会话开始 | 召回并缓存 priming 记忆 |
| `session.idle` | 会话空闲 | 防抖后 flush + 可选触发 epoch |
| `session.deleted` | 会话删除 | 最终 flush，关闭会话，关停 Worker |
| `tool.execute.after` | 每次工具调用后 | 记录工具观察用于上下文追踪 |
| `chat.system.transform` | LLM 调用前 | 注入缓存记忆到系统提示 |

**一键安装：**

```bash
./scripts/install-opencode-plugin.sh
```

**前置要求：**
- Bun 运行时（必需 — 插件使用了 Bun 的 `$` shell API 和 Unix socket `fetch()`）
- Memento Python 包已安装（`pip install -e .`）
- `memento-worker` 在 PATH 上

---

## 架构

Memento 将记忆从静态 CRUD 切换到"活记忆"模式：

- **活性记忆单元（Engram）** — 具备强度、衰减速率、情绪标记和关联网络的核心记忆单位。
- **三种认知节律：**
  - *Awake Track*（毫秒级）— 即时图检索、向量检索和记忆捕获。
  - *Subconscious Track*（分钟级）— 后台元数据更新、Hebbian 强化与降噪。
  - *Sleep / Epoch Track*（天级）— LLM 驱动的重型整合、语义抽象和快照生成。
- **不可变快照 DAG** — 类似 Git 的 Merkle DAG 跟踪认知修订历史。
- **密码粉碎** — 删除数据加密密钥即可数学意义上销毁记忆及所有关联数据。

深入了解请阅读完整设计文档：[Engram：分布式记忆操作系统与协作协议](Engram：分布式记忆操作系统与协作协议.md)

---

## 项目结构

```
memento/
├── src/memento/
│   ├── cli.py              # CLI 入口（Click 框架）
│   ├── api.py              # MementoAPI（LocalAPI）
│   ├── mcp_server.py       # MCP Server
│   ├── worker.py           # Worker 服务（Unix Socket HTTP 服务器）
│   ├── session.py          # 会话生命周期管理
│   ├── epoch.py            # Epoch 整合逻辑
│   ├── plugins/
│   │   ├── shared/         # 运行时无关桥接层
│   │   │   └── bridge.js   # 通用 Worker 客户端（JS）
│   │   └── opencode/       # OpenCode 原生插件
│   │       ├── plugin.js   # 生命周期钩子入口
│   │       ├── normalize.js# 事件 → 统一 schema
│   │       └── priming.js  # 系统提示格式化器
│   └── dashboard/          # Web Dashboard
├── plugin/                 # Claude Code 插件（hooks + 脚本）
│   ├── hooks/hooks.json    # Claude hook 注册
│   └── scripts/            # Hook 处理脚本
├── scripts/
│   ├── memento-agent.sh    # 通用 Agent 助手（多 Agent 兼容）
│   └── install-opencode-plugin.sh
├── tests/                  # 测试套件
├── docs/                   # 文档
├── CLAUDE.md               # Claude Code 指令模板
└── pyproject.toml          # 项目元数据
```

---

## 开发

```bash
git clone git@github.com:winteriscome/memento.git
cd memento
pip install -e ".[dev,dashboard]"
pytest
```

---

## 参与贡献

欢迎提交 Issue 和 Merge Request。

1. Fork 本仓库
2. 创建特性分支（`git checkout -b feat/my-feature`）
3. 提交代码
4. 推送并创建 Merge Request

---

## 许可证

[MIT](pyproject.toml)

---

<sub>Memento — 让 AI Agent 的记忆变得可生长、可遗忘、可持续积累。</sub>
