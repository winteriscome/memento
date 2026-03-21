"""导入导出：JSON 序列化的穷人版 Fork。"""

import json
from datetime import datetime
from typing import Optional

from memento.core import MementoCore


def export_memories(
    core: MementoCore,
    filter_type: Optional[str] = None,
    filter_tags: Optional[list[str]] = None,
) -> list[dict]:
    """
    导出记忆为 JSON 可序列化的 list[dict]。

    不导出 embedding（体积太大），导入方需要重新生成。
    """
    query = "SELECT * FROM engrams WHERE forgotten = 0"
    params: list = []

    if filter_type:
        query += " AND type = ?"
        params.append(filter_type)

    rows = core.conn.execute(query, params).fetchall()
    memories = []

    for row in rows:
        d = dict(row)
        tags = json.loads(d["tags"]) if d["tags"] else []

        # 按标签过滤
        if filter_tags:
            if not any(t in tags for t in filter_tags):
                continue

        memories.append(
            {
                "id": d["id"],
                "content": d["content"],
                "type": d["type"],
                "tags": tags,
                "strength": d["strength"],
                "importance": d["importance"],
                "source": d["source"],
                "origin": d["origin"],
                "verified": bool(d["verified"]),
                "created_at": d["created_at"],
                "last_accessed": d["last_accessed"],
                "access_count": d["access_count"],
            }
        )

    return memories


def import_memories(
    core: MementoCore,
    memories: list[dict],
    source: Optional[str] = None,
) -> dict:
    """
    导入记忆。

    规则：
    - strength 上限 0.5（导入的记忆不应与本地高频记忆竞争）
    - 标记 source 来源
    - 重新生成 embedding
    - 跳过已存在的 ID（幂等导入）
    """
    imported = 0
    skipped = 0

    for mem in memories:
        # 检查是否已存在
        existing = core.get_by_id(mem["id"])
        if existing:
            skipped += 1
            continue

        tags = mem.get("tags", [])
        capped_strength = min(mem.get("strength", 0.7), 0.5)

        core.conn.execute(
            """
            INSERT INTO engrams
                (id, content, type, tags, strength, importance, source, origin,
                 verified, created_at, last_accessed, access_count, forgotten,
                 embedding_pending, embedding_dim, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, NULL, NULL)
            """,
            (
                mem["id"],
                mem["content"],
                mem.get("type", "fact"),
                json.dumps(tags, ensure_ascii=False) if tags else None,
                capped_strength,
                mem.get("importance", "normal"),
                source or mem.get("source"),
                mem.get("origin", "human"),
                int(bool(mem.get("verified", False))),
                mem.get("created_at", datetime.now().isoformat()),
                mem.get(
                    "last_accessed",
                    mem.get("created_at", datetime.now().isoformat()),
                ),
                mem.get("access_count", 0),
            ),
        )
        imported += 1

    core.conn.commit()

    # 补填所有 pending embedding（import 时全量补填）
    core.backfill_pending_embeddings(limit=10000)

    return {"imported": imported, "skipped": skipped}
