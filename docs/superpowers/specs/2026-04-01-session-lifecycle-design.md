# Session Lifecycle + 自动采集框架设计 Spec

**日期**: 2026-04-01
**版本**: v0.2 首个模块
**状态**: 已确认

## 背景

Memento v0.1 交付了 CLI + agent wrapper 的记忆引擎，验证了衰减+强化模型的有效性。
当前主要短板不在记忆模型，而在 **agent-runtime 集成层**：

- 没有 session 一等对象，无法追踪会话上下文
- 记忆保存完全依赖 Agent 手动调用，遗忘率高
- 没有 observation 自动采集和治理管道
- recall 的 Mode A 强化副作用在浏览场景下不合理

## 核心设计原则

1. **三层严格分离**：session 层、event 层、engram 层各自独立
2. **session_summary 不是 engram**：摘要默认存 `sessions.summary`，不直接落长期记忆
3. **observation 不是 capture 变体**：有独立的 ingestion pipeline
4. **默认只读**：所有浏览/探索接口不触发强化，只有显式操作才写入
5. **协议无关**：统一 API 层，CLI/MCP/Function Schema 都走同一接口

## 数据模型

### 新增表：sessions

```sql
CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,       -- UUID
    project         TEXT,                   -- 项目路径或标识
    task            TEXT,                   -- 任务描述
    status          TEXT DEFAULT 'active',  -- active | completed | abandoned | error
    started_at      TEXT NOT NULL,          -- ISO datetime
    ended_at        TEXT,                   -- ISO datetime
    summary         TEXT,                   -- 会话摘要（一等字段，不是 engram）
    metadata        TEXT                    -- JSON，扩展字段（git branch, agent type 等）
);
CREATE INDEX idx_sessions_project ON sessions(project);
CREATE INDEX idx_sessions_status ON sessions(status);
```

### 新增表：session_events

Append-only 事件流，只存标准化事件，不存原始工具输出。

```sql
CREATE TABLE session_events (
    id              TEXT PRIMARY KEY,       -- UUID
    session_id      TEXT NOT NULL,          -- FK → sessions.id
    event_type      TEXT NOT NULL,          -- start | capture | recall | observation | tool_summary | end
    payload         TEXT,                   -- JSON，标准化格式
    fingerprint     TEXT,                   -- 内容指纹，用于事件级去重
    created_at      TEXT NOT NULL,          -- ISO datetime
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX idx_session_events_session ON session_events(session_id);
CREATE INDEX idx_session_events_type ON session_events(event_type);
```

**payload 标准化规则**（不存原始工具输出）：

| event_type | payload 内容 |
|------------|-------------|
| start | `{"project": "...", "task": "...", "priming_count": N}` |
| capture | `{"engram_id": "...", "type": "...", "content_preview": "前50字"}` |
| recall | `{"query": "...", "result_count": N, "top_score": 0.85}` |
| observation | `{"tool": "...", "files": [...], "summary": "...", "promoted": bool}` |
| tool_summary | `{"tool": "...", "files": [...], "summary": "摘要"}` |
| end | `{"outcome": "...", "captures_count": N, "observations_count": N, "auto_captures_count": N}` |

### 扩展 engrams 表

```sql
ALTER TABLE engrams ADD COLUMN source_session_id TEXT;   -- 产生该记忆的会话
ALTER TABLE engrams ADD COLUMN source_event_id TEXT;     -- 产生该记忆的具体事件
```

来源追踪精确到事件级：长期记忆可能来自会话中的某个 observation、session_end 汇总、人工修订、或跨会话合并。

## 统一 Memory API（api.py）

协议无关层，定义标准输入输出。CLI/MCP/Function Schema 都走这层。

```python
class MementoAPI:
    """统一 Memory API — 协议无关层"""

    def session_start(self, project: str = None, task: str = None,
                      metadata: dict = None) -> SessionStartResult:
        """
        创建会话，自动 recall 相关记忆作为 priming context。
        返回 session_id + priming_memories。
        """

    def session_end(self, session_id: str, outcome: str = "completed",
                    summary: str = None, learnings: list[str] = None) -> SessionEndResult:
        """
        结束会话。summary 先存入 sessions.summary。
        当显式 capture/observation 不足时，可将 summary 作为低信任 fallback capture
        写入 capture_log；不会直接写入 engrams。
        learnings 中值得跨会话复用的条目仍由调用方决定是否显式 capture。
        """

    def recall(self, query: str, max_results: int = 5,
               reinforce: bool = False) -> list[RecallResult]:
        """
        检索记忆。默认只读。reinforce=True 时才触发 Mode A 强化。
        """

    def capture(self, content: str, type: str = "fact",
                importance: str = "normal", tags: list[str] = None,
                origin: str = "human",
                session_id: str = None, event_id: str = None) -> str:
        """
        写入长期记忆。仅用于可跨会话复用的信息。
        session_id/event_id 记录来源。
        """

    def ingest_observation(self, content: str, tool: str = None,
                           files: list[str] = None, tags: list[str] = None,
                           session_id: str = None) -> IngestResult:
        """
        一级 API。接收 observation，经过 pipeline 处理：
        1. fingerprint 精确去重
        2. 语义相似度候选合并
        3. type + tags + file + 时间窗口最终判定
        4. 决定是否晋升为 engram（promoted=True）或仅留在 session_events
        """

    def status(self) -> StatusResult:
        """数据库统计。"""

    def forget(self, engram_id: str) -> bool:
        """软删除记忆。"""
```

