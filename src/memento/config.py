"""memento.config — Unified configuration with four-layer priority.

Priority (highest → lowest):
  1. MEMENTO_* environment variables
  2. ~/.memento/config.json
  3. Legacy provider environment variables (ZHIPU_API_KEY, etc.)
  4. Built-in defaults
"""

import json
import os
import stat
from pathlib import Path
from typing import Optional


def CONFIG_PATH() -> Path:  # noqa: N802 – named as constant for backward compat
    """Return the path to ~/.memento/config.json (lazy so Path.home() is evaluated at call time)."""
    return Path.home() / ".memento" / "config.json"

# Legacy embedding provider detection: env var(s) → (provider, key_env_var)
_LEGACY_PROVIDERS: list[tuple[list[str], str]] = [
    (["ZHIPU_API_KEY", "GLM_API_KEY"], "zhipu"),
    (["MINIMAX_API_KEY"], "minimax"),
    (["MOONSHOT_API_KEY", "KIMI_API_KEY"], "moonshot"),
    (["OPENAI_API_KEY"], "openai"),
    (["GEMINI_API_KEY"], "gemini"),
]


def _defaults() -> dict:
    """Return built-in default configuration."""
    home = Path.home()
    return {
        "database": {
            "path": str(home / ".memento" / "default.db"),
        },
        "embedding": {
            "provider": "local",
            "api_key": None,
            "model": None,
        },
        "llm": {
            "provider": None,
            "base_url": None,
            "api_key": None,
            "model": None,
            "timeout": 30,
            "max_retries": 3,
            "temperature": 0,
        },
    }


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base (one level deep for known sections)."""
    result = {}
    for key in base:
        if key in override and isinstance(base[key], dict) and isinstance(override[key], dict):
            result[key] = {**base[key], **override[key]}
        elif key in override:
            result[key] = override[key]
        else:
            result[key] = base[key]
    # Include keys only in override
    for key in override:
        if key not in result:
            result[key] = override[key]
    return result


def _detect_legacy_embedding() -> dict:
    """Scan legacy provider env vars, return embedding config fragment."""
    for env_vars, provider in _LEGACY_PROVIDERS:
        for env_var in env_vars:
            api_key = os.environ.get(env_var)
            if api_key:
                return {"provider": provider, "api_key": api_key}
    return {}


def _load_config_file() -> dict:
    """Load config.json from ~/.memento/config.json, return {} on failure."""
    path = CONFIG_PATH()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, OSError):
        return {}


def _expand_tilde(path_str: str) -> str:
    """Expand ~ to the actual home directory."""
    return os.path.expanduser(path_str)


def _apply_memento_env(cfg: dict) -> dict:
    """Apply MEMENTO_* env var overrides (highest priority)."""
    env_map = {
        "MEMENTO_DB": ("database", "path", str),
        "MEMENTO_EMBEDDING_PROVIDER": ("embedding", "provider", str),
        "MEMENTO_EMBEDDING_API_KEY": ("embedding", "api_key", str),
        "MEMENTO_LLM_PROVIDER": ("llm", "provider", str),
        "MEMENTO_LLM_BASE_URL": ("llm", "base_url", str),
        "MEMENTO_LLM_API_KEY": ("llm", "api_key", str),
        "MEMENTO_LLM_MODEL": ("llm", "model", str),
        "MEMENTO_LLM_TIMEOUT": ("llm", "timeout", int),
        "MEMENTO_LLM_MAX_RETRIES": ("llm", "max_retries", int),
        "MEMENTO_LLM_TEMPERATURE": ("llm", "temperature", float),
    }

    for env_var, (section, key, cast) in env_map.items():
        value = os.environ.get(env_var)
        if value is not None:
            cfg[section][key] = cast(value)

    return cfg


def get_config() -> dict:
    """Returns unified config dict with keys: database, embedding, llm.

    Four-layer priority (highest first):
      1. MEMENTO_* environment variables
      2. ~/.memento/config.json
      3. Legacy provider environment variables
      4. Built-in defaults
    """
    # Layer 4: defaults
    cfg = _defaults()

    # Layer 3: legacy env vars (embedding only)
    legacy_embedding = _detect_legacy_embedding()
    if legacy_embedding:
        cfg["embedding"] = {**cfg["embedding"], **legacy_embedding}

    # Layer 2: config.json
    file_cfg = _load_config_file()
    if file_cfg:
        cfg = _deep_merge(cfg, file_cfg)

    # Layer 1: MEMENTO_* env vars
    cfg = _apply_memento_env(cfg)

    # Post-processing: tilde expansion on database.path
    if cfg["database"].get("path"):
        cfg["database"]["path"] = _expand_tilde(cfg["database"]["path"])

    return cfg


def save_config(cfg: dict) -> Path:
    """Write config to ~/.memento/config.json with 0600 permissions.

    Returns the path to the written file.
    """
    path = CONFIG_PATH()
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600

    return path


def mask_key(key: Optional[str]) -> str:
    """Mask API key for display.

    - None or "" → "(未配置)"
    - len <= 7   → "****"
    - otherwise  → first 3 chars + "****" + last 4 chars
    """
    if not key:
        return "(未配置)"
    if len(key) <= 7:
        return "****"
    return key[:3] + "****" + key[-4:]
