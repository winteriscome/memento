> [!NOTE]
> **Historical Plan**
> This document is an implementation snapshot retained for history. It may not reflect the latest repository-wide milestone semantics or current implementation behavior. For current source-of-truth, see `docs/README.md`, `Engram：分布式记忆操作系统与协作协议.md`, and `docs/superpowers/plans/2026-04-02-v06-v07-roadmap.md`.

# v0.3 Runtime 集成闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 闭合 Memento 的 runtime 集成环路——MCP Server 暴露记忆能力，Worker Service 异步处理 hook 事件，Plugin 自动注册实现用户无感知。

**Architecture:** 双进程模型。MCP Server（stdio）直接 import api.py 同进程调用 DB；Worker Service（Unix Domain Socket）接收 hook 事件，单 DB 线程独占 Connection 处理所有写操作。两者通过 SQLite WAL 模式共享数据库。Plugin 打包将 hooks + MCP 配置自动注册到 Claude Code。

**Tech Stack:** Python 3.10+, `mcp` SDK, `socketserver` (stdlib), `queue` (stdlib), SQLite WAL

---

## File Structure

### 需修改

| 文件 | 职责 | 改动 |
|------|------|------|
| `src/memento/api.py` | 统一 Memory API | capture 事务性修复 |
| `pyproject.toml` | 包配置 | 新增 `mcp` 依赖 |

### 新增

| 文件 | 职责 |
|------|------|
| `src/memento/worker.py` | Worker Service：Unix Socket Server + 单 DB 线程 + Session Registry + 双队列 |
| `src/memento/mcp_server.py` | MCP Server：stdio 协议，7 Tools + 3 Resources + 1 Prompt |
| `tests/test_worker.py` | Worker 单元测试 |
| `tests/test_mcp_server.py` | MCP Server 单元测试 |
| `plugin/hooks/hooks.json` | Hook 定义 |
| `plugin/.mcp.json` | MCP 配置 |
| `plugin/scripts/hook-handler.sh` | Hook 统一入口 |
| `plugin/scripts/mcp-server.py` | MCP Server 入口（thin wrapper） |
| `plugin/scripts/worker-service.py` | Worker Service 入口（thin wrapper） |

---

### Task 0: 前置调研

**Files:**
- 无代码改动，纯调研

- [ ] **Step 1: 调研 Claude Code plugin manifest 契约**

```bash
# 查看已安装 plugin 的实际目录结构
ls -la ~/.claude/plugins/cache/
# 找一个已安装的 plugin（如 claude-mem）查看其 manifest
find ~/.claude/plugins/cache/ -name "plugin.json" -o -name "package.json" | head -5
# 读取其内容确认字段定义
```

记录：manifest 文件名、必填字段、hooks 声明方式、MCP 注册方式。

- [ ] **Step 2: 调研 CLAUDE_SESSION_ID 环境变量**

```bash
# 在 Claude Code hook 中打印所有环境变量，确认是否有 session 标识
# 创建临时 hook 测试
cat > /tmp/test-hook.sh << 'EOF'
#!/bin/bash
env | grep -i "claude\|session" > /tmp/claude-hook-env.txt
EOF
chmod +x /tmp/test-hook.sh
```

记录：是否有 CLAUDE_SESSION_ID 或类似变量。如果没有，Task 2 使用"单活跃 session"降级方案。

- [ ] **Step 3: 记录调研结果**

将调研结果写入 `docs/superpowers/specs/2026-04-01-v03-runtime-integration-design.md` 的第 7 节，更新 Plugin 章节的条件性预案。

---

### Task 1: api.py 事务性修复

**Files:**
- Modify: `src/memento/api.py:117-151`
- Test: `tests/test_api.py`

- [ ] **Step 1: 写失败测试 — session_id 无效时 engram 仍写入但不追加 event**

在 `tests/test_api.py` 末尾添加：

```python
def test_capture_with_invalid_session_still_saves_engram(api):
    """session_id 无效时 engram 应写入，但不追加 event。"""
    eid = api.capture("有价值的记忆", session_id="nonexistent-session-id")
    assert len(eid) == 36

    # engram 已落库
    engram = api.core.get_by_id(eid)
    assert engram is not None
    assert engram["content"] == "有价值的记忆"
    assert engram["source_session_id"] == "nonexistent-session-id"

    # 没有产生孤儿 event
    row = api.core.conn.execute(
        "SELECT COUNT(*) as cnt FROM session_events WHERE payload LIKE ?",
        (f'%{eid}%',),
    ).fetchone()
    assert row["cnt"] == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_api.py::test_capture_with_invalid_session_still_saves_engram -v`
Expected: FAIL（当前代码在 session_id 无效时仍尝试 append_event，可能抛异常或写入孤儿 event）

- [ ] **Step 3: 修复 api.py capture 方法**

修改 `src/memento/api.py` 的 `capture` 方法：

