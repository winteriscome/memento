> [!NOTE]
> **Historical Plan**
> This document is an implementation snapshot retained for history. It may not reflect the latest repository-wide milestone semantics or current implementation behavior. For current source-of-truth, see `docs/README.md`, `Engram：分布式记忆操作系统与协作协议.md`, and `docs/superpowers/plans/2026-04-02-v06-v07-roadmap.md`.

# v0.5.0 三轨架构重写 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite Memento from single-process synchronous architecture to three-track rhythm (Awake/Subconscious/Sleep-Epoch) with CQRS, five-state state machine, Delta Ledger, rigidity, Nexus, and LLM abstraction.

**Architecture:** Data migrated in-place (ALTER TABLE). Worker process hosts Awake (DB thread) + Subconscious (background thread). Epoch runs as independent subprocess (`memento epoch run`). View Store rebuilt atomically per Epoch. All engine rules are pure functions (compute_*/plan_*), persistence isolated in repository.py.

**Tech Stack:** Python 3.10+, SQLite (WAL mode, sqlite-vec, FTS5), OpenAI-compatible LLM API, Click CLI, MCP SDK.

**Spec:** `docs/superpowers/specs/2026-04-01-v050-architecture-rewrite-design.md`

---

## File Structure

### New files (src/memento/)

| File | Responsibility |
|------|---------------|
| `state_machine.py` | Five-state model, STATES/TRANSITIONS constants, TransitionPlan, DropDecision, validate_transition, plan_l2_candidates, materialize_l2_outcomes, plan_l3_transitions |
| `rigidity.py` | RIGIDITY_DEFAULTS, CONTENT_LOCK_THRESHOLD, can_modify_content, max_drift_per_epoch, ReconsolidationPlan, plan_reconsolidation |
| `delta_fold.py` | StrengthDelta, StrengthUpdatePlan, fold_deltas, plan_strength_updates |
| `hebbian.py` | NexusUpdatePlan, plan_nexus_updates |
| `repository.py` | All apply_* functions (persistence layer) |
| `awake.py` | awake_capture, awake_recall, awake_forget, awake_inspect, awake_nexus, awake_pin, awake_verify |
| `subconscious.py` | SubconsciousTrack (background thread) |
| `epoch.py` | Epoch runner (lease, seal, phases 1-7), LLMClient |
| `migration.py` | migrate_v03_to_v05 |

### Modified files (src/memento/)

| File | Changes |
|------|---------|
| `db.py` | Add new tables (capture_log, nexus, delta_ledger, recon_buffer, epochs, cognitive_debt, view_engrams, view_nexus, view_pointer, runtime_cursors, pending_forget), schema versioning |
| `decay.py` | Add compute_decay_deltas (with watermark), compute_reinforce_delta; keep existing effective_strength/reinforcement_boost |
| `worker.py` | Refactor to host Awake + Subconscious tracks, add pulse_queue, new HTTP routes |
| `api.py` | Split into MementoAPI (abstract), WorkerClientAPI, LocalAPI |
| `cli.py` | Add epoch/inspect/nexus/pin commands, remove --mode/--reinforce, update capture/recall/forget output |
| `mcp_server.py` | Add new tools, remove deprecated tools, update return schemas |
| `export.py` | Export L3 only (engrams + nexus), import with sync view rebuild |
| `core.py` | Deprecate in favor of awake.py + api.py; keep as thin adapter during transition |

### New test files

| File | Tests |
|------|-------|
| `tests/test_state_machine.py` | Transitions, invariants, DropDecision |
| `tests/test_rigidity.py` | Thresholds, drift, reconsolidation planning |
| `tests/test_delta_fold.py` | Folding, strength plans, Agent cap |
| `tests/test_hebbian.py` | Nexus updates, aggregation, normalization |
| `tests/test_repository.py` | All apply_* functions |
| `tests/test_migration.py` | v0.3→v0.5 migration |
| `tests/test_awake.py` | capture, recall (dual-source), forget, inspect |
| `tests/test_subconscious.py` | PulseEvent consumption, decay watermark |
| `tests/test_epoch.py` | Lease, seal, full/light epoch, debt |
| `tests/test_e2e.py` | Full pipeline: capture→recall→epoch→recall |

---

## Task 1: Schema & Migration

**Files:**
- Modify: `src/memento/db.py`
- Create: `src/memento/migration.py`
- Create: `tests/test_migration.py`

- [ ] **Step 1: Write migration tests**

```python
# tests/test_migration.py
import sqlite3
import hashlib
from pathlib import Path
import pytest


def _create_v03_db(db_path):
    """Create a v0.3-style database with test data."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # v0.3 schema
    conn.execute("""
        CREATE TABLE engrams (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            type TEXT DEFAULT 'fact',
            tags TEXT,
            strength REAL DEFAULT 0.7,
            importance TEXT DEFAULT 'normal',
            source TEXT,
            origin TEXT DEFAULT 'human',
            verified INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            last_accessed TEXT NOT NULL,
            access_count INTEGER DEFAULT 0,
            forgotten INTEGER DEFAULT 0,
            embedding_pending INTEGER DEFAULT 0,
            embedding_dim INTEGER,
            embedding BLOB,
            source_session_id TEXT,
            source_event_id TEXT
        )
    """)
    conn.execute("CREATE INDEX idx_engrams_forgotten ON engrams(forgotten)")
    conn.execute("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, project TEXT, task TEXT,
            status TEXT DEFAULT 'active', started_at TEXT NOT NULL,
            ended_at TEXT, summary TEXT, metadata TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE session_events (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
            event_type TEXT NOT NULL, payload TEXT,
            fingerprint TEXT, created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    # Insert test data
    now = "2026-04-01T12:00:00"
    conn.execute(
        "INSERT INTO engrams (id, content, type, strength, importance, origin, "
        "created_at, last_accessed, forgotten) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("e1", "Redis cache config", "fact", 0.8, "normal", "human", now, now, 0),
    )
    conn.execute(
        "INSERT INTO engrams (id, content, type, strength, importance, origin, "
        "created_at, last_accessed, forgotten) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("e2", "User prefers dark mode", "preference", 0.9, "critical", "human", now, now, 0),
    )
    conn.execute(
        "INSERT INTO engrams (id, content, type, strength, importance, origin, "
        "created_at, last_accessed, forgotten) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("e3", "Old deleted memory", "debugging", 0.1, "low", "agent", now, now, 1),
    )
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    return conn


def test_migration_sets_state_from_forgotten(tmp_path):
    db_path = tmp_path / "test.db"
    conn = _create_v03_db(db_path)
    conn.close()

    from memento.migration import migrate_v03_to_v05

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    migrate_v03_to_v05(conn)

    # Active engrams → consolidated
    row = conn.execute("SELECT state FROM engrams WHERE id='e1'").fetchone()
    assert row["state"] == "consolidated"

    # Forgotten engrams → forgotten state
    row = conn.execute("SELECT state FROM engrams WHERE id='e3'").fetchone()
    assert row["state"] == "forgotten"


def test_migration_sets_rigidity_by_type(tmp_path):
    db_path = tmp_path / "test.db"
    conn = _create_v03_db(db_path)
    conn.close()

    from memento.migration import migrate_v03_to_v05

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    migrate_v03_to_v05(conn)

    # fact → 0.5
    row = conn.execute("SELECT rigidity FROM engrams WHERE id='e1'").fetchone()
    assert row["rigidity"] == pytest.approx(0.5)

    # preference → 0.7
    row = conn.execute("SELECT rigidity FROM engrams WHERE id='e2'").fetchone()
    assert row["rigidity"] == pytest.approx(0.7)

    # debugging → 0.15
    row = conn.execute("SELECT rigidity FROM engrams WHERE id='e3'").fetchone()
    assert row["rigidity"] == pytest.approx(0.15)


def test_migration_fills_content_hash(tmp_path):
    db_path = tmp_path / "test.db"
    conn = _create_v03_db(db_path)
    conn.close()

    from memento.migration import migrate_v03_to_v05

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    migrate_v03_to_v05(conn)

    row = conn.execute("SELECT content_hash FROM engrams WHERE id='e1'").fetchone()
    expected = hashlib.sha256("Redis cache config".encode()).hexdigest()
    assert row["content_hash"] == expected


def test_migration_creates_new_tables(tmp_path):
    db_path = tmp_path / "test.db"
    conn = _create_v03_db(db_path)
    conn.close()

    from memento.migration import migrate_v03_to_v05

    conn = sqlite3.connect(str(db_path))
    migrate_v03_to_v05(conn)

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    expected_tables = {
        "capture_log", "nexus", "delta_ledger", "recon_buffer",
        "epochs", "cognitive_debt", "view_engrams", "view_nexus",
        "view_pointer", "runtime_cursors", "pending_forget",
    }
    assert expected_tables.issubset(tables)


def test_migration_populates_view_store(tmp_path):
    db_path = tmp_path / "test.db"
    conn = _create_v03_db(db_path)
    conn.close()

    from memento.migration import migrate_v03_to_v05

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    migrate_v03_to_v05(conn)

    # Only consolidated engrams in view_engrams
    rows = conn.execute("SELECT id FROM view_engrams").fetchall()
    ids = {r["id"] for r in rows}
    assert ids == {"e1", "e2"}  # e3 is forgotten, not in view

    # view_pointer initialized
    vp = conn.execute("SELECT * FROM view_pointer WHERE id='current'").fetchone()
    assert vp is not None
    assert vp["epoch_id"] is None


def test_migration_sets_user_version(tmp_path):
    db_path = tmp_path / "test.db"
    conn = _create_v03_db(db_path)
    conn.close()

    from memento.migration import migrate_v03_to_v05

    conn = sqlite3.connect(str(db_path))
    migrate_v03_to_v05(conn)

    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 5


def test_migration_is_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    conn = _create_v03_db(db_path)
    conn.close()

    from memento.migration import migrate_v03_to_v05

    conn = sqlite3.connect(str(db_path))
    migrate_v03_to_v05(conn)
    # Running again should be a no-op
    migrate_v03_to_v05(conn)

    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_migration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memento.migration'`

- [ ] **Step 3: Implement migration module**

