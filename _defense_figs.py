"""答辩 PPT 用图：用户定位 · 超几何空间画像（4 张，2400x1350）。

数据源为本机演示库（6 个用户，式一 user_vec 与统一字段指标），
运行：python _defense_figs.py  →  docs/defense/fig1~4.png
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
    "font.size": 13,
})
TARGET_NAME = "张三"


def _style_ax(ax, grid=True):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    if grid:
        ax.grid(True, color="#EEF2F7", linewidth=1)
        ax.set_axisbelow(True)


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

    # 群体分布 2σ 椭圆
    cov = np.cov(proj.T)
    vals, vecs = np.linalg.eigh(cov)
    ang = np.degrees(np.arctan2(vecs[1, 1], vecs[0, 1]))
    w, h = 2 * 2.0 * np.sqrt(np.maximum(vals, 1e-12))
    ax.add_patch(Ellipse(proj.mean(axis=0), w, h, angle=ang,
                         facecolor=PRIMARY, alpha=0.07, edgecolor=PRIMARY,
                         linewidth=1.2, linestyle="--", zorder=1, label="群体分布（2σ 椭圆）"))

    others = [i for i in range(len(ids)) if i != t_idx]
    ax.scatter(proj[others, 0], proj[others, 1], s=90, c=MUTED, alpha=0.9,
               edgecolors="white", linewidths=1.2, zorder=3, label="其他用户")
    for i in others:
        ax.annotate(names[ids[i]], (proj[i, 0], proj[i, 1]),
                    xytext=(0, 10), textcoords="offset points",
                    ha="center", fontsize=12, color=SLATE)
    # 用户向量箭头（质心→目标）
    ax.add_patch(FancyArrowPatch((0, 0), proj[t_idx], arrowstyle="-|>",
                                 mutation_scale=22, color=ACCENT, alpha=0.55,
                                 linewidth=2, zorder=2))
    ax.scatter(*proj[t_idx], s=460, marker="*", c=ACCENT, edgecolors="white",
               linewidths=1.6, zorder=4, label="定位用户（%s）" % TARGET_NAME)
    ax.annotate(TARGET_NAME, proj[t_idx], xytext=(14, 10), textcoords="offset points",
                fontsize=13.5, color=ACCENT, fontweight="bold")
    mid = proj[t_idx] / 2
    ax.annotate("式一用户向量 u", mid, xytext=(10, -20),
                textcoords="offset points", fontsize=12.5, color=ACCENT,
                fontweight="bold",
                bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.5))

    ax.set_xlabel("PC1（解释方差 %.1f%%）" % (var[0] * 100), color=SLATE)
    ax.set_ylabel("PC2（解释方差 %.1f%%）" % (var[1] * 100), color=SLATE)
    ax.set_title("超几何空间画像 · 语义空间用户定位\n式一凸组合用户表示经 PCA 投影至二维",
                 fontsize=17, color=INK, fontweight="bold", pad=14)
    ax.legend(loc="best", frameon=False, fontsize=12)
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
    ax.plot(ang, mvals, color=MUTED, linewidth=2, label="群体均值（n=6）")
    ax.fill(ang, mvals, color=MUTED, alpha=0.12)
    ax.plot(ang, tvals, color=PRIMARY, linewidth=2.6, label="定位用户（%s）" % TARGET_NAME)
    ax.fill(ang, tvals, color=PRIMARY, alpha=0.18)
    ax.set_xticks(ang[:-1])
    ax.set_xticklabels(axes_names, fontsize=13.5, color=INK)
    ax.set_ylim(0, 1.05)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0.25", "0.50", "0.75", "1.00"], fontsize=10, color=MUTED)
    ax.grid(color=LINE, linewidth=1)
    ax.spines["polar"].set_color(LINE)
    for a, v in zip(ang[:-1], tvals[:-1]):
        ax.annotate("%.2f" % v, (a, v * 0.92), xytext=(0, 5), textcoords="offset points",
                    ha="center", fontsize=10.5, color=PRIMARY, fontweight="bold",
                    bbox=dict(fc="white", ec="none", alpha=0.85, pad=0.8))
    ax.set_title("统一字段六维画像 · 定位用户 vs 群体\n（指标已归一化至 0~1）",
                 fontsize=17, color=INK, fontweight="bold", pad=22)
    ax.legend(loc="lower right", bbox_to_anchor=(1.16, -0.06), frameon=False, fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig2_radar.png"))
    plt.close(fig)
    print("saved fig2")


# ================================================================ fig3 匹配几何（式二·式三）
def fig3():
    fig = plt.figure(figsize=(12, 6.75), dpi=200)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.15, 1], wspace=0.22)
    ax = fig.add_subplot(gs[0])
    _style_ax(ax, grid=False)

    origin = np.array([0.0, 0.0])
    uvec = np.array([1.0, 0.0])
    jobs = [("岗位A", 16, ACCENT, "cosθ=0.96", "A 级强匹配"),
            ("岗位B", 42, GOLD, "cosθ=0.74", None),
            ("岗位C", 78, MUTED, "cosθ=0.21", "淘汰")]
    ax.add_patch(FancyArrowPatch(origin, uvec, arrowstyle="-|>", mutation_scale=26,
                                 color=PRIMARY, linewidth=3.2, zorder=4))
    ax.text(0.55, -0.09, "用户向量 u（式一）", color=PRIMARY, fontsize=13.5, fontweight="bold")
    for name, deg, color, note, verdict in jobs:
        v = np.array([np.cos(np.radians(deg)), np.sin(np.radians(deg))]) * 0.92
        ax.add_patch(FancyArrowPatch(origin, v, arrowstyle="-|>", mutation_scale=18,
                                     color=color, linewidth=2, zorder=3, alpha=0.9))
        ax.text(v[0] * 1.1, v[1] * 1.1, name, color=color, fontsize=12.5, fontweight="bold",
                ha="center")
        lb = note + (" → " + verdict if verdict else "")
        ax.annotate(lb, v * 0.55, xytext=(0, 10), textcoords="offset points",
                    color=color, fontsize=10.5, ha="center",
                    bbox=dict(fc="white", ec="none", alpha=0.85, pad=0.8))
    th = np.linspace(0, np.radians(42), 40)
    ax.plot(0.4 * np.cos(th), 0.4 * np.sin(th), color=SLATE, linewidth=1.4, linestyle="--")
    ax.text(0.47, 0.13, "θ", fontsize=15, color=SLATE, style="italic")
    ax.set_xlim(-0.15, 1.35); ax.set_ylim(-0.3, 1.15)
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title("式二 · 向量空间的匹配几何\ncos(u, j) = u·j / (|u||j|)",
                 fontsize=14.5, color=INK, fontweight="bold", pad=10)

    ax2 = fig.add_subplot(gs[1])
    _style_ax(ax2)
    x = np.linspace(-1, 1, 200)
    p = 1 / (1 + np.exp(-(3.2 * x)))
    ax2.plot(x, p, color=PRIMARY, linewidth=2.8)
    for xv, cv, lb in [(0.96, ACCENT, "A"), (0.74, GOLD, "B"), (0.21, MUTED, "C")]:
        yv = 1 / (1 + np.exp(-(3.2 * xv)))
        ax2.scatter([xv], [yv], s=80, c=cv, zorder=4, edgecolors="white", linewidths=1.2)
        ax2.annotate(lb, (xv, yv), xytext=(0, 9), textcoords="offset points",
                     ha="center", fontsize=12, color=cv, fontweight="bold")
    ax2.axhline(0.5, color=LINE, linewidth=1, linestyle="--")
    ax2.set_xlabel("综合输入  w_s·cosθ + w_δ·δ", color=SLATE)
    ax2.set_ylabel("匹配分 p", color=SLATE)
    ax2.set_title("式三 · 匹配分映射\np = σ(w_s·s + w_δ·δ)，冷启动 δ=0，反馈后 δ 生效",
                  fontsize=14.5, color=INK, fontweight="bold", pad=10)
    ax2.set_xlim(-1.05, 1.05); ax2.set_ylim(-0.05, 1.05)

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
        ax.scatter(proj[i, 0], proj[i, 1], proj[i, 2], s=180, c=MUTED,
                   alpha=0.55 + 0.4 * (depth[i] - depth.min()) / (np.ptp(depth) + 1e-9),
                   edgecolors="white", linewidths=1.4)
        ax.text(proj[i, 0], proj[i, 1], proj[i, 2] + 0.03, "  " + names[ids[i]],
                fontsize=12.5, color=SLATE)
    ax.scatter(*proj[t_idx], s=900, marker="*", c=ACCENT, edgecolors="white",
               linewidths=2, zorder=10)
    ax.text(proj[t_idx, 0], proj[t_idx, 1], proj[t_idx, 2] + 0.045,
            "  %s（定位用户）" % TARGET_NAME, fontsize=14, color=ACCENT, fontweight="bold")
    pad = 0.3 * max(np.ptp(proj[:, 0]), np.ptp(proj[:, 1]), np.ptp(proj[:, 2]))
    ax.set_xlim(proj[:, 0].min() - pad, proj[:, 0].max() + pad)
    ax.set_ylim(proj[:, 1].min() - pad, proj[:, 1].max() + pad)
    ax.set_zlim(proj[:, 2].min() - pad, proj[:, 2].max() + pad)
    try:
        ax.set_box_aspect((1.2, 1, 0.8))
    except Exception:
        pass
    ax.set_xlabel("PC1 (%.0f%%)" % (var[0] * 100), color=SLATE, labelpad=10, fontsize=13)
    ax.set_ylabel("PC2 (%.0f%%)" % (var[1] * 100), color=SLATE, labelpad=10, fontsize=13)
    ax.set_zlabel("PC3 (%.0f%%)" % (var[2] * 100), color=SLATE, labelpad=10, fontsize=13)
    ax.tick_params(labelsize=10, colors=MUTED)
    ax.set_title("超几何空间画像 · 三维投影\n高维用户表示在前三主成分上的分布",
                 fontsize=17, color=INK, fontweight="bold", pad=16)
    ax.view_init(elev=22, azim=-52)
    for pane in (ax.xaxis, ax.yaxis, ax.zaxis):
        pane.pane.set_alpha(0.04)
        pane._axinfo["grid"].update(color=LINE, linewidth=0.8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig4_space3d.png"))
    plt.close(fig)
    print("saved fig4")


ids, names, X, feat = _load()
fig1(ids, names, X)
fig2(feat)
fig3()
fig4(ids, names, X)
print("=== 4 张答辩用图完成 →", OUT)
