"""Embedding 抽象层：Gemini → 本地模型 → None（FTS5 回退）。"""

import os
import struct
from typing import Optional

# Gemini 输出维度
GEMINI_DIM = 768
LOCAL_DIM = 384


def _embed_gemini(text: str) -> Optional[list[float]]:
    """Level 0: 调用 Gemini embedding API。"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        result = client.models.embed_content(
            model="gemini-embedding-001",
            contents=text,
        )
        return result.embeddings[0].values
    except Exception:
        return None


def _embed_local(text: str) -> Optional[list[float]]:
    """Level 1: 本地 sentence-transformers 模型。"""
    try:
        from sentence_transformers import SentenceTransformer

        # 延迟加载，缓存到模块级变量
        if not hasattr(_embed_local, "_model"):
            _embed_local._model = SentenceTransformer(
                "all-MiniLM-L6-v2", device="cpu"
            )
        vec = _embed_local._model.encode(text).tolist()
        return vec
    except Exception:
        return None


def get_embedding(text: str) -> tuple[Optional[bytes], int, bool]:
    """
    返回 (embedding_blob, dim, is_pending)。

    - 成功获取 embedding: (blob, dim, False)
    - 全部失败:           (None, 0, True)
    """
    # Level 0: Gemini
    vec = _embed_gemini(text)
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
