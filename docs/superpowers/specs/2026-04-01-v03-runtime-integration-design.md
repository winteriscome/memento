# v0.3 Runtime 集成闭环设计 Spec

**日期**: 2026-04-01
**版本**: v0.3 (rev3)
**状态**: 已确认（Plugin 契约已调研，全部设计要素已锁定）

## 背景

v0.2 交付了 Session Lifecycle + 统一 Memory API + Observation Pipeline，但 Agent 仍需手动调用 CLI 或 source memento-agent.sh。v0.3 的目标是**闭合 runtime 集成环路**：Agent 安装 plugin 后，记忆采集和会话管理自动运行，用户无感知。

## 核心交付

1. **Worker Service** — 后台 HTTP 服务，异步 observation queue，session identity registry
2. **MCP Server** — stdio 协议，暴露 Tools / Resources / Prompts
3. **Plugin 打包** — 按 Claude Code plugin 契约自动注册 hooks + MCP

## 架构

```
Claude Code
  ├── MCP (stdio) ──→ MCP Server 进程 ──→ SQLite (直接访问，同进程)
  │                    直接 import api.py，不走 Worker
  │
  ├── Hooks (shell) ──→ Worker Service (Unix Socket)
  │     SessionStart hook → POST /session/start {claude_session_id}
  │     PostToolUse hook  → POST /observe {claude_session_id, ...}
  │     Stop hook         → POST /flush
  │     SessionEnd hook   → POST /session/end + POST /shutdown
  │
  └── Worker Service ──→ SQLite (单 DB 线程独占连接)
        Socket: /tmp/memento-worker-{hash(db_path)[:12]}.sock
```

- **MCP Server 和 Worker 是独立进程，各自管理自己的 DB 连接**
- MCP Server：直接 import `memento.api.MementoAPI`，同进程调用，不经过 Worker
- Worker Service：通过 Unix Domain Socket 接收 hook 事件，单 DB 线程处理所有写操作
- Hook 间通过 `claude_session_id` 关联，Worker 内部维护 identity registry
- Unix Socket 路径包含 DB 哈希，不同项目天然隔离，无端口冲突

## 一等设计对象 A：Hook Session Identity Mapping

### 问题

Hooks 是独立 shell 调用，没有共享进程状态。SessionStart 拿到的 memento_session_id 必须能被后续 PostToolUse / Stop / SessionEnd 找到。

### 解决方案：Worker 内部 Registry

```
Worker 内部维护:
  session_registry: dict[str, str]
    key   = claude_session_id（Claude Code 注入的环境变量 CLAUDE_SESSION_ID）
    value = memento_session_id（api.session_start() 返回的 UUID）

流程:
  SessionStart hook:
    → 从环境变量读 CLAUDE_SESSION_ID
    → POST /session/start {"claude_session_id": "xxx", "project": "...", "task": "..."}
    → Worker 调 api.session_start()，拿到 memento_session_id
    → Worker 写入 registry: xxx → memento_session_id
    → 返回 {"session_id": "...", "priming_count": N, "priming_memories": [...]}
    → Hook 将 priming_memories 格式化输出到 stdout，注入对话上下文
    → 失败时降级为 "No previous sessions found."，诊断信息写 stderr

  PostToolUse hook:
    → 从环境变量读 CLAUDE_SESSION_ID
    → POST /observe {"claude_session_id": "xxx", "content": "...", ...}
    → Worker 从 registry 查 memento_session_id
    → 入队时附带 memento_session_id
    → 如果 registry 无此 key → 丢弃（session 还没 start 或已 end）

  Stop hook:
    → POST /flush {"claude_session_id": "xxx"}
    → Worker flush queue（等待所有 pending observation 处理完毕）
    → ⚠️ 不调 session_end，会话继续

  SessionEnd hook:
    → POST /session/end {"claude_session_id": "xxx", "outcome": "completed"}
    → Worker flush queue
    → Worker 从 registry 查 memento_session_id → 调 api.session_end()
    → Worker 从 registry 删除此 key
    → POST /shutdown（如果 registry 为空）
```

### 如果 CLAUDE_SESSION_ID 不可用

降级方案：Worker 维护"当前唯一活跃 session"。同一时间只有一个 session 活跃，新 start 自动结束旧的。这适用于 Claude Code 没有暴露 session ID 环境变量的情况。

## 一等设计对象 B：Worker Connection/Ownership Model

### 问题

