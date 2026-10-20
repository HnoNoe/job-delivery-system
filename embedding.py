"""语义向量化 —— 经历向量、岗位向量落在同一表示空间。

优先使用真实嵌入模型（sentence-transformers）；未安装时回退到
确定性的离线特征哈希嵌入，保证全流程可离线运行、余弦相似度可用。
"""
import numpy as np
import config

_model = None


def _get_model():
    global _model
    if _model is None and config.EMBED_MODEL:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(config.EMBED_MODEL)
    return _model


def embed(text: str) -> np.ndarray:
    """把文本转成向量。"""
    model = _get_model()
    if model is not None:
        v = model.encode(text)
        return np.asarray(v, dtype=float)
    return _hash_embed(text)


def _hash_embed(text: str, dim: int = None) -> np.ndarray:
    """离线特征哈希嵌入（确定性：用 md5，跨进程/跨重启稳定）。"""
    import hashlib
    dim = dim or config.EMBED_DIM
    v = np.zeros(dim, dtype=float)
    for token in _tokens(text):
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % dim
        v[h] += 1.0
    n = np.linalg.norm(v)
    if n > 0:
        v = v / n
    return v


def _tokens(text: str):
    """简单中文/英文切词：按标点与空白切分，并对汉字做 bigram 增强。"""
    import re
    text = (text or "").lower()
    parts = re.split(r"[\s,，。;；:：/\\|、()（）]+", text)
    out = []
    for p in parts:
        if not p:
            continue
        out.append(p)
        # 汉字 bigram，提升匹配粒度
        if re.search(r"[\u4e00-\u9fff]", p):
            for i in range(len(p) - 1):
                out.append(p[i:i + 2])
    return [t for t in out if t]


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """式二：余弦相似度（仅在模长均 > 0 时计算）。"""
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))
