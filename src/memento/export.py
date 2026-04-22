"""导入导出：JSON 序列化。

v0.5: 导出 L3（engrams + nexus），不导出中间层。
格式 version 2 新增 nexus 字段。
"""

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

    v0.5: 只导出 L3 engrams (state != 'forgotten')，不导出 embedding。
    不导出: capture_log, delta_ledger, recon_buffer, cognitive_debt,
            runtime_cursors, epochs, pending_forget, view_*
    """
    # v0.5: 用 state 和 forgotten 双重过滤，兼容新旧路径
    # core.forget() 设 forgotten=1，epoch 路径设 state='forgotten'
    query = "SELECT * FROM engrams WHERE forgotten = 0"
    # 如果 state 列存在，额外排除 state='forgotten'
    try:
        cols = [r[1] for r in core.conn.execute("PRAGMA table_info(engrams)").fetchall()]
        if "state" in cols:
            query += " AND state != 'forgotten'"
    except Exception:
        pass
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


def export_nexus(core: MementoCore) -> list[dict]:
    """导出 nexus 关联数据。"""
    try:
        rows = core.conn.execute("SELECT * FROM nexus").fetchall()
        return [
            {
                "id": r["id"],
                "source_id": r["source_id"],
                "target_id": r["target_id"],
                "direction": r["direction"],
                "type": r["type"],
                "association_strength": r["association_strength"],
                "created_at": r["created_at"],
                "last_coactivated_at": r["last_coactivated_at"],
                "invalidated_at": r["invalidated_at"],
            }
            for r in rows
        ]
    except Exception:
        return []


def export_full(
    core: MementoCore,
    filter_type: Optional[str] = None,
    filter_tags: Optional[list[str]] = None,
) -> dict:
    """导出完整数据包（version 2 格式）。

    Returns:
        {"version": 2, "memories": [...], "nexus": [...]}
    """
    memories = export_memories(core, filter_type=filter_type, filter_tags=filter_tags)
    nexus = export_nexus(core)
    return {
        "version": 2,
        "memories": memories,
        "nexus": nexus,
    }


def import_memories(
    core: MementoCore,
    memories: list[dict],
    source: Optional[str] = None,
    nexus: Optional[list[dict]] = None,
) -> dict:
    """
    导入记忆（+ 可选的 nexus）。

    规则：
    - strength 上限 0.5（导入的记忆不应与本地高频记忆竞争）
    - 标记 source 来源
    - 重新生成 embedding
    - 跳过已存在的 ID（幂等导入）
    - 导入后 rebuild view store 使数据立即可查
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

    # Import nexus data if provided
    nexus_imported = 0
    nexus_skipped = 0
    if nexus:
        for n in nexus:
            try:
                core.conn.execute(
                    """INSERT OR IGNORE INTO nexus
                        (id, source_id, target_id, direction, type,
                         association_strength, created_at, last_coactivated_at,
                         invalidated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        n["id"],
                        n["source_id"],
                        n["target_id"],
                        n.get("direction", "directed"),
                        n["type"],
                        n.get("association_strength", 0.5),
                        n.get("created_at", datetime.now().isoformat()),
                        n.get("last_coactivated_at"),
                        n.get("invalidated_at"),
                    ),
                )
                if core.conn.execute("SELECT changes()").fetchone()[0] > 0:
                    nexus_imported += 1
                else:
                    nexus_skipped += 1
            except Exception:
                nexus_skipped += 1

    core.conn.commit()

    # 补填所有 pending embedding（import 时全量补填）
    core.backfill_pending_embeddings(limit=10000)

    # Rebuild view store to make imported data immediately queryable
    _rebuild_view_store_safe(core.conn)

    result = {"imported": imported, "skipped": skipped}
    if nexus:
        result["nexus_imported"] = nexus_imported
        result["nexus_skipped"] = nexus_skipped
    return result


def _rebuild_view_store_safe(conn) -> None:
    """安全重建 view store（如果 view_engrams 表存在）。"""
    try:
        # Check if view_engrams table exists
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='view_engrams'"
        ).fetchone()
        if not exists:
            return

        from memento.repository import rebuild_view_store
        rebuild_view_store(conn, epoch_id="import")
        conn.commit()
    except Exception:
        # view store rebuild is best-effort
        pass
