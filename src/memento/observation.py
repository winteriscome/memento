"""Observation Ingestion Pipeline — 两段式去重 + 晋升策略。

observation 不是 capture 的变体，有独立的 pipeline：
  Stage 1: fingerprint 精确去重
  Stage 2: 语义相似度候选合并（附加 type+tags+files+时间窗口检查）
  Stage 3: 晋升决策（是否落 engrams）
"""

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from memento.embedding import get_embedding, vec_to_blob
from memento.session import SessionService


@dataclass
class IngestResult:
    event_id: str
    promoted: bool
    engram_id: Optional[str] = None
    merged_with: Optional[str] = None
    skipped: bool = False


def _normalize_content(content: str) -> str:
    """标准化内容用于 fingerprint 计算。"""
    text = content.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _fingerprint(content: str) -> str:
    """计算内容指纹。"""
    normalized = _normalize_content(content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def _check_semantic_candidate(
    conn: sqlite3.Connection,
    content: str,
    embedding_blob: bytes | None,
    dim: int | None,
    tags: list[str] | None,
    files: list[str] | None,
    threshold: float = 0.85,
) -> dict | None:
    """Stage 2: 语义相似度候选查找。

    返回匹配的 engram row dict，或 None。
    要求：相似度 > threshold，且 type+tags+files 三项至少匹配两项。
    """
    from memento.db import VEC_AVAILABLE

    if not embedding_blob or not dim or not VEC_AVAILABLE:
        return None

    try:
        rows = conn.execute(
            """SELECT e.*, vec_distance_cosine(e.embedding, ?) as distance
               FROM engrams e
               WHERE e.forgotten = 0
                 AND e.embedding IS NOT NULL
                 AND e.embedding_dim = ?
               ORDER BY distance ASC
               LIMIT 5""",
            (embedding_blob, dim),
        ).fetchall()
    except Exception:
        return None

    tags_set = set(tags) if tags else set()
    files_set = set(files) if files else set()

    for row in rows:
        similarity = 1.0 - row["distance"]
        if similarity < threshold:
            continue

        # 三项匹配检查：type+tags+files，至少匹配两项
        match_count = 0

        # tags 重叠
        existing_tags = set()
        if row["tags"]:
            try:
                existing_tags = set(json.loads(row["tags"]))
            except (json.JSONDecodeError, TypeError):
                pass
        if tags_set and existing_tags and tags_set & existing_tags:
            match_count += 1

        # type 匹配（observation 默认对应 fact 或 insight）
        if row["type"] in ("fact", "insight", "debugging"):
            match_count += 1

        # files 重叠（检查 content 中是否提到相同文件）
        if files_set:
            content_lower = row["content"].lower()
            for f in files_set:
                if f.lower() in content_lower:
                    match_count += 1
                    break

        if match_count >= 2:
            return dict(row)

    return None


def _check_cross_session_occurrence(
    conn: sqlite3.Connection,
    fp: str,
    current_session_id: str | None,
) -> bool:
    """检查同一 fingerprint 是否在 >=2 个不同 session 中出现。"""
    rows = conn.execute(
        """SELECT DISTINCT session_id FROM session_events
           WHERE fingerprint = ? AND event_type = 'observation'""",
        (fp,),
    ).fetchall()

    session_ids = {row["session_id"] for row in rows}
    if current_session_id:
        session_ids.add(current_session_id)
    return len(session_ids) >= 2


def ingest_observation(
    conn: sqlite3.Connection,
    content: str,
    tool: str | None = None,
    files: list[str] | None = None,
    tags: list[str] | None = None,
    session_id: str | None = None,
    importance: str = "normal",
) -> IngestResult:
    """Observation ingestion pipeline 主入口。

    Stage 1: fingerprint 精确去重
    Stage 2: 语义相似度候选合并
    Stage 3: 晋升决策
    """
    fp = _fingerprint(content)

    # ── Stage 1: Exact/Near-Exact Fingerprint Dedup ──
    if session_id:
        session_svc = SessionService(conn)
        if session_svc.has_fingerprint(session_id, fp):
            # 同会话内重复，跳过
            return IngestResult(event_id="", promoted=False, skipped=True)

    now = datetime.now().isoformat()
    payload = {
        "tool": tool,
        "files": files,
        "summary": content[:200],
        "promoted": False,  # 先标 False，后面可能更新
    }

    # 只有在有 session 时才写 session_events 并生成 event_id
    event_id: str | None = None
    if session_id:
        event_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO session_events (id, session_id, event_type, payload, fingerprint, created_at)
               VALUES (?, ?, 'observation', ?, ?, ?)""",
            (event_id, session_id, json.dumps(payload, ensure_ascii=False), fp, now),
        )

    # ── Stage 2: Semantic Candidate Merge ──
    embedding_blob, dim, is_pending = get_embedding(content)

    candidate = _check_semantic_candidate(
        conn, content, embedding_blob, dim, tags, files
    )

    if candidate:
        # 合并到已有 engram：只扩展 tags，不动 access_count/last_accessed
        # 避免从侧门引入强化副作用（违背"默认只读"边界）
        engram_id = candidate["id"]
        existing_tags = set()
        if candidate["tags"]:
            try:
                existing_tags = set(json.loads(candidate["tags"]))
            except (json.JSONDecodeError, TypeError):
                pass
        new_tags_added = False
        if tags:
            before = len(existing_tags)
            existing_tags.update(tags)
            new_tags_added = len(existing_tags) > before
        merged_tags = json.dumps(sorted(existing_tags), ensure_ascii=False) if existing_tags else None

        if new_tags_added:
            conn.execute(
                "UPDATE engrams SET tags = ? WHERE id = ?",
                (merged_tags, engram_id),
            )
        conn.commit()

        # 更新事件 payload
        if session_id:
            payload["promoted"] = False
            payload["merged_with"] = engram_id
            conn.execute(
                "UPDATE session_events SET payload = ? WHERE id = ?",
                (json.dumps(payload, ensure_ascii=False), event_id),
            )
            conn.commit()

        return IngestResult(
            event_id=event_id or "", promoted=False, merged_with=engram_id
        )

    # ── Stage 3: Promotion Decision ──
    should_promote = False

    # 规则 1: importance=high/critical → 直接晋升
    if importance in ("high", "critical"):
        should_promote = True

    # 规则 2: 同一 observation 在 >=2 个不同 session 出现 → 晋升
    if not should_promote and _check_cross_session_occurrence(
        conn, fp, session_id
    ):
        should_promote = True

    engram_id = None
    if should_promote:
        from memento.decay import AGENT_STRENGTH_CAP

        engram_id = str(uuid.uuid4())
        tags_json = json.dumps(tags, ensure_ascii=False) if tags else None

        conn.execute(
            """INSERT INTO engrams
               (id, content, type, tags, strength, importance, origin, verified,
                created_at, last_accessed, access_count, forgotten,
                embedding_pending, embedding_dim, embedding,
                source_session_id, source_event_id)
               VALUES (?, ?, 'fact', ?, ?, ?, 'agent', 0,
                       ?, ?, 0, 0, ?, ?, ?,
                       ?, ?)""",
            (
                engram_id,
                content,
                tags_json,
                AGENT_STRENGTH_CAP,
                importance,
                now,
                now,
                1 if is_pending else 0,
                dim,
                embedding_blob,
                session_id,
                event_id,
            ),
        )

        # 更新事件 payload
        if session_id:
            payload["promoted"] = True
            conn.execute(
                "UPDATE session_events SET payload = ? WHERE id = ?",
                (json.dumps(payload, ensure_ascii=False), event_id),
            )

    conn.commit()

    # 无 session_id 且未晋升 → 什么都没持久化
    persisted = should_promote or event_id is not None
    return IngestResult(
        event_id=event_id or "",
        promoted=should_promote,
        engram_id=engram_id,
        skipped=not persisted,
    )
