# Memento Setup Wizard — 开箱即用设计

**日期**: 2026-04-09
**目标**: 将 memento 安装体验简化为 `pip install` + `memento setup` 两步完成

## 背景

当前安装后用户需要手动完成 5+ 步配置（init DB、配置环境变量、安装 hooks、配置 MCP、放置 CLAUDE.md）。目标是面向内部团队，做到最小化配置。

## 设计决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 目标用户 | 仅团队内部 | 可预设内部默认值 |
| 安装体验 | `pip install` + `memento setup` | 两步完成，首次有引导 |
| 配置持久化 | `~/.memento/config.json` | 集中管理，环境变量可覆盖 |
| Claude Code 集成 | 全局安装（hooks → `~/.claude/settings.json`，MCP → `~/.claude/.mcp.json`） | 所有项目自动生效 |
| CLAUDE.md | 不处理 | v0.9 hooks + MCP tool descriptions 已足够 |
| 后续修改 | 直接编辑 `config.json` | 不需要 `memento config` 子命令 |
| 记忆库 | 全局库（`~/.memento/default.db`） | 跨项目共享记忆是产品核心定义——agent 在项目 A 学到的用户偏好、约定应在项目 B 也能召回 |

## 一、配置文件 `~/.memento/config.json`

### 结构

```json
{
  "database": {
    "path": "~/.memento/default.db"
  },
  "embedding": {
    "provider": "zhipu",
    "api_key": "sk-xxx",
    "model": "embedding-3"
  },
  "llm": {
    "provider": "zhipu",
    "base_url": "https://open.bigmodel.cn/api/paas/v4",
    "api_key": "sk-xxx",
    "model": "glm-4-flash-250414",
    "timeout": 30,
    "max_retries": 3,
    "temperature": 0
  }
}
```

### 四层配置优先级

```
MEMENTO_* 环境变量 > config.json > 旧版 provider 环境变量 > 代码默认值
```

具体映射：

| 配置项 | MEMENTO_* 环境变量 | config.json 字段 | 旧版环境变量 |
|--------|-------------------|-----------------|-------------|
| DB 路径 | `MEMENTO_DB` | `database.path` | — |
| Embedding 提供商 | `MEMENTO_EMBEDDING_PROVIDER` | `embedding.provider` | — |
| Embedding API Key | `MEMENTO_EMBEDDING_API_KEY` | `embedding.api_key` | `ZHIPU_API_KEY`, `OPENAI_API_KEY` 等 |
| LLM Base URL | `MEMENTO_LLM_BASE_URL` | `llm.base_url` | — |
| LLM API Key | `MEMENTO_LLM_API_KEY` | `llm.api_key` | — |
| LLM Model | `MEMENTO_LLM_MODEL` | `llm.model` | — |

**旧版 provider 环境变量**（`ZHIPU_API_KEY`、`GLM_API_KEY`、`MINIMAX_API_KEY`、`MOONSHOT_API_KEY`、`KIMI_API_KEY`、`OPENAI_API_KEY`、`GEMINI_API_KEY`）继续完全支持，位于第三优先级。已有用户无需任何改动。

### 兼容性

- `config.json` 不存在时不报错，fallback 到旧版环境变量 + 默认值
- 已有环境变量配置的用户无需改动，行为完全不变
- `config.json` 和旧版环境变量同时存在时，`config.json` 优先

## 二、`memento setup` 交互式向导

### 完整流程

