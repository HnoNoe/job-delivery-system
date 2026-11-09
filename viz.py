"""可视化层 —— 全部图表的数据准备与构造集中在此（app.py 只做布局）。

设计原则：
- 每个函数返回 plotly Figure 或 None（数据不足时），不写裸颜色值，统一走 theme 令牌；
- 数据准备与图形构造同层，便于复用（_design_preview、未来测试）；
- 渲染入口始终是 theme.chart(fig)，本模块不直接调 streamlit。
"""
import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

import db
import recommend
import theme

# 六维满分（技能40+方向25+学历15+薪资10+行业5+城市5）
DIM_MAXS = [40, 25, 15, 10, 5, 5]


# ---------------------------------------------------------------- 等级与匹配分
def grade_donut(targets):
    """岗位等级分布环形图（中心标注总数）。"""
    gcount = {g: sum(1 for j in targets if j["等级"] == g) for g in ("A", "B", "C")}
    gcount = {k: v for k, v in gcount.items() if v}
    if not gcount:
        return None
    gd = pd.DataFrame({"等级": [f"{k}级" for k in gcount], "数量": list(gcount.values())})
    fig = px.pie(gd, names="等级", values="数量", hole=0.5,
                 color="等级", color_discrete_map=theme.GRADE,
                 title="岗位等级分布（A=强 / B=机会 / C=不推荐）")
    fig.update_traces(textposition="inside", textinfo="label+value",
                      marker=dict(line=dict(color="#FFFFFF", width=2)))
    fig.update_layout(annotations=[dict(text=f"{len(targets)} 岗", x=0.5, y=0.5, showarrow=False,
                                        font=dict(size=17, color=theme.INK,
                                                  family=theme.FONT_STACK))])
    return fig


def score_bar(targets):
    """岗位匹配分横向柱状图（式三 p，降序，值标签三位小数）。"""
    sdf = pd.DataFrame([{"岗位": j["岗位名称"][:8], "匹配分p": round(float(j["score"]), 4)}
                        for j in targets])
    if sdf.empty:
        return None
    fig = px.bar(sdf, x="匹配分p", y="岗位", orientation="h",
                 title="岗位匹配分（式三 p）", text="匹配分p")
    fig.update_traces(marker_color=theme.PRIMARY, texttemplate="%{text:.3f}",
                      textposition="outside")
    fig.update_layout(yaxis=dict(autorange="reversed", gridcolor="rgba(0,0,0,0)"))
    return fig


def evolution_bar(rematch, old_map):
    """匹配分进化对比（反馈前 vs 反馈后，式三 δ 生效可视化）。"""
    rows = [{"岗位": x["job"].get("岗位名称", "")[:10],
             "反馈前": round(float(old_map.get(x.get("job_id", x["job"].get("岗位名称", "")), 0)), 4),
             "反馈后": round(float(x["score"]), 4)} for x in rematch]
    if not rows:
        return None
    return px.bar(pd.DataFrame(rows), x="岗位", y=["反馈前", "反馈后"], barmode="group",
                  title="匹配分进化（式三 δ 生效）", color_discrete_map=theme.EVOLUTION)


# ---------------------------------------------------------------- 六维适配
def _dim_rows(job):
    """[(维度名, 得分, 满分)]，数据不足返回 []。"""
    bd = job.get("分数明细") or []
    if not bd:
        return []
    dims = [p[0].replace("匹配", "") for p in bd]
    scores = [p[1] for p in bd]
    return list(zip(dims, scores, DIM_MAXS[:len(bd)]))


def six_dim_radar(job):
    """第一名岗位的六维适配雷达图（得分/满分归一）。"""
    rows = _dim_rows(job)
    if not rows:
        return None
    dims = [r[0] for r in rows]
    vals = [max(0, s) / m for _, s, m in rows]
    fig = go.Figure(go.Scatterpolar(
        r=vals + vals[:1], theta=dims + dims[:1], fill="toself",
        line=dict(color=theme.PRIMARY, width=2.5),
        fillcolor="rgba(79, 70, 229, 0.18)"))
    fig.update_layout(
        polar=dict(radialaxis=dict(range=[0, 1], showticklabels=False, gridcolor=theme.LINE),
                   angularaxis=dict(gridcolor=theme.LINE), bgcolor="rgba(0,0,0,0)"),
        title="六维适配度（%s）" % job["岗位名称"][:8],
        height=340, margin=dict(l=50, r=50, t=60, b=30))
    return fig


def six_dim_bars(job):
    """第一名岗位的六维得分 vs 满分分组柱状图。"""
    rows = _dim_rows(job)
    if not rows:
        return None
    bdf = pd.DataFrame({"维度": [r[0] for r in rows],
                        "得分": [r[1] for r in rows],
                        "满分": [r[2] for r in rows]})
    return px.bar(bdf, x="维度", y=["得分", "满分"], barmode="group",
                  title="六维得分 vs 满分",
                  color_discrete_map={"得分": theme.PRIMARY, "满分": theme.TRACK})


