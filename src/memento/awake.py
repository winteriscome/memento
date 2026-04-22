"""Awake track — fast read/write path in the Worker DB thread (Layer 3)."""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from memento.embedding import get_embedding


def awake_capture(
    conn: sqlite3.Connection,
    content: str,
    type: str = "fact",
    tags=None,
    importance: str = "normal",
    origin: str = "human",
    session_id: str = None,
    event_id: str = None,
) -> dict:
    """Write to capture_log (L2) ONLY, never to engrams (L3)."""
    capture_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # content_hash = SHA256 of normalized content
    normalized = content.strip().lower()
    content_hash = hashlib.sha256(normalized.encode()).hexdigest()

    # Embedding
    # 同步调用 get_embedding — 已知妥协，可能拖慢写入（见 Scope Lock）。v0.5.1 考虑下放 Subconscious。
    embedding_blob, embedding_dim, is_pending = get_embedding(content)

    # Tags serialization
    if isinstance(tags, list):
        tags = json.dumps(tags)
    # if string, keep as-is; if None, stays None

    conn.execute(
        """INSERT INTO capture_log
           (id, content, type, tags, importance, origin,
            source_session_id, source_event_id,
            content_hash, embedding, embedding_dim, embedding_pending,
            created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            capture_id, content, type, tags, importance, origin,
            session_id, event_id,
            content_hash, embedding_blob, embedding_dim,
            1 if is_pending else 0,
            now,
        ),
    )
    conn.commit()

    return {"capture_log_id": capture_id, "state": "buffered"}


def awake_recall_by_type(
    conn: sqlite3.Connection,
    types: list[str],
    project: str | None = None,
    limit: int = 50,
    order_by: str = "strength",
) -> list[dict]:
    """Retrieve engrams filtered by type and project for layered priming.

    Note: Queries view_engrams (materialized view), which is rebuilt during
    epoch Phase 7. Between epochs, newly captured memories may not appear.
    This is consistent with awake_recall() which uses the same source.

    Project isolation:
    - project is a string → match that project + global (project IS NULL)
    - project is None → only global memories (no project-specific)

    order_by:
    - "strength": for L0 (raw strength, identity stability)
    - "last_accessed": for L1 (ensure recent memories enter candidate pool)
    """
    placeholders = ",".join("?" * len(types))
    order_col = "v.last_accessed" if order_by == "last_accessed" else "v.strength"

    if project is not None:
        sql = f"""
            SELECT v.* FROM view_engrams v
            JOIN engrams e ON v.id = e.id
            LEFT JOIN sessions s ON e.source_session_id = s.id
            WHERE v.type IN ({placeholders})
              AND (s.project = ? OR s.project IS NULL)
            ORDER BY {order_col} DESC
            LIMIT ?
        """
        params = [*types, project, limit]
    else:
        # project=None: only global memories
        sql = f"""
            SELECT v.* FROM view_engrams v
            JOIN engrams e ON v.id = e.id
            LEFT JOIN sessions s ON e.source_session_id = s.id
            WHERE v.type IN ({placeholders})
              AND s.project IS NULL
            ORDER BY {order_col} DESC
            LIMIT ?
        """
        params = [*types, limit]

    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def awake_recall(
    conn: sqlite3.Connection,
    query: str,
    max_results: int = 5,
    pulse_queue=None,
) -> list[dict]:
    """Dual-source recall: view_engrams (vector/FTS5/LIKE) + unconsumed capture_log.

    Retrieval pipeline:
    1. Vector cosine similarity (sqlite-vec) if available
    2. FTS5 BM25 via engrams_fts (joined to view_engrams)
    3. LIKE fallback
    4. effective_strength scoring with rigidity
    5. staleness_level classification

    Note: vector search on view_engrams uses brute-force distance calculation
    (not a dedicated vector index). Correct but O(N); acceptable for current
    data volumes, revisit if recall latency degrades.
    """
    from math import exp

    from memento.db import VEC_AVAILABLE
    from memento.decay import effective_strength as compute_eff_strength
    from memento.rigidity import RIGIDITY_DEFAULTS

    now = datetime.now()  # naive, matching core.py and DB timestamps
    results = []

    # ── Source 1: view_engrams (consolidated memories) ──────────────────
    query_blob, query_dim, is_pending = get_embedding(query)

    view_candidates = []

    # Strategy A: Vector search on view_engrams
    if query_blob and not is_pending and VEC_AVAILABLE:
        try:
            rows = conn.execute(
                """SELECT v.*, vec_distance_cosine(v.embedding, ?) AS distance
                   FROM view_engrams v
                   WHERE v.embedding IS NOT NULL
                     AND v.embedding_dim = ?
                   ORDER BY distance ASC
                   LIMIT ?""",
                (query_blob, query_dim, max_results * 3),
            ).fetchall()
            for row in rows:
                d = dict(row)
                d["similarity"] = 1.0 - d.pop("distance", 0.0)
                view_candidates.append(d)
        except Exception:
            pass

    # Strategy B: FTS5 via engrams_fts joined to view_engrams
    if not view_candidates:
        try:
            rows = conn.execute(
                """SELECT v.*, bm25(engrams_fts) AS bm25_score
                   FROM engrams_fts
                   JOIN engrams e ON e.rowid = engrams_fts.rowid
                   JOIN view_engrams v ON v.id = e.id
                   WHERE engrams_fts MATCH ?
                   ORDER BY bm25(engrams_fts)
                   LIMIT ?""",
                (query, max_results * 3),
            ).fetchall()
            for row in rows:
                d = dict(row)
                raw_bm25 = abs(d.pop("bm25_score", 0.0))
                d["similarity"] = 1.0 / (1.0 + exp(-0.3 * (raw_bm25 - 10.0)))
                view_candidates.append(d)
        except Exception:
            pass

    # Strategy C: LIKE fallback
    if not view_candidates:
        like_pattern = f"%{query}%"
        rows = conn.execute(
            """SELECT *, 0.5 AS similarity
               FROM view_engrams WHERE content LIKE ?
               LIMIT ?""",
            (like_pattern, max_results * 3),
        ).fetchall()
        view_candidates = [dict(row) for row in rows]

    # Score view candidates with effective_strength + rigidity
    for c in view_candidates:
        rigidity = c.get("rigidity") or RIGIDITY_DEFAULTS.get(c.get("type", "fact"), 0.0)
        eff = compute_eff_strength(
            strength=c["strength"],
            last_accessed=c["last_accessed"],
            access_count=c["access_count"],
            importance=c["importance"],
            now=now,
            rigidity=rigidity,
        )
        sim = c.get("similarity", 0.0)
        score = eff * sim

        # staleness classification (heuristic thresholds based on FSRS v6 decay
        # model; may be adjusted as recall distribution data accumulates)
        if eff > 0.6:
            staleness = "fresh"
        elif eff > 0.3:
            staleness = "stale"
        else:
            staleness = "very_stale"

        results.append({
            "id": c["id"],
            "content": c["content"],
            "type": c.get("type"),
            "tags": c.get("tags"),
            "importance": c.get("importance"),
            "origin": c.get("origin"),
            "score": round(score, 4),
            "staleness_level": staleness,
            "provisional": False,
        })

    # ── Source 2: capture_log (hot buffer — unconsumed) ──────────────────
    buffer_candidates = []

    # Vector search on capture_log
    if query_blob and not is_pending and VEC_AVAILABLE:
        try:
            rows = conn.execute(
                """SELECT *, vec_distance_cosine(embedding, ?) AS distance
                   FROM capture_log
                   WHERE epoch_id IS NULL
                     AND embedding IS NOT NULL
                     AND embedding_dim = ?
                   ORDER BY distance ASC
                   LIMIT ?""",
                (query_blob, query_dim, max_results),
            ).fetchall()
            for row in rows:
                d = dict(row)
                d["similarity"] = 1.0 - d.pop("distance", 0.0)
                buffer_candidates.append(d)
        except Exception:
            pass

    # LIKE fallback for capture_log
    if not buffer_candidates:
        like_pattern = f"%{query}%"
        rows = conn.execute(
            """SELECT *, 0.5 AS similarity
               FROM capture_log WHERE epoch_id IS NULL AND content LIKE ?
               LIMIT ?""",
            (like_pattern, max_results),
        ).fetchall()
        buffer_candidates = [dict(row) for row in rows]

    for c in buffer_candidates:
        sim = c.get("similarity", 0.0)
        results.append({
            "id": c["id"],
            "content": c["content"],
            "type": c.get("type"),
            "tags": c.get("tags"),
            "importance": c.get("importance"),
            "origin": c.get("origin"),
            "score": round(0.5 * sim, 4),  # downweight buffer hits
            "staleness_level": "fresh",  # buffer hits are always fresh
            "provisional": True,
        })

    # Sort by score desc, take top-K
    results.sort(key=lambda r: r["score"], reverse=True)
    results = results[:max_results]

    # 记录访问元数据（不修改 strength）
    now_iso = now.isoformat()
    for r in results:
        if not r["provisional"]:
            conn.execute(
                "UPDATE engrams SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                (now_iso, r["id"]),
            )
    conn.commit()

    # PulseEvents for view_engrams hits only (not hot buffer)
    if pulse_queue is not None:
        now_iso = datetime.now(timezone.utc).isoformat()
        final_view_ids = [r["id"] for r in results if not r["provisional"]]
        for engram_id in final_view_ids:
            coactivated = [eid for eid in final_view_ids if eid != engram_id]
            pulse_queue.put({
                "event_type": "recall_hit",
                "engram_id": engram_id,
                "query_context": query,
                "coactivated_ids": coactivated,
                "timestamp": now_iso,
                "idempotency_key": str(uuid.uuid4()),
            })

    return results


def awake_forget(conn: sqlite3.Connection, target_id: str) -> dict:
    """Queue a forget request into pending_forget."""
    now = datetime.now(timezone.utc).isoformat()
    forget_id = str(uuid.uuid4())

    # Auto-detect target table
    row = conn.execute(
        "SELECT id FROM capture_log WHERE id=? AND epoch_id IS NULL",
        (target_id,),
    ).fetchone()

    target_table = "capture_log" if row else "engrams"

    conn.execute(
        "INSERT INTO pending_forget (id, target_table, target_id, requested_at) "
        "VALUES (?, ?, ?, ?)",
        (forget_id, target_table, target_id, now),
    )
    conn.commit()

    return {"status": "pending", "message": "Will take effect after next epoch run"}


def awake_verify(conn: sqlite3.Connection, engram_id: str) -> dict:
    """Mark an engram as verified in both engrams and view_engrams."""
    conn.execute("UPDATE engrams SET verified=1 WHERE id=?", (engram_id,))
    conn.execute("UPDATE view_engrams SET verified=1 WHERE id=?", (engram_id,))
    conn.commit()

    return {"status": "verified", "engram_id": engram_id}


def awake_pin(conn: sqlite3.Connection, engram_id: str, rigidity: float) -> dict:
    """Pin an engram with a clamped rigidity value."""
    rigidity = max(0.0, min(1.0, rigidity))

    conn.execute("UPDATE engrams SET rigidity=? WHERE id=?", (rigidity, engram_id))
    conn.execute("UPDATE view_engrams SET rigidity=? WHERE id=?", (rigidity, engram_id))
    conn.commit()

    return {"status": "pinned", "engram_id": engram_id, "rigidity": rigidity}