```python
def capture(
    self,
    content: str,
    type: str = "fact",
    importance: str = "normal",
    tags: list[str] | None = None,
    origin: str = "human",
    session_id: str | None = None,
    event_id: str | None = None,
) -> str:
    """写入长期记忆。仅用于可跨会话复用的信息。

    事务性保证：session_id 无效时 engram 仍写入（有价值数据不丢），
    但不追加 event（不制造孤儿事件）。
    """
    try:
        engram_id = self.core.capture(
            content,
            type=type,
            importance=importance,
            tags=tags,
            origin=origin,
            source_session_id=session_id,
            source_event_id=event_id,
        )

        # 只在 session 存在且活跃时追加 event
        if session_id:
            session = self._session_svc.get(session_id)
            if session and session.status == "active":
                self._session_svc.append_event(
                    session_id,
                    "capture",
                    {
                        "engram_id": engram_id,
                        "type": type,
                        "content_preview": content[:50],
                    },
                )
        self.core.conn.commit()
        return engram_id
    except Exception:
        self.core.conn.rollback()
        raise
```

- [ ] **Step 4: 运行全部 API 测试确认通过**

Run: `pytest tests/test_api.py -v`
Expected: 全部 PASS（包括新测试和原有 7 个测试）

- [ ] **Step 5: Commit**

```bash
git add src/memento/api.py tests/test_api.py
git commit -m "fix(api): capture transactional safety — engram saved even if session invalid"
```

---

### Task 2: Worker Service — 单 DB 线程 + 双队列骨架

**Files:**
- Create: `src/memento/worker.py`
- Create: `tests/test_worker.py`

- [ ] **Step 1: 写失败测试 — DBThread 基本功能**

创建 `tests/test_worker.py`：

```python
"""Worker Service 测试。"""

import struct
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_worker.db"


@pytest.fixture
def mock_embedding():
    """统一 mock embedding，所有测试共享。"""
    fake_blob = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)
    with patch("memento.core.get_embedding") as m1, \
         patch("memento.observation.get_embedding") as m2:
        m1.return_value = (fake_blob, 4, False)
        m2.return_value = (fake_blob, 4, False)
        yield


def test_db_thread_executes_commands(db_path, mock_embedding):
    """DB 线程应能执行同步命令并返回结果。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        # 执行 status 命令
        result = t.execute("status")
        assert "total" in result
        assert result["total"] == 0
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_db_thread_processes_observations(db_path, mock_embedding):
    """DB 线程应能异步处理 observation。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        # 先创建一个 session
        result = t.execute("session_start", project="/test", task="test")
        session_id = result["session_id"]

        # 提交 observation（异步）
        t.enqueue_observation(
            content="发现连接池问题",
            tool="Read",
            session_id=session_id,
            importance="high",
        )

        # 等待队列消化
        t.flush()

        # 检查 observation 是否被处理
        status = t.execute("status")
        assert status["total_observations"] >= 1
    finally:
        t.shutdown()
        t.join(timeout=5)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_worker.py -v`
Expected: FAIL — `ImportError: cannot import name 'DBThread' from 'memento.worker'`

- [ ] **Step 3: 实现 DBThread**

创建 `src/memento/worker.py`：

