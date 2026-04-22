import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from memento.llm import LLMClient


def test_llm_client_init():
    """LLMClient init stores params correctly."""
    client = LLMClient(
        base_url="https://api.example.com/v1",
        api_key="test-key",
        model="gpt-4",
        timeout=60,
        max_retries=5,
        temperature=0.7
    )
    assert client.base_url == "https://api.example.com/v1"
    assert client.api_key == "test-key"
    assert client.model == "gpt-4"
    assert client.timeout == 60
    assert client.max_retries == 5
    assert client.temperature == 0.7


def test_llm_client_init_strips_trailing_slash():
    """LLMClient init strips trailing slash from base_url."""
    client = LLMClient(
        base_url="https://api.example.com/v1/",
        api_key="test-key",
        model="gpt-4"
    )
    assert client.base_url == "https://api.example.com/v1"


def test_llm_client_init_default_values():
    """LLMClient init uses default values for optional params."""
    client = LLMClient(
        base_url="https://api.example.com/v1",
        api_key="test-key",
        model="gpt-4"
    )
    assert client.timeout == 30
    assert client.max_retries == 3
    assert client.temperature == 0.0


def test_from_env_creates_client(tmp_path):
    """from_env creates client from env vars (delegates to from_config)."""
    with patch.object(Path, "home", return_value=tmp_path), \
         patch.dict(os.environ, {
            "MEMENTO_LLM_BASE_URL": "https://api.test.com/v1",
            "MEMENTO_LLM_API_KEY": "env-key",
            "MEMENTO_LLM_MODEL": "gpt-3.5-turbo"
         }, clear=True):
        client = LLMClient.from_env()
        assert client is not None
        assert client.base_url == "https://api.test.com/v1"
        assert client.api_key == "env-key"
        assert client.model == "gpt-3.5-turbo"


def test_from_env_returns_none_when_missing_api_key(tmp_path):
    """from_env returns None when MEMENTO_LLM_API_KEY is missing."""
    with patch.object(Path, "home", return_value=tmp_path), \
         patch.dict(os.environ, {
            "MEMENTO_LLM_BASE_URL": "https://api.test.com/v1",
            "MEMENTO_LLM_MODEL": "gpt-3.5-turbo"
         }, clear=True):
        client = LLMClient.from_env()
        assert client is None


@patch("memento.llm.urlopen")
def test_generate(mock_urlopen):
    """generate mocks urlopen and returns content string."""
    response_body = json.dumps({
        "choices": [{"message": {"content": "Hello, world!"}}]
    }).encode()

    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    client = LLMClient(
        base_url="https://api.example.com/v1",
        api_key="test-key",
        model="gpt-4"
    )

    result = client.generate("Say hello")
    assert result == "Hello, world!"
    assert mock_urlopen.call_count == 1


@patch("memento.llm.urlopen")
def test_generate_with_system(mock_urlopen):
    """generate includes system message when provided."""
    response_body = json.dumps({
        "choices": [{"message": {"content": "I am a helpful assistant."}}]
    }).encode()

    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    client = LLMClient(
        base_url="https://api.example.com/v1",
        api_key="test-key",
        model="gpt-4"
    )

    result = client.generate("Who are you?", system="You are a helpful assistant")
    assert result == "I am a helpful assistant."

    # Verify the request includes system message
    call_args = mock_urlopen.call_args
    request_obj = call_args[0][0]
    request_data = json.loads(request_obj.data.decode())
    assert request_data["messages"][0]["role"] == "system"
    assert request_data["messages"][0]["content"] == "You are a helpful assistant"
    assert request_data["messages"][1]["role"] == "user"


@patch("memento.llm.urlopen")
def test_generate_json(mock_urlopen):
    """generate_json mocks urlopen and returns parsed JSON dict."""
    json_response = {"status": "success", "data": {"key": "value"}}
    response_body = json.dumps({
        "choices": [{"message": {"content": json.dumps(json_response)}}]
    }).encode()

    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    client = LLMClient(
        base_url="https://api.example.com/v1",
        api_key="test-key",
        model="gpt-4"
    )

    result = client.generate_json("Generate JSON")
    assert result == json_response
    assert result["status"] == "success"
    assert result["data"]["key"] == "value"

    # Verify the request does NOT include response_format (removed for Claude compatibility)
    call_args = mock_urlopen.call_args
    request_obj = call_args[0][0]
    request_data = json.loads(request_obj.data.decode())
    assert "response_format" not in request_data


