import json
import os
from pathlib import Path
from unittest.mock import patch
import pytest
from memento.embedding import (
    _embed_zhipu,
    _embed_minimax,
    _embed_moonshot,
    _embed_openai,
    _call_openai_compatible_api,
    get_embedding
)

@patch("memento.embedding._call_openai_compatible_api")
def test_embed_zhipu_fallback(mock_call):
    mock_call.return_value = [0.1] * 2048
    with patch.dict(os.environ, {"ZHIPU_API_KEY": "fake_zhipu_key"}, clear=True):
        res = _embed_zhipu("test zhipu")
        assert res == [0.1] * 2048
        mock_call.assert_called_once_with(
            "fake_zhipu_key",
            "https://open.bigmodel.cn/api/paas/v4",
            "embedding-3",
            "test zhipu"
        )

@patch("memento.embedding._call_openai_compatible_api")
def test_embed_minimax(mock_call):
    mock_call.return_value = [0.2] * 1536
    with patch.dict(os.environ, {"MINIMAX_API_KEY": "fake_minimax_key"}, clear=True):
        res = _embed_minimax("test minimax")
        assert res == [0.2] * 1536
        mock_call.assert_called_once_with(
            "fake_minimax_key",
            "https://api.minimax.chat/v1",
            "embo-01",
            "test minimax"
        )

@patch("memento.embedding._call_openai_compatible_api")
def test_embed_moonshot(mock_call):
    mock_call.return_value = [0.3] * 768
    with patch.dict(os.environ, {"KIMI_API_KEY": "fake_kimi_key"}, clear=True):
        res = _embed_moonshot("test kimi")
        assert res == [0.3] * 768
        mock_call.assert_called_once_with(
            "fake_kimi_key",
            "https://api.moonshot.cn/v1",
            "moonshot-v1-embedding",
            "test kimi"
        )

@patch("memento.embedding._call_openai_compatible_api")
def test_embed_openai(mock_call):
    mock_call.return_value = [0.4] * 1536
    with patch.dict(os.environ, {"OPENAI_API_KEY": "fake_openai_key"}, clear=True):
        res = _embed_openai("test openai")
        assert res == [0.4] * 1536
        mock_call.assert_called_once_with(
            "fake_openai_key",
            "https://api.openai.com/v1",
            "text-embedding-3-small",
            "test openai"
        )

@patch("memento.embedding.urllib.request.urlopen")
def test_call_openai_compatible_api(mock_urlopen):
    mock_response = mock_urlopen.return_value.__enter__.return_value
    mock_response.read.return_value = b'{"data": [{"embedding": [0.9, 0.8, 0.7]}]}'
    res = _call_openai_compatible_api("key", "http://fake.api", "model-name", "text")
    assert res == [0.9, 0.8, 0.7]

def test_get_embedding_with_zhipu():
    with patch("memento.embedding._embed_zhipu") as mock_zhipu:
        mock_zhipu.return_value = [1.0, 2.0, 3.0]
        blob, dim, pending = get_embedding("test")
        assert dim == 3
        assert not pending
        assert isinstance(blob, bytes)
        mock_zhipu.assert_called_once()
        assert mock_zhipu.call_args[0][0] == "test"


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
