"""Embedding 抽象层：支持多种大模型 API（Gemini, Zhipu/GLM, Minimax, Moonshot/Kimi, OpenAI），回退至本地模型及 FTS5。"""

import os
import struct
import json
import urllib.request
from typing import Optional

# 默认维度参考（仅作注释用，sqlite-vec 自适应）
GEMINI_DIM = 768
ZHIPU_DIM = 2048 # embedding-3
MINIMAX_DIM = 1536 # embo-01
LOCAL_DIM = 384


def _call_openai_compatible_api(api_key: str, base_url: str, model: str, text: str) -> Optional[list[float]]:
    """通用的 OpenAI 兼容格式 Embedding 请求"""
    url = f"{base_url.rstrip('/')}/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": model,
        "input": text
    }
    req = urllib.request.Request(url, headers=headers, data=json.dumps(data).encode("utf-8"))
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result["data"][0]["embedding"]
    except Exception:
        return None


def _embed_gemini(text: str, api_key: Optional[str] = None) -> Optional[list[float]]:
    """调用 Gemini embedding API。"""
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
    except ImportError:
        import sys
        import subprocess
        print("MEMENTO: 检测到未安装 google-genai 依赖，正在自动安装...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "google-genai"], stdout=subprocess.DEVNULL)
            from google import genai
        except Exception as e:
            print(f"MEMENTO: 自动安装 google-genai 失败: {e}")
            return None
            
    try:
        client = genai.Client(api_key=api_key)
        result = client.models.embed_content(
            model="gemini-embedding-001",
            contents=text,
        )
        return result.embeddings[0].values
    except Exception:
        return None


def _embed_zhipu(text: str, api_key: Optional[str] = None) -> Optional[list[float]]:
    """调用智谱 (GLM) embedding API。"""
    api_key = api_key or os.environ.get("ZHIPU_API_KEY") or os.environ.get("GLM_API_KEY")
    if not api_key:
        return None
    try:
        # 优先尝试官方 SDK
        from zhipuai import ZhipuAI
    except ImportError:
        import sys
        import subprocess
        print("MEMENTO: 检测到未安装 zhipuai 依赖，正在自动安装...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "zhipuai"], stdout=subprocess.DEVNULL)
            from zhipuai import ZhipuAI
        except Exception as e:
            print(f"MEMENTO: 自动安装 zhipuai 失败: {e}")
            # 退回使用通用 HTTP 请求
            return _call_openai_compatible_api(api_key, "https://open.bigmodel.cn/api/paas/v4", "embedding-3", text)
            
    try:
        client = ZhipuAI(api_key=api_key)
        response = client.embeddings.create(
            model="embedding-3",
            input=text
        )
        return response.data[0].embedding
    except Exception:
        # 退回使用通用 HTTP 请求
        return _call_openai_compatible_api(api_key, "https://open.bigmodel.cn/api/paas/v4", "embedding-3", text)


def _embed_minimax(text: str, api_key: Optional[str] = None) -> Optional[list[float]]:
    """调用 Minimax embedding API。"""
    api_key = api_key or os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        return None
    return _call_openai_compatible_api(api_key, "https://api.minimax.chat/v1", "embo-01", text)


def _embed_moonshot(text: str, api_key: Optional[str] = None) -> Optional[list[float]]:
    """调用 Moonshot (Kimi) embedding API (或 OpenAI 兼容接口)。"""
    api_key = api_key or os.environ.get("MOONSHOT_API_KEY") or os.environ.get("KIMI_API_KEY")
    if not api_key:
        return None
    # 目前 Moonshot 虽然没有官方主推 embedding，但预留兼容 OpenAI 的口子或未来支持
    return _call_openai_compatible_api(api_key, "https://api.moonshot.cn/v1", "moonshot-v1-embedding", text)


def _embed_openai(text: str, api_key: Optional[str] = None) -> Optional[list[float]]:
    """调用原生 OpenAI embedding API"""
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    return _call_openai_compatible_api(api_key, base_url, "text-embedding-3-small", text)


def _embed_local(text: str) -> Optional[list[float]]:
    """本地 sentence-transformers 模型。"""
    try:
        from sentence_transformers import SentenceTransformer
        if not hasattr(_embed_local, "_model"):
            _embed_local._model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
        return _embed_local._model.encode(text).tolist()
    except ImportError:
        if not getattr(_embed_local, "_warned", False):
            _embed_local._warned = True
            print("MEMENTO: sentence-transformers not installed. "
                  "Local embedding unavailable. "
                  "Run: pip install memento[local]")
        return None
    except Exception:
        return None


def get_embedding(text: str) -> tuple[Optional[bytes], int, bool]:
    """
    返回 (embedding_blob, dim, is_pending)。
    按照优先级获取模型 embedding。
    """
    from memento.config import get_config

    cfg = get_config()
    emb_cfg = cfg.get("embedding", {})
    configured_provider = emb_cfg.get("provider")
    configured_key = emb_cfg.get("api_key")

    # If provider explicitly configured, call it directly (no env scan fallback)
    if configured_provider:
        provider_map = {
            "zhipu": _embed_zhipu, "minimax": _embed_minimax,
            "moonshot": _embed_moonshot, "openai": _embed_openai,
            "gemini": _embed_gemini,
            "local": _embed_local,
        }
        provider_fn = provider_map.get(configured_provider)
        if provider_fn:
            if configured_provider == "local":
                vec = provider_fn(text)
            else:
                vec = provider_fn(text, api_key=configured_key)
            if vec is not None:
                return vec_to_blob(vec), len(vec), False
            # Configured provider failed, return pending immediately (no fallback)
            return None, 0, True

    # Legacy fallback: scan all provider env vars in order
    providers = [
        _embed_zhipu,
        _embed_minimax,
        _embed_moonshot,
        _embed_openai,
        _embed_gemini,
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


def vec_to_blob(vec: list[float]) -> bytes:
    """将浮点向量序列化为 sqlite-vec 兼容的 BLOB 格式（little-endian float32）。"""
    return struct.pack(f"<{len(vec)}f", *vec)


def blob_to_vec(blob: bytes) -> list[float]:
    """从 BLOB 反序列化为浮点向量。"""
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))
