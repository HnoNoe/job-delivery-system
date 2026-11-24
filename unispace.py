"""统一匹配空间计算层：用户池 × 岗位池在同一坐标系对齐、聚类、归属。

数学依据（见 docs/设计-用户岗位统一匹配空间.md）：
- 用户向量（式一 user_vec）与岗位 embedding 由同一份统一字段词表生成，同空间可比；
- 对齐 = 对联合矩阵 [用户; 岗位] 做一次 PCA，两端共用投影基；
  任何第三者（簇心等）必须用同一份 fit 投影，否则坐标不可比；
- 聚类 = 岗位侧 KMeans（在原始嵌入空间），K 由轮廓系数在 2..8 自动选；
- 归属 = 用户点按最近簇心（同基投影后）归属，fit = 与最近簇心的余弦。
"""
import numpy as np

from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score


def _as_matrix(vectors, dim=None):
    """JSON 向量列表 → 定长 float 矩阵；维度不齐时截断/补零到指定/最大维度。"""
    vecs = [np.asarray(v, dtype=float) for v in vectors if v is not None and len(v)]
    if not vecs:
        return np.zeros((0, dim or 0))
    if dim is None:
        dim = max(len(v) for v in vecs)
    M = np.zeros((len(vecs), dim))
    for i, v in enumerate(vecs):
        n = min(len(v), dim)
        M[i, :n] = v[:n]
    return M


class SpaceFit:
    """联合 PCA 的拟合结果（均值 + 投影基），同一 fit 投影的一切坐标可比。"""

    def __init__(self, mean, basis, dims):
        self.mean = mean
        self.basis = basis          # (k, dim) 已按 dims 截断/补零
        self.dims = dims

    def project(self, vectors):
        M = _as_matrix(vectors, dim=len(self.mean)) - self.mean
        coords = M @ self.basis.T   # basis 行已补零到 dims，输出恒为 (n, dims)
        return coords


def fit_space(user_vecs, job_embs, dims=3):
    """对 [用户; 岗位] 联合矩阵拟合 PCA。返回 SpaceFit。

    点数不足时退化为恒等投影（原坐标截断/补零），保证接口一致。
    """
    U = _as_matrix(user_vecs)
    J = _as_matrix(job_embs, dim=U.shape[1] if U.size else None)
    dim = max(U.shape[1], J.shape[1])
    U = _as_matrix(user_vecs, dim=dim)
    J = _as_matrix(job_embs, dim=dim)
    X = np.vstack([U, J])
    if X.shape[0] < 3:
        mean = np.zeros(dim)
        basis = np.zeros((dims, dim))
        for i in range(min(dims, dim)):
            basis[i, i] = 1.0
        return SpaceFit(mean, basis, dims)
    mean = X.mean(0)
    _, _, vt = np.linalg.svd(X - mean, full_matrices=False)
    k = min(dims, vt.shape[0])
    basis = np.zeros((dims, dim))
    basis[:k] = vt[:k]
    return SpaceFit(mean, basis, dims)


def axes_top_dims(fit, topn=5):
    """每个主成分载荷绝对值 Top 维度索引（词表维度即技能序号，调用方可映射成词）。"""
    out = []
    for i in range(fit.dims):
        load = np.abs(fit.basis[i])
        nz = load[load > 0]
        out.append({"axis": i + 1,
                    "top_dims": np.argsort(load)[::-1][:topn].tolist(),
                    "weight": float(nz.sum()) if nz.size else 0.0})
    return out


def cluster_jobs(job_embs, k_range=range(2, 9)):
    """岗位聚类（原始嵌入空间）：KMeans + 轮廓系数自动选 K。返回 (labels, k, centers)。"""
    J = _as_matrix(job_embs)
    n = J.shape[0]
    if n == 0:
        return np.zeros(0, dtype=int), 0, np.zeros((0, J.shape[1]))
    if n < 3:
        return np.zeros(n, dtype=int), 1, J.copy()
    best_k, best_score, best_model = 2, -1.0, None
    for k in k_range:
        if k >= n:
            break
        km = KMeans(n_clusters=k, n_init=4, random_state=42).fit(J)
        score = silhouette_score(J, km.labels_)
        if score > best_score:
            best_k, best_score, best_model = k, score, km
    return best_model.labels_, best_k, best_model.cluster_centers_


def cluster_keywords(job_fields_list, labels):
    """簇命名：簇内岗位「岗位名称+技术工具/描述」词频 Top3。"""
    from collections import Counter
    lbs = labels.tolist() if hasattr(labels, "tolist") else list(labels)
    names = {}
    for k in sorted(set(lbs)):
        words = Counter()
        for f, lb in zip(job_fields_list, lbs):
            if lb != k:
                continue
            text = "%s %s" % (f.get("岗位名称", ""),
                              f.get("技术工具", "") or f.get("岗位描述", "") or "")
            for w in text.replace("/", " ").replace(",", " ").split():
                if len(w) >= 2:
                    words[w] += 1
        names[k] = "、".join(w for w, _c in words.most_common(3)) or ("簇 %d" % (k + 1))
    return names


def build_space(users, jobs, dims=3, highlight_owner=None):
    """总装：对齐 → 聚类 → 归属 → 统一空间数据（dict，供 viz 直接作图）。

    users: [{owner,label,user_vec,...}]（mydata.list_space_users）
    jobs:  [{job_id,fields,embedding}]（mydata.list_space_jobs）
    """
    fit = fit_space([u["user_vec"] for u in users],
                    [j["embedding"] for j in jobs], dims=dims)
    user_coords = fit.project([u["user_vec"] for u in users])
    job_coords = fit.project([j["embedding"] for j in jobs])

    labels, k, centers = cluster_jobs([j["embedding"] for j in jobs])
    names = cluster_keywords([j["fields"] for j in jobs], labels)
    # 簇心必须用同一 fit 投影，坐标才与用户/岗位可比
    centers_coords = fit.project(centers.tolist()) if k else np.zeros((0, dims))

    out_users = []
    for u, c in zip(users, user_coords):
        best, best_d = -1, 0.0
        if len(centers_coords):
            denom = np.linalg.norm(centers_coords, axis=1) * (np.linalg.norm(c) + 1e-9)
            sims = centers_coords @ c / (denom + 1e-9)
            best = int(np.argmax(sims))
            best_d = round(float(sims[best]), 4)
        out_users.append({**u, "coord": [round(float(x), 6) for x in c],
                          "cluster": best, "fit": best_d,
                          "is_me": u["owner"] == highlight_owner})
    out_jobs = []
    for j, c, lb in zip(jobs, job_coords, labels):
        out_jobs.append({**j, "coord": [round(float(x), 6) for x in c],
                         "cluster": int(lb), "cluster_name": names[int(lb)]})
    return {"users": out_users, "jobs": out_jobs,
            "clusters": {int(kk): names[int(kk)] for kk in sorted(names)},
            "k": int(k), "axes_info": axes_top_dims(fit)}