```python
"""Worker Service — 单 DB 线程 + 双队列 + Session Registry + Unix Socket。"""

import hashlib
import json
import os
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from memento.api import MementoAPI
from memento.db import get_db_path


@dataclass
class Command:
    """同步命令：HTTP 线程投入，DB 线程执行，通过 Event 返回结果。"""
    action: str
    kwargs: dict = field(default_factory=dict)
    result: Any = None
    error: Optional[Exception] = None
    done: threading.Event = field(default_factory=threading.Event)


class DBThread(threading.Thread):
    """独占 DB Connection 的后台线程。

    同时消费两个队列：
    - obs_queue：observation 异步处理（fire-and-forget）
    - cmd_queue：同步命令（session_start/end, capture, status），处理完通过 Event 返回
    """

    def __init__(self, db_path: Path | None = None):
        super().__init__(daemon=True)
        self._db_path = db_path
        self._obs_queue: queue.Queue = queue.Queue()
        self._cmd_queue: queue.Queue = queue.Queue()
        self._running = True
        self._api: Optional[MementoAPI] = None
        # Session Registry: claude_session_id → memento_session_id
        self.session_registry: dict[str, str] = {}

    def run(self):
        """DB 线程主循环：独占 Connection，交替消费两个队列。"""
        self._api = MementoAPI(db_path=self._db_path)

        while self._running:
            # 优先处理同步命令
            try:
                cmd = self._cmd_queue.get_nowait()
                self._handle_command(cmd)
                self._cmd_queue.task_done()
                continue
            except queue.Empty:
                pass

            # 再处理 observation
            try:
                obs = self._obs_queue.get(timeout=0.5)
                self._handle_observation(obs)
                self._obs_queue.task_done()
            except queue.Empty:
                pass

        # 关闭前 flush
        self._flush_all()
        if self._api:
            self._api.close()

    def execute(self, action: str, **kwargs) -> Any:
        """同步执行命令（HTTP 线程调用，阻塞等待结果）。"""
        cmd = Command(action=action, kwargs=kwargs)
        self._cmd_queue.put(cmd)
        cmd.done.wait(timeout=30)
        if cmd.error:
            raise cmd.error
        return cmd.result

    def enqueue_observation(self, **kwargs):
        """异步提交 observation（立即返回）。"""
        self._obs_queue.put(kwargs)

    def flush(self):
        """等待 obs_queue 全部消化。"""
        self._obs_queue.join()

    def shutdown(self):
        """优雅关闭。"""
        self._running = False

    @property
    def queue_depth(self) -> int:
        return self._obs_queue.qsize()

    def _handle_command(self, cmd: Command):
        """在 DB 线程内执行同步命令。"""
        try:
            if cmd.action == "status":
                raw = self._api.status()
                cmd.result = {
                    "total": raw.total,
                    "active": raw.active,
                    "total_sessions": raw.total_sessions,
                    "active_sessions": raw.active_sessions,
                    "total_observations": raw.total_observations,
                    "db_path": str(self._db_path or get_db_path()),
                    "queue_depth": self.queue_depth,
                    "active_session_ids": list(self.session_registry.values()),
                }
            elif cmd.action == "session_start":
                result = self._api.session_start(**cmd.kwargs)
                claude_sid = cmd.kwargs.get("claude_session_id", "default")
                # 如果用降级模式（default），先结束旧 session
                if claude_sid == "default" and "default" in self.session_registry:
                    old_sid = self.session_registry.pop("default")
                    self._api.session_end(old_sid, outcome="abandoned")
                self.session_registry[claude_sid] = result.session_id
                cmd.result = {
                    "session_id": result.session_id,
                    "priming_count": len(result.priming_memories),
                }
            elif cmd.action == "session_end":
                claude_sid = cmd.kwargs.pop("claude_session_id", "default")
                memento_sid = self.session_registry.pop(claude_sid, None)
                if not memento_sid:
                    cmd.result = None
                    return
                result = self._api.session_end(memento_sid, **cmd.kwargs)
                cmd.result = {
                    "status": result.status if result else None,
                    "captures_count": result.captures_count if result else 0,
                    "observations_count": result.observations_count if result else 0,
                } if result else None
            elif cmd.action == "capture":
                claude_sid = cmd.kwargs.pop("claude_session_id", "default")
                memento_sid = self.session_registry.get(claude_sid)
                cmd.kwargs["session_id"] = memento_sid
                cmd.result = {"engram_id": self._api.capture(**cmd.kwargs)}
            elif cmd.action == "flush":
                self._obs_queue.join()
                cmd.result = {"flushed": True, "remaining": 0}
            else:
                cmd.error = ValueError(f"Unknown action: {cmd.action}")
        except Exception as e:
            cmd.error = e
        finally:
            cmd.done.set()

    def _handle_observation(self, obs: dict):
        """在 DB 线程内处理单条 observation。"""
        claude_sid = obs.pop("claude_session_id", "default")
        memento_sid = self.session_registry.get(claude_sid)
        if not memento_sid:
            return  # session 不存在，丢弃
        obs["session_id"] = memento_sid
        try:
            self._api.ingest_observation(**obs)
        except Exception:
            pass  # observation 处理失败不应中断队列

    def _flush_all(self):
        """关闭前清空两个队列。"""
        while True:
            try:
                obs = self._obs_queue.get_nowait()
                self._handle_observation(obs)
                self._obs_queue.task_done()
            except queue.Empty:
                break
        while True:
            try:
                cmd = self._cmd_queue.get_nowait()
                cmd.error = RuntimeError("Worker shutting down")
                cmd.done.set()
                self._cmd_queue.task_done()
            except queue.Empty:
                break


def get_socket_path(db_path: Path | None = None) -> str:
    """计算 Unix Domain Socket 路径。"""
    path = db_path or get_db_path()
    digest = hashlib.md5(str(path.resolve()).encode()).hexdigest()[:12]
    return f"/tmp/memento-worker-{digest}.sock"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_worker.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/worker.py tests/test_worker.py
git commit -m "feat(worker): DBThread with dual queues and session registry"
```

---

### Task 3: Worker Service — Session Registry 测试

**Files:**
- Modify: `tests/test_worker.py`

- [ ] **Step 1: 写 session registry 测试**

在 `tests/test_worker.py` 末尾添加：