@patch("memento.llm.urlopen")
def test_call_retries_on_failure(mock_urlopen):
    """_call retries on HTTP error up to max_retries."""
    # First two calls fail, third succeeds
    response_body = json.dumps({
        "choices": [{"message": {"content": "Success"}}]
    }).encode()

    mock_resp_success = MagicMock()
    mock_resp_success.read.return_value = response_body
    mock_resp_success.__enter__ = lambda s: s
    mock_resp_success.__exit__ = MagicMock(return_value=False)

    # Fail twice, then succeed
    mock_urlopen.side_effect = [
        Exception("Network error"),
        Exception("Network error"),
        mock_resp_success
    ]

    client = LLMClient(
        base_url="https://api.example.com/v1",
        api_key="test-key",
        model="gpt-4",
        max_retries=3
    )

    result = client.generate("Test retry")
    assert result == "Success"
    assert mock_urlopen.call_count == 3


@patch("memento.llm.urlopen")
def test_call_raises_after_max_retries(mock_urlopen):
    """_call raises exception after exhausting max_retries."""
    mock_urlopen.side_effect = Exception("Network error")

    client = LLMClient(
        base_url="https://api.example.com/v1",
        api_key="test-key",
        model="gpt-4",
        max_retries=2
    )

    with pytest.raises(Exception, match="Network error"):
        client.generate("Test retry failure")

    assert mock_urlopen.call_count == 2


@patch("memento.llm.urlopen")
def test_generate_includes_temperature(mock_urlopen):
    """generate includes temperature in request body."""
    response_body = json.dumps({
        "choices": [{"message": {"content": "Response"}}]
    }).encode()

    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    client = LLMClient(
        base_url="https://api.example.com/v1",
        api_key="test-key",
        model="gpt-4",
        temperature=0.8
    )

    client.generate("Test temperature")

    call_args = mock_urlopen.call_args
    request_obj = call_args[0][0]
    request_data = json.loads(request_obj.data.decode())
    assert request_data["temperature"] == 0.8


# ── from_config tests ──────────────────────────────────────────────


def _write_config(tmp_path, cfg):
    """Helper: write config.json into fake ~/.memento/."""
    config_dir = tmp_path / ".memento"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps(cfg), encoding="utf-8")


def test_from_config_reads_config_json(tmp_path):
    """from_config reads LLM settings from config.json."""
    _write_config(tmp_path, {
        "llm": {
            "base_url": "https://api.cfg.com/v1",
            "api_key": "cfg-key-123",
            "model": "cfg-model",
            "timeout": 45,
            "max_retries": 5,
            "temperature": 0.3,
        }
    })
    with patch.object(Path, "home", return_value=tmp_path), \
         patch.dict(os.environ, {}, clear=True):
        client = LLMClient.from_config()

    assert client is not None
    assert client.base_url == "https://api.cfg.com/v1"
    assert client.api_key == "cfg-key-123"
    assert client.model == "cfg-model"
    assert client.timeout == 45
    assert client.max_retries == 5
    assert client.temperature == 0.3


def test_from_config_env_overrides_config(tmp_path):
    """MEMENTO_LLM_* env vars override config.json values."""
    _write_config(tmp_path, {
        "llm": {
            "base_url": "https://api.cfg.com/v1",
            "api_key": "cfg-key",
            "model": "cfg-model",
        }
    })
    env = {
        "MEMENTO_LLM_BASE_URL": "https://api.env.com/v1",
        "MEMENTO_LLM_API_KEY": "env-key",
        "MEMENTO_LLM_MODEL": "env-model",
    }
    with patch.object(Path, "home", return_value=tmp_path), \
         patch.dict(os.environ, env, clear=True):
        client = LLMClient.from_config()

    assert client is not None
    assert client.base_url == "https://api.env.com/v1"
    assert client.api_key == "env-key"
    assert client.model == "env-model"


def test_from_config_returns_none_when_incomplete(tmp_path):
    """from_config returns None when required fields are missing."""
    _write_config(tmp_path, {
        "llm": {
            "base_url": "https://api.cfg.com/v1",
            # api_key missing, model missing
        }
    })
    with patch.object(Path, "home", return_value=tmp_path), \
         patch.dict(os.environ, {}, clear=True):
        client = LLMClient.from_config()

    assert client is None


def test_from_config_with_provider_presets(tmp_path):
    """from_config fills base_url/model from zhipu preset when only provider+key given."""
    _write_config(tmp_path, {
        "llm": {
            "provider": "zhipu",
            "api_key": "zhipu-key-abc",
        }
    })
    with patch.object(Path, "home", return_value=tmp_path), \
         patch.dict(os.environ, {}, clear=True):
        client = LLMClient.from_config()

    assert client is not None
    assert client.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert client.model == "glm-4-flash-250414"
    assert client.api_key == "zhipu-key-abc"
