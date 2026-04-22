#!/usr/bin/env zsh

# Shared helper functions for Claude Code, OpenCode, Gemini CLI, Codex, and similar agents.
# v0.2: 基于 Session Lifecycle 重写。

memento_project_env() {
  export MEMENTO_DB="$PWD/.memento/project.db"
  mkdir -p "$PWD/.memento"
}

# ── Session Lifecycle ──

memento_session_start() {
  memento_project_env
  local task="${1:-}"
  local result
  result=$(memento session start --project "$(pwd)" ${task:+--task "$task"} --format json 2>/dev/null)
  if [ $? -eq 0 ] && [ -n "$result" ]; then
    # 用 Python 提取 session_id，不依赖 jq
    export MEMENTO_SESSION_ID=$(python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('session_id',''))" <<< "$result" 2>/dev/null)
    if [ -z "$MEMENTO_SESSION_ID" ]; then
      unset MEMENTO_SESSION_ID
    fi
    echo "$result"
  else
    # 降级：直接 recall
    memento recall "项目概况" --format json 2>/dev/null || true
  fi
}

memento_session_end() {
  if [ -n "$MEMENTO_SESSION_ID" ]; then
    memento session end "$MEMENTO_SESSION_ID" \
      --outcome "${1:-completed}" \
      ${2:+--summary "$2"} 2>/dev/null || true
    unset MEMENTO_SESSION_ID
  fi
}

# ── Memory Operations ──

memento_recall_topic() {
  memento_project_env
  memento recall "$1" --format json
}

memento_capture_agent_summary() {
  memento_project_env
  memento capture "$1" --type "${2:-debugging}" --origin agent
}

memento_capture_user_preference() {
  memento_project_env
  memento capture "$1" --type preference --importance critical
}

# ── Observation ──

memento_observe() {
  memento observe "$1" ${2:+--tool "$2"} ${3:+--tags "$3"} 2>/dev/null || true
}

# ── Agent Wrappers ──
# 根据子进程退出码决定 outcome

claude_memento() {
  memento_session_start
  claude "$@"
  local exit_code=$?
  if [ $exit_code -eq 0 ]; then
    memento_session_end "completed"
  else
    memento_session_end "error"
  fi
  return $exit_code
}

gemini_memento() {
  memento_session_start
  gemini "$@"
  local exit_code=$?
  if [ $exit_code -eq 0 ]; then
    memento_session_end "completed"
  else
    memento_session_end "error"
  fi
  return $exit_code
}

codex_memento() {
  memento_session_start
  codex "$@"
  local exit_code=$?
  if [ $exit_code -eq 0 ]; then
    memento_session_end "completed"
  else
    memento_session_end "error"
  fi
  return $exit_code
}