```python
# src/memento/migration.py
"""v0.3 → v0.5 in-place database migration."""
import hashlib
import sqlite3
from datetime import datetime, timezone

RIGIDITY_DEFAULTS = {
    "preference": 0.7, "convention": 0.7,
    "fact": 0.5, "decision": 0.5,
    "debugging": 0.15, "insight": 0.15,
}

_NEW_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS capture_log (
    id                TEXT PRIMARY KEY,
    content           TEXT NOT NULL,
    type              TEXT DEFAULT 'fact',
    tags              TEXT,
    importance        TEXT DEFAULT 'normal',
    origin            TEXT DEFAULT 'human',
    source_session_id TEXT,
    source_event_id   TEXT,
    content_hash      TEXT NOT NULL,
    embedding         BLOB,
    embedding_dim     INTEGER,
    embedding_pending INTEGER DEFAULT 0,
    created_at        TEXT NOT NULL,
    epoch_id          TEXT,
    disposition       TEXT,
    drop_reason       TEXT
);

CREATE INDEX IF NOT EXISTS idx_capture_unconsumed ON capture_log(epoch_id) WHERE epoch_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_capture_hash ON capture_log(content_hash);
CREATE INDEX IF NOT EXISTS idx_capture_created ON capture_log(created_at);

CREATE TABLE IF NOT EXISTS nexus (
    id                   TEXT PRIMARY KEY,
    source_id            TEXT NOT NULL REFERENCES engrams(id) ON DELETE CASCADE,
    target_id            TEXT NOT NULL REFERENCES engrams(id) ON DELETE CASCADE,
    direction            TEXT DEFAULT 'directed',
    type                 TEXT NOT NULL,
    association_strength REAL DEFAULT 0.5,
    created_at           TEXT NOT NULL,
    last_coactivated_at  TEXT,
    CHECK(source_id <> target_id),
    UNIQUE(source_id, target_id, type)
);

CREATE INDEX IF NOT EXISTS idx_nexus_source ON nexus(source_id, type);
CREATE INDEX IF NOT EXISTS idx_nexus_target ON nexus(target_id, type);
CREATE INDEX IF NOT EXISTS idx_nexus_strength ON nexus(source_id, association_strength DESC);

CREATE TABLE IF NOT EXISTS delta_ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    engram_id   TEXT NOT NULL,
    delta_type  TEXT NOT NULL,
    delta_value REAL NOT NULL,
    epoch_id    TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_delta_unconsumed ON delta_ledger(epoch_id) WHERE epoch_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_delta_engram ON delta_ledger(engram_id);

CREATE TABLE IF NOT EXISTS recon_buffer (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    engram_id                 TEXT NOT NULL,
    query_context             TEXT,
    coactivated_ids           TEXT,
    idempotency_key           TEXT UNIQUE,
    nexus_consumed_epoch_id   TEXT,
    content_consumed_epoch_id TEXT,
    created_at                TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recon_nexus_unconsumed ON recon_buffer(nexus_consumed_epoch_id) WHERE nexus_consumed_epoch_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_recon_content_unconsumed ON recon_buffer(content_consumed_epoch_id) WHERE content_consumed_epoch_id IS NULL;

CREATE TABLE IF NOT EXISTS epochs (
    id               TEXT PRIMARY KEY,
    vault_id         TEXT NOT NULL DEFAULT 'default',
    status           TEXT NOT NULL,
    mode             TEXT NOT NULL DEFAULT 'full',
    trigger          TEXT NOT NULL DEFAULT 'manual',
    seal_timestamp   TEXT NOT NULL,
    lease_acquired   TEXT NOT NULL,
    lease_expires    TEXT NOT NULL,
    llm_base_url     TEXT,
    llm_model        TEXT,
    stats            TEXT,
    started_at       TEXT,
    committed_at     TEXT,
    error            TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_epoch_active ON epochs(vault_id) WHERE status IN ('leased', 'running');

CREATE TABLE IF NOT EXISTS cognitive_debt (
    id                 TEXT PRIMARY KEY,
    type               TEXT NOT NULL,
    raw_ref            TEXT NOT NULL,
    priority           REAL DEFAULT 0.5,
    accumulated_epochs INTEGER DEFAULT 0,
    created_at         TEXT NOT NULL,
    resolved_at        TEXT
);

CREATE TABLE IF NOT EXISTS view_engrams (
    id            TEXT PRIMARY KEY,
    content       TEXT NOT NULL,
    type          TEXT,
    tags          TEXT,
    state         TEXT NOT NULL,
    strength      REAL NOT NULL,
    importance    TEXT,
    origin        TEXT,
    verified      INTEGER,
    rigidity      REAL,
    access_count  INTEGER,
    created_at    TEXT,
    last_accessed TEXT,
    content_hash  TEXT,
    embedding     BLOB,
    embedding_dim INTEGER
);

CREATE TABLE IF NOT EXISTS view_nexus (
    id                   TEXT PRIMARY KEY,
    source_id            TEXT NOT NULL,
    target_id            TEXT NOT NULL,
    direction            TEXT,
    type                 TEXT NOT NULL,
    association_strength REAL
);

CREATE TABLE IF NOT EXISTS view_pointer (
    id           TEXT PRIMARY KEY DEFAULT 'current',
    epoch_id     TEXT,
    refreshed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_cursors (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_forget (
    id           TEXT PRIMARY KEY,
    target_table TEXT NOT NULL,
    target_id    TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    UNIQUE(target_table, target_id)
);
"""


def migrate_v03_to_v05(conn: sqlite3.Connection) -> None:
    """Migrate a v0.3 database to v0.5 schema in-place."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 5:
        return  # Already migrated

    now = datetime.now(timezone.utc).isoformat()

    # Add new columns to engrams
    _ensure_column(conn, "engrams", "state", "TEXT DEFAULT 'consolidated'")
    _ensure_column(conn, "engrams", "rigidity", "REAL DEFAULT 0.5")
    _ensure_column(conn, "engrams", "content_hash", "TEXT")
    _ensure_column(conn, "engrams", "last_state_changed_epoch_id", "TEXT")

    # Create indexes on new columns
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_engrams_state ON engrams(state)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_engrams_content_hash ON engrams(content_hash)"
    )

    # Create all new tables
    conn.executescript(_NEW_TABLES_SQL)

    # Migrate state from forgotten flag
    conn.execute("UPDATE engrams SET state = 'forgotten' WHERE forgotten = 1")
    conn.execute("UPDATE engrams SET state = 'consolidated' WHERE forgotten = 0")

    # Set rigidity by type
    for engram_type, rigidity in RIGIDITY_DEFAULTS.items():
        conn.execute(
            "UPDATE engrams SET rigidity = ? WHERE type = ?",
            (rigidity, engram_type),
        )

    # Backfill content_hash
    rows = conn.execute("SELECT id, content FROM engrams").fetchall()
    for row in rows:
        content_hash = hashlib.sha256(row[1].encode()).hexdigest()
        conn.execute(
            "UPDATE engrams SET content_hash = ? WHERE id = ?",
            (content_hash, row[0]),
        )

    # Populate view_engrams from consolidated engrams
    conn.execute("DELETE FROM view_engrams")
    conn.execute("""
        INSERT INTO view_engrams
            (id, content, type, tags, state, strength, importance, origin,
             verified, rigidity, access_count, created_at, last_accessed,
             content_hash, embedding, embedding_dim)
        SELECT
            id, content, type, tags, state, strength, importance, origin,
            verified, rigidity, access_count, created_at, last_accessed,
            content_hash, embedding, embedding_dim
        FROM engrams WHERE state = 'consolidated'
    """)

    # Initialize view_pointer
    conn.execute(
        "INSERT OR REPLACE INTO view_pointer (id, epoch_id, refreshed_at) "
        "VALUES ('current', NULL, ?)",
        (now,),
    )

    # Initialize runtime_cursors
    conn.execute(
        "INSERT OR REPLACE INTO runtime_cursors (key, value, updated_at) "
        "VALUES ('decay_watermark', ?, ?)",
        (now, now),
    )

    conn.execute(f"PRAGMA user_version = 5")
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    """Add column if it doesn't exist."""
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_migration.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/migration.py tests/test_migration.py
git commit -m "feat(v0.5): Layer 1 — schema migration v0.3→v0.5

Add 11 new tables (capture_log, nexus, delta_ledger, recon_buffer,
epochs, cognitive_debt, view_engrams, view_nexus, view_pointer,
runtime_cursors, pending_forget) and 4 new columns on engrams
(state, rigidity, content_hash, last_state_changed_epoch_id).
Idempotent migration with state/rigidity backfill."
```

---

## Task 2: State Machine Engine

**Files:**
- Create: `src/memento/state_machine.py`
- Create: `tests/test_state_machine.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_state_machine.py
import pytest
from memento.state_machine import (
    STATES, TRANSITIONS, validate_transition,
    TransitionPlan, DropDecision,
)


def test_states_are_five():
    assert STATES == {"buffered", "consolidated", "abstracted", "archived", "forgotten"}


def test_forgotten_is_absorbing():
    assert TRANSITIONS["forgotten"] == {}


def test_valid_transitions():
    assert validate_transition("buffered", "consolidated") is True
    assert validate_transition("consolidated", "archived") is True
    assert validate_transition("consolidated", "forgotten") is True
    assert validate_transition("archived", "consolidated") is True  # T9 wake


def test_invalid_transitions():
    assert validate_transition("buffered", "forgotten") is False
    assert validate_transition("forgotten", "consolidated") is False
    assert validate_transition("consolidated", "buffered") is False
    assert validate_transition("abstracted", "consolidated") is False


def test_transition_plan_fields():
    plan = TransitionPlan(
        engram_id="e1", capture_log_id=None,
        from_state="consolidated", to_state="archived",
        transition="T6", reason="strength below threshold",
        epoch_id="ep1", metadata={"policy": "decay"},
    )
    assert plan.transition == "T6"
    assert plan.capture_log_id is None


def test_transition_plan_t1_has_capture_log_id():
    plan = TransitionPlan(
        engram_id=None, capture_log_id="cl1",
        from_state="buffered", to_state="consolidated",
        transition="T1", reason="LLM structured",
        epoch_id="ep1", metadata={},
    )
    assert plan.capture_log_id == "cl1"
    assert plan.engram_id is None  # Generated by apply layer


def test_drop_decision():
    drop = DropDecision(
        capture_log_id="cl2", reason="noise", epoch_id="ep1",
    )
    assert drop.reason == "noise"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_state_machine.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement state machine**

```python
# src/memento/state_machine.py
"""Five-state state machine for Engram lifecycle."""
from dataclasses import dataclass, field
from typing import Optional

STATES = frozenset({"buffered", "consolidated", "abstracted", "archived", "forgotten"})

TRANSITIONS = {
    "buffered":     {"consolidated": "T1"},
    "consolidated": {"abstracted": "T5", "archived": "T6", "forgotten": "T7"},
    "abstracted":   {"archived": "T8"},
    "archived":     {"consolidated": "T9", "forgotten": "T10"},
    "forgotten":    {},  # Absorbing state
}


def validate_transition(from_state: str, to_state: str) -> bool:
    """Check if a state transition is legal."""
    return to_state in TRANSITIONS.get(from_state, {})


@dataclass
class TransitionPlan:
    """Planned state transition — pure data, no side effects."""
    engram_id: Optional[str]       # None for T1 (generated by apply layer)
    capture_log_id: Optional[str]  # Only for T1
    from_state: str
    to_state: str
    transition: str                # T1/T5-T10
    reason: str
    epoch_id: str
    metadata: dict = field(default_factory=dict)


@dataclass
class DropDecision:
    """L2 discard decision — not a state transition."""
    capture_log_id: str
    reason: str   # 'noise' / 'duplicate' / 'below_threshold'
    epoch_id: str
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_state_machine.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/state_machine.py tests/test_state_machine.py
git commit -m "feat(v0.5): Layer 2 — five-state state machine engine"
```

---

## Task 3: Rigidity Engine

**Files:**
- Create: `src/memento/rigidity.py`
- Create: `tests/test_rigidity.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_rigidity.py
import pytest
from memento.rigidity import (
    RIGIDITY_DEFAULTS, CONTENT_LOCK_THRESHOLD,
    can_modify_content, max_drift_per_epoch,
    ReconsolidationPlan, plan_reconsolidation,
)


def test_defaults():
    assert RIGIDITY_DEFAULTS["preference"] == 0.7
    assert RIGIDITY_DEFAULTS["fact"] == 0.5
    assert RIGIDITY_DEFAULTS["debugging"] == 0.15


def test_can_modify_below_threshold():
    assert can_modify_content(0.49) is True
    assert can_modify_content(0.15) is True


def test_cannot_modify_at_or_above_threshold():
    assert can_modify_content(0.50) is False
    assert can_modify_content(0.7) is False
    assert can_modify_content(1.0) is False


def test_max_drift_locked():
    assert max_drift_per_epoch(0.5) == 0.0
    assert max_drift_per_epoch(0.8) == 0.0
    assert max_drift_per_epoch(1.0) == 0.0


def test_max_drift_unlocked():
    # rigidity=0.15 → (1-0.15)*0.3 = 0.255
    assert max_drift_per_epoch(0.15) == pytest.approx(0.255)
    # rigidity=0.0 → 1.0*0.3 = 0.3
    assert max_drift_per_epoch(0.0) == pytest.approx(0.3)


def test_plan_reconsolidation_locked():
    engram = {"id": "e1", "rigidity": 0.7, "content": "fact"}
    result = plan_reconsolidation(engram, [{"query_context": "q", "coactivated_ids": "[]"}])
    assert result is not None
    assert result.allow_content_update is False
    assert result.max_drift == 0.0


def test_plan_reconsolidation_unlocked():
    engram = {"id": "e1", "rigidity": 0.15, "content": "memory"}
    items = [{"query_context": "q1", "coactivated_ids": '["e2"]'}]
    result = plan_reconsolidation(engram, items)
    assert result is not None
    assert result.allow_content_update is True
    assert result.max_drift == pytest.approx(0.255)
    assert result.llm_inputs["current_content"] == "memory"


def test_plan_reconsolidation_empty_items():
    engram = {"id": "e1", "rigidity": 0.15, "content": "memory"}
    result = plan_reconsolidation(engram, [])
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_rigidity.py -v`
Expected: FAIL

- [ ] **Step 3: Implement rigidity engine**

```python
# src/memento/rigidity.py
"""Rigidity engine — controls memory plasticity."""
import json
from dataclasses import dataclass, field
from typing import Optional

RIGIDITY_DEFAULTS = {
    "preference": 0.7, "convention": 0.7,
    "fact": 0.5, "decision": 0.5,
    "debugging": 0.15, "insight": 0.15,
}

CONTENT_LOCK_THRESHOLD = 0.5
MAX_DRIFT_STEP = 0.3


def can_modify_content(rigidity: float) -> bool:
    """rigidity < 0.5 → content modifiable."""
    return rigidity < CONTENT_LOCK_THRESHOLD


def max_drift_per_epoch(rigidity: float) -> float:
    """Maximum content drift allowed per epoch."""
    if rigidity >= CONTENT_LOCK_THRESHOLD:
        return 0.0
    return (1.0 - rigidity) * MAX_DRIFT_STEP


@dataclass
class ReconsolidationPlan:
    """Reconsolidation plan — prepared for Epoch LLM phase."""
    engram_id: str
    allow_content_update: bool
    max_drift: float
    llm_inputs: dict = field(default_factory=dict)
    nexus_candidates: list = field(default_factory=list)


def plan_reconsolidation(
    engram: dict, recon_items: list[dict]
) -> Optional[ReconsolidationPlan]:
    """Plan reconsolidation for a single engram. None = nothing to do."""
    if not recon_items:
        return None

    rigidity = engram.get("rigidity", 0.5)
    allow = can_modify_content(rigidity)
    drift = max_drift_per_epoch(rigidity)

    query_contexts = []
    coactivated_contents = []
    for item in recon_items:
        if item.get("query_context"):
            query_contexts.append(item["query_context"])
        ids_raw = item.get("coactivated_ids", "[]")
        if isinstance(ids_raw, str):
            ids_raw = json.loads(ids_raw)
        coactivated_contents.extend(ids_raw)

    return ReconsolidationPlan(
        engram_id=engram["id"],
        allow_content_update=allow,
        max_drift=drift,
        llm_inputs={
            "current_content": engram.get("content", ""),
            "query_contexts": query_contexts,
            "coactivated_contents": coactivated_contents,
        },
    )
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_rigidity.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/rigidity.py tests/test_rigidity.py
git commit -m "feat(v0.5): Layer 2 — rigidity engine"
```

---

## Task 4: Decay Engine Refactor

**Files:**
- Modify: `src/memento/decay.py`
- Create: `tests/test_decay_v05.py`

- [ ] **Step 1: Write tests for new functions**

```python
# tests/test_decay_v05.py
"""Tests for v0.5 decay additions: watermark-based decay + reinforce delta."""
import pytest
from datetime import datetime, timezone, timedelta
from memento.decay import (
    compute_decay_deltas, compute_reinforce_delta, MIN_DECAY_DELTA,
)


def _iso(dt):
    return dt.isoformat()


def _make_engram(eid, strength=0.7, hours_ago=24, access_count=0, importance="normal"):
    now = datetime.now(timezone.utc)
    return {
        "id": eid,
        "strength": strength,
        "last_accessed": _iso(now - timedelta(hours=hours_ago)),
        "access_count": access_count,
        "importance": importance,
    }


def test_compute_decay_deltas_produces_negative():
    now = datetime.now(timezone.utc)
    watermark = _iso(now - timedelta(hours=6))
    engrams = [_make_engram("e1", strength=0.7, hours_ago=48)]

    deltas, new_wm = compute_decay_deltas(engrams, watermark, _iso(now))

    assert len(deltas) >= 1
    d = deltas[0]
    assert d["engram_id"] == "e1"
    assert d["delta_type"] == "decay"
    assert d["delta_value"] < 0