```
$ memento setup

═══ Memento Setup ═══

[1/4] 初始化数据库
  数据库路径: ~/.memento/default.db
  ✓ 数据库已创建

[2/4] 配置 Embedding 提供商
  用于记忆的语义搜索，选择一个提供商:
    1. 智谱 GLM (推荐，国内访问快)
    2. OpenAI
    3. 跳过
  请选择 [1]: 1
  请输入 API Key: ****
  验证连接中... ✓ 连接成功

[3/4] 配置 LLM 提供商
  用于 epoch 记忆整合，选择一个提供商:
    1. 智谱 GLM (推荐)
    2. OpenAI 兼容 (自定义 base_url)
    3. 跳过
  请选择 [1]: 1
  API Key 与 Embedding 相同，是否复用？[Y/n]: Y
  ✓ LLM 已配置

[4/4] 安装 Claude Code 集成
  安装 hooks 到 ~/.claude/settings.json... ✓
  配置 MCP server 到 ~/.claude/.mcp.json... ✓

═══ Setup 完成 ═══
  配置文件: ~/.memento/config.json
  数据库:   ~/.memento/default.db
  如需修改配置，直接编辑 ~/.memento/config.json
  运行 memento doctor 检查配置状态
```

### 非交互模式

支持 `--yes` 标志，跳过所有确认提示，使用默认值。用于脚本化安装：

```bash
# 使用默认 embedding/LLM（跳过，需提前在 config.json 或环境变量配置）
memento setup --yes

# 指定 provider 和 key
memento setup --yes --embedding-provider zhipu --embedding-api-key "sk-xxx" \
  --llm-provider zhipu --llm-api-key "sk-xxx"
```

非交互模式下，未提供 embedding/LLM 配置时静默跳过（不报警告），因为用户可能已通过环境变量或 config.json 预配置。

### 跳过时的告知

**跳过 Embedding：**
```
⚠ 未配置 Embedding，memento 将使用 FTS5 全文搜索:
  - 语义搜索不可用（只能精确/模糊匹配，无法理解语义相似性）
  - 记忆召回质量显著下降
稍后可编辑 ~/.memento/config.json 补充配置。
继续？[y/N]:
```

**跳过 LLM：**
```
⚠ 未配置 LLM，epoch 整合将使用 light 模式:
  - 无法进行语义合并和冲突消解
  - 记忆碎片会持续累积，认知债务无法清理
  - 长期使用后搜索噪音增大
稍后可编辑 ~/.memento/config.json 补充配置。
继续？[y/N]:
```

跳过时默认 `N`，用户必须明确输入 `y` 才能跳过。

### 各提供商配置项

| 提供商 | Embedding 需要 | LLM 需要 |
|--------|---------------|----------|
| 智谱 GLM | api_key | api_key（可复用 embedding 的） |
| OpenAI | api_key | api_key（可复用 embedding 的） |
| OpenAI 兼容 | — | base_url + api_key + model |

预设的 model 和 base_url：
- 智谱 embedding: model=`embedding-3`, 无需 base_url（SDK 内置）
- 智谱 LLM: model=`glm-4-flash-250414`, base_url=`https://open.bigmodel.cn/api/paas/v4`
- OpenAI embedding: model=`text-embedding-3-small`, 无需 base_url
- OpenAI LLM: model=`gpt-4o-mini`, 无需 base_url

### 关键行为

- **幂等性**：重复运行不破坏已有配置，已有项提示是否覆盖
- **API Key 验证**：配置后立即验证连接，失败时允许重试或跳过
- **智能复用**：embedding 和 LLM 选了同一家时，自动复用 API Key
- **默认值**：所有选择题都有默认值（1），但跳过需要明确确认

## 三、Claude Code 集成自动化

### hooks 写入

写入 `~/.claude/settings.json`（全局），注入 4 个 hooks：
- **SessionStart**: `hook-handler.sh session-start`
- **PostToolUse**: `hook-handler.sh observe`
- **Stop**: `hook-handler.sh flush-and-epoch`
- **SessionEnd**: `hook-handler.sh session-end`

如果文件已存在，合并而不覆盖用户已有的其他 hooks。

### MCP 配置

写入 `~/.claude/.mcp.json`（全局级别，Claude Code 的标准 MCP 发现路径）：

```json
{
  "mcpServers": {
    "memento": {
      "type": "stdio",
      "command": "/path/to/memento-mcp-server",
      "args": []
    }
  }
}
```

