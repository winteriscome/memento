"""tests/test_config.py — Unified Config Module tests (TDD)."""

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Env isolation: strip all config-relevant env vars for every test
# ---------------------------------------------------------------------------

# All env vars that config.py reads — must be cleaned to avoid host pollution.
_CONFIG_ENV_VARS = [
    "MEMENTO_DB",
    "MEMENTO_EMBEDDING_PROVIDER",
    "MEMENTO_EMBEDDING_API_KEY",
    "MEMENTO_LLM_PROVIDER",
    "MEMENTO_LLM_BASE_URL",
    "MEMENTO_LLM_API_KEY",
    "MEMENTO_LLM_MODEL",
    "MEMENTO_LLM_TIMEOUT",
    "MEMENTO_LLM_MAX_RETRIES",
    "MEMENTO_LLM_TEMPERATURE",
    "ZHIPU_API_KEY",
    "GLM_API_KEY",
    "MINIMAX_API_KEY",
    "MOONSHOT_API_KEY",
    "KIMI_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove all config-related env vars so tests are hermetic."""
    for var in _CONFIG_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_config(tmp_path: Path, cfg: dict) -> Path:
    """Write a config.json under tmp_path/.memento/ and return the file path."""
    memento_dir = tmp_path / ".memento"
    memento_dir.mkdir(parents=True, exist_ok=True)
    config_file = memento_dir / "config.json"
    config_file.write_text(json.dumps(cfg), encoding="utf-8")
    return config_file


# ---------------------------------------------------------------------------
# get_config — defaults
# ---------------------------------------------------------------------------

class TestGetConfigDefaults:
    """get_config() returns sane defaults when no config.json and no env vars."""

    def test_returns_dict_with_required_keys(self, tmp_path):
        with patch.object(Path, "home", return_value=tmp_path):
            from memento.config import get_config
            cfg = get_config()

        assert isinstance(cfg, dict)
        for key in ("database", "embedding", "llm"):
            assert key in cfg

    def test_default_database_path(self, tmp_path):
        with patch.object(Path, "home", return_value=tmp_path):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["database"]["path"] == str(tmp_path / ".memento" / "default.db")

    def test_default_embedding_provider(self, tmp_path):
        with patch.object(Path, "home", return_value=tmp_path):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["embedding"]["provider"] == "local"

    def test_default_llm_values(self, tmp_path):
        with patch.object(Path, "home", return_value=tmp_path):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["llm"]["timeout"] == 30
        assert cfg["llm"]["max_retries"] == 3
        assert cfg["llm"]["temperature"] == 0


# ---------------------------------------------------------------------------
# get_config — reads config.json
# ---------------------------------------------------------------------------

class TestGetConfigFromFile:
    """get_config() reads values from ~/.memento/config.json."""

    def test_reads_database_path(self, tmp_path):
        _write_config(tmp_path, {"database": {"path": "/custom/db.sqlite"}})
        with patch.object(Path, "home", return_value=tmp_path):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["database"]["path"] == "/custom/db.sqlite"

    def test_reads_embedding_provider(self, tmp_path):
        _write_config(tmp_path, {"embedding": {"provider": "openai", "api_key": "sk-test"}})
        with patch.object(Path, "home", return_value=tmp_path):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["embedding"]["provider"] == "openai"
        assert cfg["embedding"]["api_key"] == "sk-test"

    def test_reads_llm_settings(self, tmp_path):
        _write_config(tmp_path, {"llm": {"model": "gpt-4", "timeout": 60}})
        with patch.object(Path, "home", return_value=tmp_path):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["llm"]["model"] == "gpt-4"
        assert cfg["llm"]["timeout"] == 60


# ---------------------------------------------------------------------------
# get_config — MEMENTO_* env overrides config.json
# ---------------------------------------------------------------------------

class TestMementoEnvOverrides:
    """MEMENTO_* env vars override config.json values."""

    def test_memento_db_overrides_config(self, tmp_path):
        _write_config(tmp_path, {"database": {"path": "/from/config.db"}})
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"MEMENTO_DB": "/from/env.db"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["database"]["path"] == "/from/env.db"

    def test_memento_embedding_provider_overrides(self, tmp_path):
        _write_config(tmp_path, {"embedding": {"provider": "zhipu"}})
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"MEMENTO_EMBEDDING_PROVIDER": "openai"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["embedding"]["provider"] == "openai"

    def test_memento_llm_timeout_cast_to_int(self, tmp_path):
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"MEMENTO_LLM_TIMEOUT": "120"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["llm"]["timeout"] == 120
        assert isinstance(cfg["llm"]["timeout"], int)

    def test_memento_llm_temperature_cast_to_float(self, tmp_path):
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"MEMENTO_LLM_TEMPERATURE": "0.7"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["llm"]["temperature"] == 0.7
        assert isinstance(cfg["llm"]["temperature"], float)

    def test_memento_llm_max_retries_cast_to_int(self, tmp_path):
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"MEMENTO_LLM_MAX_RETRIES": "5"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["llm"]["max_retries"] == 5
        assert isinstance(cfg["llm"]["max_retries"], int)

    def test_memento_embedding_api_key_overrides(self, tmp_path):
        _write_config(tmp_path, {"embedding": {"api_key": "from-config"}})
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"MEMENTO_EMBEDDING_API_KEY": "from-env"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["embedding"]["api_key"] == "from-env"

    def test_memento_llm_provider_overrides(self, tmp_path):
        _write_config(tmp_path, {"llm": {"provider": "zhipu"}})
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"MEMENTO_LLM_PROVIDER": "openai"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["llm"]["provider"] == "openai"

    def test_memento_llm_base_url_overrides(self, tmp_path):
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"MEMENTO_LLM_BASE_URL": "https://custom.api"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["llm"]["base_url"] == "https://custom.api"

    def test_memento_llm_api_key_overrides(self, tmp_path):
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"MEMENTO_LLM_API_KEY": "sk-llm-env"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["llm"]["api_key"] == "sk-llm-env"

    def test_memento_llm_model_overrides(self, tmp_path):
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"MEMENTO_LLM_MODEL": "claude-3"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["llm"]["model"] == "claude-3"


# ---------------------------------------------------------------------------
# get_config — Legacy env vars
# ---------------------------------------------------------------------------

class TestLegacyEnvVars:
    """Legacy env vars (ZHIPU_API_KEY etc.) work when no config.json."""

    def test_zhipu_api_key(self, tmp_path):
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"ZHIPU_API_KEY": "sk-zhipu"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["embedding"]["provider"] == "zhipu"
        assert cfg["embedding"]["api_key"] == "sk-zhipu"

    def test_glm_api_key(self, tmp_path):
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"GLM_API_KEY": "sk-glm"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["embedding"]["provider"] == "zhipu"
        assert cfg["embedding"]["api_key"] == "sk-glm"

    def test_minimax_api_key(self, tmp_path):
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"MINIMAX_API_KEY": "sk-mini"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["embedding"]["provider"] == "minimax"
        assert cfg["embedding"]["api_key"] == "sk-mini"

    def test_moonshot_api_key(self, tmp_path):
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"MOONSHOT_API_KEY": "sk-moon"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["embedding"]["provider"] == "moonshot"
        assert cfg["embedding"]["api_key"] == "sk-moon"

    def test_kimi_api_key(self, tmp_path):
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"KIMI_API_KEY": "sk-kimi"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["embedding"]["provider"] == "moonshot"
        assert cfg["embedding"]["api_key"] == "sk-kimi"

    def test_openai_api_key(self, tmp_path):
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"OPENAI_API_KEY": "sk-oai"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["embedding"]["provider"] == "openai"
        assert cfg["embedding"]["api_key"] == "sk-oai"

    def test_gemini_api_key(self, tmp_path):
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"GEMINI_API_KEY": "sk-gem"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["embedding"]["provider"] == "gemini"
        assert cfg["embedding"]["api_key"] == "sk-gem"

    def test_config_json_overrides_legacy_env(self, tmp_path):
        """config.json overrides legacy env vars."""
        _write_config(tmp_path, {"embedding": {"provider": "openai", "api_key": "sk-from-config"}})
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"ZHIPU_API_KEY": "sk-zhipu-legacy"}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["embedding"]["provider"] == "openai"
        assert cfg["embedding"]["api_key"] == "sk-from-config"

    def test_legacy_priority_order(self, tmp_path):
        """ZHIPU_API_KEY takes priority over MINIMAX_API_KEY (scan order)."""
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {
                "ZHIPU_API_KEY": "sk-zhipu",
                "MINIMAX_API_KEY": "sk-mini",
            }, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert cfg["embedding"]["provider"] == "zhipu"
        assert cfg["embedding"]["api_key"] == "sk-zhipu"


