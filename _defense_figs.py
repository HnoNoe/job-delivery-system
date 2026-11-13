"""答辩 PPT 用图：用户定位 · 超几何空间画像（4 张，2400x1350）。

数据源为本机演示库（6 个用户，式一 user_vec 与统一字段指标），
运行：python _defense_figs.py  →  docs/defense/fig1~4.png

图面文字规范（答辩投影场景）：
- 双层表达：第一行白话结论（大字号），第二行技术表述（公式编号与含义绑定）；
- 缩写首次出现给全称：主成分分析（PCA）、两倍标准差椭圆、反馈修正项 δ；
- 字号按投影可读性设计：主标题 ≥22，图内标注 ≥13，任何文字不重叠。
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Ellipse, FancyArrowPatch

import db
import viz
import recommend

OUT = os.path.join("docs", "defense")
os.makedirs(OUT, exist_ok=True)

# ---- 设计系统色板（与 theme.py 一致） ----
PRIMARY, VIOLET = "#4F46E5", "#7C3AED"
INK, SLATE, MUTED, LINE = "#0F172A", "#475569", "#94A3B8", "#E2E8F0"
ACCENT = "#E11D48"   # 定位用户高亮
GOLD = "#D97706"

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "sans-serif"],
    "axes.unicode_minus": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.edgecolor": LINE,
    "axes.linewidth": 1.2,
    "font.size": 16,
    "xtick.labelsize": 14,
    "ytick.labelsize": 14,
})
TARGET_NAME = "张三"


def _style_ax(ax, grid=True):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    if grid:
        ax.grid(True, color="#EEF2F7", linewidth=1)
        ax.set_axisbelow(True)


def _titles(ax, main, sub, main_size=22, sub_size=15, pad=42):
    """主标题（白话结论，大字）+ 副标题（技术表述，小字灰）。"""
    ax.set_title(main, fontsize=main_size, color=INK, fontweight="bold", pad=pad)
    text2d = getattr(ax, "text2D", ax.text)  # Axes3D 用 text2D
    text2d(0.5, 1.035, sub, transform=ax.transAxes, ha="center", va="bottom",
           fontsize=sub_size, color=SLATE)


def _load():
    """式一 user_vec + 指标表，返回 (ids, names, X, feat_df)。"""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT p.user_id, p.user_vec FROM profile_pool p "
            "JOIN (SELECT user_id, MAX(snap_id) AS ms FROM profile_pool GROUP BY user_id) m "
            "ON p.user_id=m.user_id AND p.snap_id=m.ms").fetchall()
        users = conn.execute("SELECT user_id, l0 FROM user_records").fetchall()
    names = {r["user_id"]: (json.loads(r["l0"]).get("姓名", "") or "用户%d" % r["user_id"])
             for r in users}
    ids = [r["user_id"] for r in rows]
    X = np.vstack([np.asarray(json.loads(r["user_vec"])) for r in rows])
    return ids, names, X, viz.user_feature_table()


# ================================================================ fig1 语义空间定位
def fig1(ids, names, X):
    Xc = X - X.mean(axis=0)
    u, s, vt = np.linalg.svd(Xc, full_matrices=False)
    proj = Xc @ vt.T[:, :2]
    var = s ** 2 / np.sum(s ** 2)

    fig, ax = plt.subplots(figsize=(12, 6.75), dpi=200)
    _style_ax(ax)
    t_idx = ids.index(next(i for i in ids if names[i] == TARGET_NAME))

    # 群体分布两倍标准差椭圆
    cov = np.cov(proj.T)
    vals, vecs = np.linalg.eigh(cov)
    ang = np.degrees(np.arctan2(vecs[1, 1], vecs[0, 1]))
    w, h = 2 * 2.0 * np.sqrt(np.maximum(vals, 1e-12))
    ax.add_patch(Ellipse(proj.mean(axis=0), w, h, angle=ang,
                         facecolor=PRIMARY, alpha=0.07, edgecolor=PRIMARY,
                         linewidth=1.2, linestyle="--", zorder=1,
                         label="用户群体的分布范围（两倍标准差椭圆）"))

    others = [i for i in range(len(ids)) if i != t_idx]
    ax.scatter(proj[others, 0], proj[others, 1], s=110, c=MUTED, alpha=0.9,
               edgecolors="white", linewidths=1.2, zorder=3, label="其他用户")
    for i in others:
        ax.annotate(names[ids[i]], (proj[i, 0], proj[i, 1]),
                    xytext=(0, 12), textcoords="offset points",
                    ha="center", fontsize=15, color=SLATE)
    # 用户向量箭头（质心→目标）
    ax.add_patch(FancyArrowPatch((0, 0), proj[t_idx], arrowstyle="-|>",
                                 mutation_scale=24, color=ACCENT, alpha=0.55,
                                 linewidth=2.2, zorder=2))
    ax.scatter(*proj[t_idx], s=560, marker="*", c=ACCENT, edgecolors="white",
               linewidths=1.6, zorder=4, label="定位用户（%s）" % TARGET_NAME)
    ax.annotate(TARGET_NAME, proj[t_idx], xytext=(16, 12), textcoords="offset points",
                fontsize=17, color=ACCENT, fontweight="bold")
    mid = proj[t_idx] / 2
    ax.annotate("%s的用户表示向量 u（式一）" % TARGET_NAME, mid, xytext=(12, -30),
                textcoords="offset points", fontsize=15, color=ACCENT,
                fontweight="bold",
                bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.8))

    ax.set_xlabel("第一主成分（解释 %.1f%% 的方差）" % (var[0] * 100),
                  color=SLATE, fontsize=17)
    ax.set_ylabel("第二主成分（解释 %.1f%% 的方差）" % (var[1] * 100),
                  color=SLATE, fontsize=17)
    _titles(ax, "超几何空间画像：每个用户都是语义空间中的一个点",
            "简历信息经凸组合模型（式一）生成用户表示向量，再由主成分分析（PCA）投影至二维平面")
    ax.legend(loc="upper right", frameon=False, fontsize=15)
    pad = 0.35 * np.ptp(proj[:, 0])
    ax.set_xlim(proj[:, 0].min() - pad, proj[:, 0].max() + pad)
    ax.set_ylim(proj[:, 1].min() - pad, proj[:, 1].max() + pad)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig1_semantic_space.png"))
    plt.close(fig)
    print("saved fig1")


# ================================================================ fig2 六维雷达
def fig2(feat):
    axes_names = viz.USER_AXES
    raw = feat.copy()
    for c in ("经历段数", "技能数", "累计投递"):
        raw[c] = raw[c] / raw[c].max()
    for c in ("进面试率", "平均匹配分"):
        raw[c] = raw[c].fillna(0.0)
    raw[["GPA", "排名优秀度"]] = raw[["GPA", "排名优秀度"]].fillna(raw[["GPA", "排名优秀度"]].mean())
    t = raw[raw["姓名"] == TARGET_NAME].iloc[0]
    tvals = [float(t[c]) for c in axes_names]
    mvals = [float(raw[c].mean()) for c in axes_names]

    ang = np.linspace(0, 2 * np.pi, len(axes_names), endpoint=False).tolist()
    tvals += tvals[:1]; mvals += mvals[:1]; ang += ang[:1]

    fig, ax = plt.subplots(figsize=(12, 6.75), dpi=200, subplot_kw=dict(polar=True))
    ax.plot(ang, mvals, color=MUTED, linewidth=2.2, label="群体均值（6 名用户）")
    ax.fill(ang, mvals, color=MUTED, alpha=0.12)
    ax.plot(ang, tvals, color=PRIMARY, linewidth=2.8, label="定位用户（%s）" % TARGET_NAME)
    ax.fill(ang, tvals, color=PRIMARY, alpha=0.18)
    ax.set_xticks(ang[:-1])
    ax.set_xticklabels(axes_names, fontsize=17, color=INK)
    ax.set_ylim(0, 1.05)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0.25", "0.50", "0.75", "1.00"], fontsize=12, color=MUTED)
    ax.grid(color=LINE, linewidth=1)
    ax.spines["polar"].set_color(LINE)
    for a, v in zip(ang[:-1], tvals[:-1]):
        ax.annotate("%.2f" % v, (a, v * 0.85), xytext=(0, 6), textcoords="offset points",
                    ha="center", fontsize=14, color=PRIMARY, fontweight="bold",
                    bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.0))
    fig.suptitle("定位用户与群体均值的六维画像对比",
                 fontsize=22, color=INK, fontweight="bold", y=0.975)
    fig.text(0.5, 0.905, "六个维度取自统一字段数据库并归一化至 0~1，六边形越饱满，用户画像越全面",
             ha="center", fontsize=15, color=SLATE)
    fig.legend(loc="center left", bbox_to_anchor=(0.775, 0.42),
               frameon=False, fontsize=14)
    fig.tight_layout(rect=[0.01, 0.03, 0.80, 0.86])
    fig.savefig(os.path.join(OUT, "fig2_radar.png"))
    plt.close(fig)
    print("saved fig2")


# ================================================================ fig3 匹配几何（式二·式三）
def fig3():
    fig = plt.figure(figsize=(12, 6.75), dpi=200)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.15, 1], wspace=0.24)
    ax = fig.add_subplot(gs[0])
    _style_ax(ax, grid=False)

    origin = np.array([0.0, 0.0])
    uvec = np.array([1.0, 0.0])
    jobs = [("岗位A", 16, ACCENT, "cosθ = 0.96 → 强匹配", (0.50, 0.27)),
            ("岗位B", 42, GOLD, "cosθ = 0.74", (0.25, 0.44)),
            ("岗位C", 78, MUTED, "cosθ = 0.21 → 淘汰", (0.42, 0.60))]
    ax.add_patch(FancyArrowPatch(origin, uvec, arrowstyle="-|>", mutation_scale=28,
                                 color=PRIMARY, linewidth=3.4, zorder=4))
    ax.text(0.42, -0.11, "用户表示向量 u（式一）", color=PRIMARY, fontsize=16.5,
            fontweight="bold")
    for name, deg, color, note, note_xy in jobs:
        v = np.array([np.cos(np.radians(deg)), np.sin(np.radians(deg))]) * 0.92
        ax.add_patch(FancyArrowPatch(origin, v, arrowstyle="-|>", mutation_scale=20,
                                     color=color, linewidth=2.2, zorder=3, alpha=0.9))
        ax.text(v[0] * 1.12, v[1] * 1.12, name, color=color, fontsize=16,
                fontweight="bold", ha="center")
        # 标注放在箭头之间的空白区，绝不压在箭头线上
        ax.text(note_xy[0], note_xy[1], note, color=color, fontsize=13.5,
                ha="center", va="center", zorder=5,
                bbox=dict(fc="white", ec="none", alpha=1.0, pad=1.5))
    th = np.linspace(0, np.radians(42), 40)
    ax.plot(0.3 * np.cos(th), 0.3 * np.sin(th), color=SLATE, linewidth=1.4, linestyle="--")
    ax.text(0.35, 0.05, "θ", fontsize=19, color=SLATE, style="italic")
    ax.set_xlim(-0.15, 1.4); ax.set_ylim(-0.34, 1.18)
    ax.set_xticks([]); ax.set_yticks([])
    ax.text(-0.1, -0.26, "夹角越小，匹配程度越高；低于阈值的岗位直接淘汰",
            fontsize=15, color=SLATE)
    _titles(ax, "用户与岗位的匹配程度由向量夹角度量（式二）",
            "余弦相似度 cos(u, j) = u·j ∕ (|u|·|j|)",
            main_size=17.5, sub_size=14.5, pad=34)

    ax2 = fig.add_subplot(gs[1])
    _style_ax(ax2)
    x = np.linspace(-1, 1, 200)
    p = 1 / (1 + np.exp(-(3.2 * x)))
    ax2.plot(x, p, color=PRIMARY, linewidth=3)
    for xv, cv, lb in [(0.96, ACCENT, "A"), (0.74, GOLD, "B"), (0.21, MUTED, "C")]:
        yv = 1 / (1 + np.exp(-(3.2 * xv)))
        ax2.scatter([xv], [yv], s=110, c=cv, zorder=4, edgecolors="white", linewidths=1.4)
        ax2.annotate(lb, (xv, yv), xytext=(0, 11), textcoords="offset points",
                     ha="center", fontsize=15.5, color=cv, fontweight="bold")
    ax2.axhline(0.5, color=LINE, linewidth=1, linestyle="--")
    ax2.text(-0.96, 0.82, "冷启动时反馈修正项 δ = 0\n产生投递反馈后 δ 参与打分",
             fontsize=13.5, color=SLATE,
             bbox=dict(fc="white", ec=LINE, alpha=0.9, pad=4.5))
    ax2.set_xlabel("综合输入（s 为余弦相似度，δ 为反馈修正项）", color=SLATE, fontsize=15.5)
    ax2.set_ylabel("匹配分 p", color=SLATE, fontsize=15.5)
    _titles(ax2, "匹配分数由逻辑斯谛函数映射生成（式三）",
            "p = σ(w_s·s + w_δ·δ)",
            main_size=17.5, sub_size=14.5, pad=34)
    ax2.set_xlim(-1.05, 1.05); ax2.set_ylim(-0.05, 1.08)

    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig3_match_geometry.png"))
    plt.close(fig)
    print("saved fig3")


# ================================================================ fig4 三维超空间投影
def fig4(ids, names, X):
    Xc = X - X.mean(axis=0)
    _, s, vt = np.linalg.svd(Xc, full_matrices=False)
    proj = Xc @ vt.T[:, :3]
    var = s ** 2 / np.sum(s ** 2)
    t_idx = ids.index(next(i for i in ids if names[i] == TARGET_NAME))

    fig = plt.figure(figsize=(12, 6.75), dpi=200)
    ax = fig.add_subplot(111, projection="3d")
    depth = proj[:, 2]
    order = np.argsort(depth)
    for i in order:
        if i == t_idx:
            continue
        ax.scatter(proj[i, 0], proj[i, 1], proj[i, 2], s=220, c=MUTED,
                   alpha=0.55 + 0.4 * (depth[i] - depth.min()) / (np.ptp(depth) + 1e-9),
                   edgecolors="white", linewidths=1.4)
        ax.text(proj[i, 0], proj[i, 1], proj[i, 2] + 0.035, "  " + names[ids[i]],
                fontsize=15.5, color=SLATE)
    ax.scatter(*proj[t_idx], s=1000, marker="*", c=ACCENT, edgecolors="white",
               linewidths=2, zorder=10)
    ax.text(proj[t_idx, 0], proj[t_idx, 1], proj[t_idx, 2] + 0.05,
            "  %s（定位用户）" % TARGET_NAME, fontsize=17, color=ACCENT, fontweight="bold")
    pad = 0.3 * max(np.ptp(proj[:, 0]), np.ptp(proj[:, 1]), np.ptp(proj[:, 2]))
    ax.set_xlim(proj[:, 0].min() - pad, proj[:, 0].max() + pad)
    ax.set_ylim(proj[:, 1].min() - pad, proj[:, 1].max() + pad)
    ax.set_zlim(proj[:, 2].min() - pad, proj[:, 2].max() + pad)
    try:
        ax.set_box_aspect((1.2, 1, 0.8))
    except Exception:
        pass
    ax.set_xlabel("第一主成分（%.0f%%）" % (var[0] * 100), color=SLATE, labelpad=12, fontsize=15.5)
    ax.set_ylabel("第二主成分（%.0f%%）" % (var[1] * 100), color=SLATE, labelpad=12, fontsize=15.5)
    ax.set_zlabel("第三主成分（%.0f%%）" % (var[2] * 100), color=SLATE, labelpad=12, fontsize=15.5)
    ax.tick_params(labelsize=12, colors=MUTED)
    _titles(ax, "超几何空间画像：用户群体在三维主成分空间中的分布",
            "前三个主成分累计解释 %.0f%% 的方差，点与点的距离反映用户画像的差异"
            % (var[:3].sum() * 100),
            pad=40)
    ax.view_init(elev=22, azim=-52)
    for pane in (ax.xaxis, ax.yaxis, ax.zaxis):
        pane.pane.set_alpha(0.04)
        pane._axinfo["grid"].update(color=LINE, linewidth=0.8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig4_space3d.png"))
    plt.close(fig)
    print("saved fig4")


# ================================================================ fig5 岗位聚类图谱（真实 Boss 检索数据）
def _job_features():
    """从 jobs 表读取真实检索岗位，构建统一字段特征矩阵。"""
    import re
    deg_map = {"学历不限": 0.5, "大专": 1.0, "本科": 2.0, "硕士": 3.0, "博士": 4.0}
    exp_map = {"经验不限": 0.0, "应届生": 0.5, "1年以内": 0.7, "1-3年": 1.0,
               "3-5年": 2.0, "5-10年": 3.0, "10年以上": 4.0}
    kw_list = ["Python", "Java", "前端", "算法", "数据", "测试", "运维", "C++"]
    rows, metas = [], []
    with db.get_conn() as conn:
        recs = conn.execute("SELECT fields FROM jobs WHERE active=1").fetchall()
    for r in recs:
        f = json.loads(r["fields"])
        name = f.get("岗位名称", "")
        if not name or name.startswith("演示") or "127.0.0.1" in f.get("岗位链接", ""):
            continue  # 剔除演示岗与 mock 岗，只留真实 Boss 岗位
        m = re.search(r"(\d+)\s*-\s*(\d+)\s*[Kk]", f.get("薪资", ""))
        sal = (float(m.group(1)) + float(m.group(2))) / 2 if m else np.nan
        deg = deg_map.get(f.get("学历", ""), 2.0) / 4.0
        exp = exp_map.get(f.get("经验", ""), 0.0) / 4.0
        skl = min(len([s for s in re.split(r"[、,，\s]+", f.get("技能", "")) if s]), 8) / 8.0
        hay = (name + " " + f.get("技能", "") + " " + f.get("岗位描述", "")).lower()
        kws = [1.0 if k.lower() in hay else 0.0 for k in kw_list]
        rows.append([sal, deg, exp, skl] + kws)
        metas.append((name, f.get("行业", "") or "其他", sal))
    F = np.asarray(rows, dtype=float)
    col_mean = np.nanmean(F, axis=0)
    idx = np.where(np.isnan(F))
    F[idx] = np.take(col_mean, idx[1])
    mu, sd = F.mean(axis=0), F.std(axis=0) + 1e-9
    return (F - mu) / sd, metas


def fig5():
    from collections import Counter
    from matplotlib.lines import Line2D
    from matplotlib.ticker import MaxNLocator
    rng = np.random.default_rng(42)
    Fs, metas = _job_features()
    n = len(Fs)

    def kmeans(P, k):
        best = None
        for _ in range(30):
            cent = P[rng.choice(len(P), k, replace=False)]
            lab = np.zeros(len(P), dtype=int)
            for _ in range(50):
                d = ((P[:, None, :] - cent[None]) ** 2).sum(-1)
                lab = d.argmin(1)
                new = np.array([P[lab == j].mean(0) if (lab == j).any() else cent[j]
                                for j in range(k)])
                if np.allclose(new, cent):
                    break
                cent = new
            inertia = float(((P - cent[lab]) ** 2).sum())
            if best is None or inertia < best[0]:
                best = (inertia, lab.copy())
        return best[1]

    def silhouette(P, lab, k):
        D = np.sqrt(((P[:, None, :] - P[None]) ** 2).sum(-1))
        vals = []
        for i in range(len(P)):
            same = lab == lab[i]
            same[i] = False
            a = D[i, same].mean() if same.any() else 0.0
            b = min(D[i, lab == j].mean() for j in range(k)
                    if j != lab[i] and (lab == j).any())
            vals.append((b - a) / max(a, b) if max(a, b) > 0 else 0.0)
        return float(np.mean(vals))

    lab = kmeans(Fs, 5)
    best_k, best_lab, best_sil = 5, lab, silhouette(Fs, lab, 5)

    Xc = Fs - Fs.mean(axis=0)
    _, s, vt = np.linalg.svd(Xc, full_matrices=False)
    proj = Xc @ vt.T[:, :3]
    var = s ** 2 / np.sum(s ** 2)

    PALETTE = ["#4F46E5", "#E11D48", "#D97706", "#0D9488", "#7C3AED"]
    fig = plt.figure(figsize=(12, 6.75), dpi=200)
    ax = fig.add_axes([0.02, 0.04, 0.71, 0.81], projection="3d")

    for j in range(best_k):
        P = proj[lab == j]
        col = PALETTE[j % len(PALETTE)]
        c = P.mean(axis=0)
        if len(P) >= 3:
            cov = np.cov(P.T) + np.eye(3) * 1e-9
            vals, vecs = np.linalg.eigh(cov)
            radii = 2.0 * np.sqrt(np.maximum(vals, 1e-12))
            uu = np.linspace(0, 2 * np.pi, 24)
            vv = np.linspace(0, np.pi, 14)
            xs = np.outer(np.cos(uu), np.sin(vv))
            ys = np.outer(np.sin(uu), np.sin(vv))
            zs = np.outer(np.ones_like(uu), np.cos(vv))
            sph = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], 0)
            ell = c[:, None] + vecs @ (radii[:, None] * sph)
            ax.plot_surface(ell[0].reshape(xs.shape), ell[1].reshape(ys.shape),
                            ell[2].reshape(zs.shape), color=col, alpha=0.09,
                            linewidth=0)
        ax.scatter(P[:, 0], P[:, 1], P[:, 2], s=34, c=col, alpha=0.62,
                   edgecolors="white", linewidths=0.4, depthshade=False)

    pad = 0.035 * np.maximum(np.ptp(proj, axis=0), 0.5)
    ax.set_xlim(proj[:, 0].min() - pad[0], proj[:, 0].max() + pad[0])
    ax.set_ylim(proj[:, 1].min() - pad[1], proj[:, 1].max() + pad[1])
    ax.set_zlim(proj[:, 2].min() - pad[2], proj[:, 2].max() + pad[2])
    try:
        ax.set_box_aspect((1.75, 1.15, 0.9))
    except Exception:
        pass
    ax.set_xlabel("第一主成分（%.0f%%）" % (var[0] * 100), color=SLATE, labelpad=10, fontsize=17)
    ax.set_ylabel("第二主成分（%.0f%%）" % (var[1] * 100), color=SLATE, labelpad=10, fontsize=17)
    ax.set_zlabel("第三主成分（%.0f%%）" % (var[2] * 100), color=SLATE, labelpad=10, fontsize=17)
    ax.tick_params(labelsize=13, colors=MUTED)
    for _axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        _axis.set_major_locator(MaxNLocator(5))
    _titles(ax, "岗位画像：检索岗位在特征空间中自动聚类",
            "统一字段特征经 K 均值聚类（K=5，轮廓系数 %.2f）与主成分分析（PCA）投影至三维"
            % best_sil,
            main_size=23, sub_size=16, pad=34)
    ax.view_init(elev=15, azim=-58)
    for pane in (ax.xaxis, ax.yaxis, ax.zaxis):
        pane.pane.set_alpha(0.02)
        pane._axinfo["grid"].update(color="#EEF2F7", linewidth=0.7)

    handles = []
    for j in range(best_k):
        cnt = int((lab == j).sum())
        mem = [metas[i] for i in range(n) if lab[i] == j]
        sal_vals = [m[2] for m in mem if not np.isnan(m[2])]
        sal_txt = " · 均薪%.0fK" % (sum(sal_vals) / len(sal_vals)) if sal_vals else ""
        handles.append(Line2D([0], [0], marker="o", color="none",
                              markerfacecolor=PALETTE[j % len(PALETTE)], markersize=13,
                              label="族%d（%d 个）%s" % (j + 1, cnt, sal_txt)))
    fig.legend(handles=handles, loc="center left", bbox_to_anchor=(0.745, 0.58),
               frameon=False, fontsize=14, labelspacing=1.5)
    fig.text(0.755, 0.10,
             "数据：Boss 直聘登录态检索，去重入库\n%d 个真实岗位；特征取自统一字段\n（薪资、学历、经验、技能、关键词）" % n,
             fontsize=11.5, color=MUTED, linespacing=1.6)
    fig.savefig(os.path.join(OUT, "fig5_cluster3d.png"))
    plt.close(fig)
    print("saved fig5 (K=%d, silhouette=%.2f, n=%d)" % (best_k, best_sil, n))


ids, names, X, feat = _load()
fig1(ids, names, X)
fig2(feat)
fig3()
fig4(ids, names, X)
fig5()
print("=== 5 张答辩用图完成 →", OUT)
