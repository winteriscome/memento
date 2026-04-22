"""Worker Service — Awake track (DB thread) + Subconscious track + HTTP routes。

v0.5 架构：
- DBThread: Awake track，独占 Connection A，处理 cmd_queue + obs_queue
- SubconsciousTrack: 后台线程，独占 Connection B，消费 pulse_queue + 运行 decay
- WorkerServer: Unix Socket HTTP Server，路由请求到 DBThread
- pulse_queue: Python Queue，连接 Awake → Subconscious
"""

import hashlib
import http.server
import json
import os
import queue
import socketserver
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from memento.api import MementoAPI
from memento.db import get_db_path
from memento.logging import get_logger

logger = get_logger("memento.worker")


def _get_external_sid(kwargs: dict) -> str:
    """Extract external_session_id from kwargs (backward compat with claude_session_id)."""
    sid = kwargs.pop("external_session_id", None)
    if sid is not None:
        return sid
    return kwargs.pop("claude_session_id", "default")


@dataclass
class Command:
    """同步命令：主线程投入，DB 线程执行，通过 Event 返回结果。"""
    action: str
    kwargs: dict = field(default_factory=dict)
    result: Any = None
    error: Optional[Exception] = None
    done: threading.Event = field(default_factory=threading.Event)


class DBThread(threading.Thread):
    """Awake track — 独占 DB Connection 的后台线程。

    同时消费两个队列：
    - obs_queue：observation 异步处理（fire-and-forget）
    - cmd_queue：同步命令（session_start/end, capture, recall, etc.），处理完通过 Event 返回

    v0.5 新增：
    - pulse_queue: 可选，传递给 awake_recall 用于生成 PulseEvent
    - 新 action dispatch: capture/recall/forget/verify/inspect/pin 走 awake_* 函数
    """

    def __init__(self, db_path: Path | None = None, pulse_queue: queue.Queue | None = None):
        super().__init__(daemon=True)
        self._db_path = db_path
        self._obs_queue: queue.Queue = queue.Queue()
        self._cmd_queue: queue.Queue = queue.Queue()
        self._running = True
        self._api: Optional[MementoAPI] = None
        # Session Registry: external_session_id → memento_session_id
        self.session_registry: dict[str, str] = {}
        # v0.5: pulse_queue for Awake → Subconscious
        self.pulse_queue = pulse_queue
        # Init event: set after DB connection is established (or fails)
        self.init_event = threading.Event()
        self.init_error: Optional[Exception] = None

    def run(self):
        """DB 线程主循环：独占 Connection，交替消费两个队列。"""
        try:
            self._api = MementoAPI(db_path=self._db_path, use_awake=True)
        except Exception as e:
            logger.error(f"Failed to initialize DBThread: {e}", exc_info=True)
            self.init_error = e
            return  # Exit thread, don't enter main loop
        finally:
            self.init_event.set()  # Always signal completion

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
        """同步执行命令（主线程调用，阻塞等待结果）。"""
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
                result = {
                    "total": raw.total,
                    "active": raw.active,
                    "total_sessions": raw.total_sessions,
                    "active_sessions": raw.active_sessions,
                    "total_observations": raw.total_observations,
                    "db_path": str(self._db_path or get_db_path()),
                    "queue_depth": self.queue_depth,
                    "active_session_ids": list(self.session_registry.values()),
                    # v0.5 新增字段
                    "pending_capture": raw.pending_capture,
                    "pending_delta": raw.pending_delta,
                    "pending_recon": raw.pending_recon,
                    "cognitive_debt_count": raw.cognitive_debt_count,
                    "last_epoch_committed_at": raw.last_epoch_committed_at,
                    "decay_watermark": raw.decay_watermark,
                    "by_state": raw.by_state,
                }
                cmd.result = result
            elif cmd.action == "session_start":
                ext_sid = _get_external_sid(cmd.kwargs)
                # 降级模式（default）：新 start 自动结束旧 session
                if ext_sid == "default" and "default" in self.session_registry:
                    old_sid = self.session_registry.pop("default")
                    self._api.session_end(old_sid, outcome="abandoned")
                result = self._api.session_start(**cmd.kwargs)
                self.session_registry[ext_sid] = result.session_id
                cmd.result = {
                    "session_id": result.session_id,
                    "priming_count": len(result.priming_memories),
                    "priming_memories": [
                        {
                            "id": m.id,
                            "content": m.content,
                            "type": m.type,
                            "importance": m.importance,
                        }
                        for m in result.priming_memories
                    ],
                }
            elif cmd.action == "session_end":
                ext_sid = _get_external_sid(cmd.kwargs)
                memento_sid = self.session_registry.pop(ext_sid, None)
                if not memento_sid:
                    cmd.result = None
                    return
                result = self._api.session_end(memento_sid, **cmd.kwargs)
                cmd.result = {
                    "status": result.status if result else None,
                    "captures_count": result.captures_count if result else 0,
                    "observations_count": result.observations_count if result else 0,
                } if result else None

            # ── v0.5 Awake track dispatches ──

            elif cmd.action == "capture":
                from memento.awake import awake_capture
                ext_sid = _get_external_sid(cmd.kwargs)
                memento_sid = self.session_registry.get(ext_sid)
                cmd.kwargs["session_id"] = memento_sid
                cmd.result = awake_capture(self._api.conn, **cmd.kwargs)

            elif cmd.action == "recall":
                from memento.awake import awake_recall
                cmd.result = awake_recall(
                    self._api.conn,
                    query=cmd.kwargs.get("query", ""),
                    max_results=cmd.kwargs.get("max_results", 5),
                    pulse_queue=self.pulse_queue,
                )

            elif cmd.action == "forget":
                from memento.awake import awake_forget
                cmd.result = awake_forget(
                    self._api.conn,
                    target_id=cmd.kwargs["target_id"],
                )

            elif cmd.action == "verify":
                from memento.awake import awake_verify
                cmd.result = awake_verify(
                    self._api.conn,
                    engram_id=cmd.kwargs["engram_id"],
                )

            elif cmd.action == "inspect":
                cmd.result = self._handle_inspect(cmd.kwargs.get("engram_id", ""))

            elif cmd.action == "pin":
                from memento.awake import awake_pin
                cmd.result = awake_pin(
                    self._api.conn,
                    engram_id=cmd.kwargs["engram_id"],
                    rigidity=cmd.kwargs.get("rigidity", 0.5),
                )

            elif cmd.action == "nexus_query":
                cmd.result = self._handle_nexus_query(cmd.kwargs)

            elif cmd.action == "debt":
                cmd.result = self._handle_debt()

            elif cmd.action == "epoch_status":
                cmd.result = self._api.epoch_status()

            elif cmd.action == "flush":
                self._obs_queue.join()
                cmd.result = {"flushed": True, "remaining": 0}

            elif cmd.action == "transcript_get_context":
                from memento.transcript import CURSOR_KEY_PREFIX, EXTRACT_COOLDOWN
                from datetime import datetime, timezone as _tz
                session_id = cmd.kwargs.get("memento_session_id", "")
                cursor_key = CURSOR_KEY_PREFIX + session_id

                # Read cursor + durable cooldown from runtime_cursors
                last_offset = 0
                cooldown_ok = True
                try:
                    row = self._api.conn.execute(
                        "SELECT value, updated_at FROM runtime_cursors WHERE key = ?",
                        (cursor_key,),
                    ).fetchone()
                    if row:
                        last_offset = int(row["value"])
                        # Durable cooldown: check updated_at vs now
                        try:
                            last_dt = datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00"))
                            elapsed = (datetime.now(_tz.utc) - last_dt).total_seconds()
                            if elapsed < EXTRACT_COOLDOWN:
                                cooldown_ok = False
                        except Exception:
                            pass  # parse failure → allow extraction
                except Exception:
                    pass

                # Set durable lock immediately to prevent concurrent extractions
                if cooldown_ok:
                    try:
                        now = datetime.now(_tz.utc).isoformat()
                        self._api.conn.execute(
                            "INSERT OR REPLACE INTO runtime_cursors (key, value, updated_at) VALUES (?, ?, ?)",
                            (cursor_key, str(last_offset), now),
                        )
                        self._api.conn.commit()
                    except Exception as e:
                        import logging
                        logging.getLogger("memento.worker").error(f"Failed to set durable lock: {e}")

                # Read top 30 existing memories for dedup context
                existing_summary = "（暂无已有记忆）"
                try:
                    rows = self._api.conn.execute(
                        """SELECT type, content FROM view_engrams
                           WHERE forgotten = 0
                           ORDER BY strength DESC
                           LIMIT 30"""
                    ).fetchall()
                    if rows:
                        summary_lines = [f"- [{r['type']}] {r['content'][:80]}" for r in rows]
                        existing_summary = "\n".join(summary_lines)
                except Exception:
                    pass

                cmd.result = {
                    "last_offset": last_offset,
                    "existing_memories_summary": existing_summary,
                    "cooldown_ok": cooldown_ok,
                }

            elif cmd.action == "transcript_persist":
                from memento.transcript import CURSOR_KEY_PREFIX
                from memento.awake import awake_capture
                from datetime import datetime, timezone
                import json as _json

                candidates = cmd.kwargs.get("candidates", [])
                new_offset = cmd.kwargs.get("new_offset", 0)
                session_id = cmd.kwargs.get("memento_session_id", "")
                written = 0

                for c in candidates:
                    content_hash = c.get("content_hash", "")
                    # Dedup: check capture_log
                    try:
                        dup = self._api.conn.execute(
                            "SELECT 1 FROM capture_log WHERE content_hash = ? LIMIT 1",
                            (content_hash,),
                        ).fetchone()
                        if dup:
                            continue
                    except Exception:
                        pass
                    # Dedup: check engrams
                    try:
                        dup = self._api.conn.execute(
                            "SELECT 1 FROM engrams WHERE content_hash = ? AND forgotten = 0 LIMIT 1",
                            (content_hash,),
                        ).fetchone()
                        if dup:
                            continue
                    except Exception:
                        pass

                    awake_capture(
                        self._api.conn,
                        content=c["content"],
                        type=c.get("type", "fact"),
                        tags=_json.dumps(["transcript-extracted"]),
                        importance=c.get("importance", "normal"),
                        origin="agent",
                        session_id=session_id,
                    )
                    written += 1

                # Update cursor
                cursor_key = CURSOR_KEY_PREFIX + session_id
                now = datetime.now(timezone.utc).isoformat()
                self._api.conn.execute(
                    "INSERT OR REPLACE INTO runtime_cursors (key, value, updated_at) VALUES (?, ?, ?)",
                    (cursor_key, str(new_offset), now),
                )
                self._api.conn.commit()

                cmd.result = {"written": written, "total_candidates": len(candidates)}

            else:
                cmd.error = ValueError(f"Unknown action: {cmd.action}")
        except Exception as e:
            logger.error(f"Error handling command {cmd.action}: {e}", exc_info=True)
            cmd.error = e
        finally:
            cmd.done.set()

    def _handle_inspect(self, engram_id: str) -> dict | None:
        """查询 engram 详情 + nexus 连接。"""
        conn = self._api.conn
        row = conn.execute(
            "SELECT * FROM engrams WHERE id=?", (engram_id,)
        ).fetchone()
        if not row:
            return None

        result = dict(row)

        # Nexus connections
        try:
            nexus = conn.execute(
                "SELECT * FROM nexus WHERE source_id=? OR target_id=?",
                (engram_id, engram_id),
            ).fetchall()
            result["nexus"] = [dict(n) for n in nexus]
        except Exception:
            result["nexus"] = []

        # Pending forget flag
        try:
            pf = conn.execute(
                "SELECT * FROM pending_forget WHERE target_id=?",
                (engram_id,),
            ).fetchone()
            result["pending_forget"] = pf is not None
        except Exception:
            result["pending_forget"] = False

        return result

    def _handle_nexus_query(self, kwargs: dict) -> list[dict]:
        """查询 nexus 图。"""
        conn = self._api.conn
        engram_id = kwargs.get("engram_id")
        nexus_type = kwargs.get("type")

        query = "SELECT * FROM view_nexus WHERE 1=1"
        params = []

        if engram_id:
            query += " AND (source_id=? OR target_id=?)"
            params.extend([engram_id, engram_id])

        if nexus_type:
            query += " AND type=?"
            params.append(nexus_type)

        query += " ORDER BY association_strength DESC LIMIT 50"

        try:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def _handle_debt(self) -> dict:
        """查询 cognitive debt 统计。"""
        conn = self._api.conn
        try:
            rows = conn.execute(
                "SELECT type, COUNT(*) as cnt FROM cognitive_debt "
                "WHERE resolved_at IS NULL GROUP BY type"
            ).fetchall()
            return {r["type"]: r["cnt"] for r in rows}
        except Exception:
            return {}

    def _handle_observation(self, obs: dict):
        """在 DB 线程内处理单条 observation。"""
        ext_sid = _get_external_sid(obs)
        memento_sid = self.session_registry.get(ext_sid)
        if not memento_sid:
            logger.warning(f"Dropping observation: no active session for {ext_sid}")
            return  # session 不存在，丢弃
        obs["session_id"] = memento_sid
        try:
            self._api.ingest_observation(**obs)
        except Exception as e:
            logger.error(f"Error ingesting observation: {e}", exc_info=True)
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


