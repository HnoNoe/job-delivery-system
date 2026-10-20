"""五个核心数学公式（式一 ~ 式五）。

专利强调：每一步处理在数学上自洽、可验证。本模块将五个公式集中实现，
供模型层1（式一）、操作层1（式二式三）、模型层2（式四）、结果输出层（式五）调用。
"""
import numpy as np
import config


def logistic(x):
    """逻辑斯谛函数 σ(x) = 1/(1+e^{-x})，将实数映射到开区间 (0,1)。"""
    return 1.0 / (1.0 + np.exp(-np.clip(x, -50, 50)))


def formula_1_user_representation(experience_vectors, weights):
    """式一　用户表示（凸组合）。

    u = Σ_k α_k · v_k，α_k ≥ 0，Σ α_k = 1。
    输入: experience_vectors (K, d), weights (K,)
    输出: u (d,)
    """
    v = np.asarray(experience_vectors, dtype=float)
    a = np.asarray(weights, dtype=float)
    if v.shape[0] == 0:
        return np.zeros(config.EMBED_DIM)
    # 保证凸组合定义（非负、和为1）
    a = np.clip(a, 0.0, None)
    s = a.sum()
    if s <= 0:
        a = np.ones_like(a) / a.shape[0]
    else:
        a = a / s
    return a @ v


def formula_2_cosine(u, j):
    """式二　用户表示与岗位的余弦（仅在模长均 > 0 时计算）。"""
    from embedding import cosine
    return cosine(u, j)


def formula_3_match_score(s, delta, w_s, w_delta, has_center):
    """式三　匹配分数 p = σ(w_s·s + w_δ·δ)。

    has_center 为 False（缺任一类中心）时，间隔项系数取 0。
    """
    wd = w_delta if has_center else 0.0
    return logistic(w_s * s + wd * delta)


def interval_feature(j, c_pos, c_neg):
    """间隔特征 δ = cos(j, c_+) - cos(j, c_-)（更靠近正中心还是负中心）。"""
    from embedding import cosine
    return cosine(j, c_pos) - cosine(j, c_neg)


def formula_4_experience_allocation(weights, sims, tau):
    """式四　该岗经历分配（指数倾斜）。

    γ_k = (α_k · e^{τ·b_k}) / Σ_m (α_m · e^{τ·b_m})，τ > 0。
    """
    a = np.asarray(weights, dtype=float)
    b = np.asarray(sims, dtype=float)
    a = np.clip(a, 0.0, None)
    if a.sum() <= 0:
        a = np.ones_like(a) / a.shape[0]
    w = a * np.exp(tau * b)
    return w / w.sum()


def formula_5_weight_update(weights, z, indicators, eta):
    """式五　回写（乘性权重，同一组内先更新后归一化）。

    α_k ← α_k · e^{η·z·I_k}，再归一化。
    z ∈ {0,1}；I_k ∈ {0,1}；η > 0。先乘性更新，再归一化（先后关系，非并列）。
    """
    a = np.asarray(weights, dtype=float)
    ind = np.asarray(indicators, dtype=float)
    a = np.clip(a, 0.0, None)
    # 先乘性更新
    a = a * np.exp(eta * z * ind)
    s = a.sum()
    if s <= 0:
        return a  # 恒等（未写入任何经历）
    return a / s