路径通过 `which memento-mcp-server` 和包安装路径自动解析。

**为什么不是项目级 `.mcp.json`：** setup 的目标是全局生效。项目级 `.mcp.json` 需要每个项目单独配置，与"开箱即用"矛盾。`~/.claude/.mcp.json` 是 Claude Code 的全局 MCP 配置路径。

### 已存在配置的处理

```
检测到已有 memento hooks/MCP 配置
是否覆盖？[Y/n]: Y
```

## 四、`memento doctor` 配置检查命令

只读检查命令，验证配置是否正常。**默认不发外部请求**，仅检查文件/配置是否存在：

```
$ memento doctor

═══ Memento Doctor ═══

  配置文件     ~/.memento/config.json          ✓ 存在
  数据库       ~/.memento/default.db            ✓ 可读写 (权限 0600)
  Embedding    zhipu (embedding-3)              ✓ 已配置
  LLM          zhipu (glm-4-flash-250414)       ✓ 已配置
  Hooks        ~/.claude/settings.json          ✓ 4/4 已安装
  MCP Server   ~/.claude/.mcp.json              ✓ 已配置
  Worker       /tmp/memento-worker-xxx.sock     ✗ 未运行（首次 hook 触发时自动启动）

═══ 1 个警告，0 个错误 ═══
```

加 `--ping` 时主动验证外部连通性（会发真实请求，可能产生少量 API 计费）：

```
$ memento doctor --ping

  ...
  Embedding    zhipu (embedding-3)              ✓ 连接正常 (响应 120ms)
  LLM          zhipu (glm-4-flash-250414)       ✓ 连接正常 (响应 350ms)
  ...
```

`--ping` 超时 5 秒，失败算 warning 不算 error（网络抖动不应阻塞使用）。

不修改任何配置，仅报告状态。用户在 setup 之后或排查问题时使用。

## 五、代码改造

### 新增模块

**`src/memento/config.py`** — 统一配置加载：
- 读取 `~/.memento/config.json`
- 合并 `MEMENTO_*` 环境变量（最高优先级）
- 兼容旧版 provider 环境变量（第三优先级）
- 提供 `get_config()` 接口，返回合并后的配置字典

### 需要改造的模块

| 模块 | 当前方式 | 改造后 |
|------|---------|--------|
| `db.py` | `os.getenv("MEMENTO_DB")` | 调用 `get_config()` 获取 `database.path` |
| `embedding.py` | 逐个检查 `ZHIPU_API_KEY` 等 | 先读 `config.embedding`，无配置时 fallback 到旧版环境变量逐个检查 |
| `llm.py` | `LLMClient.from_env()` 读 `MEMENTO_LLM_*` 环境变量 | 改为 `LLMClient.from_config()`：先读 `config.llm`，无配置时 fallback 到 `MEMENTO_LLM_*` 环境变量。所有调用点（`epoch.py`、`transcript.py`、`api.py`）自动受益，无需逐个修改 |
| `hook-handler.sh` | 用 `MEMENTO_DB` 计算 socket 路径 | 改为：先尝试从 `~/.memento/config.json` 读 `database.path`，fallback 到 `MEMENTO_DB` 环境变量，再 fallback 到默认路径 |
| `cli.py` | `plugin install claude` 写项目级 `.mcp.json` | setup 命令写全局 `~/.claude/.mcp.json`；**废弃** `plugin install claude --scope project`（见去重策略） |

### hook-handler.sh 改造细节

当前脚本（第 34-37 行）用 Python 内联计算 socket 路径：

```bash
# 当前实现
SOCK_PATH=$(python3 -c "
import hashlib, os
db = os.environ.get('MEMENTO_DB', os.path.expanduser('~/.memento/default.db'))
print('/tmp/memento-worker-' + hashlib.md5(os.path.abspath(db).encode()).hexdigest()[:12] + '.sock')
")
```