1. TCP 端口 + "复用" 会串库或跨项目互踢
2. HTTP 线程和消费线程不能无锁共享同一个 sqlite3 Connection

### 解决方案 1：Unix Domain Socket — 天然项目隔离

```
Socket 路径:
  /tmp/memento-worker-{hash(abs_path(MEMENTO_DB))[:12]}.sock

  → 同一 DB 总是映射到同一 socket 文件
  → 不同 DB 映射到不同 socket 文件，无冲突，无互踢

启动时检查:
  1. socket 文件存在 → 尝试连接发 GET /status
  2. 连接成功且 db_path 匹配 → 复用
  3. 连接失败（进程已死） → 删除 stale socket 文件 → 正常启动
  4. socket 文件不存在 → 正常启动

/status 返回:
  {"db_path": "/abs/path/to/project.db", "queue_depth": N, "active_sessions": [...]}
```

### 解决方案 2：单 DB 线程模型 — 消除共享 Connection

```
Worker 内部线程模型:

  HTTP/Socket 线程 (主线程)
    │ 接收请求，解析 JSON
    │ 不直接碰 DB
    │
    ├─ observation → 投入 obs_queue（fire-and-forget）
    │
    └─ 同步操作 (session/start, session/end, capture, status)
       → 投入 cmd_queue，阻塞等待结果
       → result = cmd_queue.put(Command(...)); event.wait()

  DB 线程 (daemon 线程，独占 Connection)
    │ 拥有唯一的 sqlite3.Connection
    │ 同时消费两个队列：
    │
    ├─ obs_queue → 逐条调 ingest_observation()
    │
    └─ cmd_queue → 执行命令，通过 Event 返回结果给 HTTP 线程

  规则:
    - HTTP 线程永远不碰 DB
    - DB 线程拥有 Connection，无跨线程问题
    - 不需要 check_same_thread=False
    - 不需要连接池
```

**为什么不用 check_same_thread=False + 共享 Connection**：
`check_same_thread=False` 只绕过 Python 的检查，不提供线程安全。多线程同时执行 SQL 可能导致数据损坏。单 DB 线程模型从根本上消除了并发问题。

## 1. Worker Service

### HTTP API

```
POST /session/start
  Body: {"claude_session_id": "...", "project": "...", "task": "..."}
  → 注册 identity mapping
  → 调用 api.session_start()
  → 返回 {"session_id": "...", "priming_count": N, "priming_memories": [{id, content, type, importance}, ...]}

POST /session/end
  Body: {"claude_session_id": "...", "outcome": "completed|error", "summary": "..."}
  → flush observation queue
  → 从 registry 查 memento_session_id
  → 调用 api.session_end()
  → 从 registry 删除映射
  → 返回 {"status": "...", "captures_count": N, "observations_count": N, "auto_captures_count": N}
  → 返回 404 如果 claude_session_id 不在 registry

POST /observe
  Body: {"claude_session_id": "...", "content": "...", "tool": "...", "files": [...]}
  → 从 registry 查 memento_session_id（不存在则丢弃）
  → 入队（立即返回，不阻塞 Agent）
  → 返回 {"queued": true, "queue_depth": N}

POST /capture
  Body: {"claude_session_id": "...", "content": "...", "type": "...", ...}
  → 从 registry 查 memento_session_id
  → 同步调用 api.capture()（事务性写入，不走队列）
  → 返回 {"engram_id": "..."}

POST /flush
  Body: {"claude_session_id": "..."}
  → queue.join()（等待所有 pending observation 处理完毕）
  → ⚠️ 不结束会话
  → 返回 {"flushed": true, "remaining": 0}

GET /status
  → 返回 {"db_path": "...", "queue_depth": N, "active_sessions": [...]}

POST /shutdown
  → flush queue → 关闭 DB → 退出进程
  → 返回 {"flushed": N}
```

### 内部结构

- **Socket Server**: Python `socketserver.UnixStreamServer`，主线程接收请求
- **DB 线程**: daemon 线程，独占 sqlite3.Connection，同时消费两个队列：
  - `obs_queue`：observation 异步处理（逐条调 `ingest_observation()`）
  - `cmd_queue`：同步命令（session_start/end, capture, status），处理完通过 Event 返回结果
  - 队列为空时阻塞等待（`queue.get(timeout=1)`）
  - `/flush` 和 `/session/end` 调用时先等 `obs_queue` 清空
