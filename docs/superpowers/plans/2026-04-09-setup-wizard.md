# Setup Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `memento setup` wizard + `memento doctor` + unified config system so installation is just `pip install memento && memento setup`.

**Architecture:** New `config.py` module provides four-layer config resolution (`MEMENTO_*` env > `config.json` > legacy provider env > defaults). `setup` command is an interactive Click wizard that writes `~/.memento/config.json`, inits DB, and installs Claude Code hooks/MCP globally. `doctor` command reads config and reports status.

**Tech Stack:** Python 3.10+, Click (CLI), stdlib json/os/stat (config), existing LLMClient/embedding modules

**Spec:** `docs/superpowers/specs/2026-04-09-setup-wizard-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/memento/config.py` | Create | Four-layer config loading: read `~/.memento/config.json`, merge env vars, provide `get_config()` |
| `tests/test_config.py` | Create | Tests for config loading, priority, masking, file permissions |
| `src/memento/llm.py` | Modify | Add `LLMClient.from_config()` that reads from unified config, keep `from_env()` as deprecated alias |
| `tests/test_llm.py` | Modify | Add tests for `from_config()` |
| `src/memento/embedding.py` | Modify | `get_embedding()` reads `config.embedding` first, falls back to legacy env vars |
| `tests/test_embedding.py` | Modify | Add tests for config-based provider selection |
| `src/memento/db.py` | Modify | `get_db_path()` reads config first |
| `src/memento/cli.py` | Modify | Add `setup` and `doctor` commands, deprecate `plugin install claude` |
| `tests/test_setup.py` | Create | Tests for setup wizard and doctor command |
| `plugin/scripts/hook-handler.sh` | Modify | Read DB path from `config.json` before env var |
| `README.md` | Modify | Update Quick Start and CLI Reference |
| `README.zh-CN.md` | Modify | Update 快速开始 and CLI 命令参考 |

---

### Task 1: `config.py` — Unified Config Module

**Files:**
- Create: `src/memento/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for config loading**

```python
# tests/test_config.py
import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from memento.config import get_config, mask_key, CONFIG_PATH


class TestGetConfig:
    """Test four-layer config resolution."""

    def test_returns_empty_defaults_when_no_config_no_env(self, tmp_path):
        """No config.json, no env vars → empty/default values."""
        with patch.object(Path, "home", return_value=tmp_path):
            with patch.dict(os.environ, {}, clear=True):
                cfg = get_config()
                assert cfg["database"]["path"] == str(tmp_path / ".memento" / "default.db")
                assert cfg["embedding"]["provider"] is None
                assert cfg["embedding"]["api_key"] is None
                assert cfg["llm"]["base_url"] is None
                assert cfg["llm"]["api_key"] is None
                assert cfg["llm"]["model"] is None

    def test_reads_config_json(self, tmp_path):
        """config.json values are returned."""
        memento_dir = tmp_path / ".memento"
        memento_dir.mkdir()
        config_file = memento_dir / "config.json"
        config_file.write_text(json.dumps({
            "database": {"path": "/custom/db.db"},
            "embedding": {"provider": "zhipu", "api_key": "sk-from-config"},
            "llm": {"base_url": "https://api.test.com/v1", "api_key": "sk-llm", "model": "gpt-4"}
        }))

        with patch.object(Path, "home", return_value=tmp_path):
            with patch.dict(os.environ, {}, clear=True):
                cfg = get_config()
                assert cfg["database"]["path"] == "/custom/db.db"
                assert cfg["embedding"]["provider"] == "zhipu"
                assert cfg["embedding"]["api_key"] == "sk-from-config"
                assert cfg["llm"]["base_url"] == "https://api.test.com/v1"

    def test_memento_env_overrides_config_json(self, tmp_path):
        """MEMENTO_* env vars override config.json."""
        memento_dir = tmp_path / ".memento"
        memento_dir.mkdir()
        config_file = memento_dir / "config.json"
        config_file.write_text(json.dumps({
            "embedding": {"provider": "zhipu", "api_key": "sk-from-config"}
        }))

        with patch.object(Path, "home", return_value=tmp_path):
            with patch.dict(os.environ, {
                "MEMENTO_EMBEDDING_PROVIDER": "openai",
                "MEMENTO_EMBEDDING_API_KEY": "sk-from-env"
            }, clear=True):
                cfg = get_config()
                assert cfg["embedding"]["provider"] == "openai"
                assert cfg["embedding"]["api_key"] == "sk-from-env"

    def test_memento_db_env_overrides_config(self, tmp_path):
        """MEMENTO_DB env var overrides config.json database.path."""
        memento_dir = tmp_path / ".memento"
        memento_dir.mkdir()
        config_file = memento_dir / "config.json"
        config_file.write_text(json.dumps({
            "database": {"path": "/config/db.db"}
        }))

        with patch.object(Path, "home", return_value=tmp_path):
            with patch.dict(os.environ, {"MEMENTO_DB": "/env/db.db"}, clear=True):
                cfg = get_config()
                assert cfg["database"]["path"] == "/env/db.db"

    def test_legacy_env_vars_used_when_no_config(self, tmp_path):
        """Legacy ZHIPU_API_KEY etc. work when no config.json."""
        with patch.object(Path, "home", return_value=tmp_path):
            with patch.dict(os.environ, {"ZHIPU_API_KEY": "sk-legacy"}, clear=True):
                cfg = get_config()
                assert cfg["embedding"]["provider"] == "zhipu"
                assert cfg["embedding"]["api_key"] == "sk-legacy"

    def test_config_json_overrides_legacy_env(self, tmp_path):
        """config.json takes priority over legacy provider env vars."""
        memento_dir = tmp_path / ".memento"
        memento_dir.mkdir()
        config_file = memento_dir / "config.json"
        config_file.write_text(json.dumps({
            "embedding": {"provider": "openai", "api_key": "sk-from-config"}
        }))

        with patch.object(Path, "home", return_value=tmp_path):
            with patch.dict(os.environ, {"ZHIPU_API_KEY": "sk-legacy"}, clear=True):
                cfg = get_config()
                assert cfg["embedding"]["provider"] == "openai"
                assert cfg["embedding"]["api_key"] == "sk-from-config"

    def test_tilde_expansion_in_db_path(self, tmp_path):
        """~ in database.path gets expanded."""
        memento_dir = tmp_path / ".memento"
        memento_dir.mkdir()
        config_file = memento_dir / "config.json"
        config_file.write_text(json.dumps({
            "database": {"path": "~/.memento/custom.db"}
        }))

        with patch.object(Path, "home", return_value=tmp_path):
            with patch.dict(os.environ, {}, clear=True):
                cfg = get_config()
                assert cfg["database"]["path"] == str(tmp_path / ".memento" / "custom.db")

    def test_malformed_config_json_falls_back(self, tmp_path):
        """Malformed config.json → fall back gracefully, no crash."""
        memento_dir = tmp_path / ".memento"
        memento_dir.mkdir()
        (memento_dir / "config.json").write_text("not json{{{")

        with patch.object(Path, "home", return_value=tmp_path):
            with patch.dict(os.environ, {}, clear=True):
                cfg = get_config()
                assert cfg["database"]["path"] == str(tmp_path / ".memento" / "default.db")