class _WorkerHandler(http.server.BaseHTTPRequestHandler):
    """处理 Unix Socket 上的 HTTP 请求。"""

    def log_message(self, format, *args):
        pass  # 静默日志

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    def _respond(self, data: dict | list, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode())

    def do_GET(self):
        if self.path == "/status":
            result = self.server.db_thread.execute("status")
            self._respond(result)
        elif self.path == "/debt":
            result = self.server.db_thread.execute("debt")
            self._respond(result)
        elif self.path == "/epochs":
            result = self.server.db_thread.execute("epoch_status")
            self._respond(result or [])
        else:
            self._respond({"error": "not found"}, 404)

    def do_POST(self):
        body = self._read_body()

        if self.path == "/session/start":
            result = self.server.db_thread.execute("session_start", **body)
            self._respond(result)

        elif self.path == "/session/end":
            self.server.db_thread.flush()
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

        elif self.path == "/recall":
            result = self.server.db_thread.execute("recall", **body)
            self._respond(result)

        elif self.path == "/forget":
            result = self.server.db_thread.execute("forget", **body)
            self._respond(result)

        elif self.path == "/verify":
            result = self.server.db_thread.execute("verify", **body)
            self._respond(result)

        elif self.path == "/inspect":
            result = self.server.db_thread.execute("inspect", **body)
            if result is None:
                self._respond({"error": "engram not found"}, 404)
            else:
                self._respond(result)

        elif self.path == "/nexus":
            result = self.server.db_thread.execute("nexus_query", **body)
            self._respond(result)

        elif self.path == "/pin":
            result = self.server.db_thread.execute("pin", **body)
            self._respond(result)

        elif self.path == "/flush":
            self.server.db_thread.flush()
            self._respond({"flushed": True, "remaining": 0})

        elif self.path == "/transcript/extract":
            import threading as _threading
            from memento.transcript import should_extract, run_extraction

            transcript_path = body.get("transcript_path", "")
            ext_sid = body.get("external_session_id") or body.get("claude_session_id", "")

            if not transcript_path or not Path(transcript_path).exists():
                self._respond({"status": "skipped", "reason": "no_transcript"})
                return

            # Map external_session_id → memento_session_id
            memento_session_id = self.server.db_thread.session_registry.get(ext_sid)
            if not memento_session_id:
                self._respond({"status": "skipped", "reason": "no_session"})
                return

            # Throttle
            if not should_extract(memento_session_id):
                self._respond({"status": "skipped", "reason": "cooldown"})
                return

            # Get context from DBThread (cursor + existing memories + durable cooldown)
            context = self.server.db_thread.execute(
                "transcript_get_context",
                memento_session_id=memento_session_id,
            )

            # Durable cooldown (survives Worker restart)
            if not context.get("cooldown_ok", True):
                self._respond({"status": "skipped", "reason": "cooldown_durable"})
                return

            # Define persist callback that submits back to DBThread
            db_thread_ref = self.server.db_thread
            sid = memento_session_id

            def persist_callback(candidates, new_offset):
                db_thread_ref.execute(
                    "transcript_persist",
                    candidates=candidates,
                    new_offset=new_offset,
                    memento_session_id=sid,
                )

            # Run extraction in background thread (file I/O + LLM only, no DB)
            _threading.Thread(
                target=run_extraction,
                args=(
                    transcript_path,
                    memento_session_id,
                    context["last_offset"],
                    context["existing_memories_summary"],
                    persist_callback,
                ),
                daemon=True,
            ).start()

            self._respond({"status": "accepted"})

        elif self.path == "/shutdown":
            flushed = self.server.db_thread.queue_depth
            self.server.db_thread.flush()
            self._respond({"flushed": flushed})
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        else:
            self._respond({"error": "not found"}, 404)