改造后增加 config.json 读取：

```bash
# 改造后
SOCK_PATH=$(python3 -c "
import hashlib, os, json
db = os.environ.get('MEMENTO_DB')
if not db:
    cfg = os.path.expanduser('~/.memento/config.json')
    if os.path.exists(cfg):
        try:
            c = json.load(open(cfg))
            db = c.get('database', {}).get('path')
        except: pass
if not db:
    db = os.path.expanduser('~/.memento/default.db')
else:
    db = os.path.expanduser(db)
print('/tmp/memento-worker-' + hashlib.md5(os.path.abspath(db).encode()).hexdigest()[:12] + '.sock')
")
```

优先级：`MEMENTO_DB` 环境变量 > `config.json` > 默认路径。与 Python 端保持一致。

### 全局/项目级去重策略

**废弃 `memento plugin install claude --scope project`**，统一使用 `memento setup` 全局安装。

理由：全局 hooks 和项目级 hooks 并存时，Claude Code 会**两次执行**同一 hook（全局 + 项目），导致双 observation、双 flush、双 epoch。这不是优先级问题，而是重复执行。

- `memento setup` 只写全局配置（`~/.claude/settings.json` + `~/.claude/.mcp.json`）
- `memento plugin install claude` 命令保留但标记 deprecated，运行时打印迁移提示
- 如果检测到项目级 `.claude/settings.json` 中已有 memento hooks，`memento setup` 提示用户清理

### API Key 安全

config.json 包含明文 API key，需要基本防护：

- **文件权限**：`memento setup` 创建 `~/.memento/config.json` 时强制 `chmod 0600`
- **输出脱敏**：`memento doctor`、setup 完成提示、日志中永不回显明文 key，统一用掩码格式 `sk-****xxxx`（显示最后 4 位）
- **数据库文件**同样 `chmod 0600`

### 文档与 CLI 文案同步

以下位置引用了旧的 `memento plugin install claude` / `--scope project|global`，实现时需一并更新：

- `README.zh-CN.md`（快速开始、CLI 命令参考）
- `README.md`（Quick Start、CLI Reference）
- `cli.py` 中 `plugin install claude` 命令的 help 文案和 deprecated 提示

更新方向：快速开始改为 `pip install memento && memento setup`；CLI 参考中 `plugin install claude` 标注 deprecated 并指向 `memento setup`。

### 测试范围

需要覆盖的关键回归场景：

| 场景 | 验证点 |
|------|--------|
| `LLMClient.from_config()` 统一生效 | epoch run、transcript extraction、api.py 三个调用点都读到 config.json 中的 LLM 配置 |
| config.json 不存在时的 fallback | 旧版环境变量（`ZHIPU_API_KEY` 等）仍能正常工作，行为不变 |
| 四层优先级 | `MEMENTO_*` env > config.json > 旧版 provider env > defaults，逐层覆盖正确 |
| setup 全局安装 | hooks 写入 `~/.claude/settings.json`，MCP 写入 `~/.claude/.mcp.json` |
| 旧项目级 hooks 清理提示 | 检测到项目级 `.claude/settings.json` 中有 memento hooks 时打印迁移提示 |
| setup 幂等性 | 重复运行 setup 不产生重复 hooks |
| doctor 默认模式 | 只检查文件/配置存在性，不发外部请求 |
| doctor --ping | 发真实请求验证连通性，超时 5 秒，失败报 warning 不报 error |
| API Key 安全 | config.json 权限 0600；所有输出中 key 已掩码 |
| 非交互模式 | `memento setup --yes --embedding-provider zhipu --embedding-api-key xxx` 静默完成 |

### 向后兼容

- 已有用户如果配了环境变量但没有 `config.json`，一切照常工作
- `config.json` 不存在时不报错，直接 fallback 到旧版环境变量 + 默认值
- `memento setup` 生成 `config.json` 后，`MEMENTO_*` 环境变量仍可覆盖