class TestMaskKey:
    """Test API key masking."""

    def test_mask_normal_key(self):
        assert mask_key("sk-abc123xyz789") == "sk-****9789"

    def test_mask_short_key(self):
        assert mask_key("abc") == "****"

    def test_mask_none(self):
        assert mask_key(None) == "(未配置)"

    def test_mask_empty(self):
        assert mask_key("") == "(未配置)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memento.config'`

- [ ] **Step 3: Implement config.py**

```python
# src/memento/config.py
"""Unified configuration loader for Memento.

Four-layer priority:
    MEMENTO_* env vars > ~/.memento/config.json > legacy provider env vars > defaults
"""

import json
import os
from pathlib import Path
from typing import Optional


CONFIG_PATH = Path.home() / ".memento" / "config.json"

# Legacy provider env vars → (provider_name, env_var_names)
_LEGACY_EMBEDDING_PROVIDERS = [
    ("zhipu", ["ZHIPU_API_KEY", "GLM_API_KEY"]),
    ("minimax", ["MINIMAX_API_KEY"]),
    ("moonshot", ["MOONSHOT_API_KEY", "KIMI_API_KEY"]),
    ("openai", ["OPENAI_API_KEY"]),
    ("gemini", ["GEMINI_API_KEY"]),
]


def _read_config_file() -> dict:
    """Read ~/.memento/config.json, return {} on any error."""
    try:
        path = Path.home() / ".memento" / "config.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _detect_legacy_embedding() -> tuple[Optional[str], Optional[str]]:
    """Detect embedding provider from legacy env vars (third priority).

    Returns (provider_name, api_key) or (None, None).
    """
    for provider, env_vars in _LEGACY_EMBEDDING_PROVIDERS:
        for var in env_vars:
            key = os.environ.get(var)
            if key:
                return provider, key
    return None, None


def get_config() -> dict:
    """Load merged configuration with four-layer priority.

    Returns dict with keys: database, embedding, llm.
    """
    home = Path.home()
    default_db = str(home / ".memento" / "default.db")

    # Layer 3: defaults
    cfg = {
        "database": {"path": default_db},
        "embedding": {"provider": None, "api_key": None, "model": None},
        "llm": {
            "provider": None, "base_url": None, "api_key": None,
            "model": None, "timeout": 30, "max_retries": 3, "temperature": 0,
        },
    }

    # Layer 2: legacy provider env vars (embedding only)
    legacy_provider, legacy_key = _detect_legacy_embedding()
    if legacy_provider:
        cfg["embedding"]["provider"] = legacy_provider
        cfg["embedding"]["api_key"] = legacy_key

    # Layer 2 (LLM): legacy MEMENTO_LLM_* env vars are handled later at layer 1

    # Layer 1: config.json
    file_cfg = _read_config_file()
    if file_cfg.get("database", {}).get("path"):
        raw_path = file_cfg["database"]["path"]
        cfg["database"]["path"] = str(Path(raw_path).expanduser())
    if file_cfg.get("embedding", {}).get("provider"):
        cfg["embedding"]["provider"] = file_cfg["embedding"]["provider"]
        cfg["embedding"]["api_key"] = file_cfg["embedding"].get("api_key")
        cfg["embedding"]["model"] = file_cfg["embedding"].get("model")
    for llm_key in ("provider", "base_url", "api_key", "model", "timeout", "max_retries", "temperature"):
        val = file_cfg.get("llm", {}).get(llm_key)
        if val is not None:
            cfg["llm"][llm_key] = val

    # Layer 0: MEMENTO_* env vars (highest priority)
    env_db = os.environ.get("MEMENTO_DB")
    if env_db:
        cfg["database"]["path"] = str(Path(env_db).expanduser())

    env_emb_provider = os.environ.get("MEMENTO_EMBEDDING_PROVIDER")
    if env_emb_provider:
        cfg["embedding"]["provider"] = env_emb_provider
    env_emb_key = os.environ.get("MEMENTO_EMBEDDING_API_KEY")
    if env_emb_key:
        cfg["embedding"]["api_key"] = env_emb_key

    for env_suffix, cfg_key in [
        ("BASE_URL", "base_url"), ("API_KEY", "api_key"), ("MODEL", "model"),
        ("TIMEOUT", "timeout"), ("MAX_RETRIES", "max_retries"),
        ("TEMPERATURE", "temperature"),
    ]:
        val = os.environ.get(f"MEMENTO_LLM_{env_suffix}")
        if val is not None:
            # Cast numeric fields
            if cfg_key in ("timeout", "max_retries"):
                val = int(val)
            elif cfg_key == "temperature":
                val = float(val)
            cfg["llm"][cfg_key] = val

    return cfg


def save_config(cfg: dict) -> Path:
    """Write config to ~/.memento/config.json with 0600 permissions.

    Returns the path written.
    """
    path = Path.home() / ".memento" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def mask_key(key: Optional[str]) -> str:
    """Mask an API key for display: 'sk-abc123xyz789' → 'sk-****9789'."""
    if not key:
        return "(未配置)"
    if len(key) <= 4:
        return "****"
    return key[:3] + "****" + key[-4:]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_config.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/config.py tests/test_config.py
git commit -m "feat: add unified config module with four-layer priority"
```

---

### Task 2: `LLMClient.from_config()` — Config-Aware LLM Client

**Files:**
- Modify: `src/memento/llm.py:49-78` (add `from_config` classmethod)
- Modify: `tests/test_llm.py` (add from_config tests)

- [ ] **Step 1: Write failing tests for `from_config()`**

Add to `tests/test_llm.py`:

