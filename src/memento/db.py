"""SQLite 数据库初始化、WAL 配置、sqlite-vec 加载。"""

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_DIR = Path.home() / ".memento"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "default.db"

# Gemini embedding-001 输出 768 维
EMBEDDING_DIM = 768

# 运行时标志：sqlite-vec 是否成功加载
VEC_AVAILABLE = False


def get_db_path() -> Path:
    """获取数据库文件路径。优先级：MEMENTO_DB env > config.json > 默认路径。"""
    from memento.config import get_config
    cfg = get_config()
    return Path(cfg["database"]["path"])


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """创建并初始化一个 SQLite 连接。

    sqlite-vec 加载失败时优雅降级到 FTS5-only 模式。
    """
    global VEC_AVAILABLE

    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Increase connection timeout to wait for locks instead of failing
    conn = sqlite3.connect(str(path), timeout=60)
    conn.row_factory = sqlite3.Row

    # 尝试加载 sqlite-vec 扩展（可能因 Python 编译选项而不可用）
    # 现有实现：直接导入并加载。如果失败则降级为 FTS5-only 模式。
    # 增强：在遇到未知错误时，尝试自动安装 sqlite-vec 作为回退。
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        VEC_AVAILABLE = True
    except (AttributeError, ImportError, OSError, Exception):
        # enable_load_extension 不存在 or sqlite_vec 未安装 or 加载失败
        # 尝试自动安装 sqlite-vec 作为回退（类似 embedding 依赖的处理方式）
        try:
            import sys, subprocess
            print("MEMENTO: 检测到未安装 sqlite-vec 或加载失败，正在尝试自动安装...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "sqlite-vec"], stdout=subprocess.DEVNULL, timeout=180)
            import sqlite_vec  # retry after install
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            VEC_AVAILABLE = True
        except Exception as e:
            # 安装失败或再次加载失败，回退到 FTS5-only 模式
            print(f"MEMENTO: 自动安装或加载 sqlite-vec 失败: {e}，将降级到 FTS5-only 模式。")
            VEC_AVAILABLE = False

    # WAL 模式 + 并发安全 + 外键约束
    # Enable WAL for better concurrency. Increase busy_timeout to mitigate
    # 'database is locked' errors during heavy write traffic (e.g., epoch runs).
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=20000;")
    conn.execute("PRAGMA wal_autocheckpoint=10000;")
    # Use NORMAL synchronous mode for better throughput while keeping data durable
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")

    return conn


def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    """为旧数据库补齐缺失列。"""
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def init_db(conn: sqlite3.Connection) -> None:
    """建表 + FTS5 索引。幂等操作，可重复调用。"""
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS engrams (
            id              TEXT PRIMARY KEY,
            content         TEXT NOT NULL,
            type            TEXT DEFAULT 'fact',
            tags            TEXT,
            strength        REAL DEFAULT 0.7,
            importance      TEXT DEFAULT 'normal',
            source          TEXT,
            origin          TEXT DEFAULT 'human',
            verified        INTEGER DEFAULT 0,
            created_at      TEXT NOT NULL,
            last_accessed   TEXT NOT NULL,
            access_count    INTEGER DEFAULT 0,
            forgotten       INTEGER DEFAULT 0,
            embedding_pending INTEGER DEFAULT 0,
            embedding_dim   INTEGER,
            embedding       BLOB
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS engrams_fts
            USING fts5(content, tags, content=engrams, content_rowid=rowid);

        CREATE TRIGGER IF NOT EXISTS engrams_ai AFTER INSERT ON engrams BEGIN
            INSERT INTO engrams_fts(rowid, content, tags)
            VALUES (new.rowid, new.content, new.tags);
        END;

        CREATE TRIGGER IF NOT EXISTS engrams_ad AFTER DELETE ON engrams BEGIN
            INSERT INTO engrams_fts(engrams_fts, rowid, content, tags)
            VALUES ('delete', old.rowid, old.content, old.tags);
        END;

        CREATE TRIGGER IF NOT EXISTS engrams_au AFTER UPDATE ON engrams BEGIN
            INSERT INTO engrams_fts(engrams_fts, rowid, content, tags)
            VALUES ('delete', old.rowid, old.content, old.tags);
            INSERT INTO engrams_fts(rowid, content, tags)
            VALUES (new.rowid, new.content, new.tags);
        END;

        CREATE INDEX IF NOT EXISTS idx_engrams_forgotten
            ON engrams(forgotten);
        CREATE INDEX IF NOT EXISTS idx_engrams_type
            ON engrams(type);
    """)

    _ensure_column(conn, "engrams", "embedding_dim", "INTEGER")
    _ensure_column(conn, "engrams", "source_session_id", "TEXT")
    _ensure_column(conn, "engrams", "source_event_id", "TEXT")

    # ── v0.2: sessions + session_events ──
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id              TEXT PRIMARY KEY,
            project         TEXT,
            task            TEXT,
            status          TEXT DEFAULT 'active',
            started_at      TEXT NOT NULL,
            ended_at        TEXT,
            summary         TEXT,
            metadata        TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_project
            ON sessions(project);
        CREATE INDEX IF NOT EXISTS idx_sessions_status
            ON sessions(status);

        CREATE TABLE IF NOT EXISTS session_events (
            id              TEXT PRIMARY KEY,
            session_id      TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            payload         TEXT,
            fingerprint     TEXT,
            created_at      TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_session_events_session
            ON session_events(session_id);
        CREATE INDEX IF NOT EXISTS idx_session_events_type
            ON session_events(event_type);
    """)

    conn.commit()

    # v0.5: 运行迁移确保新表和列存在（幂等）
    from memento.migration import migrate_v03_to_v05, migrate_v05_to_v092
    migrate_v03_to_v05(conn)
    migrate_v05_to_v092(conn)
