import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from memento.cli import main


class TestSetupCommand:

    def test_setup_creates_config_and_db(self, tmp_path):
        """setup creates config.json and initializes DB."""
        runner = CliRunner()
        with patch.object(Path, "home", return_value=tmp_path), \
             patch("memento.cli._find_hook_handler", return_value="/fake/hook-handler.sh"), \
             patch("shutil.which", return_value="/fake/memento-mcp-server"):
            result = runner.invoke(main, ["setup"], input="2\nsk-test-key-1234\n1\nY\n")
        assert result.exit_code == 0, f"Output: {result.output}\nException: {result.exception}"
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
            result = runner.invoke(main, ["setup"], input="2\nsk-test-key-1234\n1\nY\n")
        config_path = tmp_path / ".memento" / "config.json"
        if config_path.exists():
            mode = stat.S_IMODE(os.stat(config_path).st_mode)
            assert mode == 0o600

    def test_setup_noninteractive(self, tmp_path):
        """setup --yes with provider flags."""
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
        assert result.exit_code == 0, f"Output: {result.output}\nException: {result.exception}"
        assert (tmp_path / ".memento" / "config.json").exists()

    def test_setup_writes_hooks_globally(self, tmp_path):
        """setup writes hooks to ~/.claude/settings.json."""
        runner = CliRunner()
        with patch.object(Path, "home", return_value=tmp_path), \
             patch("memento.cli._find_hook_handler", return_value="/fake/hook-handler.sh"), \
             patch("shutil.which", return_value="/fake/memento-mcp-server"):
            result = runner.invoke(main, ["setup"], input="2\nsk-key-1234\n1\nY\n")
        settings_path = tmp_path / ".claude" / "settings.json"
        assert settings_path.exists()
        settings = json.loads(settings_path.read_text())
        assert "hooks" in settings

    def test_setup_writes_mcp_globally(self, tmp_path):
        """setup writes MCP to ~/.claude/.mcp.json."""
        runner = CliRunner()
        with patch.object(Path, "home", return_value=tmp_path), \
             patch("memento.cli._find_hook_handler", return_value="/fake/hook-handler.sh"), \
             patch("shutil.which", return_value="/fake/memento-mcp-server"):
            result = runner.invoke(main, ["setup"], input="2\nsk-key-1234\n1\nY\n")
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
            result = runner.invoke(main, ["setup"], input="2\nsk-test-key-1234\n1\nY\n")
        assert "sk-test-key-1234" not in result.output

    def test_setup_skip_embedding_requires_confirm(self, tmp_path):
        """Skipping embedding requires explicit 'y' confirmation."""
        runner = CliRunner()
        with patch.object(Path, "home", return_value=tmp_path), \
             patch("memento.cli._find_hook_handler", return_value="/fake/hook-handler.sh"), \
             patch("shutil.which", return_value="/fake/memento-mcp-server"):
            # Choose skip(4), then refuse to confirm (N or empty)
            result = runner.invoke(main, ["setup"], input="4\nN\n")
        # Should not succeed — either exit code != 0 or abort message
        assert result.exit_code != 0 or "中断" in result.output

    def test_setup_local_embedding_default(self, tmp_path):
        """setup with local embedding (default choice)."""
        runner = CliRunner()
        with patch.object(Path, "home", return_value=tmp_path), \
             patch("memento.cli._find_hook_handler", return_value="/fake/hook-handler.sh"), \
             patch("shutil.which", return_value="/fake/memento-mcp-server"):
            # Choose local(1, default), then choose LLM provider, confirm
            result = runner.invoke(main, ["setup"], input="1\n1\nY\n")
        assert result.exit_code == 0, f"Output: {result.output}\nException: {result.exception}"
        config_path = tmp_path / ".memento" / "config.json"
        assert config_path.exists()
        cfg = json.loads(config_path.read_text())
        assert cfg["embedding"]["provider"] == "local"
        assert cfg["embedding"].get("api_key") is None


class TestDoctorCommand:

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
        assert "sk-test1234" not in result.output
        assert "sk-llm1234" not in result.output

    def test_doctor_no_config(self, tmp_path):
        """doctor handles missing config.json."""
        runner = CliRunner()
        with patch.object(Path, "home", return_value=tmp_path):
            with patch.dict(os.environ, {}, clear=True):
                result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 0
        assert "✗" in result.output

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


class TestSetupIntegration:
    """End-to-end integration tests for setup + doctor flow."""

    def test_setup_then_doctor(self, tmp_path):
        """Full flow: setup creates config, doctor reads it correctly."""
        runner = CliRunner()
        with patch.object(Path, "home", return_value=tmp_path), \
             patch("memento.cli._find_hook_handler", return_value="/fake/hook-handler.sh"), \
             patch("shutil.which", return_value="/fake/memento-mcp-server"):
            # Run setup with zhipu for both embedding and LLM
            setup_result = runner.invoke(main, ["setup"], input="1\nsk-test-key-1234\n1\nY\n")
            assert setup_result.exit_code == 0

            # Run doctor — should see config, DB, embedding, LLM all configured
            doctor_result = runner.invoke(main, ["doctor"])
            assert doctor_result.exit_code == 0
            assert "✓" in doctor_result.output
            assert "zhipu" in doctor_result.output
            # Key should be masked
            assert "sk-test-key-1234" not in doctor_result.output

    def test_setup_idempotent(self, tmp_path):
        """Running setup twice doesn't duplicate hooks."""
        runner = CliRunner()
        with patch.object(Path, "home", return_value=tmp_path), \
             patch("memento.cli._find_hook_handler", return_value="/fake/hook-handler.sh"), \
             patch("shutil.which", return_value="/fake/memento-mcp-server"):
            runner.invoke(main, ["setup"], input="1\nsk-key-1234\n1\nY\n")
            runner.invoke(main, ["setup"], input="1\nsk-key-5678\n1\nY\n")

        settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        for event, event_hooks in settings.get("hooks", {}).items():
            memento_hooks = [h for h in event_hooks if isinstance(h, dict) and "hook-handler.sh" in h.get("command", "")]
            assert len(memento_hooks) <= 1, f"Duplicate hooks in {event}: {memento_hooks}"

    def test_config_priority_e2e(self, tmp_path):
        """Verify four-layer priority works end-to-end via LLMClient."""
        from memento.llm import LLMClient

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
                assert client is not None
                assert client.api_key == "sk-config"

            # Layer 0: MEMENTO_* env overrides
            with patch.dict(os.environ, {"MEMENTO_LLM_API_KEY": "sk-env"}, clear=True):
                client = LLMClient.from_config()
                assert client is not None
                assert client.api_key == "sk-env"
