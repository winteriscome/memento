#!/usr/bin/env python3
"""MCP Server 入口 — 由 Claude Code 启动（stdio 协议）。"""

import asyncio
import sys
from pathlib import Path

# 确保 src 在 path 中
src_dir = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from mcp.server.stdio import stdio_server
from memento.mcp_server import create_mcp_app


async def main():
    app, api = create_mcp_app()
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())
    finally:
        api.close()


if __name__ == "__main__":
    asyncio.run(main())