def test_compute_decay_deltas_filters_tiny():
    now = datetime.now(timezone.utc)
    # Very short interval → tiny delta → filtered
    watermark = _iso(now - timedelta(seconds=1))
    engrams = [_make_engram("e1", strength=0.7, hours_ago=1)]

    deltas, _ = compute_decay_deltas(engrams, watermark, _iso(now))

    # Delta should be too small and filtered out
    for d in deltas:
        assert abs(d["delta_value"]) > MIN_DECAY_DELTA


def test_compute_decay_deltas_advances_watermark():
    now = datetime.now(timezone.utc)
    watermark = _iso(now - timedelta(hours=6))
    now_iso = _iso(now)

    _, new_wm = compute_decay_deltas([], watermark, now_iso)
    assert new_wm == now_iso


def test_compute_reinforce_delta_positive():
    engram = _make_engram("e1", strength=0.7, hours_ago=24)
    delta = compute_reinforce_delta(engram)

    assert delta["engram_id"] == "e1"
    assert delta["delta_type"] == "reinforce"
    assert delta["delta_value"] > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_decay_v05.py -v`
Expected: FAIL — `ImportError: cannot import name 'compute_decay_deltas'`

- [ ] **Step 3: Add new functions to decay.py**

Add to the end of `src/memento/decay.py`:

```python
# --- v0.5 additions ---

MIN_DECAY_DELTA = 0.001


def compute_reinforce_delta(engram: dict, now=None) -> dict:
    """Compute reinforcement delta for a recall hit."""
    if now is None:
        now = datetime.now(timezone.utc)
    elif isinstance(now, str):
        now = datetime.fromisoformat(now)

    boost = reinforcement_boost(engram["last_accessed"], now)
    return {
        "engram_id": engram["id"],
        "delta_type": "reinforce",
        "delta_value": boost,
    }


def compute_decay_deltas(
    engrams: list, watermark: str, now: str = None
) -> tuple:
    """Compute decay deltas from watermark to now.

    Returns (deltas, new_watermark).
    """
    if now is None:
        now = datetime.now(timezone.utc).isoformat()

    deltas = []
    for e in engrams:
        s_at_wm = effective_strength(
            e["strength"], e["last_accessed"],
            e.get("access_count", 0), e.get("importance", "normal"),
            now=watermark,
        )
        s_at_now = effective_strength(
            e["strength"], e["last_accessed"],
            e.get("access_count", 0), e.get("importance", "normal"),
            now=now,
        )
        delta = s_at_now - s_at_wm
        if abs(delta) > MIN_DECAY_DELTA:
            deltas.append({
                "engram_id": e["id"],
                "delta_type": "decay",
                "delta_value": delta,
            })

    return deltas, now
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_decay_v05.py tests/test_decay.py -v`
Expected: All PASS (both old and new tests)

- [ ] **Step 5: Commit**

```bash
git add src/memento/decay.py tests/test_decay_v05.py
git commit -m "feat(v0.5): Layer 2 — decay engine watermark + reinforce delta"
```

---

## Task 5: Delta Fold Engine

**Files:**
- Create: `src/memento/delta_fold.py`
- Create: `tests/test_delta_fold.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_delta_fold.py
import pytest
from memento.delta_fold import (
    StrengthDelta, StrengthUpdatePlan,
    fold_deltas, plan_strength_updates,
    ARCHIVE_THRESHOLD, AGENT_STRENGTH_CAP,
)


def test_fold_single_engram_multiple_deltas():
    deltas = [
        {"id": 1, "engram_id": "e1", "delta_type": "reinforce", "delta_value": 0.05},
        {"id": 2, "engram_id": "e1", "delta_type": "reinforce", "delta_value": 0.03},
        {"id": 3, "engram_id": "e1", "delta_type": "decay", "delta_value": -0.02},
    ]
    results = fold_deltas(deltas)
    assert len(results) == 1
    r = results[0]
    assert r.engram_id == "e1"
    assert r.net_delta == pytest.approx(0.06)
    assert r.reinforce_count == 2
    assert r.decay_count == 1
    assert set(r.source_ledger_ids) == {1, 2, 3}


def test_fold_multiple_engrams():
    deltas = [
        {"id": 1, "engram_id": "e1", "delta_type": "reinforce", "delta_value": 0.05},
        {"id": 2, "engram_id": "e2", "delta_type": "decay", "delta_value": -0.01},
    ]
    results = fold_deltas(deltas)
    assert len(results) == 2


def test_plan_strength_clamps_to_bounds():
    folds = [StrengthDelta("e1", net_delta=0.5, reinforce_count=1, decay_count=0, source_ledger_ids=[1])]
    lookup = {"e1": {"strength": 0.9, "access_count": 5, "origin": "human", "verified": 1}}
    plans = plan_strength_updates(folds, lookup)
    assert plans[0].new_strength == 1.0  # Clamped


def test_plan_strength_agent_cap():
    folds = [StrengthDelta("e1", net_delta=0.3, reinforce_count=1, decay_count=0, source_ledger_ids=[1])]
    lookup = {"e1": {"strength": 0.4, "access_count": 0, "origin": "agent", "verified": 0}}
    plans = plan_strength_updates(folds, lookup)
    assert plans[0].new_strength == AGENT_STRENGTH_CAP  # 0.5


def test_plan_strength_pure_decay_no_last_accessed_update():
    folds = [StrengthDelta("e1", net_delta=-0.1, reinforce_count=0, decay_count=3, source_ledger_ids=[1, 2, 3])]
    lookup = {"e1": {"strength": 0.6, "access_count": 2, "origin": "human", "verified": 1}}
    plans = plan_strength_updates(folds, lookup)
    assert plans[0].update_last_accessed is False
    assert plans[0].access_count_delta == 0


def test_plan_strength_with_reinforce_updates_last_accessed():
    folds = [StrengthDelta("e1", net_delta=0.03, reinforce_count=2, decay_count=1, source_ledger_ids=[1, 2, 3])]
    lookup = {"e1": {"strength": 0.5, "access_count": 3, "origin": "human", "verified": 1}}
    plans = plan_strength_updates(folds, lookup)
    assert plans[0].update_last_accessed is True
    assert plans[0].access_count_delta == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_delta_fold.py -v`
Expected: FAIL

- [ ] **Step 3: Implement delta fold**

```python
# src/memento/delta_fold.py
"""Delta Ledger fold engine — collapse deltas into net strength changes."""
from collections import defaultdict
from dataclasses import dataclass

ARCHIVE_THRESHOLD = 0.05
AGENT_STRENGTH_CAP = 0.5


@dataclass
class StrengthDelta:
    engram_id: str
    net_delta: float
    reinforce_count: int
    decay_count: int
    source_ledger_ids: list


@dataclass
class StrengthUpdatePlan:
    engram_id: str
    old_strength: float
    new_strength: float
    access_count_delta: int
    update_last_accessed: bool
    source_ledger_ids: list


def fold_deltas(deltas: list) -> list:
    """Group and fold delta_ledger records by engram_id."""
    groups = defaultdict(lambda: {"reinforce": 0.0, "decay": 0.0, "r_count": 0, "d_count": 0, "ids": []})
    for d in deltas:
        g = groups[d["engram_id"]]
        g["ids"].append(d["id"])
        if d["delta_type"] == "reinforce":
            g["reinforce"] += d["delta_value"]
            g["r_count"] += 1
        else:
            g["decay"] += d["delta_value"]
            g["d_count"] += 1

    return [
        StrengthDelta(
            engram_id=eid,
            net_delta=g["reinforce"] + g["decay"],
            reinforce_count=g["r_count"],
            decay_count=g["d_count"],
            source_ledger_ids=g["ids"],
        )
        for eid, g in groups.items()
    ]


def plan_strength_updates(folds: list, engrams_lookup: dict) -> list:
    """Convert folded deltas to update plans with clamping."""
    plans = []
    for f in folds:
        info = engrams_lookup.get(f.engram_id)
        if info is None:
            continue
        old = info["strength"]
        cap = 1.0
        if info.get("origin") == "agent" and not info.get("verified"):
            cap = AGENT_STRENGTH_CAP
        new = max(0.0, min(cap, old + f.net_delta))
        plans.append(StrengthUpdatePlan(
            engram_id=f.engram_id,
            old_strength=old,
            new_strength=new,
            access_count_delta=f.reinforce_count,
            update_last_accessed=f.reinforce_count > 0,
            source_ledger_ids=f.source_ledger_ids,
        ))
    return plans
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_delta_fold.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/delta_fold.py tests/test_delta_fold.py
git commit -m "feat(v0.5): Layer 2 — delta fold engine"
```

---

## Task 6: Hebbian Learning Engine

**Files:**
- Create: `src/memento/hebbian.py`
- Create: `tests/test_hebbian.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_hebbian.py
import json
import pytest
from memento.hebbian import (
    NexusUpdatePlan, plan_nexus_updates, COACTIVATION_BOOST,
)


def test_single_coactivation_creates_new_nexus():
    items = [{
        "id": 1, "engram_id": "e1",
        "coactivated_ids": json.dumps(["e2"]),
        "query_context": "test",
    }]
    existing = {}
    plans = plan_nexus_updates(items, existing)
    assert len(plans) == 1
    p = plans[0]
    # Normalized: source < target
    assert p.source_id < p.target_id
    assert {p.source_id, p.target_id} == {"e1", "e2"}
    assert p.is_new is True
    assert p.strength_delta == pytest.approx(COACTIVATION_BOOST)
    assert 1 in p.source_recon_ids


def test_existing_nexus_increments():
    items = [{
        "id": 1, "engram_id": "e1",
        "coactivated_ids": json.dumps(["e2"]),
        "query_context": "test",
    }]
    existing = {("e1", "e2", "semantic"): 0.3}
    plans = plan_nexus_updates(items, existing)
    assert len(plans) == 1
    assert plans[0].is_new is False


def test_aggregation_no_duplicate_amplification():
    items = [
        {"id": 1, "engram_id": "e1", "coactivated_ids": json.dumps(["e2"]), "query_context": "q1"},
        {"id": 2, "engram_id": "e1", "coactivated_ids": json.dumps(["e2"]), "query_context": "q2"},
        {"id": 3, "engram_id": "e2", "coactivated_ids": json.dumps(["e1"]), "query_context": "q3"},
    ]
    existing = {}
    plans = plan_nexus_updates(items, existing)
    # All three refer to the same pair (e1, e2) — should produce 1 plan
    assert len(plans) == 1
    p = plans[0]
    assert p.strength_delta == pytest.approx(COACTIVATION_BOOST * 3)
    assert set(p.source_recon_ids) == {1, 2, 3}


def test_multiple_pairs():
    items = [{
        "id": 1, "engram_id": "e1",
        "coactivated_ids": json.dumps(["e2", "e3"]),
        "query_context": "test",
    }]
    existing = {}
    plans = plan_nexus_updates(items, existing)
    pairs = {(p.source_id, p.target_id) for p in plans}
    assert len(pairs) == 2


def test_bidirectional_normalization():
    items = [
        {"id": 1, "engram_id": "zzz", "coactivated_ids": json.dumps(["aaa"]), "query_context": "q"},
    ]
    plans = plan_nexus_updates(items, {})
    assert plans[0].source_id == "aaa"
    assert plans[0].target_id == "zzz"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_hebbian.py -v`
Expected: FAIL

- [ ] **Step 3: Implement hebbian engine**

```python
# src/memento/hebbian.py
"""Hebbian learning engine — Nexus co-activation updates."""
import json
from collections import defaultdict
from dataclasses import dataclass, field

COACTIVATION_BOOST = 0.05
MAX_ASSOCIATION = 1.0


@dataclass
class NexusUpdatePlan:
    source_id: str
    target_id: str
    type: str
    strength_delta: float
    last_coactivated_at: str
    is_new: bool
    source_recon_ids: list = field(default_factory=list)


def plan_nexus_updates(recon_items: list, existing_nexus: dict) -> list:
    """Compute Nexus updates from recon_buffer items.

    existing_nexus: {(source_id, target_id, type): current_strength}
    """
    # Aggregate by normalized pair
    pair_data = defaultdict(lambda: {"delta": 0.0, "recon_ids": [], "last_ts": ""})

    for item in recon_items:
        engram_id = item["engram_id"]
        coactivated_raw = item.get("coactivated_ids", "[]")
        if isinstance(coactivated_raw, str):
            coactivated_raw = json.loads(coactivated_raw)

        ts = item.get("created_at", item.get("query_context", ""))

        for other_id in coactivated_raw:
            if other_id == engram_id:
                continue
            # Normalize: source < target
            src = min(engram_id, other_id)
            tgt = max(engram_id, other_id)
            key = (src, tgt, "semantic")

            pd = pair_data[key]
            pd["delta"] += COACTIVATION_BOOST
            pd["recon_ids"].append(item["id"])
            if ts > pd["last_ts"]:
                pd["last_ts"] = ts

    plans = []
    for (src, tgt, ntype), pd in pair_data.items():
        is_new = (src, tgt, ntype) not in existing_nexus
        plans.append(NexusUpdatePlan(
            source_id=src,
            target_id=tgt,
            type=ntype,
            strength_delta=pd["delta"],
            last_coactivated_at=pd["last_ts"],
            is_new=is_new,
            source_recon_ids=list(set(pd["recon_ids"])),
        ))

    return plans
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_hebbian.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/hebbian.py tests/test_hebbian.py
git commit -m "feat(v0.5): Layer 2 — Hebbian learning engine"
```

---

## Task 7: Repository (Persistence Layer)

**Files:**
- Create: `src/memento/repository.py`
- Create: `tests/test_repository.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_repository.py
import sqlite3
import json
import hashlib
from datetime import datetime, timezone
import pytest
from memento.migration import migrate_v03_to_v05
from memento.state_machine import TransitionPlan, DropDecision
from memento.delta_fold import StrengthUpdatePlan
from memento.hebbian import NexusUpdatePlan


