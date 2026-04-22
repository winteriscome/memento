"""统一 Memory API — 协议抽象层。

v0.5.0 架构：
  MementoAPIBase   — 协议抽象（定义操作接口，ABC）
  LocalAPI         — 直连 DB（epoch 子进程、离线 CLI、MCP Server）
  WorkerClientAPI  — 走 Unix Socket 到 Worker（占位，v0.5.1 实现）
  MementoAPI       — LocalAPI 的别名，保持向后兼容

CLI / MCP / Function Schema 都走这层。
"""

from __future__ import annotations

import http.client
import json
import socket
import sqlite3
import subprocess
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from memento.core import MementoCore, RecallResult
from memento.observation import IngestResult, ingest_observation
from memento.session import SessionEndResult, SessionInfo, SessionService, SessionStartResult


@dataclass
class StatusResult:
    """status() 返回值。"""
    total: int = 0
    active: int = 0
    forgotten: int = 0
    unverified_agent: int = 0
    with_embedding: int = 0
    pending_embedding: int = 0
    total_sessions: int = 0
    active_sessions: int = 0
    completed_sessions: int = 0
    total_observations: int = 0
    # v0.5 新增字段
    by_state: dict = field(default_factory=dict)
    pending_capture: int = 0
    pending_delta: int = 0
    pending_recon: int = 0
    cognitive_debt_count: int = 0
    last_epoch_committed_at: str | None = None
    decay_watermark: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "StatusResult":
        return cls(
            total=data.get("total", 0),
            active=data.get("active", 0),
            forgotten=data.get("forgotten", 0),
            unverified_agent=data.get("unverified_agent", 0),
            with_embedding=data.get("with_embedding", 0),
            pending_embedding=data.get("pending_embedding", 0),
            total_sessions=data.get("total_sessions", 0),
            active_sessions=data.get("active_sessions", 0),
            completed_sessions=data.get("completed_sessions", 0),
            total_observations=data.get("total_observations", 0),
            by_state=data.get("by_state", {}),
            pending_capture=data.get("pending_capture", 0),
            pending_delta=data.get("pending_delta", 0),
            pending_recon=data.get("pending_recon", 0),
            cognitive_debt_count=data.get("cognitive_debt_count", 0),
            last_epoch_committed_at=data.get("last_epoch_committed_at"),
            decay_watermark=data.get("decay_watermark"),
        )


class MementoAPIBase(ABC):
    """协议抽象 — 定义操作接口。

    LocalAPI 和 WorkerClientAPI 都实现此接口。
    """

    # ── Memory Operations ──

    @abstractmethod
    def capture(self, content, type='fact', tags=None, importance='normal',
                origin='human', session_id=None, event_id=None):
        ...

    @abstractmethod
    def recall(self, query, max_results=5, **kwargs):
        ...

    @abstractmethod
    def forget(self, target_id):
        ...

    @abstractmethod
    def verify(self, engram_id):
        ...

    @abstractmethod
    def status(self):
        ...

    @abstractmethod
    def close(self):
        ...

    # ── Session Lifecycle ──

    @abstractmethod
    def session_start(self, project=None, task=None, metadata=None, **kwargs):
        ...

    @abstractmethod
    def session_end(self, session_id, outcome='completed', summary=None):
        ...

    # ── Observation ──

    @abstractmethod
    def ingest_observation(self, content: str, tool: str = None,
                           files: list = None, importance: str = 'normal') -> None:
        ...