```python
def test_session_registry_maps_claude_to_memento(db_path, mock_embedding):
    """session_start 应建立 claude_session_id → memento_session_id 映射。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        result = t.execute("session_start",
            claude_session_id="claude-abc",
            project="/test",
        )
        assert "session_id" in result
        assert "claude-abc" in t.session_registry
        assert t.session_registry["claude-abc"] == result["session_id"]
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_session_end_removes_from_registry(db_path, mock_embedding):
    """session_end 应从 registry 中删除映射。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        result = t.execute("session_start",
            claude_session_id="claude-xyz",
            project="/test",
        )
        assert "claude-xyz" in t.session_registry

        t.execute("session_end", claude_session_id="claude-xyz", outcome="completed")
        assert "claude-xyz" not in t.session_registry
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_observe_without_session_is_discarded(db_path, mock_embedding):
    """没有 session 的 observation 应被丢弃。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        t.enqueue_observation(
            claude_session_id="nonexistent",
            content="should be discarded",
        )
        t.flush()

        status = t.execute("status")
        assert status["total_observations"] == 0
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_default_session_fallback(db_path, mock_embedding):
    """claude_session_id=default 降级模式：新 start 自动结束旧 session。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        r1 = t.execute("session_start", claude_session_id="default", project="/test")
        old_sid = r1["session_id"]

        r2 = t.execute("session_start", claude_session_id="default", project="/test")
        new_sid = r2["session_id"]

        assert old_sid != new_sid
        assert t.session_registry.get("default") == new_sid
    finally:
        t.shutdown()
        t.join(timeout=5)
```

- [ ] **Step 2: 运行测试确认通过**

Run: `pytest tests/test_worker.py -v`
Expected: 6 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_worker.py
git commit -m "test(worker): session registry mapping and fallback tests"
```

---

### Task 4: Worker Service — Unix Socket Server

**Files:**
- Modify: `src/memento/worker.py`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: 写 Socket Server 测试**

在 `tests/test_worker.py` 末尾添加：

```python
import http.client
import socket