# ---------------------------------------------------------------------------
# get_config — tilde expansion
# ---------------------------------------------------------------------------

class TestTildeExpansion:
    """Tilde expansion in database.path."""

    def test_tilde_expanded_in_config_json(self, tmp_path):
        _write_config(tmp_path, {"database": {"path": "~/.memento/my.db"}})
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {"HOME": str(tmp_path)}, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert "~" not in cfg["database"]["path"]
        assert cfg["database"]["path"] == str(tmp_path / ".memento" / "my.db")

    def test_tilde_expanded_from_env(self, tmp_path):
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(os.environ, {
                "HOME": str(tmp_path),
                "MEMENTO_DB": "~/.memento/env.db",
            }, clear=False),
        ):
            from memento.config import get_config
            cfg = get_config()

        assert "~" not in cfg["database"]["path"]
        assert cfg["database"]["path"] == str(tmp_path / ".memento" / "env.db")


# ---------------------------------------------------------------------------
# get_config — malformed config.json
# ---------------------------------------------------------------------------

class TestMalformedConfig:
    """Malformed config.json falls back gracefully (no crash)."""

    def test_invalid_json(self, tmp_path):
        memento_dir = tmp_path / ".memento"
        memento_dir.mkdir(parents=True)
        (memento_dir / "config.json").write_text("{invalid json!!!", encoding="utf-8")

        with patch.object(Path, "home", return_value=tmp_path):
            from memento.config import get_config
            cfg = get_config()

        # Should still return valid defaults
        assert isinstance(cfg, dict)
        assert "database" in cfg

    def test_non_dict_json(self, tmp_path):
        memento_dir = tmp_path / ".memento"
        memento_dir.mkdir(parents=True)
        (memento_dir / "config.json").write_text('"just a string"', encoding="utf-8")

        with patch.object(Path, "home", return_value=tmp_path):
            from memento.config import get_config
            cfg = get_config()

        assert isinstance(cfg, dict)
        assert "database" in cfg