class LocalAPI(MementoAPIBase):
    """直连 DB — 用于 epoch 子进程、离线 CLI、MCP Server。

    保持对旧 MementoAPI 的完整向后兼容：
    - self.core 仍可用（MCP server 等依赖 api.core.conn）
    - recall/capture/forget/verify 既可走旧的 MementoCore 路径
      也可走新的 awake_* 路径（通过 use_awake 参数控制）
    """

    # ── Three-layer priming constants ──
    L0_BUDGET = 3
    L1_BUDGET = 2
    PRIMING_MAX_DEFAULT = 7
    MIN_L1_THRESHOLD = 0.15

    def __init__(self, db_path: Path | str | None = None, *, use_awake: bool = True):
        """初始化 LocalAPI。

        Args:
            db_path: 数据库路径，None 使用默认路径
            use_awake: True 时 capture/recall/forget/verify 走 awake_* 函数
                       （写 capture_log 而非直接写 engrams）
        """
        from memento.migration import migrate_v03_to_v05, migrate_v05_to_v092

        db_path = Path(db_path) if db_path else None
        self.core = MementoCore(db_path=db_path)
        self.conn = self.core.conn
        self._session_svc = SessionService(self.conn)
        self._use_awake = use_awake

        # 运行 v0.3→v0.5 迁移（幂等）
        migrate_v03_to_v05(self.conn)
        migrate_v05_to_v092(self.conn)

    def close(self):
        self.core.close()

    # ── Session Lifecycle ──

    def session_start(
        self,
        project: str | None = None,
        task: str | None = None,
        metadata: dict | None = None,
        priming_query: str | None = None,
        priming_max: int | None = None,
    ) -> SessionStartResult:
        """创建会话，使用三层 priming (L0/L1/L2) 注入相关记忆。

        L0 (Identity): preference/convention — sorted by raw strength
        L1 (Core Memory): decision/fact/insight — sorted by effective_strength
        L2 (Task): query-based recall — fills remaining budget
        """
        if priming_max is None:
            priming_max = self.PRIMING_MAX_DEFAULT

        session_id = self._session_svc.start(
            project=project, task=task, metadata=metadata
        )

        conn = self.core.conn
        priming: list[dict] = []

        # ── L0 (Identity) ─────────────────────────────────────────
        from memento.awake import awake_recall_by_type

        l0_candidates = awake_recall_by_type(
            conn, types=["preference", "convention"],
            project=project, order_by="strength",
        )
        l0 = self._select_l0(l0_candidates, self.L0_BUDGET)
        for m in l0:
            m["layer"] = "L0"
        priming.extend(l0)

        # ── L1 (Core Memory) ──────────────────────────────────────
        l0_ids = {m["id"] for m in l0}

        l1_candidates = awake_recall_by_type(
            conn, types=["decision", "fact", "insight"],
            project=project, order_by="last_accessed",
        )
        l1 = self._select_l1(l1_candidates, self.L1_BUDGET, exclude_ids=l0_ids)
        for m in l1:
            m["layer"] = "L1"
        priming.extend(l1)

        # ── L2 (Task) ─────────────────────────────────────────────
        l2_budget = priming_max - len(l0) - len(l1)
        exclude_ids = l0_ids | {m["id"] for m in l1}

        if l2_budget > 0:
            query = priming_query or task or project or "项目概况"
            l2_raw = self.recall(query, max_results=l2_budget + len(exclude_ids))
            # Deduplicate: exclude L0+L1 ids
            l2 = []
            for m in l2_raw:
                # self.recall() returns list[dict] when _use_awake=True
                mid = m["id"] if isinstance(m, dict) else m.id
                if mid in exclude_ids:
                    continue
                if not isinstance(m, dict):
                    m = {
                        "id": m.id, "content": m.content, "type": m.type,
                        "tags": m.tags, "strength": m.strength,
                        "importance": m.importance, "origin": m.origin,
                    }
                m["layer"] = "L2"
                l2.append(m)
                if len(l2) >= l2_budget:
                    break
            priming.extend(l2)

        return SessionStartResult(
            session_id=session_id,
            priming_memories=priming,
            project=project,
            task=task,
        )

    def _select_l0(self, candidates: list[dict], budget: int) -> list[dict]:
        """L0: preference top-1 + convention top-1 + wildcard top-1."""
        pref = [c for c in candidates if c.get("type") == "preference"]
        conv = [c for c in candidates if c.get("type") == "convention"]
        selected = []
        if pref:
            selected.append(pref[0])
        if conv:
            selected.append(conv[0])
        selected_ids = {m["id"] for m in selected}
        remaining = [c for c in candidates if c["id"] not in selected_ids]
        if remaining and len(selected) < budget:
            selected.append(remaining[0])
        return selected[:budget]

    def _select_l1(self, candidates: list[dict], budget: int, exclude_ids: set) -> list[dict]:
        """L1: decision/fact/insight, top-2 by effective_strength."""
        from datetime import datetime
        from memento.decay import effective_strength as compute_eff_strength
        from memento.rigidity import RIGIDITY_DEFAULTS
        now = datetime.now()
        scored = []
        for c in candidates:
            if c["id"] in exclude_ids:
                continue
            rigidity = c.get("rigidity") or RIGIDITY_DEFAULTS.get(c.get("type", "fact"), 0.5)
            eff = compute_eff_strength(
                strength=c["strength"], last_accessed=c.get("last_accessed", now.isoformat()),
                access_count=c.get("access_count", 0), importance=c.get("importance", "normal"),
                now=now, rigidity=rigidity,
            )
            if eff >= self.MIN_L1_THRESHOLD:
                c["_eff_strength"] = eff
                scored.append(c)
        by_type: dict[str, list[dict]] = {}
        for c in scored:
            by_type.setdefault(c["type"], []).append(c)
        per_type_tops = []
        for t, group in by_type.items():
            group.sort(key=lambda x: x["_eff_strength"], reverse=True)
            per_type_tops.append(group[0])
        per_type_tops.sort(key=lambda x: x["_eff_strength"], reverse=True)
        result = per_type_tops[:budget]
        for r in result:
            r.pop("_eff_strength", None)
        return result

    def session_end(
        self,
        session_id: str,
        outcome: str = "completed",
        summary: str | None = None,
    ) -> SessionEndResult | None:
        """结束会话。summary 默认存入 sessions 表；如果显式 capture/observation 不足（<2），
        自动将 summary 补录为低信任 capture（origin='agent'，strength 上限 0.5）。
        去重方式为 content hash（保守级，非语义去重）。"""
        result = self._session_svc.end(
            session_id=session_id, outcome=outcome, summary=summary
        )
        if result is None:
            return None

        # ── Auto-summary fallback ──────────────────────────────────
        # Count actual captures + observations for this session (awake mode
        # writes to capture_log without session_events, so we query directly)
        auto_count = 0
        if summary:
            explicit_captures = self.core.conn.execute(
                "SELECT COUNT(*) FROM capture_log WHERE source_session_id = ?",
                (session_id,),
            ).fetchone()[0]
            explicit_obs = result.observations_count
            if (explicit_captures + explicit_obs) < 2:
                import hashlib
                content_hash = hashlib.sha256(
                    summary.strip().lower().encode()
                ).hexdigest()

                if not self._session_svc.has_capture_hash(session_id, content_hash):
                    from memento.awake import awake_capture
                    awake_capture(
                        self.core.conn,
                        content=summary,
                        type="insight",
                        importance="normal",
                        origin="agent",
                        session_id=session_id,
                    )
                    auto_count = 1

        result.auto_captures_count = auto_count
        return result

    def session_status(self, session_id: str | None = None) -> SessionInfo | None:
        """查看指定会话详情，或获取当前活跃会话。"""
        if session_id:
            return self._session_svc.get(session_id)
        return self._session_svc.get_active_session()

    def session_list(
        self,
        project: str | None = None,
        limit: int = 10,
    ) -> list[SessionInfo]:
        """列出最近会话。"""
        return self._session_svc.list_sessions(project=project, limit=limit)

    # ── Memory Operations ──

    def recall(
        self,
        query: str,
        max_results: int = 5,
        reinforce: bool = False,
    ) -> list:
        """检索记忆。默认只读。

        use_awake=True 时返回 list[dict]（awake_recall），
        否则返回 list[RecallResult]（MementoCore.recall）。
        """
        if self._use_awake:
            from memento.awake import awake_recall
            return awake_recall(self.conn, query, max_results=max_results)

        return self.core.recall(
            query, max_results=max_results, reinforce=reinforce
        )

    def capture(
        self,
        content: str,
        type: str = "fact",
        importance: str = "normal",
        tags: list[str] | None = None,
        origin: str = "human",
        session_id: str | None = None,
        event_id: str | None = None,
    ) -> str | dict:
        """写入长期记忆。

        use_awake=True 时写入 capture_log（返回 dict），
        否则直接写 engrams（返回 engram_id str）。
        """
        if self._use_awake:
            from memento.awake import awake_capture
            return awake_capture(
                self.conn, content, type=type, tags=tags,
                importance=importance, origin=origin,
                session_id=session_id, event_id=event_id,
            )

        # 旧路径：直接写 engrams
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

    def ingest_observation(
        self,
        content: str,
        tool: str | None = None,
        files: list[str] | None = None,
        tags: list[str] | None = None,
        session_id: str | None = None,
        importance: str = "normal",
    ) -> IngestResult:
        """一级 API。接收 observation，经 pipeline 处理。"""
        return ingest_observation(
            self.core.conn,
            content=content,
            tool=tool,
            files=files,
            tags=tags,
            session_id=session_id,
            importance=importance,
        )

    # ── Utility ──

    def status(self) -> StatusResult:
        """数据库统计（含 v0.5 新增字段）。"""
        raw = self.core.status()
        result = StatusResult(
            total=raw.get("total", 0) or 0,
            active=raw.get("active", 0) or 0,
            forgotten=raw.get("forgotten", 0) or 0,
            unverified_agent=raw.get("unverified_agent", 0) or 0,
            with_embedding=raw.get("with_embedding", 0) or 0,
            pending_embedding=raw.get("pending_embedding", 0) or 0,
            total_sessions=raw.get("total_sessions", 0) or 0,
            active_sessions=raw.get("active_sessions", 0) or 0,
            completed_sessions=raw.get("completed_sessions", 0) or 0,
            total_observations=raw.get("total_observations", 0) or 0,
        )

        # v0.5 新增：by_state counts
        try:
            state_rows = self.conn.execute(
                "SELECT state, COUNT(*) as cnt FROM engrams GROUP BY state"
            ).fetchall()
            result.by_state = {r["state"]: r["cnt"] for r in state_rows}
        except Exception:
            pass

        # pending_capture
        try:
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM capture_log WHERE epoch_id IS NULL"
            ).fetchone()
            result.pending_capture = row["cnt"] if row else 0
        except Exception:
            pass

        # pending_delta
        try:
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM delta_ledger WHERE epoch_id IS NULL"
            ).fetchone()
            result.pending_delta = row["cnt"] if row else 0
        except Exception:
            pass

        # pending_recon
        try:
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM recon_buffer "
                "WHERE nexus_consumed_epoch_id IS NULL OR content_consumed_epoch_id IS NULL"
            ).fetchone()
            result.pending_recon = row["cnt"] if row else 0
        except Exception:
            pass

        # cognitive_debt_count
        try:
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM cognitive_debt WHERE resolved_at IS NULL"
            ).fetchone()
            result.cognitive_debt_count = row["cnt"] if row else 0
        except Exception:
            pass

        # last_epoch_committed_at
        try:
            row = self.conn.execute(
                "SELECT committed_at FROM epochs "
                "WHERE status IN ('committed', 'degraded') "
                "ORDER BY committed_at DESC LIMIT 1"
            ).fetchone()
            result.last_epoch_committed_at = row["committed_at"] if row else None
        except Exception:
            pass

        # decay_watermark
        try:
            row = self.conn.execute(
                "SELECT value FROM runtime_cursors WHERE key='decay_watermark'"
            ).fetchone()
            result.decay_watermark = row["value"] if row else None
        except Exception:
            pass

        return result

    def forget(self, engram_id: str) -> bool | dict:
        """软删除记忆。

        use_awake=True 时走 pending_forget 队列（返回 dict），
        否则直接标记 forgotten（返回 bool）。
        """
        if self._use_awake:
            from memento.awake import awake_forget
            return awake_forget(self.conn, engram_id)

        return self.core.forget(engram_id)

    def verify(self, engram_id: str) -> bool | dict:
        """人类确认 Agent 记忆为可信。"""
        if self._use_awake:
            from memento.awake import awake_verify
            return awake_verify(self.conn, engram_id)

        return self.core.verify(engram_id)

    # ── Dashboard-specific queries ──

    def list_engrams(
        self,
        type: str | None = None,
        origin: str | None = None,
        importance: str | None = None,
        verified: bool | None = None,
        sort: str = "created_at",
        order: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Dashboard-specific list/filter/pagination for engrams."""
        conditions = [
            "forgotten = 0",
            "id NOT IN (SELECT target_id FROM pending_forget WHERE target_table = 'engrams')",
        ]
        params: list = []

        if type:
            types = [t.strip() for t in type.split(",")]
            placeholders = ",".join("?" * len(types))
            conditions.append(f"type IN ({placeholders})")
            params.extend(types)
        if origin:
            conditions.append("origin = ?")
            params.append(origin)
        if importance:
            conditions.append("importance = ?")
            params.append(importance)
        if verified is not None:
            conditions.append("verified = ?")
            params.append(1 if verified else 0)

        where = " AND ".join(conditions)
        allowed_sorts = {"created_at", "strength", "access_count", "last_accessed"}
        if sort not in allowed_sorts:
            sort = "created_at"
        if order not in ("asc", "desc"):
            order = "desc"
        limit = min(max(1, limit), 200)
        offset = max(0, offset)

        query = f"""
            SELECT id, content, type, tags, strength, importance, origin,
                   verified, created_at, last_accessed, access_count,
                   COALESCE(rigidity, 0.0) as rigidity
            FROM engrams
            WHERE {where}
            ORDER BY {sort} {order}
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        rows = self.conn.execute(query, params).fetchall()

        results = []
        for row in rows:
            d = dict(row)
            tags_raw = d.get("tags")
            if isinstance(tags_raw, str):
                try:
                    import json as _json
                    d["tags"] = _json.loads(tags_raw)
                except (ValueError, TypeError):
                    d["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]
            elif tags_raw is None:
                d["tags"] = []
            d["verified"] = bool(d.get("verified"))
            d["provisional"] = False
            results.append(d)
        return results

    def list_pending_captures(self, limit: int = 50) -> list[dict]:
        """List unconsumed captures in L2 buffer (capture_log)."""
        try:
            rows = self.conn.execute(
                """SELECT id, content, type, tags, importance, origin,
                          created_at, source_session_id
                   FROM capture_log
                   WHERE epoch_id IS NULL
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                tags_raw = d.get("tags")
                if isinstance(tags_raw, str):
                    try:
                        import json as _json
                        d["tags"] = _json.loads(tags_raw)
                    except (ValueError, TypeError):
                        d["tags"] = []
                elif tags_raw is None:
                    d["tags"] = []
                results.append(d)
            return results
        except Exception:
            return []

    # ── v0.5 新增方法 ──

    def inspect(self, engram_id: str) -> dict | None:
        """检查单条 engram 的详细信息，含 nexus 连接和 pending 状态。"""
        row = self.conn.execute(
            "SELECT * FROM engrams WHERE id=?", (engram_id,)
        ).fetchone()
        if not row:
            return None

        result = dict(row)

        # Nexus connections
        try:
            nexus = self.conn.execute(
                "SELECT * FROM nexus WHERE source_id=? OR target_id=?",
                (engram_id, engram_id),
            ).fetchall()
            result["nexus"] = [dict(n) for n in nexus]
        except Exception:
            result["nexus"] = []

        # Pending forget flag
        try:
            pf = self.conn.execute(
                "SELECT * FROM pending_forget WHERE target_id=?",
                (engram_id,),
            ).fetchone()
            result["pending_forget"] = pf is not None
        except Exception:
            result["pending_forget"] = False

        return result

    def pin(self, engram_id: str, rigidity: float) -> dict:
        """钉住一条 engram，设置 rigidity 值。"""
        from memento.awake import awake_pin
        return awake_pin(self.conn, engram_id, rigidity)

    def epoch_run(self, mode: str = 'full', trigger: str = 'manual') -> dict:
        """触发一次 epoch 运行。"""
        from memento.epoch import acquire_lease, run_epoch_phases
        from memento.llm import LLMClient

        epoch_id = acquire_lease(self.conn, 'default', mode, trigger)
        if not epoch_id:
            return {"error": "Another epoch is running"}

        llm = LLMClient.from_config() if mode == 'full' else None
        if mode == 'full' and llm is None:
            mode = 'light'
            # Fix 4: Update epochs table to reflect actual mode after degradation
            self.conn.execute(
                "UPDATE epochs SET mode = 'light' WHERE id = ?", (epoch_id,)
            )
            self.conn.commit()

        run_epoch_phases(self.conn, epoch_id, mode=mode, llm_client=llm)
        return {"epoch_id": epoch_id, "status": "completed", "mode": mode}

    def epoch_status(self) -> list[dict]:
        """查看最近 epoch 运行记录。"""
        try:
            rows = self.conn.execute(
                "SELECT * FROM epochs ORDER BY lease_acquired DESC LIMIT 10"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def epoch_debt(self) -> dict:
        """查看未解决的 cognitive debt 按类型统计。"""
        try:
            rows = self.conn.execute(
                "SELECT type, COUNT(*) as cnt FROM cognitive_debt "
                "WHERE resolved_at IS NULL GROUP BY type"
            ).fetchall()
            return {r["type"]: r["cnt"] for r in rows}
        except Exception:
            return {}

    # ── Export / Import (updated in Task 16) ──

    def export_memories(self, **filters) -> list[dict]:
        """导出记忆。"""
        from memento.export import export_memories
        return export_memories(self.core, **filters)

    def import_memories(self, data: list[dict], source: str | None = None) -> dict:
        """导入记忆。"""
        from memento.export import import_memories
        return import_memories(self.core, data, source=source)


# ── 向后兼容别名 ──
# 旧代码 `from memento.api import MementoAPI` 和 `MementoAPI(db_path=...)` 继续工作
MementoAPI = LocalAPI


class WorkerClientAPI(MementoAPIBase):
    """Unix Socket HTTP client to Worker process."""

    def __init__(self, socket_path: str):
        self.socket_path = socket_path
        self.external_session_id = str(uuid.uuid4())

    def _request(self, method: str, path: str, body: dict = None):
        """Send HTTP request over Unix Domain Socket."""
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect(self.socket_path)
        except (FileNotFoundError, ConnectionRefusedError, OSError) as e:
            raise ConnectionError(f"Worker not running at {self.socket_path}: {e}")

        try:
            conn = http.client.HTTPConnection("localhost")
            conn.sock = sock
            headers = {"Content-Type": "application/json"}
            body_bytes = json.dumps(body).encode() if body else None
            conn.request(method, path, body=body_bytes, headers=headers)
            resp = conn.getresponse()
            data = resp.read().decode()
            if resp.status >= 400:
                raise RuntimeError(f"Worker returned {resp.status}: {data}")
            if not data or data.strip() == "":
                return None
            return json.loads(data)
        finally:
            sock.close()

    def capture(self, content, type='fact', tags=None, importance='normal',
                origin='human', session_id=None, event_id=None):
        return self._request("POST", "/capture", {
            "content": content, "type": type, "tags": tags,
            "importance": importance, "origin": origin,
        })

    def recall(self, query, max_results=5, **kwargs):
        return self._request("POST", "/recall", {"query": query, "max_results": max_results})

    def forget(self, target_id):
        return self._request("POST", "/forget", {"target_id": target_id})

    def verify(self, engram_id):
        return self._request("POST", "/verify", {"engram_id": engram_id})

    def status(self):
        data = self._request("GET", "/status")
        return StatusResult.from_dict(data) if data else StatusResult()

    def inspect(self, engram_id):
        return self._request("POST", "/inspect", {"engram_id": engram_id})

    def pin(self, engram_id, rigidity):
        return self._request("POST", "/pin", {"engram_id": engram_id, "rigidity": rigidity})

    def session_start(self, project=None, task=None, metadata=None, **kwargs):
        data = self._request("POST", "/session/start", {
            "external_session_id": self.external_session_id,
            "project": project, "task": task,
        })
        return SessionStartResult.from_dict(data) if data else SessionStartResult(session_id="")

    def session_end(self, session_id, outcome='completed', summary=None):
        """session_id ignored — Worker uses external_session_id for routing."""
        data = self._request("POST", "/session/end", {
            "external_session_id": self.external_session_id,
            "outcome": outcome, "summary": summary,
        })
        return SessionEndResult.from_dict(data) if data else SessionEndResult(session_id="", status="error")

    def ingest_observation(self, content, tool=None, files=None, importance='normal'):
        self._request("POST", "/observe", {
            "external_session_id": self.external_session_id,
            "content": content, "tool": tool, "files": files,
        })

    def epoch_run(self, mode='full', trigger='manual'):
        result = subprocess.run(
            ['memento', 'epoch', 'run', '--mode', mode, '--trigger', trigger],
            capture_output=True, text=True, timeout=3600,
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        epochs = self._request("GET", "/epochs")
        if epochs and len(epochs) > 0:
            latest = epochs[0]
            return {"epoch_id": latest.get("id"), "status": latest.get("status", "completed"), "mode": latest.get("mode", mode)}
        return {"status": "completed", "mode": mode}

    def epoch_status(self):
        return self._request("GET", "/epochs") or []

    def epoch_debt(self):
        return self._request("GET", "/debt") or {}

    def close(self):
        pass
