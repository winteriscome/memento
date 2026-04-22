#!/usr/bin/env python3
"""Worker Service 入口 — 由 hook 启动。"""

import sys
from pathlib import Path

# 确保 src 在 path 中
src_dir = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from memento.worker import WorkerServer, get_socket_path
from memento.db import get_db_path


def main():
    db_path = get_db_path()
    sock_path = get_socket_path(db_path)

    print(f"Starting Worker: db={db_path} sock={sock_path}", file=sys.stderr)
    server = WorkerServer(db_path, sock_path)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown_gracefully()


if __name__ == "__main__":
    main()