# ---------------------------------------------------------------------------
# mask_key
# ---------------------------------------------------------------------------

class TestMaskKey:
    """mask_key() masks API keys for display."""

    def test_normal_key(self):
        from memento.config import mask_key
        result = mask_key("sk-abc123xyz789")
        assert result == "sk-****z789"

    def test_none_key(self):
        from memento.config import mask_key
        assert mask_key(None) == "(未配置)"

    def test_empty_key(self):
        from memento.config import mask_key
        assert mask_key("") == "(未配置)"

    def test_short_key_fully_masked(self):
        from memento.config import mask_key
        assert mask_key("abc") == "****"

    def test_exactly_seven_chars(self):
        from memento.config import mask_key
        # 7 chars: first 3 + **** + last 4 = 11 chars — but key only 7 chars
        # Key length <= 7 should be fully masked
        assert mask_key("abcdefg") == "****"

    def test_eight_chars(self):
        from memento.config import mask_key
        # 8 chars: should show first 3 + **** + last 4
        result = mask_key("abcdefgh")
        assert result == "abc****efgh"


# ---------------------------------------------------------------------------
# save_config
# ---------------------------------------------------------------------------

class TestSaveConfig:
    """save_config() writes config to ~/.memento/config.json with 0600 perms."""

    def test_creates_config_file(self, tmp_path):
        with patch.object(Path, "home", return_value=tmp_path):
            from memento.config import save_config
            path = save_config({"database": {"path": "/my/db.sqlite"}})

        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["database"]["path"] == "/my/db.sqlite"

    def test_creates_memento_dir_if_missing(self, tmp_path):
        with patch.object(Path, "home", return_value=tmp_path):
            from memento.config import save_config
            save_config({"llm": {"model": "test"}})

        assert (tmp_path / ".memento").is_dir()

    def test_file_permissions_0600(self, tmp_path):
        with patch.object(Path, "home", return_value=tmp_path):
            from memento.config import save_config
            path = save_config({"embedding": {"provider": "test"}})

        mode = path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_returns_path_object(self, tmp_path):
        with patch.object(Path, "home", return_value=tmp_path):
            from memento.config import save_config
            result = save_config({})

        assert isinstance(result, Path)

    def test_overwrites_existing_config(self, tmp_path):
        with patch.object(Path, "home", return_value=tmp_path):
            from memento.config import save_config
            save_config({"llm": {"model": "old"}})
            save_config({"llm": {"model": "new"}})
            path = tmp_path / ".memento" / "config.json"

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["llm"]["model"] == "new"


# ---------------------------------------------------------------------------
# db.get_db_path reads from unified config
# ---------------------------------------------------------------------------

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