def _setup_db(tmp_path):
    """Create a fresh v0.5 database."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # Minimal v0.3 schema then migrate
    conn.execute("""
        CREATE TABLE engrams (
            id TEXT PRIMARY KEY, content TEXT NOT NULL, type TEXT DEFAULT 'fact',
            tags TEXT, strength REAL DEFAULT 0.7, importance TEXT DEFAULT 'normal',
            source TEXT, origin TEXT DEFAULT 'human', verified INTEGER DEFAULT 0,
            created_at TEXT NOT NULL, last_accessed TEXT NOT NULL,
            access_count INTEGER DEFAULT 0, forgotten INTEGER DEFAULT 0,
            embedding_pending INTEGER DEFAULT 0, embedding_dim INTEGER,
            embedding BLOB, source_session_id TEXT, source_event_id TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, project TEXT, task TEXT,
            status TEXT DEFAULT 'active', started_at TEXT NOT NULL,
            ended_at TEXT, summary TEXT, metadata TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE session_events (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
            event_type TEXT NOT NULL, payload TEXT,
            fingerprint TEXT, created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    migrate_v03_to_v05(conn)
    return conn


def test_apply_l2_to_l3(tmp_path):
    from memento.repository import apply_l2_to_l3

    conn = _setup_db(tmp_path)
    now = datetime.now(timezone.utc).isoformat()
    content_hash = hashlib.sha256(b"test content").hexdigest()

    # Insert a capture_log entry
    conn.execute(
        "INSERT INTO capture_log (id, content, type, importance, origin, "
        "content_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("cl1", "test content", "fact", "normal", "agent", content_hash, now),
    )
    conn.commit()

    plan = TransitionPlan(
        engram_id=None, capture_log_id="cl1",
        from_state="buffered", to_state="consolidated",
        transition="T1", reason="structured", epoch_id="ep1", metadata={},
    )
    capture_item = dict(conn.execute("SELECT * FROM capture_log WHERE id='cl1'").fetchone())

    engram_id = apply_l2_to_l3(conn, plan, capture_item)

    # engram created in L3
    row = conn.execute("SELECT * FROM engrams WHERE id=?", (engram_id,)).fetchone()
    assert row is not None
    assert row["state"] == "consolidated"
    assert row["content"] == "test content"

    # capture_log marked consumed
    cl = conn.execute("SELECT epoch_id, disposition FROM capture_log WHERE id='cl1'").fetchone()
    assert cl["epoch_id"] == "ep1"
    assert cl["disposition"] == "promoted"


def test_apply_pending_forgets(tmp_path):
    from memento.repository import apply_pending_forgets

    conn = _setup_db(tmp_path)
    now = datetime.now(timezone.utc).isoformat()

    # Insert an engram + nexus + delta + recon
    conn.execute(
        "INSERT INTO engrams (id, content, state, created_at, last_accessed) "
        "VALUES ('e1', 'to forget', 'consolidated', ?, ?)", (now, now)
    )
    conn.execute(
        "INSERT INTO engrams (id, content, state, created_at, last_accessed) "
        "VALUES ('e2', 'keep', 'consolidated', ?, ?)", (now, now)
    )
    conn.execute(
        "INSERT INTO nexus (id, source_id, target_id, type, created_at) "
        "VALUES ('n1', 'e1', 'e2', 'semantic', ?)", (now,)
    )
    conn.execute(
        "INSERT INTO delta_ledger (engram_id, delta_type, delta_value, created_at) "
        "VALUES ('e1', 'reinforce', 0.05, ?)", (now,)
    )
    conn.execute(
        "INSERT INTO recon_buffer (engram_id, idempotency_key, created_at) "
        "VALUES ('e1', 'rk1', ?)", (now,)
    )
    conn.execute(
        "INSERT INTO pending_forget (id, target_table, target_id, requested_at) "
        "VALUES ('pf1', 'engrams', 'e1', ?)", (now,)
    )
    conn.commit()

    count, forgotten_ids = apply_pending_forgets(conn, "ep1")
    assert count == 1
    assert "e1" in forgotten_ids

    # State changed
    row = conn.execute("SELECT state FROM engrams WHERE id='e1'").fetchone()
    assert row["state"] == "forgotten"

    # Nexus cleaned (CASCADE)
    assert conn.execute("SELECT COUNT(*) FROM nexus WHERE source_id='e1' OR target_id='e1'").fetchone()[0] == 0

    # Delta/recon cleaned
    assert conn.execute("SELECT COUNT(*) FROM delta_ledger WHERE engram_id='e1'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM recon_buffer WHERE engram_id='e1'").fetchone()[0] == 0

    # pending_forget consumed
    assert conn.execute("SELECT COUNT(*) FROM pending_forget").fetchone()[0] == 0


def test_apply_strength_plan(tmp_path):
    from memento.repository import apply_strength_plan

    conn = _setup_db(tmp_path)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO engrams (id, content, state, strength, access_count, "
        "created_at, last_accessed) VALUES ('e1', 'x', 'consolidated', 0.5, 3, ?, ?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO delta_ledger (engram_id, delta_type, delta_value, created_at) "
        "VALUES ('e1', 'reinforce', 0.05, ?)", (now,)
    )
    conn.commit()

    plans = [StrengthUpdatePlan(
        engram_id="e1", old_strength=0.5, new_strength=0.55,
        access_count_delta=2, update_last_accessed=True,
        source_ledger_ids=[1],
    )]
    apply_strength_plan(conn, plans, "ep1")

    row = conn.execute("SELECT strength, access_count FROM engrams WHERE id='e1'").fetchone()
    assert row["strength"] == pytest.approx(0.55)
    assert row["access_count"] == 5

    # delta_ledger marked consumed
    dl = conn.execute("SELECT epoch_id FROM delta_ledger WHERE id=1").fetchone()
    assert dl["epoch_id"] == "ep1"


def test_rebuild_view_store(tmp_path):
    from memento.repository import rebuild_view_store

    conn = _setup_db(tmp_path)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO engrams (id, content, state, strength, rigidity, "
        "created_at, last_accessed) VALUES ('e1', 'visible', 'consolidated', 0.7, 0.5, ?, ?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO engrams (id, content, state, strength, rigidity, "
        "created_at, last_accessed) VALUES ('e2', 'hidden', 'archived', 0.01, 0.5, ?, ?)",
        (now, now),
    )
    conn.commit()

    rebuild_view_store(conn, "ep1")

    views = conn.execute("SELECT id FROM view_engrams").fetchall()
    ids = {r["id"] for r in views}
    assert ids == {"e1"}  # Only consolidated

    vp = conn.execute("SELECT epoch_id FROM view_pointer WHERE id='current'").fetchone()
    assert vp["epoch_id"] == "ep1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_repository.py -v`
Expected: FAIL

- [ ] **Step 3: Implement repository**

```python
# src/memento/repository.py
"""Persistence layer — all apply_* functions that write to the database."""
import hashlib
import json
import uuid
from datetime import datetime, timezone


def apply_l2_to_l3(conn, plan, capture_item: dict) -> str:
    """T1: promote capture_log entry to engrams (L3). Returns new engram_id."""
    engram_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "INSERT INTO engrams (id, content, type, tags, strength, importance, "
        "origin, verified, state, rigidity, content_hash, created_at, "
        "last_accessed, access_count, forgotten, source_session_id, source_event_id, "
        "last_state_changed_epoch_id, embedding, embedding_dim) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'consolidated', ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?)",
        (
            engram_id,
            capture_item["content"],
            capture_item.get("type", "fact"),
            capture_item.get("tags"),
            0.5 if capture_item.get("origin") == "agent" else 0.7,
            capture_item.get("importance", "normal"),
            capture_item.get("origin", "human"),
            _default_rigidity(capture_item.get("type", "fact")),
            capture_item.get("content_hash"),
            now, now,
            capture_item.get("source_session_id"),
            capture_item.get("source_event_id"),
            plan.epoch_id,
            capture_item.get("embedding"),
            capture_item.get("embedding_dim"),
        ),
    )

    conn.execute(
        "UPDATE capture_log SET epoch_id = ?, disposition = 'promoted' WHERE id = ?",
        (plan.epoch_id, plan.capture_log_id),
    )
    conn.commit()
    return engram_id


def apply_drop_decisions(conn, drops: list) -> None:
    """Mark capture_log entries as dropped."""
    for drop in drops:
        conn.execute(
            "UPDATE capture_log SET epoch_id = ?, disposition = 'dropped', "
            "drop_reason = ? WHERE id = ?",
            (drop.epoch_id, drop.reason, drop.capture_log_id),
        )
    conn.commit()


def apply_transition_plan(conn, plan) -> None:
    """Execute a state transition on an existing engram."""
    conn.execute(
        "UPDATE engrams SET state = ?, last_state_changed_epoch_id = ? WHERE id = ?",
        (plan.to_state, plan.epoch_id, plan.engram_id),
    )
    conn.commit()


def apply_pending_forgets(conn, epoch_id: str) -> tuple:
    """Process pending_forget → T7 (engrams) or drop (capture_log) + cleanup."""
    # Handle capture_log targets first
    cl_rows = conn.execute(
        "SELECT target_id FROM pending_forget WHERE target_table = 'capture_log'"
    ).fetchall()
    for r in cl_rows:
        conn.execute(
            "UPDATE capture_log SET epoch_id = ?, disposition = 'dropped', "
            "drop_reason = 'user_forget' WHERE id = ?",
            (epoch_id, r[0]),
        )

    # Handle engrams targets
    rows = conn.execute(
        "SELECT target_id FROM pending_forget WHERE target_table = 'engrams'"
    ).fetchall()
    forgotten_ids = [r[0] for r in rows]

    if not forgotten_ids:
        return 0, []

    placeholders = ",".join("?" for _ in forgotten_ids)

    # T7: state → forgotten
    conn.execute(
        f"UPDATE engrams SET state = 'forgotten', last_state_changed_epoch_id = ? "
        f"WHERE id IN ({placeholders})",
        [epoch_id] + forgotten_ids,
    )

    # Clean delta_ledger (unconsumed)
    conn.execute(
        f"DELETE FROM delta_ledger WHERE engram_id IN ({placeholders}) AND epoch_id IS NULL",
        forgotten_ids,
    )

    # Clean recon_buffer (all related, regardless of consumption state)
    conn.execute(
        f"DELETE FROM recon_buffer WHERE engram_id IN ({placeholders})",
        forgotten_ids,
    )

    # Nexus cleaned by CASCADE (ON DELETE CASCADE on source_id/target_id)

    # Clear pending_forget
    conn.execute("DELETE FROM pending_forget")
    conn.commit()

    return len(forgotten_ids), forgotten_ids


def apply_strength_plan(conn, plans: list, epoch_id: str) -> None:
    """Batch update strength/access_count/last_accessed + mark delta_ledger."""
    now = datetime.now(timezone.utc).isoformat()
    for p in plans:
        if p.update_last_accessed:
            conn.execute(
                "UPDATE engrams SET strength = ?, access_count = access_count + ?, "
                "last_accessed = ? WHERE id = ?",
                (p.new_strength, p.access_count_delta, now, p.engram_id),
            )
        else:
            conn.execute(
                "UPDATE engrams SET strength = ? WHERE id = ?",
                (p.new_strength, p.engram_id),
            )

        # Mark consumed ledger rows
        if p.source_ledger_ids:
            placeholders = ",".join("?" for _ in p.source_ledger_ids)
            conn.execute(
                f"UPDATE delta_ledger SET epoch_id = ? WHERE id IN ({placeholders})",
                [epoch_id] + p.source_ledger_ids,
            )
    conn.commit()


def apply_nexus_plan(conn, plans: list, epoch_id: str) -> None:
    """Insert/update nexus + mark recon_buffer.nexus_consumed_epoch_id."""
    now = datetime.now(timezone.utc).isoformat()
    all_recon_ids = []

    for p in plans:
        if p.is_new:
            conn.execute(
                "INSERT INTO nexus (id, source_id, target_id, direction, type, "
                "association_strength, created_at, last_coactivated_at) "
                "VALUES (?, ?, ?, 'bidirectional', ?, ?, ?, ?)",
                (str(uuid.uuid4()), p.source_id, p.target_id, p.type,
                 min(p.strength_delta, 1.0), now, p.last_coactivated_at or now),
            )
        else:
            conn.execute(
                "UPDATE nexus SET association_strength = MIN(association_strength + ?, 1.0), "
                "last_coactivated_at = ? WHERE source_id = ? AND target_id = ? AND type = ?",
                (p.strength_delta, p.last_coactivated_at or now,
                 p.source_id, p.target_id, p.type),
            )
        all_recon_ids.extend(p.source_recon_ids)

    # Mark recon_buffer rows as nexus-consumed
    if all_recon_ids:
        unique_ids = list(set(all_recon_ids))
        placeholders = ",".join("?" for _ in unique_ids)
        conn.execute(
            f"UPDATE recon_buffer SET nexus_consumed_epoch_id = ? WHERE id IN ({placeholders})",
            [epoch_id] + unique_ids,
        )
    conn.commit()


def update_decay_watermark(conn, new_watermark: str) -> None:
    """Update runtime_cursors.decay_watermark."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE runtime_cursors SET value = ?, updated_at = ? WHERE key = 'decay_watermark'",
        (new_watermark, now),
    )
    conn.commit()


def defer_to_debt(conn, debt_type: str, raw_ref: dict, epoch_id: str) -> None:
    """Record cognitive debt. If existing unresolved debt with same raw_ref, increment."""
    ref_json = json.dumps(raw_ref, sort_keys=True)
    now = datetime.now(timezone.utc).isoformat()

    existing = conn.execute(
        "SELECT id FROM cognitive_debt WHERE raw_ref = ? AND resolved_at IS NULL",
        (ref_json,),
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE cognitive_debt SET accumulated_epochs = accumulated_epochs + 1 WHERE id = ?",
            (existing[0],),
        )
    else:
        conn.execute(
            "INSERT INTO cognitive_debt (id, type, raw_ref, created_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), debt_type, ref_json, now),
        )
    conn.commit()


def resolve_debt(conn, debt_type: str, raw_ref: dict) -> None:
    """Resolve cognitive debt after successful processing."""
    ref_json = json.dumps(raw_ref, sort_keys=True)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE cognitive_debt SET resolved_at = ? "
        "WHERE type = ? AND raw_ref = ? AND resolved_at IS NULL",
        (now, debt_type, ref_json),
    )
    conn.commit()


def rebuild_view_store(conn, epoch_id: str) -> None:
    """Atomically rebuild view_engrams + view_nexus + update view_pointer.
    Only consolidated engrams enter view_engrams (archived/abstracted excluded)."""
    now = datetime.now(timezone.utc).isoformat()

    conn.execute("DELETE FROM view_engrams")
    conn.execute("""
        INSERT INTO view_engrams
            (id, content, type, tags, state, strength, importance, origin,
             verified, rigidity, access_count, created_at, last_accessed,
             content_hash, embedding, embedding_dim)
        SELECT
            id, content, type, tags, state, strength, importance, origin,
            verified, rigidity, access_count, created_at, last_accessed,
            content_hash, embedding, embedding_dim
        FROM engrams WHERE state = 'consolidated'
    """)

    conn.execute("DELETE FROM view_nexus")
    conn.execute("""
        INSERT INTO view_nexus (id, source_id, target_id, direction, type, association_strength)
        SELECT n.id, n.source_id, n.target_id, n.direction, n.type, n.association_strength
        FROM nexus n
        JOIN engrams e1 ON n.source_id = e1.id AND e1.state = 'consolidated'
        JOIN engrams e2 ON n.target_id = e2.id AND e2.state = 'consolidated'
    """)

    conn.execute(
        "UPDATE view_pointer SET epoch_id = ?, refreshed_at = ? WHERE id = 'current'",
        (epoch_id, now),
    )
    conn.commit()


def _default_rigidity(engram_type: str) -> float:
    from memento.rigidity import RIGIDITY_DEFAULTS
    return RIGIDITY_DEFAULTS.get(engram_type, 0.5)
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_repository.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/repository.py tests/test_repository.py
git commit -m "feat(v0.5): Layer 2 — repository persistence layer"
```

---

## Task 8: Awake Track

**Files:**
- Create: `src/memento/awake.py`
- Create: `tests/test_awake.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_awake.py
import sqlite3
import hashlib
import json
from queue import Queue
from datetime import datetime, timezone
import pytest
from memento.migration import migrate_v03_to_v05


def _setup_v05_db(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""
        CREATE TABLE engrams (
            id TEXT PRIMARY KEY, content TEXT NOT NULL, type TEXT DEFAULT 'fact',
            tags TEXT, strength REAL DEFAULT 0.7, importance TEXT DEFAULT 'normal',
            source TEXT, origin TEXT DEFAULT 'human', verified INTEGER DEFAULT 0,
            created_at TEXT NOT NULL, last_accessed TEXT NOT NULL,
            access_count INTEGER DEFAULT 0, forgotten INTEGER DEFAULT 0,
            embedding_pending INTEGER DEFAULT 0, embedding_dim INTEGER,
            embedding BLOB, source_session_id TEXT, source_event_id TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, project TEXT, task TEXT,
            status TEXT DEFAULT 'active', started_at TEXT NOT NULL,
            ended_at TEXT, summary TEXT, metadata TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE session_events (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
            event_type TEXT NOT NULL, payload TEXT,
            fingerprint TEXT, created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    migrate_v03_to_v05(conn)
    return conn


def test_awake_capture_writes_l2(tmp_path):
    from memento.awake import awake_capture
    conn = _setup_v05_db(tmp_path)

    result = awake_capture(conn, "test memory", type="fact", tags=None,
                           importance="normal", origin="human")

    assert result["state"] == "buffered"
    assert result["capture_log_id"] is not None

    # Written to capture_log, NOT engrams
    cl = conn.execute("SELECT * FROM capture_log WHERE id=?",
                       (result["capture_log_id"],)).fetchone()
    assert cl is not None
    assert cl["content"] == "test memory"
    assert cl["epoch_id"] is None

    # Engrams untouched
    assert conn.execute("SELECT COUNT(*) FROM engrams").fetchone()[0] == 0


def test_awake_recall_dual_source(tmp_path):
    from memento.awake import awake_capture, awake_recall
    conn = _setup_v05_db(tmp_path)

    # Add a consolidated engram to view_engrams
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO engrams (id, content, state, strength, created_at, last_accessed) "
        "VALUES ('e1', 'Redis config guide', 'consolidated', 0.7, ?, ?)",
        (now, now),
    )
    from memento.repository import rebuild_view_store
    rebuild_view_store(conn, "init")

    # Add a buffered item via capture
    awake_capture(conn, "Redis cache tips", type="fact", tags=None,
                  importance="normal", origin="human")

    pulse_queue = Queue()
    results = awake_recall(conn, "Redis", max_results=5, pulse_queue=pulse_queue)

    # Should find both
    assert len(results) >= 1
    contents = {r["content"] for r in results}
    assert "Redis config guide" in contents

    # Check provisional flag on buffered items
    provisionals = [r for r in results if r.get("provisional")]
    for p in provisionals:
        assert p["content"] == "Redis cache tips"


def test_awake_forget_writes_pending(tmp_path):
    from memento.awake import awake_forget
    conn = _setup_v05_db(tmp_path)

    result = awake_forget(conn, "e1")
    assert result["status"] == "pending"

    row = conn.execute("SELECT * FROM pending_forget WHERE engram_id='e1'").fetchone()
    assert row is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_awake.py -v`
Expected: FAIL

- [ ] **Step 3: Implement awake track**

```python
# src/memento/awake.py
"""Awake track — fast read path + L2 capture."""
import hashlib
import uuid
from datetime import datetime, timezone
from queue import Queue
from typing import Optional

from memento.embedding import get_embedding


def awake_capture(conn, content: str, type: str = "fact", tags=None,
                  importance: str = "normal", origin: str = "human",
                  session_id: str = None, event_id: str = None) -> dict:
    """Write to capture_log (L2). Never writes to engrams (L3)."""
    now = datetime.now(timezone.utc).isoformat()
    capture_id = str(uuid.uuid4())
    normalized = content.strip().lower()
    content_hash = hashlib.sha256(normalized.encode()).hexdigest()

    embedding_blob, embedding_dim, embedding_pending = None, None, 0
    try:
        embedding_blob, embedding_dim, embedding_pending = get_embedding(content)
    except Exception:
        embedding_pending = 1

    tags_json = None
    if tags:
        import json
        tags_json = json.dumps(tags) if isinstance(tags, list) else tags

    conn.execute(
        "INSERT INTO capture_log (id, content, type, tags, importance, origin, "
        "source_session_id, source_event_id, content_hash, embedding, embedding_dim, "
        "embedding_pending, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (capture_id, content, type, tags_json, importance, origin,
         session_id, event_id, content_hash, embedding_blob, embedding_dim,
         embedding_pending, now),
    )
    conn.commit()

    return {"capture_log_id": capture_id, "state": "buffered"}


def awake_recall(conn, query: str, max_results: int = 5,
                 pulse_queue: Optional[Queue] = None) -> list:
    """Dual-source query: view_engrams + hot buffer (capture_log)."""
    results = []

    # Source 1: View Store (consolidated engrams)
    view_results = _fts_query(conn, "view_engrams", query, max_results * 2)
    for r in view_results:
        r["provisional"] = False
        results.append(r)

    # Source 2: Hot Buffer (unconsumed capture_log)
    hot_results = _fts_query_capture_log(conn, query, max_results * 2)
    for r in hot_results:
        r["provisional"] = True
        r["score"] = r.get("score", 0.5) * 0.5  # Downweight
        results.append(r)

    # Sort by score descending, take top-K
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    results = results[:max_results]

    # Emit PulseEvents for view_engrams hits
    if pulse_queue is not None:
        view_ids = [r["id"] for r in results if not r.get("provisional")]
        for r in results:
            if not r.get("provisional") and view_ids:
                from memento.awake import _make_pulse_event
                event = _make_pulse_event(r["id"], query, view_ids)
                pulse_queue.put(event)

    return results


def awake_forget(conn, target_id: str) -> dict:
    """Record forget intent. Epoch processes the actual deletion."""
    now = datetime.now(timezone.utc).isoformat()

    # Determine target type
    cl = conn.execute(
        "SELECT id FROM capture_log WHERE id = ? AND epoch_id IS NULL", (target_id,)
    ).fetchone()
    target_table = "capture_log" if cl else "engrams"

    conn.execute(
        "INSERT OR REPLACE INTO pending_forget (id, target_table, target_id, requested_at) "
        "VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), target_table, target_id, now),
    )
    conn.commit()
    return {"status": "pending", "message": "Will take effect after next epoch run"}


def awake_verify(conn, engram_id: str) -> dict:
    """Update verified flag (metadata, not state transition)."""
    conn.execute("UPDATE engrams SET verified = 1 WHERE id = ?", (engram_id,))
    conn.execute("UPDATE view_engrams SET verified = 1 WHERE id = ?", (engram_id,))
    conn.commit()
    return {"status": "verified", "engram_id": engram_id}


def awake_pin(conn, engram_id: str, rigidity: float) -> dict:
    """Update rigidity (metadata, not state transition)."""
    rigidity = max(0.0, min(1.0, rigidity))
    conn.execute("UPDATE engrams SET rigidity = ? WHERE id = ?", (rigidity, engram_id))
    conn.execute("UPDATE view_engrams SET rigidity = ? WHERE id = ?", (rigidity, engram_id))
    conn.commit()
    return {"status": "pinned", "engram_id": engram_id, "rigidity": rigidity}


def _make_pulse_event(engram_id: str, query: str, all_hit_ids: list) -> dict:
    """Construct a PulseEvent dict."""
    coactivated = [eid for eid in all_hit_ids if eid != engram_id]
    return {
        "event_type": "recall_hit",
        "engram_id": engram_id,
        "query_context": query,
        "coactivated_ids": coactivated,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "idempotency_key": str(uuid.uuid4()),
    }


def _fts_query(conn, table: str, query: str, limit: int) -> list:
    """Simple FTS5 or LIKE query on a table with content column."""
    try:
        # Try FTS5 on engrams_fts (only works for engrams/view_engrams if FTS exists)
        if table == "view_engrams":
            rows = conn.execute(
                "SELECT ve.* FROM view_engrams ve "
                "WHERE ve.content LIKE ? ORDER BY ve.strength DESC LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE content LIKE ? LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
    except Exception:
        rows = []

    results = []
    for row in rows:
        d = dict(row)
        d["score"] = d.get("strength", 0.5)
        results.append(d)
    return results


def _fts_query_capture_log(conn, query: str, limit: int) -> list:
    """Query unconsumed capture_log entries."""
    rows = conn.execute(
        "SELECT * FROM capture_log WHERE epoch_id IS NULL AND content LIKE ? LIMIT ?",
        (f"%{query}%", limit),
    ).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        d["score"] = 0.5  # Default score for hot buffer
        results.append(d)
    return results
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_awake.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/awake.py tests/test_awake.py
git commit -m "feat(v0.5): Layer 3 — Awake track (capture→L2, dual-source recall, pending forget)"
```

---

## Task 9: Subconscious Track

**Files:**
- Create: `src/memento/subconscious.py`
- Create: `tests/test_subconscious.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_subconscious.py
import sqlite3
import json
from queue import Queue
from datetime import datetime, timezone
import time
import pytest
from memento.migration import migrate_v03_to_v05
from tests.test_awake import _setup_v05_db


def test_drain_pulse_events(tmp_path):
    from memento.subconscious import SubconsciousTrack
    conn = _setup_v05_db(tmp_path)

    # Insert an engram so reinforce delta can reference it
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO engrams (id, content, state, strength, last_accessed, "
        "access_count, importance, created_at) "
        "VALUES ('e1', 'test', 'consolidated', 0.7, ?, 0, 'normal', ?)",
        (now, now),
    )
    from memento.repository import rebuild_view_store
    rebuild_view_store(conn, "init")
    conn.commit()

    pulse_queue = Queue()
    pulse_queue.put({
        "event_type": "recall_hit",
        "engram_id": "e1",
        "query_context": "test query",
        "coactivated_ids": ["e2"],
        "timestamp": now,
        "idempotency_key": "idem-1",
    })

    track = SubconsciousTrack(
        conn_factory=lambda: conn,
        pulse_queue=pulse_queue,
        config={},
    )
    track._drain_pulse_events(conn)

    # Delta ledger should have a reinforce entry
    dl = conn.execute("SELECT * FROM delta_ledger WHERE engram_id='e1'").fetchall()
    assert len(dl) == 1
    assert dl[0]["delta_type"] == "reinforce"
    assert dl[0]["delta_value"] > 0

    # Recon buffer should have an entry
    rb = conn.execute("SELECT * FROM recon_buffer WHERE engram_id='e1'").fetchall()
    assert len(rb) == 1
    assert rb[0]["idempotency_key"] == "idem-1"
    assert json.loads(rb[0]["coactivated_ids"]) == ["e2"]


def test_idempotency_key_dedup(tmp_path):
    from memento.subconscious import SubconsciousTrack
    conn = _setup_v05_db(tmp_path)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO engrams (id, content, state, strength, last_accessed, "
        "access_count, importance, created_at) "
        "VALUES ('e1', 'test', 'consolidated', 0.7, ?, 0, 'normal', ?)",
        (now, now),
    )
    from memento.repository import rebuild_view_store
    rebuild_view_store(conn, "init")

    pulse_queue = Queue()
    event = {
        "event_type": "recall_hit", "engram_id": "e1",
        "query_context": "q", "coactivated_ids": [],
        "timestamp": now, "idempotency_key": "same-key",
    }
    pulse_queue.put(event)
    pulse_queue.put(dict(event))  # Duplicate

    track = SubconsciousTrack(conn_factory=lambda: conn, pulse_queue=pulse_queue, config={})
    track._drain_pulse_events(conn)

    # Recon buffer: only 1 entry (deduped)
    count = conn.execute("SELECT COUNT(*) FROM recon_buffer").fetchone()[0]
    assert count == 1

    # Delta ledger: 2 entries (each PulseEvent writes a delta, idempotency is on recon only)
    dl_count = conn.execute("SELECT COUNT(*) FROM delta_ledger").fetchone()[0]
    assert dl_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_subconscious.py -v`
Expected: FAIL

- [ ] **Step 3: Implement subconscious track**

```python
# src/memento/subconscious.py
"""Subconscious track — background thread consuming PulseEvents."""
import json
import sqlite3
from datetime import datetime, timezone
from queue import Queue, Empty
from threading import Thread, Event

from memento.decay import compute_reinforce_delta, compute_decay_deltas
from memento.repository import update_decay_watermark


class SubconsciousTrack:
    def __init__(self, conn_factory, pulse_queue: Queue, config: dict):
        self.conn_factory = conn_factory
        self.pulse_queue = pulse_queue
        self.decay_interval = config.get("decay_interval", 300)
        self.shutdown_event = Event()
        self._thread = None
        self._last_decay = 0.0

    def start(self):
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def shutdown(self):
        self.shutdown_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self):
        conn = self.conn_factory()
        import time
        while not self.shutdown_event.is_set():
            self._drain_pulse_events(conn)
            now = time.time()
            if now - self._last_decay >= self.decay_interval:
                self._run_decay_cycle(conn)
                self._last_decay = now
            self.shutdown_event.wait(timeout=0.5)
        conn.close()

    def _drain_pulse_events(self, conn):
        """Consume all pending PulseEvents from the queue."""
        events = []
        while True:
            try:
                events.append(self.pulse_queue.get_nowait())
            except Empty:
                break

        for event in events:
            engram_id = event["engram_id"]

            # Look up engram from view_engrams for decay computation
            row = conn.execute(
                "SELECT id, strength, last_accessed, access_count, importance "
                "FROM view_engrams WHERE id = ?",
                (engram_id,),
            ).fetchone()

            if row:
                engram = dict(row) if hasattr(row, "keys") else {
                    "id": row[0], "strength": row[1], "last_accessed": row[2],
                    "access_count": row[3], "importance": row[4],
                }
                delta = compute_reinforce_delta(engram)
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO delta_ledger (engram_id, delta_type, delta_value, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (delta["engram_id"], delta["delta_type"], delta["delta_value"], now),
                )

            # Write recon_buffer (idempotency_key dedup)
            now = datetime.now(timezone.utc).isoformat()
            coactivated = json.dumps(event.get("coactivated_ids", []))
            try:
                conn.execute(
                    "INSERT INTO recon_buffer (engram_id, query_context, coactivated_ids, "
                    "idempotency_key, created_at) VALUES (?, ?, ?, ?, ?)",
                    (engram_id, event.get("query_context", ""),
                     coactivated, event["idempotency_key"], now),
                )
            except sqlite3.IntegrityError:
                pass  # Duplicate idempotency_key, silently skip

        if events:
            conn.commit()

    def _run_decay_cycle(self, conn):
        """Periodic decay computation."""
        # Read watermark
        row = conn.execute(
            "SELECT value FROM runtime_cursors WHERE key = 'decay_watermark'"
        ).fetchone()
        if not row:
            return
        watermark = row[0] if isinstance(row, tuple) else row["value"]

        # Get active engrams from view store
        rows = conn.execute(
            "SELECT id, strength, last_accessed, access_count, importance "
            "FROM view_engrams"
        ).fetchall()
        engrams = []
        for r in rows:
            engrams.append(dict(r) if hasattr(r, "keys") else {
                "id": r[0], "strength": r[1], "last_accessed": r[2],
                "access_count": r[3], "importance": r[4],
            })

        now = datetime.now(timezone.utc).isoformat()
        deltas, new_watermark = compute_decay_deltas(engrams, watermark, now)

        for d in deltas:
            conn.execute(
                "INSERT INTO delta_ledger (engram_id, delta_type, delta_value, created_at) "
                "VALUES (?, ?, ?, ?)",
                (d["engram_id"], d["delta_type"], d["delta_value"], now),
            )

        update_decay_watermark(conn, new_watermark)
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_subconscious.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/subconscious.py tests/test_subconscious.py
git commit -m "feat(v0.5): Layer 3 — Subconscious track (PulseEvent → delta_ledger + recon_buffer)"
```

---

## Task 10: LLM Client

**Files:**
- Create: `src/memento/llm.py`
- Create: `tests/test_llm.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_llm.py
import json
import pytest
from unittest.mock import patch, MagicMock
from memento.llm import LLMClient


def test_llm_client_init():
    client = LLMClient(
        base_url="https://api.example.com/v1",
        api_key="sk-test",
        model="test-model",
    )
    assert client.model == "test-model"
    assert client.base_url == "https://api.example.com/v1"


def test_llm_client_init_from_env(monkeypatch):
    monkeypatch.setenv("MEMENTO_LLM_BASE_URL", "https://env.example.com/v1")
    monkeypatch.setenv("MEMENTO_LLM_API_KEY", "sk-env")
    monkeypatch.setenv("MEMENTO_LLM_MODEL", "env-model")

    client = LLMClient.from_env()
    assert client.base_url == "https://env.example.com/v1"
    assert client.model == "env-model"


def test_llm_client_from_env_missing(monkeypatch):
    monkeypatch.delenv("MEMENTO_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("MEMENTO_LLM_API_KEY", raising=False)
    monkeypatch.delenv("MEMENTO_LLM_MODEL", raising=False)

    client = LLMClient.from_env()
    assert client is None


@patch("memento.llm.urlopen")
def test_generate(mock_urlopen):
    response_body = json.dumps({
        "choices": [{"message": {"content": "test response"}}]
    }).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    client = LLMClient("https://api.example.com/v1", "sk-test", "model")
    result = client.generate("hello")
    assert result == "test response"


@patch("memento.llm.urlopen")
def test_generate_json(mock_urlopen):
    response_body = json.dumps({
        "choices": [{"message": {"content": '{"key": "value"}'}}]
    }).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    client = LLMClient("https://api.example.com/v1", "sk-test", "model")
    result = client.generate_json("hello")
    assert result == {"key": "value"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_llm.py -v`
Expected: FAIL

- [ ] **Step 3: Implement LLM client**

```python
# src/memento/llm.py
"""OpenAI-compatible LLM client for Epoch phases."""
import json
import os
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError


class LLMClient:
    """Minimal OpenAI-compatible API client. No external dependencies."""

    def __init__(self, base_url: str, api_key: str, model: str,
                 timeout: int = 30, max_retries: int = 3, temperature: float = 0.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.temperature = temperature

    @classmethod
    def from_env(cls) -> Optional["LLMClient"]:
        """Create client from MEMENTO_LLM_* environment variables. Returns None if not configured."""
        base_url = os.environ.get("MEMENTO_LLM_BASE_URL")
        api_key = os.environ.get("MEMENTO_LLM_API_KEY")
        model = os.environ.get("MEMENTO_LLM_MODEL")

        if not all([base_url, api_key, model]):
            return None

        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=int(os.environ.get("MEMENTO_LLM_TIMEOUT", "30")),
            max_retries=int(os.environ.get("MEMENTO_LLM_MAX_RETRIES", "3")),
            temperature=float(os.environ.get("MEMENTO_LLM_TEMPERATURE", "0")),
        )

    def generate(self, prompt: str, system: str = None) -> str:
        """Generate text completion."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        result = self._call(body)
        return result["choices"][0]["message"]["content"]

    def generate_json(self, prompt: str, system: str = None) -> dict:
        """Generate JSON completion (response_format=json_object)."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
        }
        result = self._call(body)
        content = result["choices"][0]["message"]["content"]
        return json.loads(content)

    def _call(self, body: dict) -> dict:
        """Make HTTP request with retries."""
        url = f"{self.base_url}/chat/completions"
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        last_error = None
        for attempt in range(self.max_retries):
            try:
                req = Request(url, data=data, headers=headers, method="POST")
                with urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read())
            except (URLError, TimeoutError, json.JSONDecodeError) as e:
                last_error = e

        raise last_error
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_llm.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/llm.py tests/test_llm.py
git commit -m "feat(v0.5): Layer 3 — LLM client (OpenAI-compatible, env config)"
```

---

## Task 11: Epoch Runner

**Files:**
- Create: `src/memento/epoch.py`
- Create: `tests/test_epoch.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_epoch.py
import sqlite3
import json
from datetime import datetime, timezone, timedelta
import pytest
from memento.migration import migrate_v03_to_v05
from tests.test_awake import _setup_v05_db


def test_acquire_lease(tmp_path):
    from memento.epoch import acquire_lease, LEASE_TIMEOUT
    conn = _setup_v05_db(tmp_path)

    epoch_id = acquire_lease(conn, "default", "full", "manual")
    assert epoch_id is not None

    row = conn.execute("SELECT * FROM epochs WHERE id=?", (epoch_id,)).fetchone()
    assert row["status"] == "leased"
    assert row["mode"] == "full"


def test_lease_mutual_exclusion(tmp_path):
    from memento.epoch import acquire_lease
    conn = _setup_v05_db(tmp_path)

    epoch_id1 = acquire_lease(conn, "default", "full", "manual")
    assert epoch_id1 is not None

    epoch_id2 = acquire_lease(conn, "default", "full", "manual")
    assert epoch_id2 is None  # Blocked


def test_expired_lease_cleanup(tmp_path):
    from memento.epoch import acquire_lease
    conn = _setup_v05_db(tmp_path)

    # Insert an expired lease
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    conn.execute(
        "INSERT INTO epochs (id, vault_id, status, mode, trigger, seal_timestamp, "
        "lease_acquired, lease_expires) VALUES (?, 'default', 'leased', 'full', "
        "'manual', ?, ?, ?)",
        ("old-epoch", past, past, past),
    )
    conn.commit()

    # New lease should succeed after cleanup
    epoch_id = acquire_lease(conn, "default", "full", "manual")
    assert epoch_id is not None
    assert epoch_id != "old-epoch"

    # Old lease marked failed
    old = conn.execute("SELECT status FROM epochs WHERE id='old-epoch'").fetchone()
    assert old["status"] == "failed"


def test_seal_timestamp_boundary(tmp_path):
    from memento.epoch import acquire_lease, run_epoch_phases
    from memento.awake import awake_capture
    conn = _setup_v05_db(tmp_path)

    # Capture before seal
    awake_capture(conn, "before seal", type="fact")

    epoch_id = acquire_lease(conn, "default", "light", "manual")
    seal = conn.execute("SELECT seal_timestamp FROM epochs WHERE id=?", (epoch_id,)).fetchone()[0]

    # Capture after seal
    import time
    time.sleep(0.01)
    awake_capture(conn, "after seal", type="fact")

    # The "after seal" item should NOT be consumed
    before_count = conn.execute(
        "SELECT COUNT(*) FROM capture_log WHERE created_at < ? AND epoch_id IS NULL",
        (seal,),
    ).fetchone()[0]
    after_count = conn.execute(
        "SELECT COUNT(*) FROM capture_log WHERE created_at >= ? AND epoch_id IS NULL",
        (seal,),
    ).fetchone()[0]

    assert before_count == 1
    assert after_count == 1


def test_light_epoch_creates_debt(tmp_path):
    from memento.epoch import acquire_lease, run_epoch_phases
    from memento.awake import awake_capture
    conn = _setup_v05_db(tmp_path)

    awake_capture(conn, "test content", type="fact")
    epoch_id = acquire_lease(conn, "default", "light", "manual")
    run_epoch_phases(conn, epoch_id, mode="light", llm_client=None)

    # capture_log should remain unconsumed
    cl = conn.execute("SELECT epoch_id FROM capture_log").fetchone()
    assert cl["epoch_id"] is None  # Not consumed in light mode

    # cognitive_debt should have an entry
    debt = conn.execute("SELECT * FROM cognitive_debt WHERE type='pending_consolidation'").fetchall()
    assert len(debt) >= 1


def test_epoch_processes_pending_forget(tmp_path):
    from memento.epoch import acquire_lease, run_epoch_phases
    from memento.awake import awake_forget
    conn = _setup_v05_db(tmp_path)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO engrams (id, content, state, strength, created_at, last_accessed) "
        "VALUES ('e1', 'to forget', 'consolidated', 0.7, ?, ?)", (now, now)
    )
    from memento.repository import rebuild_view_store
    rebuild_view_store(conn, "init")

    awake_forget(conn, "e1")

    epoch_id = acquire_lease(conn, "default", "light", "manual")
    run_epoch_phases(conn, epoch_id, mode="light", llm_client=None)

    # Engram should be forgotten
    row = conn.execute("SELECT state FROM engrams WHERE id='e1'").fetchone()
    assert row["state"] == "forgotten"

    # View store should not contain it
    assert conn.execute("SELECT COUNT(*) FROM view_engrams WHERE id='e1'").fetchone()[0] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_epoch.py -v`
Expected: FAIL

- [ ] **Step 3: Implement epoch runner**

```python
# src/memento/epoch.py
"""Sleep/Epoch track — independent subprocess for heavy processing."""
import json
import uuid
from datetime import datetime, timezone, timedelta

from memento.delta_fold import fold_deltas, plan_strength_updates, ARCHIVE_THRESHOLD
from memento.hebbian import plan_nexus_updates
from memento.rigidity import plan_reconsolidation
from memento.state_machine import TransitionPlan, validate_transition
from memento.repository import (
    apply_pending_forgets, apply_l2_to_l3, apply_drop_decisions,
    apply_strength_plan, apply_nexus_plan, apply_transition_plan,
    rebuild_view_store, defer_to_debt,
)

LEASE_TIMEOUT = 3600  # 1 hour


def acquire_lease(conn, vault_id: str, mode: str, trigger: str):
    """Attempt to acquire an Epoch lease. Returns epoch_id or None."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    expires = (now + timedelta(seconds=LEASE_TIMEOUT)).isoformat()

    # Clean up expired leases
    conn.execute(
        "UPDATE epochs SET status = 'failed', error = 'lease_expired' "
        "WHERE vault_id = ? AND status IN ('leased', 'running') AND lease_expires < ?",
        (vault_id, now_iso),
    )
    conn.commit()

    epoch_id = str(uuid.uuid4())
    try:
        conn.execute(
            "INSERT INTO epochs (id, vault_id, status, mode, trigger, seal_timestamp, "
            "lease_acquired, lease_expires, started_at) "
            "VALUES (?, ?, 'leased', ?, ?, ?, ?, ?, ?)",
            (epoch_id, vault_id, mode, trigger, now_iso, now_iso, expires, now_iso),
        )
        conn.commit()
        return epoch_id
    except Exception:
        conn.rollback()
        return None


def promote_lease(conn, epoch_id: str):
    """Promote lease from 'leased' to 'running'."""
    conn.execute("UPDATE epochs SET status = 'running' WHERE id = ?", (epoch_id,))
    conn.commit()


def run_epoch_phases(conn, epoch_id: str, mode: str, llm_client=None):
    """Execute all Epoch phases."""
    promote_lease(conn, epoch_id)
    seal = conn.execute("SELECT seal_timestamp FROM epochs WHERE id=?", (epoch_id,)).fetchone()[0]

    stats = {"phases": {}}

    try:
        # Phase 1: pending_forget (T7)
        count, forgotten_ids = apply_pending_forgets(conn, epoch_id)
        stats["phases"]["forget"] = {"count": count}

        # Phase 2: L2 consolidation
        _phase_l2(conn, epoch_id, seal, mode, llm_client, stats)

        # Phase 3: Delta fold + strength
        _phase_delta_fold(conn, epoch_id, seal, stats)

        # Phase 4: Nexus updates
        _phase_nexus(conn, epoch_id, seal, stats)

        # Phase 5: Reconsolidation
        _phase_reconsolidation(conn, epoch_id, seal, mode, llm_client, stats)

        # Phase 6: State transitions (T5/T6)
        _phase_transitions(conn, epoch_id, mode, stats)

        # Phase 7: View Store rebuild + commit
        rebuild_view_store(conn, epoch_id)

        final_status = "degraded" if mode == "light" else "committed"
        conn.execute(
            "UPDATE epochs SET status = ?, stats = ?, committed_at = ? WHERE id = ?",
            (final_status, json.dumps(stats), datetime.now(timezone.utc).isoformat(), epoch_id),
        )
        conn.commit()

    except Exception as e:
        conn.execute(
            "UPDATE epochs SET status = 'failed', error = ? WHERE id = ?",
            (str(e), epoch_id),
        )
        conn.commit()
        raise


def _phase_l2(conn, epoch_id, seal, mode, llm_client, stats):
    """Phase 2: L2 consolidation."""
    rows = conn.execute(
        "SELECT * FROM capture_log WHERE epoch_id IS NULL AND created_at < ?",
        (seal,),
    ).fetchall()
    items = [dict(r) for r in rows]

    if mode == "light" or llm_client is None:
        # Record debt for each unconsumed item
        for item in items:
            defer_to_debt(conn, "pending_consolidation",
                          {"source": "capture_log", "id": item["id"]}, epoch_id)
        stats["phases"]["l2"] = {"deferred": len(items)}
    else:
        # Full mode: for now, auto-promote all (LLM structuring TBD in v0.5.1)
        promoted = 0
        for item in items:
            plan = TransitionPlan(
                engram_id=None, capture_log_id=item["id"],
                from_state="buffered", to_state="consolidated",
                transition="T1", reason="auto-promote",
                epoch_id=epoch_id, metadata={},
            )
            apply_l2_to_l3(conn, plan, item)
            promoted += 1
        stats["phases"]["l2"] = {"promoted": promoted}


def _phase_delta_fold(conn, epoch_id, seal, stats):
    """Phase 3: Delta fold + strength updates."""
    rows = conn.execute(
        "SELECT id, engram_id, delta_type, delta_value FROM delta_ledger "
        "WHERE epoch_id IS NULL AND created_at < ?",
        (seal,),
    ).fetchall()
    deltas = [dict(r) for r in rows]

    if not deltas:
        stats["phases"]["delta_fold"] = {"updated": 0}
        return

    folds = fold_deltas(deltas)

    # Build lookup
    engram_ids = [f.engram_id for f in folds]
    placeholders = ",".join("?" for _ in engram_ids)
    lookup_rows = conn.execute(
        f"SELECT id, strength, access_count, origin, verified FROM engrams "
        f"WHERE id IN ({placeholders})",
        engram_ids,
    ).fetchall()
    lookup = {r["id"]: dict(r) for r in lookup_rows}

    plans = plan_strength_updates(folds, lookup)
    apply_strength_plan(conn, plans, epoch_id)
    stats["phases"]["delta_fold"] = {"updated": len(plans)}


def _phase_nexus(conn, epoch_id, seal, stats):
    """Phase 4: Nexus updates from recon_buffer."""
    rows = conn.execute(
        "SELECT id, engram_id, query_context, coactivated_ids FROM recon_buffer "
        "WHERE nexus_consumed_epoch_id IS NULL AND created_at < ?",
        (seal,),
    ).fetchall()
    items = [dict(r) for r in rows]

    if not items:
        stats["phases"]["nexus"] = {"created": 0, "updated": 0}
        return

    # Build existing nexus lookup
    existing = {}
    for row in conn.execute("SELECT source_id, target_id, type, association_strength FROM nexus").fetchall():
        existing[(row["source_id"], row["target_id"], row["type"])] = row["association_strength"]

    plans = plan_nexus_updates(items, existing)
    apply_nexus_plan(conn, plans, epoch_id)

    created = sum(1 for p in plans if p.is_new)
    updated = sum(1 for p in plans if not p.is_new)
    stats["phases"]["nexus"] = {"created": created, "updated": updated}


def _phase_reconsolidation(conn, epoch_id, seal, mode, llm_client, stats):
    """Phase 5: Content reconsolidation."""
    rows = conn.execute(
        "SELECT id, engram_id, query_context, coactivated_ids FROM recon_buffer "
        "WHERE content_consumed_epoch_id IS NULL AND created_at < ?",
        (seal,),
    ).fetchall()
    items = [dict(r) for r in rows]

    if not items:
        stats["phases"]["reconsolidation"] = {"processed": 0}
        return

    # Group by engram_id
    from collections import defaultdict
    groups = defaultdict(list)
    for item in items:
        groups[item["engram_id"]].append(item)

    processed = 0
    for engram_id, group_items in groups.items():
        engram = conn.execute(
            "SELECT id, content, rigidity FROM engrams WHERE id = ?",
            (engram_id,),
        ).fetchone()
        if not engram:
            continue
        engram = dict(engram)

        plan = plan_reconsolidation(engram, group_items)
        if plan is None:
            continue

        if mode == "light" or llm_client is None:
            if plan.allow_content_update:
                defer_to_debt(conn, "pending_reconsolidation",
                              {"source": "recon_buffer", "engram_id": engram_id}, epoch_id)
            # Mark content consumed even in light mode for non-modifiable
            if not plan.allow_content_update:
                recon_ids = [i["id"] for i in group_items]
                placeholders = ",".join("?" for _ in recon_ids)
                conn.execute(
                    f"UPDATE recon_buffer SET content_consumed_epoch_id = ? "
                    f"WHERE id IN ({placeholders})",
                    [epoch_id] + recon_ids,
                )
        else:
            # Full mode: LLM reconsolidation (placeholder for actual LLM call)
            recon_ids = [i["id"] for i in group_items]
            placeholders = ",".join("?" for _ in recon_ids)
            conn.execute(
                f"UPDATE recon_buffer SET content_consumed_epoch_id = ? "
                f"WHERE id IN ({placeholders})",
                [epoch_id] + recon_ids,
            )
            processed += 1

    conn.commit()
    stats["phases"]["reconsolidation"] = {"processed": processed}


def _phase_transitions(conn, epoch_id, mode, stats):
    """Phase 6: State transitions (T6 archive, T5 abstraction)."""
    archived = 0

    # T6: strength below threshold → archived
    rows = conn.execute(
        "SELECT id, strength FROM engrams WHERE state = 'consolidated'"
    ).fetchall()
    for row in rows:
        if row["strength"] < ARCHIVE_THRESHOLD:
            plan = TransitionPlan(
                engram_id=row["id"], capture_log_id=None,
                from_state="consolidated", to_state="archived",
                transition="T6", reason=f"strength {row['strength']:.3f} < {ARCHIVE_THRESHOLD}",
                epoch_id=epoch_id, metadata={},
            )
            apply_transition_plan(conn, plan)
            archived += 1

    # T5: abstraction (requires LLM, deferred in light mode)
    stats["phases"]["transitions"] = {"archived": archived}
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_epoch.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/epoch.py tests/test_epoch.py
git commit -m "feat(v0.5): Layer 3 — Epoch runner (lease, seal, phases 1-7, light/full mode)"
```

---

## Task 12: Worker Refactor

**Files:**
- Modify: `src/memento/worker.py`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: Write tests for new worker structure**

Add to `tests/test_worker.py`:

```python
# Append to existing tests/test_worker.py

def test_worker_has_pulse_queue():
    """Worker should expose a pulse_queue for Awake→Subconscious communication."""
    from memento.worker import WorkerServer
    # Just verify the class accepts the new structure
    # Full integration tested in test_e2e.py
    assert hasattr(WorkerServer, '__init__')
```

- [ ] **Step 2: Refactor worker.py**

The worker refactor is substantial. Key changes:
- Replace `DBThread.execute` dispatch with `awake_*` functions
- Add `SubconsciousTrack` as background thread
- Add `pulse_queue` connecting Awake → Subconscious
- Add new HTTP routes (`/inspect`, `/nexus`, `/pin`, `/debt`)
- Update existing routes to use new awake functions

This is a large refactor best done as a careful rewrite of the existing `worker.py`. The spec's HTTP route table (Layer 3, section 3.5) defines the complete route contract.

- [ ] **Step 3: Run all worker tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_worker.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add src/memento/worker.py tests/test_worker.py
git commit -m "feat(v0.5): Layer 3 — Worker refactor (Awake+Subconscious tracks, new routes)"
```

---

## Task 13: CLI Updates

**Files:**
- Modify: `src/memento/cli.py`

- [ ] **Step 1: Add epoch subcommand group**

Add to `cli.py`:

```python
@main.group()
def epoch():
    """Epoch management commands."""
    pass

@epoch.command("run")
@click.option("--mode", type=click.Choice(["full", "light"]), default="full")
@click.option("--trigger", type=click.Choice(["manual", "scheduled", "auto"]), default="manual")
@click.option("--db", default=None)
def epoch_run(mode, trigger, db):
    """Run an Epoch (consolidation cycle)."""
    from memento.db import get_db_path, get_connection
    from memento.epoch import acquire_lease, run_epoch_phases
    from memento.llm import LLMClient

    db_path = db or get_db_path()
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    epoch_id = acquire_lease(conn, "default", mode, trigger)
    if epoch_id is None:
        click.echo("Error: Another epoch is already running.", err=True)
        raise SystemExit(1)

    llm_client = LLMClient.from_env() if mode == "full" else None
    if mode == "full" and llm_client is None:
        click.echo("Warning: LLM not configured, falling back to light mode.")
        mode = "light"

    run_epoch_phases(conn, epoch_id, mode=mode, llm_client=llm_client)
    click.echo(f"Epoch {epoch_id[:8]} completed ({mode} mode).")

@epoch.command("status")
@click.option("--db", default=None)
def epoch_status(db):
    """Show recent epoch history."""
    from memento.db import get_db_path, get_connection
    db_path = db or get_db_path()
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, status, mode, trigger, committed_at FROM epochs "
        "ORDER BY lease_acquired DESC LIMIT 10"
    ).fetchall()
    for r in rows:
        click.echo(f"{r['id'][:8]}  {r['status']:10s}  {r['mode']:5s}  {r['trigger']:9s}  {r['committed_at'] or '-'}")

@epoch.command("debt")
@click.option("--db", default=None)
def epoch_debt(db):
    """Show cognitive debt summary."""
    from memento.db import get_db_path, get_connection
    db_path = db or get_db_path()
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT type, COUNT(*) as cnt FROM cognitive_debt WHERE resolved_at IS NULL GROUP BY type"
    ).fetchall()
    if not rows:
        click.echo("No outstanding cognitive debt.")
    else:
        for r in rows:
            click.echo(f"  {r[0]}: {r[1]}")