```python
# Add at top of file:
from pathlib import Path
import json

# Add these test functions after existing from_env tests:

def test_from_config_reads_config_json(tmp_path):
    """from_config reads LLM settings from config.json."""
    memento_dir = tmp_path / ".memento"
    memento_dir.mkdir()
    (memento_dir / "config.json").write_text(json.dumps({
        "llm": {
            "base_url": "https://api.config.com/v1",
            "api_key": "sk-config-key",
            "model": "glm-4-flash"
        }
    }))

    with patch.object(Path, "home", return_value=tmp_path):
        with patch.dict(os.environ, {}, clear=True):
            client = LLMClient.from_config()
            assert client is not None
            assert client.base_url == "https://api.config.com/v1"
            assert client.api_key == "sk-config-key"
            assert client.model == "glm-4-flash"


def test_from_config_env_overrides_config(tmp_path):
    """MEMENTO_LLM_* env vars override config.json."""
    memento_dir = tmp_path / ".memento"
    memento_dir.mkdir()
    (memento_dir / "config.json").write_text(json.dumps({
        "llm": {
            "base_url": "https://api.config.com/v1",
            "api_key": "sk-config-key",
            "model": "glm-4-flash"
        }
    }))

    with patch.object(Path, "home", return_value=tmp_path):
        with patch.dict(os.environ, {
            "MEMENTO_LLM_API_KEY": "sk-env-override"
        }, clear=True):
            client = LLMClient.from_config()
            assert client is not None
            assert client.api_key == "sk-env-override"
            assert client.base_url == "https://api.config.com/v1"  # from config


def test_from_config_returns_none_when_incomplete(tmp_path):
    """from_config returns None when required fields missing."""
    with patch.object(Path, "home", return_value=tmp_path):
        with patch.dict(os.environ, {}, clear=True):
            client = LLMClient.from_config()
            assert client is None


def test_from_config_with_provider_presets(tmp_path):
    """from_config fills base_url/model from provider presets."""
    memento_dir = tmp_path / ".memento"
    memento_dir.mkdir()
    (memento_dir / "config.json").write_text(json.dumps({
        "llm": {
            "provider": "zhipu",
            "api_key": "sk-zhipu-key"
        }
    }))

    with patch.object(Path, "home", return_value=tmp_path):
        with patch.dict(os.environ, {}, clear=True):
            client = LLMClient.from_config()
            assert client is not None
            assert "bigmodel.cn" in client.base_url
            assert client.model == "glm-4-flash-250414"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_llm.py::test_from_config_reads_config_json -v`
Expected: FAIL — `AttributeError: type object 'LLMClient' has no attribute 'from_config'`

- [ ] **Step 3: Implement `from_config()` in llm.py**

Add after `from_env()` in `src/memento/llm.py` (after line 78):

```python
    @classmethod
    def from_config(cls) -> Optional["LLMClient"]:
        """Create LLMClient from unified config (config.json + env vars).

        Uses get_config() which resolves: MEMENTO_* env > config.json > defaults.
        If provider is set but base_url/model are not, uses provider presets.
        Returns None if required fields (base_url, api_key, model) are missing.
        """
        from memento.config import get_config

        cfg = get_config()
        llm = cfg["llm"]

        base_url = llm.get("base_url")
        api_key = llm.get("api_key")
        model = llm.get("model")
        provider = llm.get("provider")

        # Fill from provider presets if provider is set
        if provider and (not base_url or not model):
            presets = {
                "zhipu": ("https://open.bigmodel.cn/api/paas/v4", "glm-4-flash-250414"),
                "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
            }
            if provider in presets:
                preset_url, preset_model = presets[provider]
                base_url = base_url or preset_url
                model = model or preset_model

        if not base_url or not api_key or not model:
            return None

        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=int(llm.get("timeout", 30)),
            max_retries=int(llm.get("max_retries", 3)),
            temperature=float(llm.get("temperature", 0)),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_llm.py -v`
Expected: All PASS (old + new tests)

- [ ] **Step 5: Replace `from_env()` callers with `from_config()`**

Find all callers of `LLMClient.from_env()` and replace with `LLMClient.from_config()`:

Files to grep: `src/memento/epoch.py`, `src/memento/transcript.py`, `src/memento/api.py`

Each file: replace `LLMClient.from_env()` → `LLMClient.from_config()`

In `src/memento/llm.py`, add deprecation to `from_env()`:

```python
    @classmethod
    def from_env(cls) -> Optional["LLMClient"]:
        """Deprecated: use from_config() instead. Kept for backward compatibility."""
        return cls.from_config()
```

- [ ] **Step 6: Run full test suite to verify no regressions**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_llm.py tests/test_epoch.py tests/test_transcript.py tests/test_api.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/memento/llm.py src/memento/epoch.py src/memento/transcript.py src/memento/api.py tests/test_llm.py
git commit -m "feat: add LLMClient.from_config() with unified config support"
```

---

### Task 3: Embedding Config Integration

**Files:**
- Modify: `src/memento/embedding.py:134-159` (config-aware provider selection)
- Modify: `tests/test_embedding.py` (add config tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_embedding.py`:

```python
import json
from pathlib import Path
from unittest.mock import patch
import os

def test_get_embedding_uses_config_provider(tmp_path):
    """get_embedding reads provider from config.json."""
    memento_dir = tmp_path / ".memento"
    memento_dir.mkdir()
    (memento_dir / "config.json").write_text(json.dumps({
        "embedding": {"provider": "zhipu", "api_key": "sk-test-key", "model": "embedding-3"}
    }))

    with patch.object(Path, "home", return_value=tmp_path):
        with patch.dict(os.environ, {}, clear=True):
            with patch("memento.embedding._embed_zhipu") as mock_zhipu:
                mock_zhipu.return_value = [0.1, 0.2, 0.3]
                result = get_embedding("test text")
                mock_zhipu.assert_called_once()


def test_get_embedding_config_overrides_legacy_env(tmp_path):
    """Config provider takes priority over legacy env vars."""
    memento_dir = tmp_path / ".memento"
    memento_dir.mkdir()
    (memento_dir / "config.json").write_text(json.dumps({
        "embedding": {"provider": "openai", "api_key": "sk-openai-key"}
    }))

    with patch.object(Path, "home", return_value=tmp_path):
        with patch.dict(os.environ, {"ZHIPU_API_KEY": "sk-legacy"}, clear=True):
            with patch("memento.embedding._embed_openai") as mock_openai, \
                 patch("memento.embedding._embed_zhipu") as mock_zhipu:
                mock_openai.return_value = [0.1, 0.2, 0.3]
                result = get_embedding("test text")
                mock_openai.assert_called_once()
                mock_zhipu.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_embedding.py::test_get_embedding_uses_config_provider -v`
Expected: FAIL

- [ ] **Step 3: Modify `get_embedding()` in embedding.py**

At the top of `get_embedding()` (line 134), add config-based provider dispatch before the legacy loop:

