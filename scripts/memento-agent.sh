#!/usr/bin/env zsh

# Shared helper functions for Claude Code, Gemini CLI, Codex, and similar agents.

memento_project_env() {
  export MEMENTO_DB="$PWD/.memento/project.db"
  mkdir -p "$PWD/.memento"
}

memento_session_start() {
  memento_project_env
  memento recall "项目概况" --format json
}

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

claude_memento() {
  memento_session_start
  claude "$@"
}

gemini_memento() {
  memento_session_start
  gemini "$@"
}

codex_memento() {
  memento_session_start
  codex "$@"
}