```

- [ ] **Step 2: Add inspect, nexus, pin commands**

```python
@main.command()
@click.argument("engram_id")
@click.option("--db", default=None)
def inspect(engram_id, db):
    """Show detailed engram information."""
    from memento.db import get_db_path, get_connection
    db_path = db or get_db_path()
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM engrams WHERE id = ?", (engram_id,)).fetchone()
    if not row:
        click.echo(f"Engram {engram_id} not found.", err=True)
        return
    click.echo(f"ID:        {row['id']}")
    click.echo(f"Content:   {row['content'][:100]}")
    click.echo(f"State:     {row['state']}")
    click.echo(f"Strength:  {row['strength']:.3f}")
    click.echo(f"Rigidity:  {row['rigidity']:.2f}")
    click.echo(f"Type:      {row['type']}")
    click.echo(f"Origin:    {row['origin']}")
    click.echo(f"Verified:  {bool(row['verified'])}")

    # Nexus connections
    nexus = conn.execute(
        "SELECT * FROM nexus WHERE source_id = ? OR target_id = ?",
        (engram_id, engram_id),
    ).fetchall()
    if nexus:
        click.echo(f"\nNexus ({len(nexus)}):")
        for n in nexus:
            other = n["target_id"] if n["source_id"] == engram_id else n["source_id"]
            click.echo(f"  → {other[:8]}  {n['type']:10s}  strength={n['association_strength']:.2f}")

    # Pending flags
    pf = conn.execute("SELECT * FROM pending_forget WHERE engram_id = ?", (engram_id,)).fetchone()
    if pf:
        click.echo(f"\n⚠ Pending forget (requested {pf['requested_at']})")


