# v0.5.1a 基础设施补强 — 设计规格书

## Scope

**版本**：v0.5.1a

**交付物**：
1. Worker fail-fast（DBThread 初始化失败时快速报错，不带伤启动）
2. WorkerClientAPI 完整实现（Unix Socket HTTP 客户端，替换占位 NotImplementedError）

**不做**：
- Archive Tombstone Index → v0.5.1b
- LLM 语义阶段 → v0.5.1b
- 新增 dataclass（除 `from_dict` 外不新增类型）

---

## 1. Worker Fail-Fast

### 1.1 问题

当前 `DBThread.run()` 初始化失败时，线程静默死亡，`WorkerServer` 等待 `ready_event` 超时后继续启动。结果：HTTP 服务正常监听，但所有请求都会挂死或报错。

### 1.2 改动

**DBThread 改动**（worker.py）：

```python
class DBThread(Thread):
    def __init__(self, db_path, pulse_queue=None):
        super().__init__(daemon=True)
        self._db_path = db_path
        self.pulse_queue = pulse_queue
        self.init_event = Event()       # 改名：ready_event → init_event
        self.init_error = None          # 新增：初始化异常
        self._running = True
        # ... 其余不变

    def run(self):
        try:
            self._api = MementoAPI(db_path=self._db_path, use_awake=False)
            self._conn = self._api.conn
        except Exception as e:
            self.init_error = e
            return                       # 线程退出，不进入主循环
        finally:
            self.init_event.set()        # 无论成功失败都通知
        
        # ... 正常主循环（不变）
```

**WorkerServer 改动**（worker.py）：

```python
class WorkerServer:
    def __init__(self, db_path=None, ...):
        # ... 创建 DBThread
        self.db_thread.start()
        
        # 等待初始化完成
        if not self.db_thread.init_event.wait(timeout=10):
            raise RuntimeError("DBThread initialization timed out after 10s")
        if self.db_thread.init_error is not None:
            raise RuntimeError(f"DBThread initialization failed: {self.db_thread.init_error}")
        
        # 初始化成功，启动 SubconsciousTrack
        # ... 不变
```

**SubconsciousTrack**：不加 init_event。daemon 线程，失败不影响核心功能。

### 1.3 新增 Worker 路由

为 WorkerClientAPI 的 `epoch_status()` 新增路由：

```
GET /epochs → 返回最近 10 条 epoch 记录（JSON array）
```

实现：DBThread 新增 action `'epoch_status'`，委托给 `self._api.epoch_status()`。

### 1.4 测试

- DBThread 初始化失败 → `init_error` 非空，`init_event` 已 set
- WorkerServer 初始化时 DBThread 失败 → raise RuntimeError
- WorkerServer 初始化超时 → raise RuntimeError（需 mock）
- GET /epochs 返回 epoch 记录列表

---

## 2. WorkerClientAPI

### 2.1 架构

```
CLI / MCP
    ↓
WorkerClientAPI._request(method, path, body)
    ↓
Unix Domain Socket → HTTP → Worker HTTP Handler
    ↓
DBThread.execute(action, **kwargs)
    ↓
awake_* / api.*
```

### 2.2 核心方法

```python
class WorkerClientAPI(MementoAPIBase):
    def __init__(self, socket_path: str):
        self.socket_path = socket_path

    def _request(self, method: str, path: str, body: dict = None) -> dict:
        """通过 Unix Socket 发送 HTTP 请求，返回 JSON 响应。
        
        使用 http.client.HTTPConnection + socket 替换（与 hook-handler.sh 中
        send_to_worker 的 Python 版一致）。
        
        超时：10s
        错误：
        - Socket 不存在 → ConnectionError("Worker not running at {path}")
        - 超时 → TimeoutError
        - HTTP 4xx/5xx → RuntimeError(response body)
        - JSON 解析失败 → ValueError
        """
```

### 2.3 方法路由表

| 方法 | HTTP | Path | Body | 返回类型 |
|------|------|------|------|---------|
| `capture(content, **kw)` | POST | /capture | `{content, type, tags, importance, origin, session_id}` | dict |
| `recall(query, **kw)` | POST | /recall | `{query, max_results}` | list[dict] |
| `forget(target_id)` | POST | /forget | `{target_id}` | dict |
| `verify(engram_id)` | POST | /verify | `{engram_id}` | dict |
| `status()` | GET | /status | — | `StatusResult.from_dict(data)` |
| `inspect(engram_id)` | POST | /inspect | `{engram_id}` | dict |
| `pin(engram_id, rigidity)` | POST | /pin | `{engram_id, rigidity}` | dict |
| `session_start(project, task, metadata)` | POST | /session/start | `{claude_session_id, project, task}` | `SessionStartResult.from_dict(data)` |
| `session_end(session_id, outcome, summary)` | POST | /session/end | `{claude_session_id, outcome, summary}` | `SessionEndResult.from_dict(data)` |

> **session_id 语义差异**：Worker 按 `claude_session_id` 路由会话（内部维护 claude→memento 映射）。
> WorkerClientAPI 在 `__init__` 时生成 `self.claude_session_id = uuid4()`。
> - `session_start()` 发送此 claude_session_id，Worker 创建 memento session 并建立映射
> - `session_end(session_id, ...)` 忽略传入的 `session_id` 参数，发送 `self.claude_session_id`
> - 这是已知的语义差异：LocalAPI 用 memento session_id 直接操作，WorkerClientAPI 用 claude session_id 间接操作。两者通过 Worker 的 session_registry 桥接。
> - 调用方不应依赖 `session_end` 的 `session_id` 参数在 WorkerClientAPI 下有效——它是为 LocalAPI 路径保留的。
| `ingest_observation(content, tool, files, importance)` | POST | /observe | `{claude_session_id, content, tool, files}` | None |

