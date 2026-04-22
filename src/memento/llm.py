"""
Memento v0.5.0 — LLM Client

Minimal OpenAI-compatible LLM client using only Python stdlib (urllib).
No external dependencies.

Layer 3 — Used exclusively by Epoch runner.
Single Epoch binds to single model. Failure → cognitive debt, not failover.
"""

import os
import json
import re
import time
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class LLMClient:
    """Minimal OpenAI-compatible LLM client using stdlib urllib."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 30,
        max_retries: int = 3,
        temperature: float = 0.0
    ):
        """Initialize LLM client.

        Args:
            base_url: Base URL of the LLM API (e.g., "https://api.openai.com/v1")
            api_key: API key for authentication
            model: Model name (e.g., "gpt-4", "gpt-3.5-turbo")
            timeout: Request timeout in seconds (default: 30)
            max_retries: Maximum number of retry attempts (default: 3)
            temperature: Sampling temperature 0.0-2.0 (default: 0.0)
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.temperature = temperature

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

    @classmethod
    def from_env(cls) -> Optional["LLMClient"]:
        """Deprecated: use from_config() instead."""
        return cls.from_config()

    def generate(self, prompt: str, system: Optional[str] = None) -> str:
        """Generate text completion.

        Args:
            prompt: User prompt
            system: Optional system message

        Returns:
            Generated text content as string
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature
        }

        response = self._call(body)
        return response["choices"][0]["message"]["content"]

    def generate_json(self, prompt: str, system: Optional[str] = None) -> dict:
        """Generate JSON completion.

        Args:
            prompt: User prompt
            system: Optional system message

        Returns:
            Parsed JSON dict or list
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }

        response = self._call(body)
        content = response["choices"][0]["message"]["content"]
        return self._extract_json(content)

    @staticmethod
    def _extract_json(text: str):
        """Extract JSON from LLM response, handling markdown code fences."""
        # Try direct parse first
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Extract from ```json ... ``` or ``` ... ```
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if m:
            return json.loads(m.group(1).strip())

        raise json.JSONDecodeError("No valid JSON found in LLM response", text, 0)

    def _call(self, body: dict) -> dict:
        """Make HTTP POST request to /chat/completions with retries.

        Args:
            body: Request body dict

        Returns:
            Response JSON dict

        Raises:
            Exception: After exhausting max_retries
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        data = json.dumps(body).encode("utf-8")

        last_exception = None
        for attempt in range(self.max_retries):
            try:
                req = Request(url, data=data, headers=headers)
                with urlopen(req, timeout=self.timeout) as response:
                    response_data = response.read()
                    return json.loads(response_data.decode("utf-8"))
            except (HTTPError, URLError, Exception) as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    # Exponential backoff: 1s, 2s, 4s, etc.
                    time.sleep(2 ** attempt)
                continue

        # Exhausted all retries
        raise last_exception