```python
def get_embedding(text: str) -> tuple[Optional[bytes], int, bool]:
    """返回 (embedding_blob, dim, is_pending)。按照优先级获取模型 embedding。"""
    from memento.config import get_config

    cfg = get_config()
    emb_cfg = cfg.get("embedding", {})
    configured_provider = emb_cfg.get("provider")
    configured_key = emb_cfg.get("api_key")

    # If provider explicitly configured (via config.json or MEMENTO_* env),
    # use that provider directly instead of scanning all legacy env vars
    if configured_provider and configured_key:
        provider_map = {
            "zhipu": _embed_zhipu,
            "minimax": _embed_minimax,
            "moonshot": _embed_moonshot,
            "openai": _embed_openai,
            "gemini": _embed_gemini,
        }
        provider_fn = provider_map.get(configured_provider)
        if provider_fn:
            # Temporarily set the legacy env var so provider function finds it
            legacy_var = {
                "zhipu": "ZHIPU_API_KEY", "minimax": "MINIMAX_API_KEY",
                "moonshot": "MOONSHOT_API_KEY", "openai": "OPENAI_API_KEY",
                "gemini": "GEMINI_API_KEY",
            }[configured_provider]
            old_val = os.environ.get(legacy_var)
            os.environ[legacy_var] = configured_key
            try:
                vec = provider_fn(text)
            finally:
                if old_val is None:
                    os.environ.pop(legacy_var, None)
                else:
                    os.environ[legacy_var] = old_val
            if vec is not None:
                return vec_to_blob(vec), len(vec), False

    # Legacy fallback: scan all provider env vars in order
    providers = [
        _embed_zhipu, _embed_minimax, _embed_moonshot,
        _embed_openai, _embed_gemini,
    ]
    for provider in providers:
        vec = provider(text)
        if vec is not None:
            return vec_to_blob(vec), len(vec), False

    # Level 1: 本地模型
    vec = _embed_local(text)
    if vec is not None:
        return vec_to_blob(vec), len(vec), False

    # Level 2: 无 embedding 能力
    return None, 0, True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_embedding.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/embedding.py tests/test_embedding.py
git commit -m "feat: embedding provider reads from unified config"
```

---

### Task 4: `db.py` Config Integration

**Files:**
- Modify: `src/memento/db.py:17-22`

- [ ] **Step 1: Write failing test**

Add to existing test file or create inline:

```python
# In tests/test_config.py, add:
def test_db_get_db_path_reads_config(tmp_path):
    """get_db_path reads from config.json."""
    memento_dir = tmp_path / ".memento"
    memento_dir.mkdir()
    (memento_dir / "config.json").write_text(json.dumps({
        "database": {"path": str(tmp_path / "custom.db")}
    }))

    with patch.object(Path, "home", return_value=tmp_path):
        with patch.dict(os.environ, {}, clear=True):
            from memento.db import get_db_path
            result = get_db_path()
            assert str(result) == str(tmp_path / "custom.db")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_config.py::test_db_get_db_path_reads_config -v`
Expected: FAIL — get_db_path still reads env only

- [ ] **Step 3: Modify `get_db_path()` in db.py**

Replace lines 17-22 in `src/memento/db.py`:

```python
def get_db_path() -> Path:
    """获取数据库文件路径。优先级：MEMENTO_DB env > config.json > 默认路径。"""
    from memento.config import get_config
    cfg = get_config()
    return Path(cfg["database"]["path"])
```