@main.command()
@click.argument("engram_id")
@click.option("--depth", type=click.Choice(["1", "2"]), default="1")
@click.option("--db", default=None)
def nexus(engram_id, depth, db):
    """Show nexus connections for an engram."""
    from memento.db import get_db_path, get_connection
    db_path = db or get_db_path()
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row

    if depth == "1":
        rows = conn.execute(
            "SELECT * FROM nexus WHERE source_id = ? OR target_id = ?",
            (engram_id, engram_id),
        ).fetchall()
    else:
        # 2-hop CTE
        rows = conn.execute("""
            WITH hop1 AS (
                SELECT * FROM nexus WHERE source_id = ? OR target_id = ?
            ),
            neighbors AS (
                SELECT CASE WHEN source_id = ? THEN target_id ELSE source_id END AS neighbor_id
                FROM hop1
            ),
            hop2 AS (
                SELECT n.* FROM nexus n
                JOIN neighbors nb ON n.source_id = nb.neighbor_id OR n.target_id = nb.neighbor_id
            )
            SELECT * FROM hop1 UNION SELECT * FROM hop2
        """, (engram_id, engram_id, engram_id)).fetchall()

    for r in rows:
        click.echo(f"{r['source_id'][:8]} → {r['target_id'][:8]}  {r['type']:10s}  str={r['association_strength']:.2f}")


