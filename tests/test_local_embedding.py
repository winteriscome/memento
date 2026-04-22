"""Tests for local-first embedding (v0.9.2 — Feature 2)."""
from unittest.mock import patch
import pytest


class TestLocalProviderInMap:
    """Verify 'local' is in the provider_map."""

    def test_local_in_provider_map(self):
        from memento.embedding import get_embedding
        with patch.dict("os.environ", {}, clear=False):
            with patch("memento.config.get_config", return_value={
                "embedding": {"provider": "local", "api_key": None, "model": None},
                "database": {"path": ":memory:"},
                "llm": {},
            }):
                with patch("memento.embedding._embed_local", return_value=None):
                    blob, dim, pending = get_embedding("test")
                    assert pending is True

    def test_local_provider_returns_embedding(self):
        from memento.embedding import get_embedding
        fake_vec = [0.1] * 384
        with patch("memento.config.get_config", return_value={
            "embedding": {"provider": "local", "api_key": None, "model": None},
            "database": {"path": ":memory:"},
            "llm": {},
        }):
            with patch("memento.embedding._embed_local", return_value=fake_vec):
                blob, dim, pending = get_embedding("test")
                assert pending is False
                assert dim == 384

    def test_local_skips_cloud_scan(self):
        from memento.embedding import get_embedding
        with patch("memento.config.get_config", return_value={
            "embedding": {"provider": "local", "api_key": None, "model": None},
            "database": {"path": ":memory:"},
            "llm": {},
        }):
            with patch("memento.embedding._embed_local", return_value=[0.1] * 384):
                with patch("memento.embedding._embed_zhipu") as mock_zhipu:
                    get_embedding("test")
                    mock_zhipu.assert_not_called()