> **命名说明**：Worker 路由使用 `/observe`，公共方法名统一为 `ingest_observation()`。
> WorkerClientAPI 内部调用 POST /observe，但公共方法名为 `ingest_observation()`。
> 
> **基类扩展**：MementoAPIBase 新增抽象方法：
> ```python
> @abstractmethod
> def ingest_observation(self, content: str, tool: str = None,
>                        files: list = None, importance: str = 'normal') -> None: ...
> ```
> LocalAPI 已有此方法实现。WorkerClientAPI 在本次实现。
| `epoch_run(mode, trigger)` | — | — | — | dict（见 2.4） |
| `epoch_status()` | GET | /epochs | — | list[dict] |
| `epoch_debt()` | GET | /debt | — | dict |

### 2.4 epoch_run 特殊处理

Epoch 是独立子进程，不走 Worker HTTP。但返回值必须和 LocalAPI.epoch_run() 一致（含 epoch_id 和真实 mode）。

```python
def epoch_run(self, mode='full', trigger='manual'):
    """Spawn memento epoch run 子进程，然后查询最近 epoch 记录获取真实结果。"""
    import subprocess
    result = subprocess.run(
        ['memento', 'epoch', 'run', '--mode', mode, '--trigger', trigger],
        capture_output=True, text=True, timeout=3600,
    )
    if result.returncode != 0:
        return {"error": result.stderr.strip()}
    
    # 查询最近一条 epoch 记录，获取真实 epoch_id 和 mode（可能降级）
    epochs = self._request("GET", "/epochs")
    if epochs and len(epochs) > 0:
        latest = epochs[0]
        return {
            "epoch_id": latest.get("id"),
            "status": latest.get("status", "completed"),
            "mode": latest.get("mode", mode),  # 真实 mode（可能 full→light 降级）
        }
    return {"status": "completed", "mode": mode}
```

**关键**：不硬编码返回 mode，而是从 epochs 表读取真实值，确保降级场景下返回正确的 mode。

### 2.5 session_start 的 claude_session_id

WorkerClientAPI 需要管理 `claude_session_id`。两种策略：

- **方案**：在 `__init__` 时生成一个 UUID 作为 `self.claude_session_id`，session_start/end/observe 自动携带
- session_start 返回的 `SessionStartResult` 中 `priming_memories` 经 HTTP 后是 `list[dict]`（不是 RecallResult 列表）

### 2.6 from_dict 方法

在已有 dataclass 上添加 `@classmethod from_dict(cls, data: dict)`：

**StatusResult**：
```python
@classmethod
def from_dict(cls, data: dict) -> "StatusResult":
    return cls(
        total=data.get("total", 0),
        active=data.get("active", 0),
        forgotten=data.get("forgotten", 0),
        # ... 所有字段
    )
```

**SessionStartResult**（字段：session_id, priming_memories, project, task）：

Worker `/session/start` 返回 `{session_id, priming_count, priming_memories: [{id, content, type, importance}, ...]}`。
from_dict 对齐 Worker 响应：

```python
@classmethod
def from_dict(cls, data: dict) -> "SessionStartResult":
    return cls(
        session_id=data["session_id"],
        priming_memories=data.get("priming_memories", []),
        project=data.get("project"),
        task=data.get("task"),
    )
```

> v0.9 变更：Worker 现在返回完整 priming_memories（含 id/content/type/importance）。
> SessionStart hook 将 priming_memories 格式化输出到 stdout，由宿主注入对话上下文。

**SessionEndResult**（字段：session_id, status, captures_count, observations_count, auto_captures_count）：

Worker `/session/end` 实际返回 `{status, captures_count, observations_count, auto_captures_count}`。
from_dict 对齐真实字段：

```python
@classmethod
def from_dict(cls, data: dict) -> "SessionEndResult":
    return cls(
        session_id=data.get("session_id", ""),
        status=data.get("status", "completed"),
        captures_count=data.get("captures_count", 0),
        observations_count=data.get("observations_count", 0),
        auto_captures_count=data.get("auto_captures_count", 0),
    )
```

> 说明：v0.6.1 起，`auto_captures_count` 表示 `session_end()` 在显式 capture/observation 不足时，通过低信任 fallback 自动补录的 capture 数量。

### 2.7 close()

```python
def close(self):
    """WorkerClientAPI 无需关闭（无持有连接）。"""
    pass
```

### 2.8 测试策略

**单元测试**（mock socket）：
- `_request` 发送正确的 HTTP 方法/路径/body
- `_request` 处理 socket 不存在 → ConnectionError
- `_request` 处理 HTTP 500 → RuntimeError
- `status()` 返回 `StatusResult` 实例
- `session_start()` 返回 `SessionStartResult` 实例
- `epoch_run()` 调用 subprocess

**集成测试**（需要真实 Worker）：
- 启动 Worker → WorkerClientAPI.capture() → recall() → 验证结果
- 标记为 `@pytest.mark.integration`，CI 可选跳过

---

## 不变量

- WorkerClientAPI 和 LocalAPI 对同一操作返回相同类型（StatusResult 等为 dataclass，其余为 dict）
- WorkerClientAPI 内部不持有 DB 连接
- epoch_run 不走 Worker HTTP
- init_event 语义："初始化已结束"，不是"成功就绪"
