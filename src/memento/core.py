"""核心业务逻辑：capture / recall / forget / verify / status。"""

import json
import sqlite3
import uuid
from dataclasses import dataclass
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
        initial_strength = (
            AGENT_STRENGTH_CAP if origin == "agent" and verified == 0 else 0.7
        )

        # 生成 embedding（可能降级为 None）
        embedding_blob, dim, is_pending = get_embedding(content)

        self.conn.execute(
            """
            INSERT INTO engrams
                (id, content, type, tags, strength, importance, source, origin,
                 verified, created_at, last_accessed, access_count, forgotten,
                 embedding_pending, embedding_dim, embedding)
            VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, 0, 0, ?, ?, ?)
            """,
            (
                engram_id,
                content,
                type,
                tags_json,
                initial_strength,
                importance,
                origin,
                verified,
                now,
                now,
                int(is_pending),
                dim or None,
                embedding_blob,
            ),
        )
        self.conn.commit()
        return engram_id

    def recall(
        self,
        query: str,
        max_results: int = 5,
        mode: str = "A",
        read_only: bool | None = None,
    ) -> list[RecallResult]:
        """
        检索记忆。

        Mode A: effective_strength × similarity，并对命中结果再巩固。
        Mode B: similarity × recency_bonus，只读基线，不写副作用。
        """
        mode = mode.upper()
        if mode not in {"A", "B"}:
            raise ValueError("mode must be 'A' or 'B'")

        now = datetime.now()
        embedding_blob, dim, is_pending = get_embedding(query)
        should_reinforce = mode == "A" and read_only is not True

        candidates = []

        if embedding_blob and not is_pending:
            # 向量检索路径
            candidates = self._vector_recall(
                embedding_blob, dim, max_results * 3
            )

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

            if mode == "A":
                score = eff * similarity
            else:
                score = similarity * self._recency_bonus(
                    row["created_at"], now
                )
            scored.append((row, score))

        scored.sort(key=lambda x: -x[1])
        top = scored[:max_results]

        # 再巩固 + 构造返回结果
        results = []
        for row, score in top:
            if should_reinforce:
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

        if should_reinforce:
            self.conn.commit()

        # 机会性补填：API 恢复后逐步补填离线期间写入的记忆
        self.backfill_pending_embeddings(limit=5)

        return results

    def _vector_recall(
        self, query_blob: bytes, embedding_dim: int, limit: int
    ) -> list[sqlite3.Row]:
        """sqlite-vec 向量近邻检索。"""
        try:
            rows = self.conn.execute(
                """
                SELECT e.*, vec_distance_cosine(e.embedding, ?) AS distance
                FROM engrams e
                WHERE e.embedding IS NOT NULL
                  AND e.embedding_dim = ?
                  AND e.forgotten = 0
                ORDER BY distance ASC
                LIMIT ?
                """,
                (query_blob, embedding_dim, limit),
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

    def _recency_bonus(
        self, created_at: str, now: datetime | None = None
    ) -> float:
        """Mode B 的简单时间排序基线。"""
        if now is None:
            now = datetime.now()

        created = datetime.fromisoformat(created_at)
        hours_since_created = (now - created).total_seconds() / 3600.0
        return 1.0 / (1.0 + hours_since_created * 0.01)

    def evaluate(
        self,
        queries: list[dict],
        max_results: int = 5,
        mode: str = "A",
    ) -> dict:
        """对一组标注查询执行只读评估。"""
        precision_total = 0.0
        reciprocal_rank_total = 0.0
        stale_hit_total = 0
        labeled_count = 0
        stale_labeled_count = 0
        samples = []

        for item in queries:
            query = item["query"]
            results = self.recall(
                query,
                max_results=max_results,
                mode=mode,
                read_only=True,
            )
            result_ids = [result.id for result in results]
            expected_ids = set(item.get("expected_ids", []))
            stale_ids = set(item.get("stale_ids", []))

            precision_at_3 = None
            reciprocal_rank = None
            stale_hit = None

            if expected_ids:
                hits = sum(
                    1 for result_id in result_ids[:3] if result_id in expected_ids
                )
                precision_at_3 = hits / 3.0
                reciprocal_rank = 0.0
                for rank, result_id in enumerate(result_ids, start=1):
                    if result_id in expected_ids:
                        reciprocal_rank = 1.0 / rank
                        break
                precision_total += precision_at_3
                reciprocal_rank_total += reciprocal_rank
                labeled_count += 1

            if stale_ids:
                stale_hit = any(
                    result_id in stale_ids for result_id in result_ids[:5]
                )
                stale_hit_total += int(stale_hit)
                stale_labeled_count += 1

            samples.append(
                {
                    "query": query,
                    "result_ids": result_ids,
                    "precision_at_3": precision_at_3,
                    "reciprocal_rank": reciprocal_rank,
                    "stale_hit": stale_hit,
                }
            )

        metrics = {
            "mode": mode.upper(),
            "query_count": len(queries),
            "labeled_count": labeled_count,
            "stale_labeled_count": stale_labeled_count,
            "precision_at_3": (
                precision_total / labeled_count if labeled_count else None
            ),
            "mrr": (
                reciprocal_rank_total / labeled_count if labeled_count else None
            ),
            "stale_hit_rate": (
                stale_hit_total / stale_labeled_count
                if stale_labeled_count
                else None
            ),
            "samples": samples,
        }
        return metrics

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

    def backfill_pending_embeddings(self, limit: int = 5) -> int:
        """为 embedding_pending=1 的记忆补填 embedding，每次最多 limit 条。"""
        rows = self.conn.execute(
            "SELECT id, content FROM engrams WHERE embedding_pending = 1 LIMIT ?",
            (limit,),
        ).fetchall()
        if not rows:
            return 0

        filled = 0
        for row in rows:
            blob, dim, still_pending = get_embedding(row["content"])
            if not still_pending and blob:
                self.conn.execute(
                    "UPDATE engrams SET embedding = ?, embedding_dim = ?, embedding_pending = 0 WHERE id = ?",
                    (blob, dim, row["id"]),
                )
                filled += 1
        if filled:
            self.conn.commit()
        return filled

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