- **Session Registry**: `dict[str, str]`，claude_session_id → memento_session_id
- **SQLite**: DB 线程独占 Connection，不跨线程，不需要 check_same_thread=False

### 生命周期

- SessionStart hook 启动（如果没在跑，或 DB 不匹配）
- SessionEnd hook 停止（如果 registry 为空）
- 异常退出：下次 SessionStart 会重新启动
- 不做 daemon / systemd 注册，不做开机自启

### 不做的事

- 不做持久化队列（crash 丢几条 observation 可接受）
- 不做认证（只监听 127.0.0.1）
- 不做多 DB 同时服务（一个 Worker 只服务一个 DB）

## 2. MCP Server

### 通信方式

stdio 协议，由 Claude Code 自动管理进程生命周期。

### Tools (7 个，对齐 api.py)

```
memento_session_start(project?, task?)
  → api.session_start()
  → 返回 session_id + priming memories

memento_session_end(session_id, outcome?, summary?)
  → api.session_end()
  → 返回会话统计（含 auto_captures_count）

memento_recall(query, max_results?, reinforce?)
  → api.recall()（默认 reinforce=False）
  → 返回记忆列表

memento_capture(content, type?, importance?, tags?, origin?, session_id?)
  → api.capture()（awake 默认写 capture_log，非 awake 路径才直接写 engrams）
  → 返回 capture_log_id/state 或 engram_id

memento_observe(content, tool?, files?, tags?, session_id?, importance?)
  → 同步调用 api.ingest_observation()（MCP Server 同进程直接访问 DB）
  → 不经过 Worker（Worker 只服务 hooks，MCP Server 有自己的 DB 连接）
  → 返回 IngestResult

memento_status()
  → api.status()
  → 返回统计信息

memento_forget(engram_id)
  → api.forget()
  → 返回操作结果
```

### Resources（现状已扩展为 5 个，只读）

```
memento://session/{session_id}/context
  → 当前会话的事件流摘要
  → 从 session_events 聚合：event_type 统计、最近 N 条事件 payload

memento://vault/stats
  → DB 统计概要（engram 数、session 数、observation 数等）

memento://vault/recent
  → 最近 10 条活跃记忆（按 last_accessed 排序，不触发强化）

memento://epochs
  → 最近 Epoch 运行记录

memento://daily/today
  → 当日 `capture_log` + `session_events` 的时间线视图
  → `capture_log` 仅返回 `epoch_id IS NULL` 的未消费 buffer 项
```

### Prompts (1 个)

```
memento_prime(project?, task?)
  → 基于 project + task 生成 priming prompt
  → 内容：项目上下文 + 高 strength 记忆 + 用户偏好（type=preference/convention）
  → Agent 可在会话开始时调用，注入 system context
```

### 实现方式

- 基于 `mcp` Python SDK（`pip install mcp`）
- 直接 import `memento.api.MementoAPI`，同进程调用，不走 Worker
- MCP Server 拥有自己的 DB 连接，与 Worker 的 DB 连接独立（WAL 模式保证并发安全）
- 所有 MCP Tools 都是同步调用，不涉及 Worker 的 queue 或 registry

### 不做的事

- 不做 OpenAI Function Schema 适配（v0.5）
- 不做 MCP Sampling（不需要 MCP Server 调 LLM）
- Resources 不暴露 embedding 原始数据

## 3. Plugin 打包与 Hook 自动注册

### 安装方式

```bash
claude plugins install memento
# 或从本地
claude plugins install ./path/to/memento
```

### Plugin 目录结构

⚠️ **条件性预案**：需先调研 Claude Code 当前 plugin manifest 契约（`.claude-plugin/plugin.json` vs `package.json`），以下为预估结构，实现前必须对齐官方文档。如果契约与预估不符，本章节需要重写：

```
memento-plugin/
├── .claude-plugin/
│   └── plugin.json         # Plugin manifest（按 Claude Code 契约定义）
├── hooks/
│   └── hooks.json          # Hook 定义（由 manifest 声明路径）
├── .mcp.json               # MCP Server 配置
├── scripts/
│   ├── mcp-server.py       # MCP Server 入口
│   ├── worker-service.py   # Worker Service 入口
│   └── hook-handler.sh     # Hook 统一入口脚本
└── README.md
```

### hooks.json 定义

