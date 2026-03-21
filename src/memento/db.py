"""SQLite 数据库初始化、WAL 配置、sqlite-vec 加载。"""

import os
import sqlite3
from pathlib import Path

import sqlite_vec

DEFAULT_DB_DIR = Path.home() / ".memento"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "default.db"

# Gemini embedding-001 输出 768 维
EMBEDDING_DIM = 768


def get_db_path() -> Path:
    """获取数据库文件路径，支持环境变量覆盖。"""
    custom = os.environ.get("MEMENTO_DB")
    if custom:
        return Path(custom)
    return DEFAULT_DB_PATH


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """创建并初始化一个 SQLite 连接。"""
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    # 加载 sqlite-vec 扩展
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    # WAL 模式 + 并发安全
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA wal_autocheckpoint=1000;")

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
    conn.commit()