class WorkerServer(socketserver.UnixStreamServer):
    """Unix Domain Socket 上的 HTTP Server。

    v0.5: 管理 Awake track (DBThread) + Subconscious track 的生命周期。
    """

    allow_reuse_address = True

    def __init__(self, db_path: Path | None, sock_path: str, config: dict | None = None):
        config = config or {}

        # v0.5: pulse_queue connects Awake → Subconscious
        self.pulse_queue: queue.Queue = queue.Queue()

        # Awake track: DBThread with pulse_queue
        self.db_thread = DBThread(db_path, pulse_queue=self.pulse_queue)
        self.db_thread.start()

        # Wait for DBThread to fully initialize its connection before
        # starting SubconsciousTrack (Fix 2: prevent race condition)
        if not self.db_thread.init_event.wait(timeout=10):
            raise RuntimeError("DBThread initialization timed out after 10s")
        if self.db_thread.init_error is not None:
            raise RuntimeError(f"DBThread initialization failed: {self.db_thread.init_error}")

        # v0.5: Subconscious track
        self._subconscious = None
        if db_path is not None:
            from memento.subconscious import SubconsciousTrack
            from memento.db import get_connection

            def conn_factory():
                return get_connection(db_path)

            self._subconscious = SubconsciousTrack(conn_factory, self.pulse_queue, config)
            self._subconscious.start()

        # 清理 stale socket
        if os.path.exists(sock_path):
            os.unlink(sock_path)
        super().__init__(sock_path, _WorkerHandler)

    def shutdown_gracefully(self):
        """优雅关闭：先停 Subconscious，再停 Awake (DB 线程)，最后停 server。"""
        # Stop subconscious track first
        if self._subconscious is not None:
            self._subconscious.shutdown()

        # Stop awake track
        self.db_thread.shutdown()
        self.db_thread.join(timeout=10)

        # Stop HTTP server
        self.shutdown()
        if hasattr(self, "server_address") and os.path.exists(self.server_address):
            os.unlink(self.server_address)


def main():
    """Entry point for `memento-worker` console script."""
    import sys

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