- [ ] **Step 4: Run tests to verify**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_config.py::test_db_get_db_path_reads_config tests/test_core.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/db.py tests/test_config.py
git commit -m "feat: get_db_path reads from unified config"
```

---

### Task 5: `hook-handler.sh` Config Integration

**Files:**
- Modify: `plugin/scripts/hook-handler.sh:34-39`

- [ ] **Step 1: Modify socket path computation**

Replace lines 34-39 in `plugin/scripts/hook-handler.sh`:

```bash
SOCK_PATH=$(python3 -c '
import hashlib, os, json
from pathlib import Path
db = os.environ.get("MEMENTO_DB")
if not db:
    cfg_path = Path.home() / ".memento" / "config.json"
    if cfg_path.exists():
        try:
            c = json.loads(cfg_path.read_text())
            db = c.get("database", {}).get("path")
        except Exception:
            pass
if not db:
    db = str(Path.home() / ".memento" / "default.db")
else:
    db = str(Path(db).expanduser())
print("/tmp/memento-worker-" + hashlib.md5(os.path.abspath(db).encode()).hexdigest()[:12] + ".sock")
')
```

- [ ] **Step 2: Test manually**

Run: `cd /Users/maizi/data/work/memento && bash -c 'source plugin/scripts/hook-handler.sh 2>/dev/null; echo "test"'`
Expected: No syntax errors

Run: `python3 -c "
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
    db = str(Path.home() / '.memento' / 'default.db')
else:
    db = str(Path(db).expanduser())
print('/tmp/memento-worker-' + hashlib.md5(os.path.abspath(db).encode()).hexdigest()[:12] + '.sock')
"`
Expected: Prints a valid socket path like `/tmp/memento-worker-xxxxxxxxxxxx.sock`

- [ ] **Step 3: Commit**

```bash
git add plugin/scripts/hook-handler.sh
git commit -m "feat: hook-handler reads DB path from config.json"
```

---

### Task 6: `memento setup` Command

**Files:**
- Modify: `src/memento/cli.py` (add `setup` command group)
- Create: `tests/test_setup.py`

- [ ] **Step 1: Write failing tests for setup**

```python
# tests/test_setup.py
import json
import os
import stat
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from memento.cli import main


class TestSetupCommand:
    """Test memento setup wizard."""

    def test_setup_creates_config_and_db(self, tmp_path):
        """setup creates config.json and initializes DB."""
        runner = CliRunner()
        claude_dir = tmp_path / ".claude"

        with patch.object(Path, "home", return_value=tmp_path), \
             patch("memento.cli._find_hook_handler", return_value="/fake/hook-handler.sh"), \
             patch("shutil.which", return_value="/fake/memento-mcp-server"):
            # Simulate: choose zhipu(1), enter key, choose zhipu(1), reuse key(Y)
            result = runner.invoke(main, ["setup"], input="1\nsk-test-key-1234\n1\nY\n")

        assert result.exit_code == 0
        config_path = tmp_path / ".memento" / "config.json"
        assert config_path.exists()

        cfg = json.loads(config_path.read_text())
        assert cfg["embedding"]["provider"] == "zhipu"
        assert cfg["embedding"]["api_key"] == "sk-test-key-1234"

    def test_setup_config_file_permissions(self, tmp_path):
        """setup creates config.json with 0600 permissions."""
        runner = CliRunner()

        with patch.object(Path, "home", return_value=tmp_path), \
             patch("memento.cli._find_hook_handler", return_value="/fake/hook-handler.sh"), \
             patch("shutil.which", return_value="/fake/memento-mcp-server"):
            result = runner.invoke(main, ["setup"], input="1\nsk-test-key-1234\n1\nY\n")

        config_path = tmp_path / ".memento" / "config.json"
        if config_path.exists():
            mode = stat.S_IMODE(os.stat(config_path).st_mode)
            assert mode == 0o600

    def test_setup_noninteractive(self, tmp_path):
        """setup --yes with provider flags works non-interactively."""
        runner = CliRunner()

        with patch.object(Path, "home", return_value=tmp_path), \
             patch("memento.cli._find_hook_handler", return_value="/fake/hook-handler.sh"), \
             patch("shutil.which", return_value="/fake/memento-mcp-server"):
            result = runner.invoke(main, [
                "setup", "--yes",
                "--embedding-provider", "zhipu",
                "--embedding-api-key", "sk-test-1234",
                "--llm-provider", "zhipu",
                "--llm-api-key", "sk-test-1234",
            ])

        assert result.exit_code == 0
        config_path = tmp_path / ".memento" / "config.json"
        assert config_path.exists()

    def test_setup_skip_embedding_requires_confirm(self, tmp_path):
        """Skipping embedding requires explicit 'y' confirmation."""
        runner = CliRunner()

        with patch.object(Path, "home", return_value=tmp_path), \
             patch("memento.cli._find_hook_handler", return_value="/fake/hook-handler.sh"), \
             patch("shutil.which", return_value="/fake/memento-mcp-server"):
            # Choose skip(3), then refuse to confirm(N)
            result = runner.invoke(main, ["setup"], input="3\nN\n")

        assert result.exit_code != 0 or "中断" in result.output

    def test_setup_writes_hooks_globally(self, tmp_path):
        """setup writes hooks to ~/.claude/settings.json."""
        runner = CliRunner()

        with patch.object(Path, "home", return_value=tmp_path), \
             patch("memento.cli._find_hook_handler", return_value="/fake/hook-handler.sh"), \
             patch("shutil.which", return_value="/fake/memento-mcp-server"):
            result = runner.invoke(main, ["setup"], input="1\nsk-key-1234\n1\nY\n")

        settings_path = tmp_path / ".claude" / "settings.json"
        assert settings_path.exists()
        settings = json.loads(settings_path.read_text())
        assert "hooks" in settings

    def test_setup_writes_mcp_globally(self, tmp_path):
        """setup writes MCP config to ~/.claude/.mcp.json."""
        runner = CliRunner()

        with patch.object(Path, "home", return_value=tmp_path), \
             patch("memento.cli._find_hook_handler", return_value="/fake/hook-handler.sh"), \
             patch("shutil.which", return_value="/fake/memento-mcp-server"):
            result = runner.invoke(main, ["setup"], input="1\nsk-key-1234\n1\nY\n")

        mcp_path = tmp_path / ".claude" / ".mcp.json"
        assert mcp_path.exists()
        mcp = json.loads(mcp_path.read_text())
        assert "memento" in mcp.get("mcpServers", {})

    def test_setup_key_masked_in_output(self, tmp_path):
        """API keys are masked in setup output."""
        runner = CliRunner()

        with patch.object(Path, "home", return_value=tmp_path), \
             patch("memento.cli._find_hook_handler", return_value="/fake/hook-handler.sh"), \
             patch("shutil.which", return_value="/fake/memento-mcp-server"):
            result = runner.invoke(main, ["setup"], input="1\nsk-test-key-1234\n1\nY\n")

        # Full key should not appear in output
        assert "sk-test-key-1234" not in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_setup.py -v`
Expected: FAIL — no `setup` command

- [ ] **Step 3: Implement `setup` command in cli.py**

Add the `setup` command to `src/memento/cli.py`. Place it after the existing `init` command (around line 97):

```python
# Provider presets used by setup wizard
_PROVIDER_PRESETS = {
    "zhipu": {
        "embedding_model": "embedding-3",
        "llm_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "llm_model": "glm-4-flash-250414",
    },
    "openai": {
        "embedding_model": "text-embedding-3-small",
        "llm_base_url": "https://api.openai.com/v1",
        "llm_model": "gpt-4o-mini",
    },
}


@main.command()
@click.option("--yes", "-y", is_flag=True, help="非交互模式，跳过确认提示")
@click.option("--embedding-provider", type=click.Choice(["zhipu", "openai"]), default=None)
@click.option("--embedding-api-key", default=None)
@click.option("--llm-provider", type=click.Choice(["zhipu", "openai"]), default=None)
@click.option("--llm-api-key", default=None)
@click.option("--llm-base-url", default=None, help="OpenAI 兼容 LLM 的 base URL")
@click.option("--llm-model", default=None, help="LLM 模型名称")
def setup(yes, embedding_provider, embedding_api_key, llm_provider, llm_api_key, llm_base_url, llm_model):
    """交互式安装向导：初始化数据库、配置提供商、安装 Claude Code 集成。"""
    import shutil
    from memento.config import save_config, mask_key

    home = Path.home()
    config = {"database": {}, "embedding": {}, "llm": {}}

    click.echo("\n═══ Memento Setup ═══\n")

    # [1/4] 初始化数据库
    click.echo("[1/4] 初始化数据库")
    db_path = home / ".memento" / "default.db"
    config["database"]["path"] = str(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    from memento.db import get_connection, init_db
    conn = get_connection(db_path)
    init_db(conn)
    conn.close()
    os.chmod(db_path, 0o600)
    click.echo(f"  数据库路径: {db_path}")
    click.echo("  ✓ 数据库已创建\n")

    # [2/4] 配置 Embedding
    click.echo("[2/4] 配置 Embedding 提供商")
    if yes:
        emb_prov = embedding_provider
        emb_key = embedding_api_key
    else:
        click.echo("  用于记忆的语义搜索，选择一个提供商:")
        click.echo("    1. 智谱 GLM (推荐，国内访问快)")
        click.echo("    2. OpenAI")
        click.echo("    3. 跳过")
        choice = click.prompt("  请选择", default="1", type=str)
        if choice == "1":
            emb_prov = "zhipu"
        elif choice == "2":
            emb_prov = "openai"
        else:
            emb_prov = None

        if emb_prov:
            emb_key = click.prompt("  请输入 API Key", hide_input=True)
        else:
            emb_key = None
            click.echo("\n  ⚠ 未配置 Embedding，memento 将使用 FTS5 全文搜索:")
            click.echo("    - 语义搜索不可用（只能精确/模糊匹配，无法理解语义相似性）")
            click.echo("    - 记忆召回质量显著下降")
            click.echo("  稍后可编辑 ~/.memento/config.json 补充配置。")
            if not click.confirm("  继续？", default=False):
                click.echo("  安装中断。")
                raise SystemExit(1)

    if emb_prov and emb_key:
        preset = _PROVIDER_PRESETS.get(emb_prov, {})
        config["embedding"] = {
            "provider": emb_prov,
            "api_key": emb_key,
            "model": preset.get("embedding_model"),
        }
        if not yes:
            # Verify connectivity
            click.echo("  验证连接中...", nl=False)
            try:
                from memento.embedding import get_embedding
                # Temporarily set env so provider can find the key
                legacy_var = {"zhipu": "ZHIPU_API_KEY", "openai": "OPENAI_API_KEY"}[emb_prov]
                old_val = os.environ.get(legacy_var)
                os.environ[legacy_var] = emb_key
                try:
                    blob, dim, pending = get_embedding("memento setup verification")
                finally:
                    if old_val is None:
                        os.environ.pop(legacy_var, None)
                    else:
                        os.environ[legacy_var] = old_val
                if blob and not pending:
                    click.echo(" ✓ 连接成功")
                else:
                    click.echo(" ⚠ 返回空结果，请检查 API Key")
            except Exception as e:
                click.echo(f" ✗ 连接失败: {e}")
                if not click.confirm("  是否仍然使用此配置？", default=True):
                    config["embedding"] = {}
        click.echo(f"  ✓ Embedding 已配置 ({emb_prov})\n")

    # [3/4] 配置 LLM
    click.echo("[3/4] 配置 LLM 提供商")
    if yes:
        l_prov = llm_provider
        l_key = llm_api_key
        l_base = llm_base_url
        l_model = llm_model
    else:
        click.echo("  用于 epoch 记忆整合，选择一个提供商:")
        click.echo("    1. 智谱 GLM (推荐)")
        click.echo("    2. OpenAI 兼容 (自定义 base_url)")
        click.echo("    3. 跳过")
        choice = click.prompt("  请选择", default="1", type=str)
        if choice == "1":
            l_prov = "zhipu"
        elif choice == "2":
            l_prov = "openai_compat"
        else:
            l_prov = None

        l_key = None
        l_base = None
        l_model = None
        if l_prov:
            # Check if we can reuse embedding key
            if emb_prov and l_prov == emb_prov and emb_key:
                if click.confirm(f"  API Key 与 Embedding 相同，是否复用？", default=True):
                    l_key = emb_key
            if not l_key:
                l_key = click.prompt("  请输入 API Key", hide_input=True)
            if l_prov == "openai_compat":
                l_base = click.prompt("  请输入 base_url", default="https://api.openai.com/v1")
                l_model = click.prompt("  请输入模型名称", default="gpt-4o-mini")
        else:
            click.echo("\n  ⚠ 未配置 LLM，epoch 整合将使用 light 模式:")
            click.echo("    - 无法进行语义合并和冲突消解")
            click.echo("    - 记忆碎片会持续累积，认知债务无法清理")
            click.echo("    - 长期使用后搜索噪音增大")
            click.echo("  稍后可编辑 ~/.memento/config.json 补充配置。")
            if not click.confirm("  继续？", default=False):
                click.echo("  安装中断。")
                raise SystemExit(1)

    if l_prov and l_key:
        actual_prov = l_prov if l_prov != "openai_compat" else "openai"
        preset = _PROVIDER_PRESETS.get(actual_prov, {})
        config["llm"] = {
            "provider": actual_prov,
            "base_url": l_base or preset.get("llm_base_url"),
            "api_key": l_key,
            "model": l_model or preset.get("llm_model"),
            "timeout": 30,
            "max_retries": 3,
            "temperature": 0,
        }
        click.echo(f"  ✓ LLM 已配置 ({actual_prov})\n")

    # [4/4] Claude Code 集成
    click.echo("[4/4] 安装 Claude Code 集成")
    hook_handler = _find_hook_handler()
    if not hook_handler:
        click.echo("  ⚠ 找不到 hook-handler.sh，跳过 Claude Code 集成")
    else:
        claude_dir = home / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)

        # Write hooks to settings.json
        settings_path = claude_dir / "settings.json"
        settings = {}
        if settings_path.exists():
            try:
                settings = json.loads(settings_path.read_text())
            except json.JSONDecodeError:
                settings = {}

        _inject_hooks(settings, str(hook_handler))
        settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False))
        click.echo(f"  安装 hooks 到 {settings_path}... ✓")

        # Write MCP to .mcp.json (global)
        mcp_path = claude_dir / ".mcp.json"
        mcp_config = {}
        if mcp_path.exists():
            try:
                mcp_config = json.loads(mcp_path.read_text())
            except json.JSONDecodeError:
                mcp_config = {}

        mcp_cmd = shutil.which("memento-mcp-server")
        if not mcp_cmd:
            import sys
            mcp_server_path = Path(__file__).parent / "mcp_server.py"
            mcp_cmd = f"{sys.executable} {mcp_server_path}"

        servers = mcp_config.setdefault("mcpServers", {})
        servers["memento"] = {"type": "stdio", "command": mcp_cmd, "args": []}
        mcp_path.write_text(json.dumps(mcp_config, indent=2, ensure_ascii=False))
        click.echo(f"  配置 MCP server 到 {mcp_path}... ✓")

        # Check for project-level hooks that might conflict
        project_settings = Path.cwd() / ".claude" / "settings.json"
        if project_settings.exists():
            try:
                ps = json.loads(project_settings.read_text())
                for hook_list in ps.get("hooks", {}).values():
                    if any("hook-handler.sh" in h.get("command", "") for h in hook_list if isinstance(h, dict)):
                        click.echo("\n  ⚠ 检测到项目级 .claude/settings.json 中已有 memento hooks")
                        click.echo("    全局 hooks 已安装，项目级 hooks 可能导致重复执行")
                        click.echo("    建议从项目级 settings.json 中移除 memento hooks")
                        break
            except (json.JSONDecodeError, OSError):
                pass

    # Save config
    config_path = save_config(config)

    click.echo(f"\n═══ Setup 完成 ═══")
    click.echo(f"  配置文件: {config_path}")
    click.echo(f"  数据库:   {config['database']['path']}")
    click.echo(f"  如需修改配置，直接编辑 {config_path}")
    click.echo(f"  运行 memento doctor 检查配置状态")
```

Also add an `_inject_hooks` helper (extracted from existing `_install_claude`):

```python
def _inject_hooks(settings: dict, hook_handler_path: str):
    """Inject memento hooks into settings dict (mutates in place)."""
    hooks = settings.setdefault("hooks", {})
    hook_defs = [
        ("SessionStart", "session-start", 10),
        ("PostToolUse", "observe", 5),
        ("Stop", "flush-and-epoch", 15),
        ("SessionEnd", "session-end", 15),
    ]
    for event, cmd, timeout in hook_defs:
        event_hooks = hooks.setdefault(event, [])
        # Skip if already present
        if any("hook-handler.sh" in h.get("command", "") for h in event_hooks if isinstance(h, dict)):
            continue
        event_hooks.append({
            "type": "command",
            "command": f"{hook_handler_path} {cmd}",
            "timeout": timeout * 1000,
        })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_setup.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/cli.py tests/test_setup.py
git commit -m "feat: add memento setup interactive wizard"
```

---

### Task 7: `memento doctor` Command

**Files:**
- Modify: `src/memento/cli.py` (add `doctor` command)
- Modify: `tests/test_setup.py` (add doctor tests)

- [ ] **Step 1: Write failing tests for doctor**

Add to `tests/test_setup.py`:

```python
class TestDoctorCommand:
    """Test memento doctor command."""

    def test_doctor_reports_config_status(self, tmp_path):
        """doctor shows config file status."""
        runner = CliRunner()
        memento_dir = tmp_path / ".memento"
        memento_dir.mkdir()
        (memento_dir / "config.json").write_text(json.dumps({
            "database": {"path": str(tmp_path / "test.db")},
            "embedding": {"provider": "zhipu", "api_key": "sk-test1234"},
            "llm": {"provider": "zhipu", "api_key": "sk-llm1234", "model": "glm-4"}
        }))

        with patch.object(Path, "home", return_value=tmp_path):
            result = runner.invoke(main, ["doctor"])

        assert result.exit_code == 0
        assert "config.json" in result.output
        assert "zhipu" in result.output
        # Key should be masked
        assert "sk-test1234" not in result.output
        assert "sk-llm1234" not in result.output

    def test_doctor_no_config(self, tmp_path):
        """doctor handles missing config.json gracefully."""
        runner = CliRunner()

        with patch.object(Path, "home", return_value=tmp_path):
            result = runner.invoke(main, ["doctor"])

        assert result.exit_code == 0
        assert "未找到" in result.output or "✗" in result.output

    def test_doctor_ping_flag(self, tmp_path):
        """doctor --ping attempts connectivity check."""
        runner = CliRunner()
        memento_dir = tmp_path / ".memento"
        memento_dir.mkdir()
        (memento_dir / "config.json").write_text(json.dumps({
            "embedding": {"provider": "zhipu", "api_key": "sk-test1234"}
        }))

        with patch.object(Path, "home", return_value=tmp_path), \
             patch("memento.embedding.get_embedding") as mock_emb:
            mock_emb.return_value = (b"\x00" * 16, 4, False)
            result = runner.invoke(main, ["doctor", "--ping"])

        assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_setup.py::TestDoctorCommand -v`
Expected: FAIL — no `doctor` command

- [ ] **Step 3: Implement doctor command in cli.py**

```python
@main.command()
@click.option("--ping", is_flag=True, help="主动验证外部服务连通性（会发真实请求）")
def doctor(ping):
    """检查 Memento 配置状态。"""
    from memento.config import get_config, mask_key, CONFIG_PATH

    home = Path.home()
    errors = 0
    warnings = 0

    click.echo("\n═══ Memento Doctor ═══\n")

    # Config file
    config_path = home / ".memento" / "config.json"
    if config_path.exists():
        click.echo(f"  配置文件     {config_path:<40s} ✓ 存在")
    else:
        click.echo(f"  配置文件     {str(config_path):<40s} ✗ 未找到")
        warnings += 1

    cfg = get_config()

    # Database
    db_path = Path(cfg["database"]["path"])
    if db_path.exists():
        try:
            mode = stat.S_IMODE(os.stat(db_path).st_mode)
            perm_str = f"(权限 {oct(mode)})" if mode == 0o600 else f"(权限 {oct(mode)}, 建议 0600)"
            click.echo(f"  数据库       {str(db_path):<40s} ✓ 可读写 {perm_str}")
        except OSError:
            click.echo(f"  数据库       {str(db_path):<40s} ✗ 无法访问")
            errors += 1
    else:
        click.echo(f"  数据库       {str(db_path):<40s} ✗ 不存在")
        errors += 1

    # Embedding
    emb = cfg.get("embedding", {})
    emb_prov = emb.get("provider")
    emb_model = emb.get("model", "")
    if emb_prov and emb.get("api_key"):
        label = f"{emb_prov} ({emb_model})" if emb_model else emb_prov
        if ping:
            try:
                import time
                import signal
                def _timeout_handler(signum, frame):
                    raise TimeoutError("ping timeout")
                old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(5)  # 5 second timeout per spec
                t0 = time.time()
                from memento.embedding import get_embedding
                blob, dim, pending = get_embedding("memento doctor ping test")
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
                elapsed = int((time.time() - t0) * 1000)
                if blob and not pending:
                    click.echo(f"  Embedding    {label:<40s} ✓ 连接正常 (响应 {elapsed}ms)")
                else:
                    click.echo(f"  Embedding    {label:<40s} ⚠ 返回空结果")
                    warnings += 1
            except Exception as e:
                click.echo(f"  Embedding    {label:<40s} ⚠ 连接失败: {e}")
                warnings += 1
        else:
            click.echo(f"  Embedding    {label:<40s} ✓ 已配置")
    else:
        click.echo(f"  Embedding    {'(无)':<40s} ⚠ 未配置 (将使用 FTS5)")
        warnings += 1

    # LLM
    llm = cfg.get("llm", {})
    llm_prov = llm.get("provider")
    llm_model = llm.get("model", "")
    if llm_prov and llm.get("api_key"):
        label = f"{llm_prov} ({llm_model})" if llm_model else llm_prov
        if ping:
            try:
                import time
                from memento.llm import LLMClient
                t0 = time.time()
                client = LLMClient.from_config()
                if client:
                    client.generate("ping")
                    elapsed = int((time.time() - t0) * 1000)
                    click.echo(f"  LLM          {label:<40s} ✓ 连接正常 (响应 {elapsed}ms)")
                else:
                    click.echo(f"  LLM          {label:<40s} ⚠ 配置不完整")
                    warnings += 1
            except Exception as e:
                click.echo(f"  LLM          {label:<40s} ⚠ 连接失败: {e}")
                warnings += 1
        else:
            click.echo(f"  LLM          {label:<40s} ✓ 已配置")
    else:
        click.echo(f"  LLM          {'(无)':<40s} ⚠ 未配置 (epoch 将用 light 模式)")
        warnings += 1

    # Hooks
    settings_path = home / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
            hooks = settings.get("hooks", {})
            expected = ["SessionStart", "PostToolUse", "Stop", "SessionEnd"]
            found = sum(1 for e in expected if any(
                "hook-handler.sh" in h.get("command", "")
                for h in hooks.get(e, []) if isinstance(h, dict)
            ))
            click.echo(f"  Hooks        {str(settings_path):<40s} ✓ {found}/{len(expected)} 已安装")
            if found < len(expected):
                warnings += 1
        except (json.JSONDecodeError, OSError):
            click.echo(f"  Hooks        {str(settings_path):<40s} ✗ 文件损坏")
            errors += 1
    else:
        click.echo(f"  Hooks        {str(settings_path):<40s} ✗ 未安装")
        errors += 1

    # MCP
    mcp_path = home / ".claude" / ".mcp.json"
    if mcp_path.exists():
        try:
            mcp = json.loads(mcp_path.read_text())
            if "memento" in mcp.get("mcpServers", {}):
                click.echo(f"  MCP Server   {str(mcp_path):<40s} ✓ 已配置")
            else:
                click.echo(f"  MCP Server   {str(mcp_path):<40s} ✗ memento 未注册")
                errors += 1
        except (json.JSONDecodeError, OSError):
            click.echo(f"  MCP Server   {str(mcp_path):<40s} ✗ 文件损坏")
            errors += 1
    else:
        click.echo(f"  MCP Server   {str(mcp_path):<40s} ✗ 未配置")
        errors += 1

    # Worker
    import hashlib
    db_abs = os.path.abspath(cfg["database"]["path"])
    sock_hash = hashlib.md5(db_abs.encode()).hexdigest()[:12]
    sock_path = f"/tmp/memento-worker-{sock_hash}.sock"
    if os.path.exists(sock_path):
        click.echo(f"  Worker       {sock_path:<40s} ✓ 运行中")
    else:
        click.echo(f"  Worker       {sock_path:<40s} ✗ 未运行（首次 hook 触发时自动启动）")
        warnings += 1

    click.echo(f"\n═══ {warnings} 个警告，{errors} 个错误 ═══\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_setup.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/cli.py tests/test_setup.py
git commit -m "feat: add memento doctor config check command"
```

---

### Task 8: Deprecate `plugin install claude`

**Files:**
- Modify: `src/memento/cli.py:858-998`

- [ ] **Step 1: Add deprecation warning to `plugin install claude`**

In `src/memento/cli.py`, modify the `_install_claude` function to print a deprecation notice:

```python
def _install_claude(scope, project_dir):
    """安装 Claude Code 集成 (deprecated, use memento setup)."""
    click.echo("⚠ 'memento plugin install claude' 已废弃，请使用 'memento setup' 代替。")
    click.echo("  memento setup 会全局安装 hooks 和 MCP，无需每个项目单独配置。\n")
    # ... rest of existing implementation unchanged ...
```

- [ ] **Step 2: Run existing plugin install tests to verify no regression**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_cli.py -k "plugin" -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add src/memento/cli.py
git commit -m "chore: deprecate plugin install claude in favor of memento setup"
```

---

### Task 9: Update README Documentation

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`

- [ ] **Step 1: Update README.md Quick Start**

Find the Quick Start section (around line 48) and replace the multi-step install instructions with:

```markdown
### Quick Start

```bash
pip install git+ssh://git@github.com:winteriscome/memento.git
memento setup
```

`memento setup` will guide you through:
1. Database initialization
2. Embedding provider selection (Zhipu GLM / OpenAI)
3. LLM provider selection (for epoch consolidation)
4. Claude Code hooks & MCP global installation

After setup, verify with `memento doctor`.
```

Find the CLI reference section (around line 179) and add `setup` and `doctor`, mark `plugin install claude` as deprecated.

- [ ] **Step 2: Update README.zh-CN.md accordingly**

Same changes in Chinese.

- [ ] **Step 3: Commit**

```bash
git add README.md README.zh-CN.md
git commit -m "docs: update README with memento setup as primary install method"
```

---

### Task 10: Integration Test — Full Setup Flow

**Files:**
- Modify: `tests/test_setup.py` (add integration test)

- [ ] **Step 1: Write end-to-end integration test**

Add to `tests/test_setup.py`:

```python
class TestSetupIntegration:
    """End-to-end integration tests for setup + doctor flow."""

    def test_setup_then_doctor(self, tmp_path):
        """Full flow: setup creates config, doctor reads it correctly."""
        runner = CliRunner()

        with patch.object(Path, "home", return_value=tmp_path), \
             patch("memento.cli._find_hook_handler", return_value="/fake/hook-handler.sh"), \
             patch("shutil.which", return_value="/fake/memento-mcp-server"):
            # Run setup
            setup_result = runner.invoke(main, ["setup"], input="1\nsk-test-key-1234\n1\nY\n")
            assert setup_result.exit_code == 0

            # Run doctor
            doctor_result = runner.invoke(main, ["doctor"])
            assert doctor_result.exit_code == 0
            assert "✓" in doctor_result.output
            assert "zhipu" in doctor_result.output
            # Key masked
            assert "sk-test-key-1234" not in doctor_result.output

    def test_setup_idempotent(self, tmp_path):
        """Running setup twice doesn't duplicate hooks."""
        runner = CliRunner()

        with patch.object(Path, "home", return_value=tmp_path), \
             patch("memento.cli._find_hook_handler", return_value="/fake/hook-handler.sh"), \
             patch("shutil.which", return_value="/fake/memento-mcp-server"):
            # Run setup twice
            runner.invoke(main, ["setup"], input="1\nsk-key-1234\n1\nY\n")
            runner.invoke(main, ["setup"], input="1\nsk-key-5678\n1\nY\n")

        settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        for event_hooks in settings.get("hooks", {}).values():
            memento_hooks = [h for h in event_hooks if isinstance(h, dict) and "hook-handler.sh" in h.get("command", "")]
            assert len(memento_hooks) <= 1, f"Duplicate hooks found: {memento_hooks}"

    def test_config_priority_e2e(self, tmp_path):
        """Verify four-layer priority works end-to-end via LLMClient."""
        memento_dir = tmp_path / ".memento"
        memento_dir.mkdir()
        (memento_dir / "config.json").write_text(json.dumps({
            "llm": {
                "provider": "zhipu",
                "base_url": "https://api.config.com/v1",
                "api_key": "sk-config",
                "model": "glm-4"
            }
        }))

        with patch.object(Path, "home", return_value=tmp_path):
            # Layer 1: config.json
            with patch.dict(os.environ, {}, clear=True):
                client = LLMClient.from_config()
                assert client.api_key == "sk-config"

            # Layer 0: MEMENTO_* env overrides
            with patch.dict(os.environ, {"MEMENTO_LLM_API_KEY": "sk-env"}, clear=True):
                client = LLMClient.from_config()
                assert client.api_key == "sk-env"
```

- [ ] **Step 2: Run all tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_setup.py tests/test_config.py tests/test_llm.py tests/test_embedding.py -v`
Expected: All PASS

- [ ] **Step 3: Run full test suite for regressions**

Run: `cd /Users/maizi/data/work/memento && python -m pytest --tb=short -q`
Expected: All PASS, no regressions

- [ ] **Step 4: Commit**

```bash
git add tests/test_setup.py
git commit -m "test: add integration tests for setup + doctor + config priority"
```
