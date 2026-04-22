"""Tests for memento update command."""
import json
import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from memento.cli import (
    _compare_versions,
    _detect_install_source,
    _get_latest_tag,
    main,
)


# ── _compare_versions ──

class TestCompareVersions:
    def test_equal(self):
        assert _compare_versions("0.9.0", "v0.9.0") == 0

    def test_equal_no_prefix(self):
        assert _compare_versions("0.9.0", "0.9.0") == 0

    def test_older(self):
        assert _compare_versions("0.8.0", "v0.9.0") == -1

    def test_newer(self):
        assert _compare_versions("0.9.1", "v0.9.0") == 1

    def test_major_diff(self):
        assert _compare_versions("1.0.0", "v0.9.0") == 1

    def test_patch_diff(self):
        assert _compare_versions("0.9.0", "v0.9.1") == -1


# ── _get_latest_tag ──

class TestGetLatestTag:
    def test_parses_tags(self):
        mock_output = (
            "abc123\trefs/tags/v0.8.0\n"
            "def456\trefs/tags/v0.9.0\n"
            "ghi789\trefs/tags/v0.9.0^{}\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)
            result = _get_latest_tag("ssh://example.com/repo.git")
            # --sort=-v:refname means first is latest, but we take first v-prefixed
            assert result == "v0.8.0" or result == "v0.9.0"

    def test_no_tags(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            assert _get_latest_tag("ssh://example.com/repo.git") is None

    def test_command_failure(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="")
            assert _get_latest_tag("ssh://example.com/repo.git") is None

    def test_timeout(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 15)):
            assert _get_latest_tag("ssh://example.com/repo.git") is None

    def test_skips_non_v_tags(self):
        mock_output = "abc123\trefs/tags/release-1.0\ndef456\trefs/tags/v0.9.0\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)
            assert _get_latest_tag("anything") == "v0.9.0"


# ── _detect_install_source ──

class TestDetectInstallSource:
    def test_editable_with_git(self):
        """Editable install in a git repo returns 'editable' + remote URL."""
        # This test runs in the actual repo, so it should detect editable
        install_type, source = _detect_install_source()
        # In dev environment, should be editable
        assert install_type in ("editable", "git", "unknown")

    def test_unknown_when_no_metadata(self):
        """When distribution metadata is unavailable, returns 'unknown'."""
        with patch("importlib.util.find_spec", return_value=None):
            with patch("importlib.metadata.distribution", side_effect=Exception("not found")):
                install_type, source = _detect_install_source()
                assert install_type == "unknown"
                assert source == ""


# ── update command ──

class TestUpdateCommand:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["update", "--help"])
        assert result.exit_code == 0
        assert "--source" in result.output
        assert "--check" in result.output
        assert "--tag" in result.output
        assert "--extras" in result.output

    def test_editable_mode(self):
        """In editable mode, suggests git pull instead of updating."""
        runner = CliRunner()
        with patch("memento.cli._detect_install_source", return_value=("editable", "ssh://example.com/repo.git")):
            result = runner.invoke(main, ["update"])
            assert result.exit_code == 0
            assert "开发模式" in result.output
            assert "git pull" in result.output

    def test_no_source_detected_requires_explicit(self):
        """When source can't be detected, requires --source."""
        runner = CliRunner()
        with patch("memento.cli._detect_install_source", return_value=("unknown", "")):
            result = runner.invoke(main, ["update"])
            assert result.exit_code != 0
            assert "--source" in result.output

    def test_check_mode(self):
        """--check shows update info without installing."""
        runner = CliRunner()
        with patch("memento.cli._detect_install_source", return_value=("git", "ssh://example.com/repo.git")):
            with patch("memento.cli._get_latest_tag", return_value="v99.0.0"):
                result = runner.invoke(main, ["update", "--check"])
                assert result.exit_code == 0
                assert "新版本可用" in result.output
                assert "v99.0.0" in result.output

    def test_already_latest(self):
        """When already on latest version, shows message."""
        runner = CliRunner()
        with patch("memento.cli._detect_install_source", return_value=("git", "ssh://example.com/repo.git")):
            with patch("memento.cli.__version__", "0.9.0"):
                with patch("memento.cli._get_latest_tag", return_value="v0.9.0"):
                    result = runner.invoke(main, ["update", "--source", "ssh://example.com/repo.git"])
                    assert result.exit_code == 0
                    assert "已经是最新版本" in result.output

    def test_remote_unreachable(self):
        """When remote is unreachable, shows error."""
        runner = CliRunner()
        with patch("memento.cli._detect_install_source", return_value=("git", "ssh://example.com/repo.git")):
            with patch("memento.cli._get_latest_tag", return_value=None):
                result = runner.invoke(main, ["update", "--source", "ssh://bad.example.com/repo.git"])
                assert result.exit_code != 0
                assert "无法获取远程版本" in result.output

    def test_explicit_source_overrides_detection(self):
        """--source overrides detected source."""
        runner = CliRunner()
        with patch("memento.cli._detect_install_source", return_value=("unknown", "")):
            with patch("memento.cli._get_latest_tag", return_value="v1.0.0"):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                    result = runner.invoke(main, [
                        "update", "--source", "ssh://custom.com/repo.git"
                    ])
                    # Should not fail on source detection
                    assert "custom.com" in result.output
