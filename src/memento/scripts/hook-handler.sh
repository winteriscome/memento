#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Resolve Python command robustly: prefer python3, fallback to python
if command -v python3 >/dev/null 2>&1; then
  PY_CMD="python3"
elif command -v python >/dev/null 2>&1; then
  PY_CMD="python"
else
  echo "Error: neither python3 nor python interpreter found" >&2
  exit 1
 fi
alias python3="$PY_CMD"

# Resolve Python command robustly: prefer python3, fallback to python
if command -v python3 >/dev/null 2>&1; then
  PY_CMD="python3"
elif command -v python >/dev/null 2>&1; then
  PY_CMD="python"
else
  echo "Error: neither python3 nor python interpreter found" >&2
  exit 1
fi

# 读取 stdin JSON（Claude Code 传入 hook 上下文）
HOOK_INPUT=$(cat)

# 提取 session_id（Claude Code 通过 stdin 传递）
CLAUDE_SID=$(echo "$HOOK_INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('session_id', d.get('id', d.get('sessionId', 'default'))))
except Exception:
    print('default')
" 2>/dev/null || echo "default")

# 计算 socket 路径（优先级：MEMENTO_DB env > config.json > 默认路径）
SOCK_PATH=$(python3 -c "
import hashlib, os, json
from pathlib import Path
db = os.environ.get('MEMENTO_DB')
if not db:
    cfg_path = Path.home() / '.memento' / 'config.json'
    if cfg_path.exists():
        try:
            c = json.loads(cfg_path.read_text())
            db = c.get('database', {}).get('path')
        except Exception:
            pass
if not db:
    db = os.path.expanduser('~/.memento/default.db')
else:
    db = os.path.expanduser(db)
print('/tmp/memento-worker-' + hashlib.md5(os.path.abspath(db).encode()).hexdigest()[:12] + '.sock')
" 2>/dev/null)

# 通过 Unix Socket 与 Worker 通信
send_to_worker() {
  python3 -c "
import http.client, socket, sys, json
sock_path, method, path = sys.argv[1], sys.argv[2], sys.argv[3]
body = sys.argv[4] if len(sys.argv) > 4 else '{}'
try:
    conn = http.client.HTTPConnection('localhost')
    conn.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.sock.connect(sock_path)
    conn.request(method, path, body, {'Content-Type': 'application/json'})
    resp = conn.getresponse()
    print(resp.read().decode())
    conn.close()
except Exception as e:
    print(json.dumps({'error': str(e)}))
" "$SOCK_PATH" "$@" 2>/dev/null || true
}

ensure_worker_running() {
  if [ -S "$SOCK_PATH" ]; then
    # socket 存在，检查是否活着
    send_to_worker GET /status > /dev/null 2>&1 && return 0
    # 死了，清理
    rm -f "$SOCK_PATH"
  fi
  # Start worker in background
  if command -v memento-worker &>/dev/null; then
    nohup memento-worker > /dev/null 2>&1 &
  else
    nohup python3 "$SCRIPT_DIR/worker-service.py" > /dev/null 2>&1 &
  fi
  # Wait for readiness with retry
  for i in $(seq 1 20); do
    send_to_worker GET /status > /dev/null 2>&1 && return 0
    sleep 0.2
  done
  echo "memento-worker failed to start within 4s" >&2
}

# 从 hook input 提取工具摘要
extract_tool_summary() {
  echo "$HOOK_INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    tool_name = d.get('tool_name', 'unknown')
    tool_input = d.get('tool_input', {})
    tool_response = str(d.get('tool_response', ''))[:200]
    files = []
    if isinstance(tool_input, dict):
        for k in ('file_path', 'path', 'command', 'pattern'):
            if k in tool_input:
                files.append(str(tool_input[k]))
    print(json.dumps({
        'tool': tool_name,
        'files': files,
        'summary': f'{tool_name}: {tool_response}',
    }))
except Exception:
    print(json.dumps({'tool': 'unknown', 'files': [], 'summary': 'extraction failed'}))
" 2>/dev/null || echo '{"tool":"unknown","files":[],"summary":"extraction failed"}'
}

case "${1:-}" in
  session-start)
    ensure_worker_running
    PAYLOAD=$(CLAUDE_SID="$CLAUDE_SID" MEMENTO_PROJECT="$(pwd)" python3 -c "
import json, os
print(json.dumps({
    'external_session_id': os.environ['CLAUDE_SID'],
    'project': os.environ['MEMENTO_PROJECT'],
}))
")
    send_to_worker POST /session/start "$PAYLOAD"
    ;;
  observe)
    TOOL_INFO=$(extract_tool_summary)
    # Build JSON safely using Python to handle all special characters
    send_to_worker POST /observe "$(echo "$TOOL_INFO" | CLAUDE_SID="$CLAUDE_SID" python3 -c "
import json, sys, os
sid = os.environ['CLAUDE_SID']
try:
    d = json.load(sys.stdin)
    print(json.dumps({
        'external_session_id': sid,
        'content': d.get('summary', ''),
        'tool': d.get('tool', ''),
        'files': d.get('files', []),
    }))
except Exception:
    print(json.dumps({'external_session_id': sid, 'content': 'extraction failed', 'tool': 'unknown', 'files': []}))
" 2>/dev/null)" &
    ;;
  flush)
    PAYLOAD=$(CLAUDE_SID="$CLAUDE_SID" python3 -c "
import json, os
print(json.dumps({'external_session_id': os.environ['CLAUDE_SID']}))
")
    send_to_worker POST /flush "$PAYLOAD"
    ;;
  flush-and-epoch)
    # 1. Flush (unchanged)
    PAYLOAD=$(CLAUDE_SID="$CLAUDE_SID" python3 -c "
import json, os
print(json.dumps({'external_session_id': os.environ['CLAUDE_SID']}))
")
    send_to_worker POST /flush "$PAYLOAD"

    # 2. Transcript extraction (v0.9 — async, failure logged but must not block)
    EXTRACT_PAYLOAD=$(echo "$HOOK_INPUT" | CLAUDE_SID="$CLAUDE_SID" python3 -c "
import json, sys, os
try:
    d = json.load(sys.stdin)
    print(json.dumps({
        'external_session_id': os.environ['CLAUDE_SID'],
        'transcript_path': d.get('transcript_path', ''),
    }))
except Exception:
    print(json.dumps({'external_session_id': os.environ['CLAUDE_SID'], 'transcript_path': ''}))
" 2>/dev/null)
    EXTRACT_RESULT=$(send_to_worker POST /transcript/extract "$EXTRACT_PAYLOAD" 2>/dev/null || echo '{"status":"error","reason":"worker_unreachable"}')
    # Log extraction status for observability (non-blocking)
    echo "$EXTRACT_RESULT" | python3 -c "
import sys, json
raw = sys.stdin.read().strip()
if not raw:
    print('[memento] transcript extraction: no response from worker', file=sys.stderr)
else:
    try:
        d = json.loads(raw)
        status = d.get('status', 'unknown')
        reason = d.get('reason', '')
        if status not in ('accepted', 'skipped'):
            print(f'[memento] transcript extraction: {status} {reason}', file=sys.stderr)
    except (json.JSONDecodeError, Exception):
        print(f'[memento] transcript extraction: invalid response: {raw[:200]}', file=sys.stderr)
" 2>/dev/null &

    # 3. Throttle epoch: only run if enough time has passed and pending items exist
    MIN_EPOCH_INTERVAL=300   # seconds
    MIN_PENDING_ITEMS=1

    STATUS_JSON=$(send_to_worker GET /status 2>/dev/null || echo '{}')
    SHOULD_EPOCH=$(echo "$STATUS_JSON" | python3 -c "
import json, sys
from datetime import datetime, timezone
try:
    d = json.load(sys.stdin)
    # Check pending counts
    pending = d.get('pending_capture', 0) + d.get('pending_delta', 0) + d.get('pending_recon', 0)
    if pending < $MIN_PENDING_ITEMS:
        print('no')
        sys.exit(0)
    # Check cooldown
    last = d.get('last_epoch_committed_at')
    if last:
        last_dt = datetime.fromisoformat(last.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        elapsed = (now - last_dt).total_seconds()
        if elapsed < $MIN_EPOCH_INTERVAL:
            print('no')
            sys.exit(0)
    print('yes')
except Exception:
    print('no')
" 2>/dev/null || echo "no")

    if [ "$SHOULD_EPOCH" = "yes" ]; then
      # Run light epoch in background to avoid blocking
      python3 -m memento epoch run --mode light --trigger auto > /dev/null 2>&1 &
    fi
    ;;
  session-end)
    PAYLOAD=$(CLAUDE_SID="$CLAUDE_SID" python3 -c "
import json, os
print(json.dumps({
    'external_session_id': os.environ['CLAUDE_SID'],
    'outcome': 'completed'
}))
")
    send_to_worker POST /session/end "$PAYLOAD"
    # 只有 registry 为空（无活跃会话）才 shutdown worker
    # 注意：active_session_ids 是列表，active_sessions 是整数
    ACTIVE=$(send_to_worker GET /status 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    ids = d.get('active_session_ids', [])
    print(len(ids) if isinstance(ids, list) else 0)
except Exception:
    print('0')
" 2>/dev/null || echo "0")
    if [ "$ACTIVE" = "0" ]; then
      send_to_worker POST /shutdown '{}' || true
    fi
    ;;
  *)
    echo "Usage: $0 {session-start|observe|flush|flush-and-epoch|session-end}" >&2
    exit 1
    ;;
esac
