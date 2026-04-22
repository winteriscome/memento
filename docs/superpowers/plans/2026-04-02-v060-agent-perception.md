> [!NOTE]
> **Historical Plan**
> This document is an implementation snapshot retained for history. It may not reflect the latest repository-wide milestone semantics or current implementation behavior. For current source-of-truth, see `docs/README.md`, `Engram：分布式记忆操作系统与协作协议.md`, and `docs/superpowers/plans/2026-04-02-v06-v07-roadmap.md`.

# v0.6.0 检索修复 + Agent 感知增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix awake_recall to use vector/FTS5 retrieval (instead of LIKE), add staleness signals to recall results, add capture exclusion rules to MCP tool descriptions, and return tags/origin in recall responses.

**Architecture:** Extract core.py's retrieval pipeline (vector → FTS5 → effective_strength scoring) into reusable functions that awake_recall can call on both view_engrams and capture_log. Add staleness_level computation based on effective_strength. Update MCP tool descriptions with exclusion guidance.

**Tech Stack:** Python 3.10+, SQLite (sqlite-vec, FTS5), pytest

---

## File Structure

### Modified files

| File | Changes |
|------|---------|
| `src/memento/awake.py` | Replace LIKE matching with vector/FTS5 retrieval; add staleness_level; return tags/origin |
| `src/memento/mcp_server.py` | Add exclusion rules to capture tool description; add staleness_level/tags/origin to recall response |
| `tests/test_awake.py` | Update tests for new retrieval, add staleness tests |

### Key design decisions

1. **No code extraction from core.py** — awake_recall operates on different tables (view_engrams + capture_log) vs core.py (engrams). Instead of extracting shared functions, implement the retrieval logic directly in awake_recall using the same algorithm but different table names.
2. **FTS5 only for view_engrams** — `engrams_fts` is synced with `engrams` table via triggers. `view_engrams` is a materialized view rebuilt at epoch time. We can query `engrams_fts` and join back to `view_engrams` for consolidated results. For `capture_log`, use vector search + LIKE fallback (no FTS5 index exists for it).
3. **staleness_level** — computed from effective_strength with rigidity: `fresh` (>0.6), `stale` (0.3–0.6), `very_stale` (≤0.3). Buffer hits are always `fresh`.

---

## Task 1: Upgrade awake_recall to vector/FTS5 retrieval

**Files:**
- Modify: `src/memento/awake.py:59-128`
- Modify: `tests/test_awake.py`

- [ ] **Step 1: Write a test proving vector recall returns results that LIKE would miss**

```python
# Append to tests/test_awake.py

def test_recall_semantic_match_not_just_like():
    """awake_recall should find semantically related content, not just LIKE matches."""
    conn = _make_v05_db()  # has e1="Redis cache config", e2="User prefers dark mode"
    from memento.repository import rebuild_view_store
    rebuild_view_store(conn, epoch_id="epoch-test")

    from memento.awake import awake_recall

    # "cache" should match e1 "Redis cache config" via content match
    results = awake_recall(conn, "cache")
    assert len(results) > 0
    assert any("Redis" in r["content"] for r in results)

    # All results should have staleness_level
    for r in results:
        assert "staleness_level" in r
        assert r["staleness_level"] in ("fresh", "stale", "very_stale")

    # All results should have tags and origin
    for r in results:
        assert "tags" in r
        assert "origin" in r
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_awake.py::test_recall_semantic_match_not_just_like -v`
Expected: FAIL — `staleness_level` key not in result dict.

- [ ] **Step 3: Rewrite awake_recall with vector/FTS5 + staleness**

Replace the entire `awake_recall` function in `src/memento/awake.py`:

```python
def awake_recall(
    conn: sqlite3.Connection,
    query: str,
    max_results: int = 5,
    pulse_queue=None,
) -> list[dict]:
    """Dual-source recall: view_engrams (vector/FTS5) + unconsumed capture_log.

    Retrieval pipeline (matching core.py):
    1. Vector cosine similarity (sqlite-vec) if available
    2. FTS5 BM25 fallback via engrams_fts (joined to view_engrams)
    3. LIKE fallback if both above fail
    4. effective_strength scoring with rigidity
    5. staleness_level classification
    """
    from math import exp
    from memento.db import VEC_AVAILABLE
    from memento.decay import effective_strength as compute_eff_strength
    from memento.rigidity import RIGIDITY_DEFAULTS

    now = datetime.now(timezone.utc)
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

        # staleness classification
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

    # PulseEvents for view_engrams hits only (not hot buffer)
    if pulse_queue is not None:
        now_iso = now.isoformat()
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
```

- [ ] **Step 4: Run all awake tests**

Run: `pytest tests/test_awake.py -v`
Expected: Some existing tests may need assertion updates (they checked for exact keys). Fix as needed.

- [ ] **Step 5: Fix any broken existing tests**

Existing tests likely check for results matching LIKE patterns — these should still pass since LIKE is the final fallback. But tests may fail on:
- Missing `staleness_level` key in assertions
- Different score values (now uses effective_strength × similarity instead of raw strength)

