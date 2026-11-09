"""第⑤步「岗位匹配空间」分析工作台。

界面本体是一个存放于 `components/match_space/` 的轻量 Streamlit 组件（原生 HTML/CSS/SVG，
无第三方前端依赖）：左侧三维正交投影 + 右侧岗位详情，支持点击点位、同坐标岗位切换、
拖动旋转与复位视角。Python 侧只负责把真实 `target_jobs` / 人物画像整理成组件参数，
并用稳定 `task_id` 维护选中态。

数据契约：
    jobs: [{task_id, name, company, salary, grade, score, x, y, z, reasons}]
    坐标为 None 表示缺少六维分数（不画入图，详情显示“未知”）。
"""
from pathlib import Path
import sys

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import theme
import viz


def _component_dir():
    """定位组件目录：源码运行用模块同目录；PyInstaller 便携版用 _MEIPASS。"""
    roots = [Path(__file__).resolve().parent]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    for root in roots:
        candidate = root / "components" / "match_space"
        if candidate.joinpath("index.html").is_file():
            return candidate
    return roots[0] / "components" / "match_space"


_COMPONENT_DIR = _component_dir()
_component = None


def _get_component():
    """惰性声明组件（组件目录缺失时由调用方兜底）。"""
    global _component
    if _component is None:
        _component = components.declare_component(
            "match_space_workbench", path=str(_COMPONENT_DIR))
    return _component


def _theme_payload():
    colors = theme.match_space_colors()
    return {
        "surface": colors["bg"], "subtle": colors["panel"], "ink": colors["ink"],
        "secondary": colors["sub"], "line": colors["line"], "grid": colors["grid"],
        "other": colors["dot"], "accent": colors["accent"], "wash": colors["accent_soft"],
    }


def _profile_payload(persona_data):
    persona_data = persona_data or {}
    name = persona_data.get("姓名") or "未填写"
    directions = persona_data.get("求职方向") or []
    skills = persona_data.get("技能标签") or []
    return {
        "name": name,
        "initial": name[:1] if name and name != "未填写" else "我",
        "identity": persona_data.get("身份") or "",
        "direction": "、".join(directions[:2]),
        "skills": "、".join(skills[:5]),
    }


def _jobs_payload(space):
    jobs = []
    for task_id, record in space["jobs_by_id"].items():
        job = record["job"]
        coords = record["coords"] or (None, None, None)
        score = job.get("score")
        jobs.append({
            "task_id": task_id,
            "name": job.get("岗位名称") or "未命名岗位",
            "company": job.get("单位名称") or "",
            "salary": job.get("薪资") or "",
            "grade": job.get("等级") or "",
            "score": float(score) if score is not None else None,
            "x": coords[0], "y": coords[1], "z": coords[2],
        })
    return jobs


def render(targets, persona_data=None, key_prefix="ms", demo_label=None):
    """渲染分析工作台。targets 为 pipeline 的 target_jobs。

    demo_label: 仅视觉验收页使用（例如“示意图 · 合成数据”），正式页面留空。
    """
    space = viz.build_match_space_data(targets)
    if not space["job_count"]:
        st.caption("暂无岗位可绘制：完成第④步生成投递材料后这里会出现匹配空间。")
        return

    selected_key = key_prefix + "_selected_task"
    selected = viz.resolve_selected_task(space, st.session_state.get(selected_key))
    st.session_state[selected_key] = selected

    if not _COMPONENT_DIR.joinpath("index.html").exists():
        st.warning("匹配空间组件缺失：components/match_space/index.html 不存在。")
        return

    value = _get_component()(
        jobs=_jobs_payload(space),
        profile=_profile_payload(persona_data),
        selected=selected,
        theme=_theme_payload(),
        demo_label=demo_label,
        key=key_prefix + "_space",
        default=None,
    )
    picked = value.get("task_id") if isinstance(value, dict) else None
    if picked and str(picked) in space["jobs_by_id"]:
        st.session_state[selected_key] = str(picked)

    with st.expander("查看全部岗位（%d）" % space["job_count"], expanded=False):
        rows = viz.match_space_rows(targets)
        theme.dataframe(pd.DataFrame(rows), hide_index=True,
                        height=min(38 * (len(rows) + 1), 320))
        if space["unknown_task_ids"]:
            st.caption("其中 %d 个岗位缺少六维分数，坐标显示为“未知”，未画入三维图。"
                       % len(space["unknown_task_ids"]))