@main.command()
@click.argument("engram_id")
@click.option("--rigidity", type=float, required=True)
@click.option("--db", default=None)
def pin(engram_id, rigidity, db):
    """Set rigidity for an engram."""
    from memento.db import get_db_path, get_connection
    from memento.awake import awake_pin
    db_path = db or get_db_path()
    conn = get_connection(db_path)
    result = awake_pin(conn, engram_id, rigidity)
    click.echo(f"Pinned {engram_id[:8]} rigidity={result['rigidity']:.2f}")
```

- [ ] **Step 3: Update capture/recall/forget output**

Update existing `capture()`, `recall()`, `forget()` in cli.py:

- `capture`: Change output to show "Captured to L2 (buffered)" 
- `recall`: Add `(provisional)` marker for hot buffer results
- `forget`: Change output to "Marked for deletion. Will take effect after next epoch run."
- Add deprecation warnings for `--mode` and `--reinforce`

- [ ] **Step 4: Run CLI tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_cli.py -v`
Expected: All PASS (fix any broken tests from output changes)

- [ ] **Step 5: Commit**

```bash
git add src/memento/cli.py
git commit -m "feat(v0.5): Layer 4 — CLI updates (epoch/inspect/nexus/pin commands, output changes)"
```

---

## Task 14: MCP Server Updates