def stacked_dims(targets):
    """所有岗位六维得分堆叠柱状图。"""
    rows = []
    for j in targets:
        row = {"岗位": j["岗位名称"][:10]}
        for p in (j.get("分数明细") or []):
            row[p[0].replace("匹配", "")] = p[1]
        rows.append(row)
    if not rows:
        return None
    stack = pd.DataFrame(rows).set_index("岗位")
    return px.bar(stack, x=stack.index, y=stack.columns, barmode="stack",
                  title="所有岗位六维得分堆叠")


# ---------------------------------------------------------------- 技能与漏斗
def skill_coverage(targets, user_l2):
    """技能覆盖分析。返回 (fig|None, 用户技能列表)。"""
    user_skills = set(recommend.extract_user_skills(user_l2))
    rows = []
    for j in targets:
        job_skills = set(recommend.extract_job_skills({"技能": j.get("技能", ""),
                                                       "岗位名称": j.get("岗位名称", "")}))
        hit = user_skills & job_skills
        rows.append({"岗位": j.get("岗位名称", "")[:10], "命中技能数": len(hit),
                     "覆盖率%": round(100 * len(hit) / len(job_skills)) if job_skills else 0})
    if not rows:
        return None, sorted(user_skills)
    fig = px.bar(pd.DataFrame(rows), x="岗位", y=["命中技能数", "覆盖率%"], barmode="group",
                 title="技能覆盖分析（用户技能命中岗位要求）",
                 color_discrete_map={"命中技能数": theme.PRIMARY, "覆盖率%": theme.INFO})
    return fig, sorted(user_skills)


def delivery_funnel(retrieved, matched, delivered, interviewed):
    """投递转化漏斗（检索→匹配→投递→进面试）。"""
    if not (retrieved or matched):
        return None
    fig = go.Figure(go.Funnel(
        y=["检索", "匹配", "投递", "进面试"],
        x=[retrieved, matched, delivered, interviewed],
        textinfo="value+percent initial",
        marker=dict(color=[theme.TRACK, "#818CF8", theme.VIOLET, theme.PRIMARY]),
        connector=dict(line=dict(color=theme.LINE, width=1))))
    fig.update_layout(title="投递转化漏斗", height=320)
    return fig


def funnel_rates(retrieved, matched, delivered, interviewed):
    """漏斗相邻环节转化率（%），供文案展示。"""
    return (round(100 * matched / retrieved) if retrieved else 0,
            round(100 * delivered / matched) if matched else 0,
            round(100 * interviewed / delivered) if delivered else 0)


# ---------------------------------------------------------------- 三维匹配空间
def _fit_point(job):
    """岗位在三维匹配空间的坐标 (技能, 方向, 条件)，各自归一化到 0~100。

    技能 = 技能匹配得分 / 40；方向 = 岗位方向得分 / 25；
    条件 = 学历+薪资+行业+城市 / 35（四项先求和再整体截断，负分按 0 计）。
    """
    scores = {p[0]: p[1] for p in (job.get("分数明细") or [])}

    def pct(v, full):
        return max(0.0, min(100.0, 100.0 * float(v) / full))

    cond = sum(scores.get(k, 0) for k in ("学历", "薪资", "行业", "城市"))
    return pct(scores.get("技能匹配", 0), 40), pct(scores.get("岗位方向", 0), 25), pct(cond, 35)


def _has_dims(job):
    """是否有六维分数明细；缺失时坐标属于“未知”，不能当成真实 0 分。"""
    return bool(job.get("分数明细"))


def _coord_key(x, y, z):
    """同坐标聚合键：归一到 6 位小数，吸收浮点误差但不合并屏幕上只是相邻的点。"""
    return "%.6f|%.6f|%.6f" % (round(x, 6), round(y, 6), round(z, 6))


def build_match_space_data(targets):
    """把目标岗位整理成“坐标组 + 岗位索引”，供三维图与详情联动使用。

    返回：
      groups: [{group_id, coords, task_ids, jobs, count}]，按岗位原始顺序首次出现排序
      jobs_by_id: {task_id: {task_id, job, coords, group_id, index}}
      default_task_id: 第一个有效岗位（原顺序）
      unknown_task_ids: 缺少六维分数、无法定位的岗位
    岗位缺少 task_id 时使用“序号+名称”的稳定替代键，保证同名岗位不冲突。
    """
    jobs_by_id, groups, unknown = {}, {}, []
    for index, job in enumerate(targets or []):
        task_id = job.get("task_id")
        if task_id in (None, ""):
            task_id = "未编号-%d-%s" % (index, job.get("岗位名称", ""))
        task_id = str(task_id)
        if task_id in jobs_by_id:
            task_id = "%s#%d" % (task_id, index)

        if _has_dims(job):
            coords = _fit_point(job)
            group_id = _coord_key(*coords)
        else:
            coords, group_id = None, None

        jobs_by_id[task_id] = {"task_id": task_id, "job": job,
                               "coords": coords, "group_id": group_id, "index": index}
        if group_id is None:
            unknown.append(task_id)
            continue
        group = groups.get(group_id)
        if group is None:
            group = {"group_id": group_id, "coords": list(coords),
                     "task_ids": [], "jobs": []}
            groups[group_id] = group
        group["task_ids"].append(task_id)
        group["jobs"].append(job)

    ordered = list(groups.values())
    for group in ordered:
        group["count"] = len(group["task_ids"])

    default_task_id = next(iter(jobs_by_id), None)
    return {
        "groups": ordered,
        "group_by_id": groups,
        "jobs_by_id": jobs_by_id,
        "default_task_id": default_task_id,
        "job_count": len(jobs_by_id),
        "group_count": len(ordered),
        "unknown_task_ids": unknown,
    }