```json
{
  "hooks": [
    {
      "event": "SessionStart",
      "triggers": ["startup", "clear", "compact"],
      "command": "scripts/hook-handler.sh session-start"
    },
    {
      "event": "PostToolUse",
      "triggers": ["*"],
      "command": "scripts/hook-handler.sh observe"
    },
    {
      "event": "Stop",
      "command": "scripts/hook-handler.sh flush"
    },
    {
      "event": "SessionEnd",
      "command": "scripts/hook-handler.sh session-end"
    }
  ]
}
```

### hook-handler.sh 逻辑

```bash
# 所有 hook 统一入口
# $1 = 子命令 (session-start | observe | flush | session-end)
# CLAUDE_SESSION_ID = Claude Code 注入的环境变量（如果可用）
# 如果不可用，传 "default" 让 Worker 用单活跃 session 降级

CLAUDE_SID="${CLAUDE_SESSION_ID:-default}"
SOCK_PATH="/tmp/memento-worker-$(python3 -c "
import hashlib, os
db = os.environ.get('MEMENTO_DB', os.path.expanduser('~/.memento/default.db'))
print(hashlib.md5(os.path.abspath(db).encode()).hexdigest()[:12])
").sock"

# 通过 Unix Socket 与 Worker 通信（用 Python 发送，因为 curl 对 UDS 支持不一致）
send_to_worker() {
  python3 -c "
import http.client, socket, sys, json
sock_path, method, path, body = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv)>4 else '{}'
conn = http.client.HTTPConnection('localhost')
conn.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
conn.sock.connect(sock_path)
conn.request(method, path, body, {'Content-Type': 'application/json'})
print(conn.getresponse().read().decode())
" "$SOCK_PATH" "$@" 2>/dev/null
}

case "$1" in
  session-start)
    ensure_worker_running "$SOCK_PATH"
    send_to_worker POST /session/start \
      "{\"claude_session_id\": \"$CLAUDE_SID\", \"project\": \"$(pwd)\"}"
    ;;
  observe)
    SUMMARY=$(extract_tool_summary)  # 从 stdin/env 提取
    send_to_worker POST /observe \
      "{\"claude_session_id\": \"$CLAUDE_SID\", \"content\": \"$SUMMARY\"}" &
    ;;
  flush)
    send_to_worker POST /flush \
      "{\"claude_session_id\": \"$CLAUDE_SID\"}"
    ;;
  session-end)
    send_to_worker POST /session/end \
      "{\"claude_session_id\": \"$CLAUDE_SID\", \"outcome\": \"completed\"}"
    send_to_worker POST /shutdown '{}' || true
    ;;
esac
```

### PostToolUse 摘要提取

Hook 脚本拿到 tool_name + tool_input + tool_output，不存原始 output：

- 提取工具名
- 从 input 中解析涉及的文件路径
- output 取前 200 字作为 summary
- 打包为 JSON POST 到 Worker `/observe`

### 与 v0.2 memento-agent.sh 的关系

- Plugin 安装后，hooks 自动接管，`memento-agent.sh` 变为可选手动降级方案
- 没装 plugin 的环境（Codex、Gemini CLI）继续用 `memento-agent.sh`
- CLI 命令保留，可独立使用

## 4. api.py 事务性修复

v0.2 的 `api.capture()` 不是原子操作：先写 engram，再追加 capture 事件。如果 session_id 失效，会出现 engram 已落库、event 失败的半成功状态。

v0.3 修复：

```python
def capture(self, content, ..., session_id=None, event_id=None):
    # 包在同一个事务中
    try:
        engram_id = self.core.capture(content, ...,
            source_session_id=session_id, source_event_id=event_id)

        if session_id:
            # 验证 session 存在且活跃
            session = self._session_svc.get(session_id)
            if session and session.status == 'active':
                self._session_svc.append_event(session_id, "capture", {...})
            # session 无效时 engram 仍然写入，但不追加事件
            # （engram 本身是有价值的，不应因 session 问题丢弃）

        self.core.conn.commit()
        return engram_id
    except Exception:
        self.core.conn.rollback()
        raise
```

决策：session_id 无效时 engram 仍然写入（有价值的数据不丢），但不追加 event（不制造孤儿事件）。这比整体回滚更合理。

注意：此修复同时适用于 MCP Server（同进程调 api.py）和 Worker（DB 线程调 api.py）。

## 5. 与现有代码的关系

### 需修改

| 文件 | 改动 |
|------|------|
| `src/memento/api.py` | capture 事务性修复（session_id 无效时 engram 仍写入，不追加 event） |

### 新增文件