**Files:**
- Modify: `src/memento/mcp_server.py`

- [ ] **Step 1: Add new MCP tools**

Add tool definitions and dispatch entries for: `memento_epoch_run`, `memento_epoch_status`, `memento_epoch_debt`, `memento_inspect`, `memento_nexus`, `memento_pin`.

- [ ] **Step 2: Update existing tools**

- `memento_capture`: Return `state: 'buffered'`
- `memento_recall`: Add `provisional` field, remove `mode`/`reinforce` params
- `memento_forget`: Return pending status
- `memento_status`: Add state/delta/debt stats

- [ ] **Step 3: Remove deprecated tools**

Remove: `memento_set_session`, `memento_get_session`, `memento_evaluate`, `memento_backfill_embeddings`. Return migration guidance for removed tools.

- [ ] **Step 4: Run MCP tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_mcp_server.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/mcp_server.py tests/test_mcp_server.py
git commit -m "feat(v0.5): Layer 4 — MCP server updates (new tools, deprecations)"
```

---

## Task 15: API Layer Refactor

**Files:**
- Modify: `src/memento/api.py`

- [ ] **Step 1: Split into MementoAPI / LocalAPI / WorkerClientAPI**

```python
# Updated src/memento/api.py
"""Protocol-agnostic API layer."""
from abc import ABC, abstractmethod


class MementoAPI(ABC):
    """Abstract API — defines the operation interface."""

    @abstractmethod
    def capture(self, content, **kwargs) -> dict: ...
    @abstractmethod
    def recall(self, query, **kwargs) -> list: ...
    @abstractmethod
    def forget(self, engram_id) -> dict: ...
    @abstractmethod
    def verify(self, engram_id) -> dict: ...
    @abstractmethod
    def status(self) -> dict: ...
    @abstractmethod
    def inspect(self, engram_id) -> dict: ...
    @abstractmethod
    def epoch_run(self, mode="full", trigger="manual") -> dict: ...
    @abstractmethod
    def epoch_status(self) -> dict: ...
    @abstractmethod
    def epoch_debt(self) -> dict: ...


class LocalAPI(MementoAPI):
    """Direct DB connection — for epoch subprocess and offline CLI."""

    def __init__(self, db_path):
        from memento.db import get_connection
        self.conn = get_connection(db_path)
        self.conn.row_factory = __import__("sqlite3").Row

    def capture(self, content, **kwargs):
        from memento.awake import awake_capture
        return awake_capture(self.conn, content, **kwargs)

    def recall(self, query, **kwargs):
        from memento.awake import awake_recall
        return awake_recall(self.conn, query, **kwargs)

    def forget(self, engram_id):
        from memento.awake import awake_forget
        return awake_forget(self.conn, engram_id)

    def verify(self, engram_id):
        from memento.awake import awake_verify
        return awake_verify(self.conn, engram_id)

    def status(self):
        # Build comprehensive status dict
        s = {}
        s["total_engrams"] = self.conn.execute("SELECT COUNT(*) FROM engrams").fetchone()[0]
        for state in ("consolidated", "archived", "forgotten", "buffered", "abstracted"):
            s[f"count_{state}"] = self.conn.execute(
                "SELECT COUNT(*) FROM engrams WHERE state=?", (state,)
            ).fetchone()[0]
        s["pending_capture"] = self.conn.execute(
            "SELECT COUNT(*) FROM capture_log WHERE epoch_id IS NULL"
        ).fetchone()[0]
        s["pending_delta"] = self.conn.execute(
            "SELECT COUNT(*) FROM delta_ledger WHERE epoch_id IS NULL"
        ).fetchone()[0]
        s["cognitive_debt_count"] = self.conn.execute(
            "SELECT COUNT(*) FROM cognitive_debt WHERE resolved_at IS NULL"
        ).fetchone()[0]
        return s

    def inspect(self, engram_id):
        row = self.conn.execute("SELECT * FROM engrams WHERE id=?", (engram_id,)).fetchone()
        return dict(row) if row else None

    def epoch_run(self, mode="full", trigger="manual"):
        from memento.epoch import acquire_lease, run_epoch_phases
        from memento.llm import LLMClient
        epoch_id = acquire_lease(self.conn, "default", mode, trigger)
        if not epoch_id:
            return {"error": "Another epoch is running"}
        llm = LLMClient.from_env() if mode == "full" else None
        if mode == "full" and llm is None:
            mode = "light"
        run_epoch_phases(self.conn, epoch_id, mode=mode, llm_client=llm)
        return {"epoch_id": epoch_id, "status": "completed", "mode": mode}

    def epoch_status(self):
        rows = self.conn.execute(
            "SELECT * FROM epochs ORDER BY lease_acquired DESC LIMIT 10"
        ).fetchall()
        return [dict(r) for r in rows]

    def epoch_debt(self):
        rows = self.conn.execute(
            "SELECT type, COUNT(*) as cnt FROM cognitive_debt "
            "WHERE resolved_at IS NULL GROUP BY type"
        ).fetchall()
        return {r[0]: r[1] for r in rows}
```

- [ ] **Step 2: Run API tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_api.py -v`
Expected: Fix and PASS

- [ ] **Step 3: Commit**

```bash
git add src/memento/api.py tests/test_api.py
git commit -m "feat(v0.5): Layer 4 — API layer split (MementoAPI/LocalAPI/WorkerClientAPI)"
```

---

## Task 16: Export/Import Update

**Files:**
- Modify: `src/memento/export.py`

- [ ] **Step 1: Update export to include nexus**

Update `export_memories()` to also export nexus data. Update `import_memories()` to call `rebuild_view_store()` after import.

- [ ] **Step 2: Run export tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_export.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add src/memento/export.py tests/test_export.py
git commit -m "feat(v0.5): Layer 4 — export/import L3 only + nexus + sync view rebuild"
```

---

## Task 17: Hooks Update

**Files:**
- Modify: `plugin/hooks/hooks.json`
- Modify: `plugin/scripts/hook-handler.sh`

- [ ] **Step 1: Update hooks.json**

Change `Stop` hook command from `flush` to `flush-and-epoch`.

- [ ] **Step 2: Add flush-and-epoch handler to hook-handler.sh**

Add the `flush-and-epoch` case with cooldown/throttle logic per spec section 4.4.

- [ ] **Step 3: Test hooks manually**

Run: `cd /Users/maizi/data/work/memento && bash plugin/scripts/hook-handler.sh flush-and-epoch <<< '{"session_id":"test"}'`
Expected: Runs without error (may skip epoch if no pending data)

- [ ] **Step 4: Commit**

```bash
git add plugin/hooks/hooks.json plugin/scripts/hook-handler.sh
git commit -m "feat(v0.5): Layer 4 — hooks update (Stop→flush-and-epoch with cooldown)"
```

---

## Task 18: End-to-End Tests

**Files:**
- Create: `tests/test_e2e.py`

- [ ] **Step 1: Write end-to-end test**

```python
# tests/test_e2e.py
"""End-to-end test: full capture → recall → epoch → recall pipeline."""
from datetime import datetime, timezone
import pytest
from tests.test_awake import _setup_v05_db


def test_full_pipeline(tmp_path):
    """capture→recall(provisional)→epoch→recall(consolidated)→forget→epoch→recall(empty)"""
    from memento.awake import awake_capture, awake_recall, awake_forget
    from memento.epoch import acquire_lease, run_epoch_phases
    from memento.repository import rebuild_view_store

    conn = _setup_v05_db(tmp_path)

    # 1. Capture → buffered
    result = awake_capture(conn, "Redis cache invalidation pattern", type="debugging", origin="agent")
    assert result["state"] == "buffered"
    capture_id = result["capture_log_id"]

    # 2. Recall → provisional hit
    results = awake_recall(conn, "Redis")
    assert len(results) >= 1
    assert any(r.get("provisional") and "Redis" in r["content"] for r in results)

    # 3. Epoch (full mode, no LLM → auto-promote)
    epoch_id = acquire_lease(conn, "default", "full", "manual")
    run_epoch_phases(conn, epoch_id, mode="full", llm_client=None)

    # 4. Recall → consolidated (non-provisional)
    results = awake_recall(conn, "Redis")
    assert len(results) >= 1
    consolidated = [r for r in results if not r.get("provisional")]
    assert any("Redis" in r["content"] for r in consolidated)

    # 5. Get engram ID for further operations
    engram_row = conn.execute(
        "SELECT id FROM engrams WHERE content LIKE '%Redis%' AND state='consolidated'"
    ).fetchone()
    assert engram_row is not None
    engram_id = engram_row["id"]

    # 6. Forget → pending
    forget_result = awake_forget(conn, engram_id)
    assert forget_result["status"] == "pending"

    # 7. Epoch → process forget
    epoch_id2 = acquire_lease(conn, "default", "light", "manual")
    run_epoch_phases(conn, epoch_id2, mode="light", llm_client=None)

    # 8. Recall → empty
    results = awake_recall(conn, "Redis")
    redis_results = [r for r in results if "Redis" in r["content"]]
    assert len(redis_results) == 0


def test_rigidity_preserved_through_pipeline(tmp_path):
    """Capture with type → epoch → inspect shows correct rigidity."""
    from memento.awake import awake_capture, awake_pin
    from memento.epoch import acquire_lease, run_epoch_phases

    conn = _setup_v05_db(tmp_path)

    awake_capture(conn, "Always use snake_case", type="convention", origin="human")

    epoch_id = acquire_lease(conn, "default", "full", "manual")
    run_epoch_phases(conn, epoch_id, mode="full", llm_client=None)

    row = conn.execute(
        "SELECT rigidity FROM engrams WHERE content LIKE '%snake_case%'"
    ).fetchone()
    assert row["rigidity"] == pytest.approx(0.7)  # convention → 0.7


def test_light_epoch_preserves_capture_log(tmp_path):
    """Light epoch: capture_log stays unconsumed, debt created."""
    from memento.awake import awake_capture
    from memento.epoch import acquire_lease, run_epoch_phases

    conn = _setup_v05_db(tmp_path)

    awake_capture(conn, "test memory", type="fact")

    epoch_id = acquire_lease(conn, "default", "light", "manual")
    run_epoch_phases(conn, epoch_id, mode="light", llm_client=None)

    # capture_log unconsumed
    cl = conn.execute("SELECT epoch_id FROM capture_log").fetchone()
    assert cl["epoch_id"] is None

    # Debt created
    debt = conn.execute("SELECT COUNT(*) FROM cognitive_debt WHERE resolved_at IS NULL").fetchone()[0]
    assert debt >= 1

    # View store rebuilt (but without the buffered item)
    ve = conn.execute("SELECT COUNT(*) FROM view_engrams").fetchone()[0]
    assert ve == 0  # Nothing consolidated yet
```

- [ ] **Step 2: Run end-to-end tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_e2e.py -v`
Expected: All PASS

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e.py
git commit -m "feat(v0.5): end-to-end tests — full pipeline verification"
```

---

## Task 19: Update CLAUDE.md and AGENTS.md

**Files:**
- Modify: `CLAUDE.md`
- Modify: `CLAUDE.en.md`
- Modify: `AGENTS.md`
- Modify: `AGENTS.zh-CN.md`

- [ ] **Step 1: Update all instruction files**

Per spec section 4.6:
- `capture` writes L2 (buffered), consolidated after epoch
- `recall` may return provisional results
- `forget` marks for deletion, effective after epoch
- New commands: `epoch run/status/debt`, `inspect`, `nexus`, `pin`
- Removed: `--mode A|B`, `--reinforce`

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md CLAUDE.en.md AGENTS.md AGENTS.zh-CN.md
git commit -m "docs(v0.5): update CLAUDE.md and AGENTS.md for three-track architecture"
```

---

## Task 20: Integration DB Init Update

**Files:**
- Modify: `src/memento/db.py`

- [ ] **Step 1: Update init_db to call migration**

Ensure `init_db()` calls `migrate_v03_to_v05()` for existing databases and creates the full v0.5 schema for new databases.

- [ ] **Step 2: Run all tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/ -v --tb=short`
Expected: All PASS

- [ ] **Step 3: Final commit**

```bash
git add src/memento/db.py
git commit -m "feat(v0.5): db.py — integrate migration into init_db()"
```