## Observation Ingestion Pipeline

### 两段式去重 + 晋升策略

```
observation 进入
    │
    ├─ Stage 1: Exact/Near-Exact Dedup
    │   计算 fingerprint = hash(normalize(content))
    │   查 session_events 最近 N 条同 fingerprint → 跳过
    │
    ├─ Stage 2: Semantic Candidate Merge
    │   生成 embedding，查 engrams 相似度 > 0.85 的候选
    │   检查 type + tags + files 是否一致
    │   检查时间窗口（同一 session 内 or 最近 1h）
    │   → 如果匹配：合并到已有 engram（更新 content/tags/access_count）
    │   → 如果不匹配：视为新 observation
    │
    └─ Stage 3: Promotion Decision
        新 observation 是否晋升为 engram？
        规则：
        - 同一 observation 在 ≥2 个不同 session 出现 → 晋升
        - 用户显式 verify → 晋升
        - importance=high/critical → 直接晋升
        - 其他 → 仅存 session_events，不落 engrams
```

### 晋升后的 engram 属性

- `origin = "agent"`, `verified = 0`
- `strength = 0.5`（agent 上限）
- `source_session_id` + `source_event_id` 记录来源

## recall 默认只读改造

当前 `core.py` 的 `recall()` 在 Mode A 下默认写入强化。改为：

- API 层 `recall()` 默认 `reinforce=False`（只读）
- 只有显式传 `reinforce=True` 才触发 Mode A 强化
- 保持 Mode B 的 read-only 语义不变
- 现有 CLI `memento recall` 默认行为保持 `reinforce=False`

## CLI 适配

新增 `session` 子命令组：

```bash
memento session start [--project PATH] [--task "描述"]
# 输出 session_id + priming memories

memento session end <session_id> [--outcome completed|abandoned|error] [--summary "摘要"]
# 结束会话；可能在显式摄取不足时触发低信任 auto-summary fallback

memento session status [session_id]
# 查看当前活跃会话 / 指定会话详情

memento session list [--project PATH] [--limit 10]
# 列出最近会话
```

现有命令扩展：

```bash
memento recall <query> [--reinforce]
# 新增 --reinforce 标志，默认只读

memento observe <content> [--tool TOOL] [--files "a.py,b.py"] [--tags "a,b"]
# ingest_observation 的 CLI 入口
```

## memento-agent.sh 升级

```bash
memento_session_start() {
  memento_project_env
  SESSION_ID=$(memento session start --project "$(pwd)" --task "$1" --format json | jq -r '.session_id')
  export MEMENTO_SESSION_ID="$SESSION_ID"
}

memento_session_end() {
  if [ -n "$MEMENTO_SESSION_ID" ]; then
    memento session end "$MEMENTO_SESSION_ID" --outcome "${1:-completed}" --summary "${2:-}"
    unset MEMENTO_SESSION_ID
  fi
}

memento_observe() {
  memento observe "$1" --tool "${2:-}" --tags "${3:-}" 2>/dev/null || true
}
```

## 不做的事

- 不上常驻进程/Worker Service（CLI 直接调用足够）
- 不上 MCP Server（先做统一 API，MCP 适配后续版本）
- 不上 Function Schema 适配（同上）
- 不做 session_artifacts 表（sessions.summary 够用，需要时再加）
- 不做基于 transcript 的 LLM 自动汇总（summary 由调用方提供；后续若需要，可在更高版本追加 transcript 级分析）

> 后续实现说明（v0.6.1）：
> - `session_end()` 已增加一个非 LLM 的保守兜底：当 `summary` 存在且本 session 的显式 capture + observation 总量不足 2 时，会通过 `awake_capture(origin='agent')` 将 summary 写入 `capture_log`。
> - 该兜底只进入低信任入口，不直接进入 `engrams`。
> - 默认 awake 模式下，`capture()` 写 `capture_log`，**不会**追加 `session_events.capture`；因此抑制判断不能只看 `captures_count`，而要直接查 `capture_log WHERE source_session_id = ?`。

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `src/memento/db.py` | 修改 | 新增 sessions/session_events 表，engrams 加列 |
| `src/memento/session.py` | 新建 | Session service（start/end/append_event/list） |
| `src/memento/observation.py` | 新建 | Observation ingestion pipeline |
| `src/memento/api.py` | 新建 | 统一 Memory API 层 |
| `src/memento/core.py` | 修改 | recall 默认只读，capture 支持 source 追踪 |
| `src/memento/cli.py` | 修改 | 新增 session 子命令组，recall 加 --reinforce，新增 observe |
| `scripts/memento-agent.sh` | 修改 | 基于 session lifecycle 重写 |
| `tests/test_session.py` | 新建 | Session 生命周期测试 |
| `tests/test_observation.py` | 新建 | Observation pipeline 测试 |
| `tests/test_api.py` | 新建 | 统一 API 测试 |
| `Engram 设计文档` | 修改 | 更新 v0.2 章节 |

## 落地顺序

1. schema + migration（db.py）
2. session service（session.py）
3. observation pipeline（observation.py）
4. 统一 API（api.py）
5. core.py recall 只读改造
6. CLI adapter（cli.py）
7. memento-agent.sh 升级
8. 测试
9. Engram 设计文档更新