def resolve_selected_task(space, selected_task_id):
    """选中态解析：原选中任务仍存在就保留，否则回到第一个有效岗位。"""
    jobs = (space or {}).get("jobs_by_id") or {}
    if selected_task_id in jobs:
        return selected_task_id
    return (space or {}).get("default_task_id")


def match_space_rows(targets):
    """全部岗位明细（“查看全部岗位”折叠区用）；缺分数时明确显示“未知”。"""
    rows = []
    for job in targets or []:
        if _has_dims(job):
            x, y, z = _fit_point(job)
            pos = (round(x), round(y), round(z))
        else:
            pos = ("未知", "未知", "未知")
        score = job.get("score")
        rows.append({
            "岗位": job.get("岗位名称", ""),
            "单位": job.get("单位名称", ""),
            "等级": job.get("等级", ""),
            "匹配分": round(float(score), 3) if score is not None else "未知",
            "技能适配": pos[0], "方向适配": pos[1], "条件适配": pos[2],
        })
    return rows


# ---------------------------------------------------------------- 语义空间
def pca_scatter(user_id):
    """岗位语义空间 PCA 散点图（★=用户画像）。降维失败或数据不足返回 None。"""
    try:
        import numpy as np
        import user_profile as profile_mod
        prof = profile_mod.build_profile(user_id)
        uv = prof.get("user_vec")
        conn = db.get_conn()
        jrows = conn.execute("SELECT j.fields, j.embedding FROM jobs j JOIN user_jobs u ON u.job_id=j.job_id WHERE u.user_id=?", (user_id,)).fetchall()
        conn.close()
        vecs, names = [], []
        for jr in jrows:
            if jr["embedding"]:
                vecs.append(np.asarray(json.loads(jr["embedding"])))
                names.append(json.loads(jr["fields"]).get("岗位名称", "")[:8])
        if uv is None or len(vecs) < 2:
            return None
        allv = np.vstack([np.asarray(uv)] + vecs)
        centered = allv - allv.mean(axis=0)
        _, _, vt = np.linalg.svd(centered, full_matrices=False)
        pca = centered @ vt.T[:, :2]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=pca[1:, 0], y=pca[1:, 1], mode="markers+text",
                                 text=names, textposition="top center",
                                 marker=dict(size=11, color=theme.MUTED,
                                             line=dict(color="#FFFFFF", width=1)),
                                 name="岗位"))
        fig.add_trace(go.Scatter(x=[pca[0, 0]], y=[pca[0, 1]], mode="markers",
                                 marker=dict(size=20, color=theme.DANGER, symbol="star",
                                             line=dict(color="#FFFFFF", width=1.5)),
                                 name="你的画像"))
        fig.update_layout(title="岗位语义空间（PCA：★=你，越近越匹配）", height=360,
                          xaxis=dict(showticklabels=False),
                          yaxis=dict(showticklabels=False))
        return fig
    except Exception:
        return None  # 降维失败不阻断主流程


# ---------------------------------------------------------------- 结果统计
def result_pie(results):
    """投递结果分布环形图（进面试绿 / 未进面试红）。"""
    if not results:
        return None
    rcount = {x: results.count(x) for x in dict.fromkeys(results)}
    rd = pd.DataFrame({"结果": list(rcount), "数量": list(rcount.values())})
    fig = px.pie(rd, names="结果", values="数量", hole=0.5, title="投递结果分布",
                 color="结果",
                 color_discrete_map={"进面试": theme.SUCCESS, "未进面试": theme.DANGER})
    fig.update_traces(textposition="inside", textinfo="label+value",
                      marker=dict(line=dict(color="#FFFFFF", width=2)))
    return fig


def weight_pie(weights, exp_names):
    """经历权重 α_k 环形图（式一）。"""
    if not weights:
        return None
    wd = pd.DataFrame({"经历": exp_names[:len(weights)],
                       "权重": [round(float(x), 4) for x in weights]})
    fig = px.pie(wd, names="经历", values="权重", hole=0.5, title="经历权重 α_k（式一）")
    fig.update_traces(textposition="inside", textinfo="label+percent",
                      marker=dict(line=dict(color="#FFFFFF", width=2)))
    return fig