def _send_request(sock_path: str, method: str, path: str, body: dict = None) -> dict:
    """通过 Unix Socket 发送 HTTP 请求。"""
    conn = http.client.HTTPConnection("localhost")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(sock_path)
    conn.sock = sock
    body_str = json.dumps(body) if body else "{}"
    conn.request(method, path, body_str, {"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = json.loads(resp.read().decode())
    conn.close()
    return data


def test_socket_server_status(tmp_path, mock_embedding):
    """Socket Server 应响应 GET /status。"""
    import json
    from memento.worker import WorkerServer

    db_path = tmp_path / "test_sock.db"
    sock_path = str(tmp_path / "test.sock")

    server = WorkerServer(db_path, sock_path)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        time.sleep(0.3)  # 等待 server 启动
        data = _send_request(sock_path, "GET", "/status")
        assert "db_path" in data
        assert "queue_depth" in data
    finally:
        server.shutdown_gracefully()


def test_socket_server_session_lifecycle(tmp_path, mock_embedding):
    """Socket Server 应支持完整的 session 生命周期。"""
    import json
    from memento.worker import WorkerServer

    db_path = tmp_path / "test_sock2.db"
    sock_path = str(tmp_path / "test2.sock")

    server = WorkerServer(db_path, sock_path)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        time.sleep(0.3)

        # start
        data = _send_request(sock_path, "POST", "/session/start", {
            "claude_session_id": "test-session",
            "project": "/test",
        })
        assert "session_id" in data

        # observe
        data = _send_request(sock_path, "POST", "/observe", {
            "claude_session_id": "test-session",
            "content": "发现问题",
            "tool": "Read",
            "importance": "high",
        })
        assert data.get("queued") is True

        # flush
        data = _send_request(sock_path, "POST", "/flush", {
            "claude_session_id": "test-session",
        })
        assert data.get("flushed") is True

        # end
        data = _send_request(sock_path, "POST", "/session/end", {
            "claude_session_id": "test-session",
            "outcome": "completed",
        })
        assert data.get("status") == "completed"
    finally:
        server.shutdown_gracefully()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_worker.py::test_socket_server_status -v`
Expected: FAIL — `ImportError: cannot import name 'WorkerServer'`

- [ ] **Step 3: 实现 WorkerServer**

在 `src/memento/worker.py` 末尾添加：

```python
import http.server
import socketserver


class _WorkerHandler(http.server.BaseHTTPRequestHandler):
    """处理 Unix Socket 上的 HTTP 请求。"""

    def log_message(self, format, *args):
        pass  # 静默日志

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    def _respond(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def do_GET(self):
        if self.path == "/status":
            result = self.server.db_thread.execute("status")
            self._respond(result)
        else:
            self._respond({"error": "not found"}, 404)

    def do_POST(self):
        body = self._read_body()

        if self.path == "/session/start":
            result = self.server.db_thread.execute("session_start", **body)
            self._respond(result)

        elif self.path == "/session/end":
            result = self.server.db_thread.execute("session_end", **body)
            if result is None:
                self._respond({"error": "session not found"}, 404)
            else:
                self._respond(result)

        elif self.path == "/observe":
            self.server.db_thread.enqueue_observation(**body)
            self._respond({
                "queued": True,
                "queue_depth": self.server.db_thread.queue_depth,
            })

        elif self.path == "/capture":
            result = self.server.db_thread.execute("capture", **body)
            self._respond(result)

        elif self.path == "/flush":
            self.server.db_thread.flush()
            self._respond({"flushed": True, "remaining": 0})

        elif self.path == "/shutdown":
            flushed = self.server.db_thread.queue_depth
            self.server.db_thread.flush()
            self._respond({"flushed": flushed})
            # 在响应发送后关闭
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        else:
            self._respond({"error": "not found"}, 404)


class WorkerServer(socketserver.UnixStreamServer):
    """Unix Domain Socket 上的 HTTP Server。"""

    allow_reuse_address = True

    def __init__(self, db_path: Path | None, sock_path: str):
        self.db_thread = DBThread(db_path)
        self.db_thread.start()
        # 清理 stale socket
        if os.path.exists(sock_path):
            os.unlink(sock_path)
        super().__init__(sock_path, _WorkerHandler)

    def shutdown_gracefully(self):
        """优雅关闭：先停 DB 线程再停 server。"""
        self.db_thread.shutdown()
        self.db_thread.join(timeout=10)
        self.shutdown()
        if hasattr(self, "server_address") and os.path.exists(self.server_address):
            os.unlink(self.server_address)
```

- [ ] **Step 4: 运行全部 Worker 测试**

Run: `pytest tests/test_worker.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/worker.py tests/test_worker.py
git commit -m "feat(worker): Unix Socket server with HTTP API"
```

---

### Task 5: Worker Service — 入口脚本

**Files:**
- Create: `plugin/scripts/worker-service.py`

- [ ] **Step 1: 创建 Worker 入口脚本**

```bash
mkdir -p plugin/scripts
```

创建 `plugin/scripts/worker-service.py`：

```python
#!/usr/bin/env python3
"""Worker Service 入口 — 由 hook 启动。"""

import sys
from pathlib import Path

# 确保 src 在 path 中
src_dir = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from memento.worker import WorkerServer, get_socket_path
from memento.db import get_db_path


def main():
    db_path = get_db_path()
    sock_path = get_socket_path(db_path)

    print(f"Starting Worker: db={db_path} sock={sock_path}", file=sys.stderr)
    server = WorkerServer(db_path, sock_path)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown_gracefully()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add plugin/scripts/worker-service.py
git commit -m "feat(worker): add worker-service.py entry point"
```

---

### Task 6: MCP Server — Tools

**Files:**
- Create: `src/memento/mcp_server.py`
- Create: `tests/test_mcp_server.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: 添加 mcp 依赖**

在 `pyproject.toml` 的 dependencies 中添加 `mcp`：

```toml
dependencies = [
    "click>=8.0",
    "google-genai>=1.0",
    "sqlite-vec>=0.1.6",
    "mcp>=1.0",
]
```

- [ ] **Step 2: 安装新依赖**

Run: `pip install -e ".[dev]"`

- [ ] **Step 3: 写测试 — MCP Tools 能调用 api.py**

创建 `tests/test_mcp_server.py`：

```python
"""MCP Server 测试 — 验证 Tools 正确映射到 api.py。"""

import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from memento.mcp_server import create_mcp_app


@pytest.fixture
def mcp_app(tmp_path):
    db_path = tmp_path / "test_mcp.db"
    with patch("memento.core.get_embedding") as m1, \
         patch("memento.observation.get_embedding") as m2:
        fake_blob = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)
        m1.return_value = (fake_blob, 4, False)
        m2.return_value = (fake_blob, 4, False)

        app, api = create_mcp_app(db_path)
        yield app, api
        api.close()


def test_mcp_session_start(mcp_app):
    """memento_session_start tool 应返回 session_id。"""
    _, api = mcp_app
    result = api.session_start(project="/test", task="fix bug")
    assert result.session_id
    assert len(result.session_id) == 36


def test_mcp_capture_and_recall(mcp_app):
    """capture + recall 应能写入和检索。"""
    _, api = mcp_app
    eid = api.capture("MCP 测试记忆", type="fact")
    assert len(eid) == 36

    results = api.recall("MCP 测试")
    # 可能有结果也可能没有（取决于 FTS5 匹配）


def test_mcp_status(mcp_app):
    """status 应返回统计信息。"""
    _, api = mcp_app
    api.capture("一条记忆")
    status = api.status()
    assert status.active >= 1


def test_mcp_forget(mcp_app):
    """forget 应软删除。"""
    _, api = mcp_app
    eid = api.capture("要遗忘的")
    assert api.forget(eid) is True
```

- [ ] **Step 4: 实现 MCP Server**

创建 `src/memento/mcp_server.py`：

```python
"""MCP Server — stdio 协议，暴露 Memento 能力给 Claude Code。

直接 import api.py，同进程调用，不走 Worker。
"""

import json
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import Resource, Tool, TextContent, Prompt, PromptMessage

from memento.api import MementoAPI


def create_mcp_app(db_path: Path | None = None) -> tuple[Server, MementoAPI]:
    """创建 MCP Server 实例和 API 实例。"""
    app = Server("memento")
    api = MementoAPI(db_path=db_path)

    # ── Tools ──

    @app.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="memento_session_start",
                description="创建新的记忆会话，返回 session_id 和 priming 记忆。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "项目路径或标识"},
                        "task": {"type": "string", "description": "任务描述"},
                    },
                },
            ),
            Tool(
                name="memento_session_end",
                description="结束记忆会话。summary 存入会话记录，不落长期记忆。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "outcome": {"type": "string", "enum": ["completed", "abandoned", "error"]},
                        "summary": {"type": "string", "description": "会话摘要"},
                    },
                    "required": ["session_id"],
                },
            ),
            Tool(
                name="memento_recall",
                description="从长期记忆中检索相关知识。默认只读，不改变记忆状态。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "自然语言检索查询"},
                        "max_results": {"type": "integer", "default": 5},
                        "reinforce": {"type": "boolean", "default": False},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="memento_capture",
                description="将重要发现、决策、用户偏好存入长期记忆。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "type": {"type": "string", "enum": ["decision", "insight", "convention", "debugging", "preference", "fact"]},
                        "importance": {"type": "string", "enum": ["low", "normal", "high", "critical"]},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "origin": {"type": "string", "enum": ["human", "agent"]},
                        "session_id": {"type": "string"},
                    },
                    "required": ["content"],
                },
            ),
            Tool(
                name="memento_observe",
                description="写入 observation（经去重/晋升 pipeline 处理）。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "tool": {"type": "string"},
                        "files": {"type": "array", "items": {"type": "string"}},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "session_id": {"type": "string"},
                        "importance": {"type": "string", "enum": ["low", "normal", "high", "critical"]},
                    },
                    "required": ["content"],
                },
            ),
            Tool(
                name="memento_status",
                description="返回记忆数据库统计信息。",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="memento_forget",
                description="软删除一条记忆。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "engram_id": {"type": "string"},
                    },
                    "required": ["engram_id"],
                },
            ),
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "memento_session_start":
            result = api.session_start(
                project=arguments.get("project"),
                task=arguments.get("task"),
            )
            data = {
                "session_id": result.session_id,
                "priming_count": len(result.priming_memories),
                "priming_memories": [
                    {"id": m.id, "content": m.content, "type": m.type, "score": m.score}
                    for m in result.priming_memories
                ],
            }
        elif name == "memento_session_end":
            result = api.session_end(
                session_id=arguments["session_id"],
                outcome=arguments.get("outcome", "completed"),
                summary=arguments.get("summary"),
            )
            data = (
                {
                    "status": result.status,
                    "captures_count": result.captures_count,
                    "observations_count": result.observations_count,
                    "auto_captures_count": result.auto_captures_count,
                }
                if result else {"error": "session not found"}
            )
        elif name == "memento_recall":
            results = api.recall(
                query=arguments["query"],
                max_results=arguments.get("max_results", 5),
                reinforce=arguments.get("reinforce", False),
            )
            data = [
                {"id": r.id, "content": r.content, "type": r.type, "score": r.score, "strength": r.strength}
                for r in results
            ]
        elif name == "memento_capture":
            engram_id = api.capture(
                content=arguments["content"],
                type=arguments.get("type", "fact"),
                importance=arguments.get("importance", "normal"),
                tags=arguments.get("tags"),
                origin=arguments.get("origin", "human"),
                session_id=arguments.get("session_id"),
            )
            data = {"engram_id": engram_id}
        elif name == "memento_observe":
            result = api.ingest_observation(
                content=arguments["content"],
                tool=arguments.get("tool"),
                files=arguments.get("files"),
                tags=arguments.get("tags"),
                session_id=arguments.get("session_id"),
                importance=arguments.get("importance", "normal"),
            )
            data = {"event_id": result.event_id, "promoted": result.promoted, "engram_id": result.engram_id, "skipped": result.skipped}
        elif name == "memento_status":
            s = api.status()
            data = {
                "total": s.total, "active": s.active, "forgotten": s.forgotten,
                "total_sessions": s.total_sessions, "active_sessions": s.active_sessions,
                "total_observations": s.total_observations,
            }
        elif name == "memento_forget":
            ok = api.forget(arguments["engram_id"])
            data = {"success": ok}
        else:
            data = {"error": f"unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]

    # ── Resources ──

    @app.list_resources()
    async def list_resources() -> list[Resource]:
        return [
            Resource(uri="memento://vault/stats", name="Vault 统计", description="记忆数据库统计概要"),
            Resource(uri="memento://vault/recent", name="最近记忆", description="最近 10 条活跃记忆"),
        ]

    @app.read_resource()
    async def read_resource(uri: str) -> str:
        if uri == "memento://vault/stats":
            s = api.status()
            return json.dumps({
                "total": s.total, "active": s.active, "forgotten": s.forgotten,
                "total_sessions": s.total_sessions, "total_observations": s.total_observations,
            }, ensure_ascii=False)
        elif uri == "memento://vault/recent":
            results = api.recall("", max_results=10, reinforce=False)
            return json.dumps([
                {"id": r.id, "content": r.content, "type": r.type, "strength": r.strength}
                for r in results
            ], ensure_ascii=False)
        return json.dumps({"error": "resource not found"})

    # ── Prompts ──

    @app.list_prompts()
    async def list_prompts() -> list[Prompt]:
        return [
            Prompt(
                name="memento_prime",
                description="基于项目和任务生成 priming prompt，包含相关记忆和用户偏好。",
                arguments=[
                    {"name": "project", "description": "项目路径", "required": False},
                    {"name": "task", "description": "任务描述", "required": False},
                ],
            ),
        ]

    @app.get_prompt()
    async def get_prompt(name: str, arguments: dict | None = None) -> list[PromptMessage]:
        if name != "memento_prime":
            return []

        args = arguments or {}
        result = api.session_start(
            project=args.get("project"),
            task=args.get("task"),
        )

        lines = ["# Memento 项目记忆上下文\n"]
        if result.priming_memories:
            lines.append(f"以下是与当前任务相关的 {len(result.priming_memories)} 条记忆：\n")
            for m in result.priming_memories:
                lines.append(f"- [{m.type}] {m.content}")
        else:
            lines.append("暂无相关记忆。")

        return [PromptMessage(role="user", content=TextContent(type="text", text="\n".join(lines)))]

    return app, api
```

- [ ] **Step 5: 运行 MCP Server 测试**

Run: `pytest tests/test_mcp_server.py -v`
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add src/memento/mcp_server.py tests/test_mcp_server.py pyproject.toml
git commit -m "feat(mcp): MCP Server with 7 tools, 2 resources, 1 prompt"
```

---

### Task 7: MCP Server — 入口脚本

**Files:**
- Create: `plugin/scripts/mcp-server.py`

- [ ] **Step 1: 创建入口脚本**

创建 `plugin/scripts/mcp-server.py`：

```python
#!/usr/bin/env python3
"""MCP Server 入口 — 由 Claude Code 启动（stdio 协议）。"""

import asyncio
import sys
from pathlib import Path

# 确保 src 在 path 中
src_dir = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from mcp.server.stdio import stdio_server
from memento.mcp_server import create_mcp_app


async def main():
    app, api = create_mcp_app()
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())
    finally:
        api.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Commit**

```bash
git add plugin/scripts/mcp-server.py
git commit -m "feat(mcp): add mcp-server.py entry point"
```

---

### Task 8: Plugin 配置文件（条件性 — 依赖 Task 0 调研结果）

**Files:**
- Create: `plugin/hooks/hooks.json`
- Create: `plugin/.mcp.json`
- Create: `plugin/scripts/hook-handler.sh`

⚠️ 此 Task 的目录结构和字段名需根据 Task 0 调研结果调整。以下基于预估。

- [ ] **Step 1: 创建 hooks.json**

```bash
mkdir -p plugin/hooks
```

创建 `plugin/hooks/hooks.json`：

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

- [ ] **Step 2: 创建 .mcp.json**

创建 `plugin/.mcp.json`：

```json
{
  "mcpServers": {
    "memento": {
      "command": "python3",
      "args": ["scripts/mcp-server.py"],
      "env": {}
    }
  }
}
```

- [ ] **Step 3: 创建 hook-handler.sh**

创建 `plugin/scripts/hook-handler.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail

CLAUDE_SID="${CLAUDE_SESSION_ID:-default}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 计算 socket 路径
SOCK_PATH="/tmp/memento-worker-$(python3 -c "
import hashlib, os
db = os.environ.get('MEMENTO_DB', os.path.expanduser('~/.memento/default.db'))
print(hashlib.md5(os.path.abspath(db).encode()).hexdigest()[:12])
").sock"

send_to_worker() {
  python3 -c "
import http.client, socket, sys, json
sock_path, method, path = sys.argv[1], sys.argv[2], sys.argv[3]
body = sys.argv[4] if len(sys.argv) > 4 else '{}'
conn = http.client.HTTPConnection('localhost')
conn.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
conn.sock.connect(sock_path)
conn.request(method, path, body, {'Content-Type': 'application/json'})
print(conn.getresponse().read().decode())
" "$SOCK_PATH" "$@" 2>/dev/null || true
}

ensure_worker_running() {
  if [ -S "$SOCK_PATH" ]; then
    # socket 存在，检查是否活着
    send_to_worker GET /status > /dev/null 2>&1 && return 0
    # 死了，清理
    rm -f "$SOCK_PATH"
  fi
  # 启动 worker
  python3 "$SCRIPT_DIR/worker-service.py" &
  sleep 0.5
}

# 从 hook 环境提取工具摘要
extract_tool_summary() {
  # Claude Code hook 会通过 stdin 或环境变量传递工具信息
  # 提取工具名、文件路径、output 前 200 字
  python3 -c "
import json, sys, os
tool_name = os.environ.get('TOOL_NAME', 'unknown')
tool_input = os.environ.get('TOOL_INPUT', '{}')
tool_output = os.environ.get('TOOL_OUTPUT', '')[:200]
files = []
try:
    inp = json.loads(tool_input)
    for k in ('file_path', 'path', 'command'):
        if k in inp:
            files.append(str(inp[k]))
except Exception:
    pass
print(json.dumps({
    'tool': tool_name,
    'files': files,
    'summary': f'{tool_name}: {tool_output[:200]}',
}))
" 2>/dev/null || echo '{"tool":"unknown","files":[],"summary":"extraction failed"}'
}

case "${1:-}" in
  session-start)
    ensure_worker_running
    send_to_worker POST /session/start \
      "{\"claude_session_id\": \"$CLAUDE_SID\", \"project\": \"$(pwd)\"}"
    ;;
  observe)
    TOOL_INFO=$(extract_tool_summary)
    CONTENT=$(echo "$TOOL_INFO" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('summary',''))")
    TOOL=$(echo "$TOOL_INFO" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool',''))")
    send_to_worker POST /observe \
      "{\"claude_session_id\": \"$CLAUDE_SID\", \"content\": \"$CONTENT\", \"tool\": \"$TOOL\"}" &
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
  *)
    echo "Usage: $0 {session-start|observe|flush|session-end}" >&2
    exit 1
    ;;
esac
```

```bash
chmod +x plugin/scripts/hook-handler.sh
```

- [ ] **Step 4: Commit**

```bash
git add plugin/
git commit -m "feat(plugin): hooks.json, .mcp.json, hook-handler.sh"
```

---

### Task 9: Engram 文档同步

**Files:**
- Modify: `Engram：分布式记忆操作系统与协作协议.md`

- [ ] **Step 1: 更新顶层路线图**

在 L11-14 的版本表中插入 v0.3 行，v0.5 调整：

```markdown
| **v0.2**（1-2 月） | Agent-Runtime 集成层 | Session Lifecycle、统一 Memory API（7 工具）、Observation Pipeline | Ch23.2.1 |
| **v0.3**（+1 月） | Runtime 集成闭环 | MCP Server、Plugin + Hooks 自动注册、Worker Service | Ch23.2.2 |
| **v0.5**（+2 月） | 三轨架构重写 | 三轨节律、CQRS、六态状态机、LLM 抽象化、Function Schema、Fork/PR/Merge | Ch23.3 |
```

- [ ] **Step 2: 更新能力矩阵**

在 23.3 能力矩阵中：
- MCP Server 从 v0.5 列的 Y 提前到 v0.3 列
- 新增行：Plugin Hooks 自动注册、Worker Service（异步 Observation）

- [ ] **Step 3: 更新 23.2.1.7 砍掉清单**

将"v0.3"引用改为"见 23.2.2 节"。

- [ ] **Step 4: 新增 23.2.2 节**

在 23.2.1 之后、23.3 之前，新增 v0.3 完整设计章节。内容从 spec 文件提取核心要点（架构图、Worker API、MCP Tools/Resources/Prompts、Plugin 结构、落地顺序）。

- [ ] **Step 5: Commit**

```bash
git add "Engram：分布式记忆操作系统与协作协议.md"
git commit -m "docs: add v0.3 to Engram roadmap and capability matrix"
```

---

### Task 10: 全量回归 + 端到端验证

**Files:**
- 无新增，验证所有测试通过

- [ ] **Step 1: 运行全部测试**

Run: `pytest tests/ -v`
Expected: 所有测试 PASS（v0.2 原有 62 个 + v0.3 新增约 12 个）

- [ ] **Step 2: 手动端到端验证 Worker**

```bash
# 终端 1：启动 Worker
MEMENTO_DB=/tmp/e2e-test.db python3 plugin/scripts/worker-service.py

# 终端 2：模拟 hook 调用
export MEMENTO_DB=/tmp/e2e-test.db
plugin/scripts/hook-handler.sh session-start
plugin/scripts/hook-handler.sh observe
plugin/scripts/hook-handler.sh flush
plugin/scripts/hook-handler.sh session-end

# 验证
memento status  # 应显示 1 个 session、至少 1 个 observation
```

- [ ] **Step 3: 清理测试数据**

```bash
rm -f /tmp/e2e-test.db /tmp/memento-worker-*.sock
```

- [ ] **Step 4: Final commit**

```bash
git commit --allow-empty -m "chore: v0.3 implementation complete — MCP + Worker + Plugin"
```
