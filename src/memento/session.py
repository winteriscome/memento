"""Session lifecycle service — 会话一等对象管理。"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import sqlite3


@dataclass
class SessionStartResult:
    session_id: str
    priming_memories: list = field(default_factory=list)  # list[RecallResult] from core
    project: Optional[str] = None
    task: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "SessionStartResult":
        return cls(
            session_id=data["session_id"],
            priming_memories=data.get("priming_memories", []),
            project=data.get("project"),
            task=data.get("task"),
        )


@dataclass
class SessionEndResult:
    session_id: str
    status: str
    captures_count: int = 0
    observations_count: int = 0
    auto_captures_count: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "SessionEndResult":
        return cls(
            session_id=data.get("session_id", ""),
            status=data.get("status", "completed"),
            captures_count=data.get("captures_count", 0),
            observations_count=data.get("observations_count", 0),
            auto_captures_count=data.get("auto_captures_count", 0),
        )


@dataclass
class SessionInfo:
    id: str
    project: Optional[str]
    task: Optional[str]
    status: str
    started_at: str
    ended_at: Optional[str]
    summary: Optional[str]
    metadata: Optional[dict]
    event_counts: dict = field(default_factory=dict)


class SessionService:
    """管理 session 生命周期和事件流。"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def start(
        self,
        project: str | None = None,
        task: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """创建新会话，返回 session_id。"""
        session_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None

        self.conn.execute(
            """INSERT INTO sessions (id, project, task, status, started_at, metadata)
               VALUES (?, ?, ?, 'active', ?, ?)""",
            (session_id, project, task, now, metadata_json),
        )

        # 记录 start 事件
        self.append_event(
            session_id,
            "start",
            {"project": project, "task": task},
        )

        self.conn.commit()
        return session_id

    def end(
        self,
        session_id: str,
        outcome: str = "completed",
        summary: str | None = None,
    ) -> SessionEndResult | None:
        """结束会话。summary 存入 sessions.summary，不落 engrams。

        返回 None 如果 session_id 不存在。
        """
        now = datetime.now().isoformat()

        # 先验证 session 存在
        cursor = self.conn.execute(
            """UPDATE sessions
               SET status = ?, ended_at = ?, summary = ?
               WHERE id = ? AND status = 'active'""",
            (outcome, now, summary, session_id),
        )
        if cursor.rowcount == 0:
            return None

        # 统计本次会话的事件数
        counts = {}
        rows = self.conn.execute(
            """SELECT event_type, COUNT(*) as cnt
               FROM session_events WHERE session_id = ?
               GROUP BY event_type""",
            (session_id,),
        ).fetchall()
        for row in rows:
            counts[row["event_type"]] = row["cnt"]

        # 记录 end 事件
        self.append_event(
            session_id,
            "end",
            {
                "outcome": outcome,
                "captures_count": counts.get("capture", 0),
                "observations_count": counts.get("observation", 0),
            },
        )

        self.conn.commit()
        return SessionEndResult(
            session_id=session_id,
            status=outcome,
            captures_count=counts.get("capture", 0),
            observations_count=counts.get("observation", 0),
        )

    def append_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict | None = None,
        fingerprint: str | None = None,
    ) -> str:
        """追加标准化事件。返回 event_id。"""
        event_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        payload_json = json.dumps(payload, ensure_ascii=False) if payload else None

        self.conn.execute(
            """INSERT INTO session_events (id, session_id, event_type, payload, fingerprint, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (event_id, session_id, event_type, payload_json, fingerprint, now),
        )
        return event_id

    def get(self, session_id: str) -> SessionInfo | None:
        """获取会话详情。"""
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None

        # 获取事件统计
        event_rows = self.conn.execute(
            """SELECT event_type, COUNT(*) as cnt
               FROM session_events WHERE session_id = ?
               GROUP BY event_type""",
            (session_id,),
        ).fetchall()
        event_counts = {r["event_type"]: r["cnt"] for r in event_rows}

        metadata = json.loads(row["metadata"]) if row["metadata"] else None
        return SessionInfo(
            id=row["id"],
            project=row["project"],
            task=row["task"],
            status=row["status"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            summary=row["summary"],
            metadata=metadata,
            event_counts=event_counts,
        )

    def list_sessions(
        self,
        project: str | None = None,
        limit: int = 10,
    ) -> list[SessionInfo]:
        """列出最近会话。"""
        if project:
            rows = self.conn.execute(
                """SELECT * FROM sessions
                   WHERE project = ?
                   ORDER BY started_at DESC LIMIT ?""",
                (project, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT * FROM sessions
                   ORDER BY started_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()

        results = []
        for row in rows:
            metadata = json.loads(row["metadata"]) if row["metadata"] else None
            results.append(
                SessionInfo(
                    id=row["id"],
                    project=row["project"],
                    task=row["task"],
                    status=row["status"],
                    started_at=row["started_at"],
                    ended_at=row["ended_at"],
                    summary=row["summary"],
                    metadata=metadata,
                )
            )
        return results

    def get_active_session(self, project: str | None = None) -> SessionInfo | None:
        """获取当前活跃会话。"""
        if project:
            row = self.conn.execute(
                """SELECT * FROM sessions
                   WHERE status = 'active' AND project = ?
                   ORDER BY started_at DESC LIMIT 1""",
                (project,),
            ).fetchone()
        else:
            row = self.conn.execute(
                """SELECT * FROM sessions
                   WHERE status = 'active'
                   ORDER BY started_at DESC LIMIT 1""",
            ).fetchone()
        if not row:
            return None
        metadata = json.loads(row["metadata"]) if row["metadata"] else None
        return SessionInfo(
            id=row["id"],
            project=row["project"],
            task=row["task"],
            status=row["status"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            summary=row["summary"],
            metadata=metadata,
        )

    def has_capture_hash(self, session_id: str, content_hash: str) -> bool:
        """检查 capture_log 中是否已有相同 content_hash 的记录（用于 auto-summary 去重）。"""
        row = self.conn.execute(
            """SELECT 1 FROM capture_log
               WHERE source_session_id = ? AND content_hash = ?
               LIMIT 1""",
            (session_id, content_hash),
        ).fetchone()
        return row is not None

    def has_fingerprint(self, session_id: str, fingerprint: str) -> bool:
        """检查事件指纹是否在当前会话中已存在（用于去重）。"""
        row = self.conn.execute(
            """SELECT 1 FROM session_events
               WHERE session_id = ? AND fingerprint = ?
               LIMIT 1""",
            (session_id, fingerprint),
        ).fetchone()
        return row is not None