| 文件 | 说明 |
|------|------|
| `src/memento/worker.py` | Worker Service（HTTP + Queue + Session Registry） |
| `src/memento/mcp_server.py` | MCP Server（stdio，Tools/Resources/Prompts） |
| `plugin/.claude-plugin/plugin.json` | Plugin manifest（需调研后确定格式） |
| `plugin/hooks/hooks.json` | Hook 定义 |
| `plugin/.mcp.json` | MCP 配置 |
| `plugin/scripts/hook-handler.sh` | Hook 统一入口脚本 |
| `plugin/scripts/mcp-server.py` | MCP Server 入口 |
| `plugin/scripts/worker-service.py` | Worker Service 入口 |
| `tests/test_worker.py` | Worker HTTP API + Session Registry 测试 |
| `tests/test_mcp_server.py` | MCP Tools/Resources/Prompts 测试 |

### 不改 DB schema

v0.2 的 sessions / session_events / engrams 够用，不加表不加列。

## 6. v0.3 明确不做

- ~~OpenAI Function Schema 适配~~ → v0.5
- ~~LLM 自动汇总~~ → v0.5（summary 仍由调用方提供）
- ~~三轨节律 / CQRS / 六态状态机~~ → v0.5
- ~~持久化队列~~ → 进程内 Queue 足够
- ~~多 DB 同时服务~~ → 一个 Worker 只服务一个 DB
- ~~Plugin 市场发布~~ → 先本地安装验证
- ~~MCP Sampling~~ → 不需要
- ~~Gemini CLI / Codex 适配~~ → 继续用 memento-agent.sh

## 7. 实现前置调研（已完成）

### 7.1 Claude Code Plugin Manifest 契约（已确认）

- **Manifest**: `.claude-plugin/plugin.json`，必填字段：`name`, `description`, `author`
- **Hooks**: `hooks/hooks.json`（独立文件），事件结构：`{hooks: {EventName: [{matcher?, hooks: [{type, command, timeout?, async?}]}]}}`
- **MCP**: `.mcp.json`（plugin 根目录），支持 `${CLAUDE_PLUGIN_ROOT}` 变量展开
- **已知 hook 事件**: SessionStart, UserPromptSubmit, PostToolUse, Stop, SessionEnd
- **环境变量**: `CLAUDE_PLUGIN_ROOT`（plugin 安装根目录）

### 7.2 Session ID 传递机制（已确认）

- **没有 CLAUDE_SESSION_ID 环境变量**
- Claude Code 通过 **stdin JSON** 传递 hook 上下文，包含：
  - `session_id` — Claude Code 会话标识
  - `tool_name`, `tool_input`, `tool_response` — PostToolUse 时的工具信息
  - `cwd`, `prompt`, `transcript_path`
- hook-handler.sh 必须从 stdin 读取 JSON，不能从环境变量读
- spec 中"一等设计对象 A"的降级方案不再需要——stdin 始终提供 session_id

## 8. Engram 文档同步清单

| 位置 | 改动 |
|------|------|
| 顶层路线图（L11） | 插入 v0.3 行 |
| 读者导引（L20） | 新增 v0.3 实现者行 |
| 能力矩阵（23.3） | MCP Server 从 v0.5 提前到 v0.3，新增 Plugin Hooks / Worker Service 行 |
| 23.2.1.7 砍掉清单 | 删除 v0.3 引用，改为"见 23.2.2" |
| 新增 23.2.2 节 | v0.3 完整设计 |

## 9. 落地顺序

0. 前置调研（Claude Code plugin manifest 契约 + CLAUDE_SESSION_ID 环境变量可用性）
1. api.py 事务性修复
2. Worker Service（worker.py + 单 DB 线程 + Session Registry + Unix Socket + 测试）
3. MCP Server（mcp_server.py + 测试）
4. Plugin 打包（manifest + hooks + scripts）— 依赖 Step 0 调研结果
5. Engram 文档同步
6. 端到端验证（安装 plugin → 开会话 → 工具调用 → 自动 observe → 结束会话）

## 版本线最终形态

```
v0.1  极简验证（衰减+强化 CLI）                              ✅ 已交付
v0.2  Agent-Runtime 集成层（Session + API + Pipeline）       ✅ 已交付
v0.3  Runtime 集成闭环（MCP + Plugin Hooks + Worker）        ← 当前
v0.5  三轨架构重写（CQRS/状态机/LLM 抽象化/Function Schema/Fork/PR）
v1.0  联邦同步（EFP/跨实例身份/混合检索）
```
