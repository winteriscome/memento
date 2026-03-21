"""核心业务逻辑：capture / recall / forget / verify / status。"""

import json
import sqlite3
import struct
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from math import exp
from typing import Optional

from memento.db import get_connection, init_db
from memento.decay import (
    AGENT_STRENGTH_CAP,
    effective_strength,
    needs_review,
    reinforcement_boost,
)
from memento.embedding import get_embedding


@dataclass
class RecallResult:
    """recall 返回的单条结果。"""

    id: str
    content: str
    type: str
    tags: list[str]
    strength: float
    importance: str
    origin: str
    verified: bool
    score: float
    created_at: str
    last_accessed: str
    access_count: int
    review_hint: Optional[str] = None


class MementoCore:
    """Memento v0.1 核心引擎。"""

    def __init__(self, db_path=None):
        self.conn = get_connection(db_path)
        init_db(self.conn)

    def close(self):
        self.conn.close()

    def capture(
        self,
        content: str,
        type: str = "fact",
        importance: str = "normal",
        tags: list[str] | None = None,
        origin: str = "human",
    ) -> str:
        """
        写入一条记忆。返回 engram ID。

        - origin='human' → verified=1（用户直接输入，可信度最高）
        - origin='agent' → verified=0（Agent 自动写入，strength 上限 0.5）
        """
        engram_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        tags_json = json.dumps(tags, ensure_ascii=False) if tags else None
        verified = 1 if origin == "human" else 0

        # 生成 embedding（可能降级为 None）
        embedding_blob, dim, is_pending = get_embedding(content)

        self.conn.execute(
            """
            INSERT INTO engrams
                (id, content, type, tags, strength, importance, source, origin,
                 verified, created_at, last_accessed, access_count, forgotten,
                 embedding_pending, embedding)
            VALUES (?, ?, ?, ?, 0.7, ?, NULL, ?, ?, ?, ?, 0, 0, ?, ?)
            """,
            (
                engram_id,
                content,
                type,
                tags_json,
                importance,
                origin,
                verified,
                now,
                now,
                1 if is_pending else 0,
                embedding_blob,
            ),
        )
        self.conn.commit()
        return engram_id

    def recall(self, query: str, max_results: int = 5) -> list[RecallResult]:
        """
        向量相似度 × 衰减权重检索。

        1. 向量检索 top-K×3 候选
        2. 计算 effective_strength × similarity → 排序
        3. 原子 SQL UPDATE 执行再巩固
        """
        now = datetime.now()
        embedding_blob, dim, is_pending = get_embedding(query)

        candidates = []

        if embedding_blob and not is_pending:
            # 向量检索路径
            candidates = self._vector_recall(embedding_blob, max_results * 3)

        if not candidates:
            # FTS5 回退路径
            candidates = self._fts_recall(query, max_results * 3)

        if not candidates:
            return []

        # 计算综合得分
        scored: list[tuple[sqlite3.Row, float]] = []
        for row in candidates:
            if row["forgotten"]:
                continue
            eff = effective_strength(
                row["strength"],
                row["last_accessed"],
                row["access_count"],
                row["importance"],
                now,
            )
            similarity = row["similarity"] if "similarity" in row.keys() else None
            bm25_score = row["bm25_score"] if "bm25_score" in row.keys() else None

            if bm25_score is not None:
                raw = abs(bm25_score)  # FTS5 BM25 返回负值
                similarity = 1.0 / (1.0 + exp(-0.3 * (raw - 10.0)))
            elif similarity is None:
                similarity = 0.0

            score = eff * similarity
            scored.append((row, score))

        scored.sort(key=lambda x: -x[1])
        top = scored[:max_results]

        # 再巩固 + 构造返回结果
        results = []
        for row, score in top:
            boost = reinforcement_boost(row["last_accessed"], now)

            # 原子 UPDATE — 无竞态窗口
            self.conn.execute(
                """
                UPDATE engrams SET
                    strength = MIN(
                        CASE WHEN origin = 'agent' AND verified = 0 THEN ? ELSE 1.0 END,
                        strength + ?
                    ),
                    access_count = access_count + 1,
                    last_accessed = ?
                WHERE id = ?
                """,
                (AGENT_STRENGTH_CAP, boost, now.isoformat(), row["id"]),
            )

            tags = json.loads(row["tags"]) if row["tags"] else []

            result = RecallResult(
                id=row["id"],
                content=row["content"],
                type=row["type"],
                tags=tags,
                strength=row["strength"],
                importance=row["importance"],
                origin=row["origin"],
                verified=bool(row["verified"]),
                score=round(score, 4),
                created_at=row["created_at"],
                last_accessed=row["last_accessed"],
                access_count=row["access_count"],
            )

            # critical 记忆复验提醒
            eff = effective_strength(
                row["strength"],
                row["last_accessed"],
                row["access_count"],
                row["importance"],
                now,
            )
            if needs_review(row["importance"], eff):
                hours = (
                    now - datetime.fromisoformat(row["last_accessed"])
                ).total_seconds() / 3600
                result.review_hint = (
                    f"此关键记忆已 {int(hours)}h 未访问，建议复验是否仍然准确"
                )

            results.append(result)

        self.conn.commit()
        return results

    def _vector_recall(
        self, query_blob: bytes, limit: int
    ) -> list[sqlite3.Row]:
        """sqlite-vec 向量近邻检索。"""
        try:
            rows = self.conn.execute(
                """
                SELECT e.*, vec_distance_cosine(e.embedding, ?) AS distance
                FROM engrams e
                WHERE e.embedding IS NOT NULL
                  AND e.forgotten = 0
                ORDER BY distance ASC
                LIMIT ?
                """,
                (query_blob, limit),
            ).fetchall()

            # 将 distance 转为 similarity（cosine distance → cosine similarity）
            results = []
            for row in rows:
                # sqlite3.Row 不可变，用 dict 做中间层
                d = dict(row)
                d["similarity"] = 1.0 - d.pop("distance", 0.0)
                results.append(d)

            # 包装回类 Row 对象
            return [_DictRow(d) for d in results]
        except Exception:
            return []

    def _fts_recall(self, query: str, limit: int) -> list[sqlite3.Row]:
        """FTS5 全文检索回退。"""
        try:
            rows = self.conn.execute(
                """
                SELECT e.*, bm25(engrams_fts) AS bm25_score
                FROM engrams_fts
                JOIN engrams e ON e.rowid = engrams_fts.rowid
                WHERE engrams_fts MATCH ?
                  AND e.forgotten = 0
                ORDER BY bm25(engrams_fts)
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
            return rows
        except Exception:
            # FTS5 查询语法错误时静默降级
            return []

    def forget(self, engram_id: str) -> bool:
        """标记一条记忆为遗忘。"""
        cursor = self.conn.execute(
            "UPDATE engrams SET forgotten = 1 WHERE id = ? AND forgotten = 0",
            (engram_id,),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def verify(self, engram_id: str) -> bool:
        """人类确认 Agent 记忆为可信。"""
        cursor = self.conn.execute(
            "UPDATE engrams SET verified = 1 WHERE id = ? AND verified = 0",
            (engram_id,),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def status(self) -> dict:
        """返回数据库统计信息。"""
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN forgotten = 0 THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN forgotten = 1 THEN 1 ELSE 0 END) AS forgotten,
                SUM(CASE WHEN origin = 'agent' AND verified = 0 THEN 1 ELSE 0 END) AS unverified_agent,
                SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) AS with_embedding,
                SUM(CASE WHEN embedding_pending = 1 THEN 1 ELSE 0 END) AS pending_embedding
            FROM engrams
            """
        ).fetchone()
        return dict(row)

    def get_by_id(self, engram_id: str) -> Optional[dict]:
        """根据 ID 查询单条记忆。"""
        row = self.conn.execute(
            "SELECT * FROM engrams WHERE id = ?", (engram_id,)
        ).fetchone()
        return dict(row) if row else None


class _DictRow:
    """轻量包装器，让 dict 支持 row['key'] 和 row.keys() 访问。"""

    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def keys(self):
        return self._data.keys()