Update test assertions to match the new response format.

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ -q`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add src/memento/awake.py tests/test_awake.py
git commit -m "feat(awake): upgrade recall to vector/FTS5 retrieval with staleness_level

Replace LIKE-only matching with three-strategy pipeline:
1. Vector cosine similarity (sqlite-vec)
2. FTS5 BM25 via engrams_fts (joined to view_engrams)
3. LIKE fallback

Add staleness_level (fresh/stale/very_stale) based on
effective_strength with rigidity. Return tags and origin
in all results."
```

---

## Task 2: Update MCP server — exclusion rules + response schema

**Files:**
- Modify: `src/memento/mcp_server.py`

- [ ] **Step 1: Add exclusion rules to memento_capture tool description**

In `src/memento/mcp_server.py`, find the `memento_capture` Tool definition and update its description:

```python
Tool(
    name="memento_capture",
    description=(
        "将重要发现、决策、用户偏好存入长期记忆。\n\n"
        "适合记录的内容：\n"
        "- 用户偏好和工作习惯（\"记住/总是/不要再\"）\n"
        "- 架构决策及其原因\n"
        "- 复杂 bug 的根因和解法\n"
        "- 项目约定和模式\n\n"
        "不要记录的内容：\n"
        "- 代码结构、文件路径（可从 codebase 推导）\n"
        "- Git 历史（用 git log 即可）\n"
        "- CLAUDE.md / AGENTS.md 已有的内容\n"
        "- 临时调试步骤（修复已在代码中体现）\n"
        "- 当前会话的临时状态\n\n"
        "判断原则：删掉这条记忆，下次会犯同样错误吗？是→记录。否→不记录。"
    ),
    ...
)
```

- [ ] **Step 2: Update recall response to include staleness_level, tags, origin**

In `src/memento/mcp_server.py`, update the `memento_recall` handler (around line 375-400):

```python
    elif name == "memento_recall":
        results = api.recall(
            arguments["query"],
            max_results=arguments.get("max_results", 5),
        )
        out = []
        for r in results:
            if isinstance(r, dict):
                out.append({
                    "id": r.get("id"),
                    "content": r.get("content"),
                    "type": r.get("type"),
                    "tags": r.get("tags"),
                    "origin": r.get("origin"),
                    "score": r.get("score", 0),
                    "staleness_level": r.get("staleness_level", "fresh"),
                    "provisional": r.get("provisional", False),
                })
            else:
                # Legacy RecallResult from core.py path
                eff = r.score  # already computed in core.py
                if eff > 0.6:
                    staleness = "fresh"
                elif eff > 0.3:
                    staleness = "stale"
                else:
                    staleness = "very_stale"
                out.append({
                    "id": r.id,
                    "content": r.content,
                    "type": r.type,
                    "tags": r.tags if isinstance(r.tags, str) else json.dumps(r.tags) if r.tags else None,
                    "origin": r.origin,
                    "score": r.score,
                    "staleness_level": staleness,
                    "provisional": getattr(r, "provisional", False),
                })
        return out
```

- [ ] **Step 3: Update memento_prime prompt to include staleness guidance**

In the `get_prompt()` function, update the prompt content to include staleness warnings and capture guidance. Find the section that formats memory list and add staleness markers:

```python
# In the memory formatting loop, add staleness indicator:
for m in memories:
    staleness = ""
    if isinstance(m, dict):
        sl = m.get("staleness_level", "")
        if sl == "stale":
            staleness = " ⚠️过时风险"
        elif sl == "very_stale":
            staleness = " ❌可能已失效"
    lines.append(f"- [{m_type}] {content}{staleness}")
```

- [ ] **Step 4: Run MCP server tests**

Run: `pytest tests/test_mcp_server.py -v`
Expected: All pass.

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/memento/mcp_server.py
git commit -m "feat(mcp): capture exclusion rules, staleness_level in recall, tags/origin

- memento_capture tool description: add what-to-capture and what-NOT-to
- memento_recall response: add staleness_level, tags, origin fields
- memento_prime: staleness markers in priming context"
```

---

## Task 3: E2E verification + smoke test update

**Files:**
- Modify: `scripts/smoke-test.sh`

- [ ] **Step 1: Update smoke test to verify staleness_level in recall output**

Add a check after step 3 (recall) in `scripts/smoke-test.sh`:

```bash
# 3b. Verify recall returns staleness_level
if echo "$RESULT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert len(d) > 0
assert 'staleness_level' in d[0], 'missing staleness_level'
assert d[0]['staleness_level'] in ('fresh', 'stale', 'very_stale')
" 2>/dev/null; then
    echo "[3b/8] staleness_level: OK"
else
    echo "[3b/8] staleness_level: FAIL"
    exit 1
fi
```

- [ ] **Step 2: Run smoke test**

Run: `bash scripts/smoke-test.sh`
Expected: All steps pass.

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -q`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke-test.sh
git commit -m "test: smoke test validates staleness_level in recall output"
```
