"""用户画像广场 —— 联动投影台。

左侧三维总览 + 右侧 XY / XZ 二维投影 + 下方人物详情；三张图共享同一批用户、
同一个 `user_id` 选中态。数据准备、缺失原因、坐标范围与 PCA 都在
`profile_plaza.py` 中一次算好，前端只做投影与联动。
"""
import pandas as pd
import streamlit as st

import db
import profile_plaza
import theme
import viz

st.set_page_config(page_title="用户画像广场 · 联动投影台", page_icon="🧭", layout="wide")
theme.apply()
db.init_db()

# Streamlit 的顶栏背景取自 body（而非 .stApp）；显式暗色主题时随页面一起转暗，
# 避免出现“正文暗、顶栏白”的混合主题。颜色仍来自 theme.plaza_colors()。
if theme.is_dark():
    _plaza_surface = theme.plaza_colors()["surface"]
    st.markdown(
        "<style>html, body, [data-testid='stHeader'], [data-testid='stToolbar'] "
        "{ background: %s !important; }</style>" % _plaza_surface,
        unsafe_allow_html=True)

st.markdown("## 🧭 用户画像广场")
st.caption("群体分布与个体定位：左侧三维总览 + 右侧 XY / XZ 投影；"
           "三图共享同一批用户与同一个选中人物，点任意视图即可联动。")

df = viz.user_feature_table()
if df.empty:
    theme.empty_state("🧭", "还没有用户数据",
                      "回到主页完成 ①→④ 步后，用户画像会出现在这里；"
                      "多用几个人的信息跑几轮，广场就热闹了")
    st.stop()

# ---------------- 一行概览（不改变原有统计口径） ----------------
_n = len(df)
_gpa = df["GPA"].mean() if df["GPA"].notna().any() else None
_match = df["平均匹配分"].mean() if df["平均匹配分"].notna().any() else None
st.caption(
    "用户 **%d** · 平均 GPA **%s** · 总投递 **%d** · 平均匹配分 **%s**"
    % (_n, "%.2f" % _gpa if _gpa is not None else "—",
       int(df["累计投递"].sum()),
       "%.3f" % _match if _match is not None else "—"))

# ---------------- 空间与视图 ----------------
_c1, _c2 = st.columns([1.7, 1.3])
_mode_label = _c1.radio("空间模式", ["指标空间", "语义空间（式一 PCA）"],
                        horizontal=True, label_visibility="collapsed")
mode = "metrics" if _mode_label == "指标空间" else "semantic"
_view3d = _c2.toggle("三维联动模式（关闭为二维查看）", value=True)

if mode == "metrics":
    _axis_ids = list(profile_plaza.METRIC_AXES)

    def _axis_name(axis_id):
        return profile_plaza.AXIS_META[axis_id]["label"]

    def _ensure_axis_state(key, default, options):
        if st.session_state.get(key) not in options:
            st.session_state[key] = default

    _ax1, _ax2, _ax3 = st.columns(3)
    _ensure_axis_state("plaza_axis_x", profile_plaza.DEFAULT_AXES[0], _axis_ids)
    _x = _ax1.selectbox("X 轴", _axis_ids, key="plaza_axis_x", format_func=_axis_name)
    _y_options = [a for a in _axis_ids if a != _x]
    _ensure_axis_state("plaza_axis_y", profile_plaza.DEFAULT_AXES[1], _y_options)
    _y = _ax2.selectbox("Y 轴", _y_options, key="plaza_axis_y", format_func=_axis_name)
    _z_options = [a for a in _axis_ids if a not in (_x, _y)]
    _ensure_axis_state("plaza_axis_z", profile_plaza.DEFAULT_AXES[2], _z_options)
    _z = _ax3.selectbox("Z 轴", _z_options, key="plaza_axis_z", format_func=_axis_name)
    axes = (_x, _y, _z)
    st.caption("轴不可重复；GPA/排名为 0~1 归一值，进面试率按百分比显示，计数轴用整数刻度。")
else:
    axes = profile_plaza.SEMANTIC_AXES
    st.caption("语义空间：每位用户取最新画像快照的式一用户向量 u = Σ α_k·v_k，"
               "只做一次 PCA，三张图共用同一组 PC1/PC2/PC3 坐标；邻近只表示投影距离，"
               "不表示用户优劣，也不等于完整语义相似度。")

# ---------------- 定位用户（Python 侧稳定状态） ----------------
_SEL_KEY = "plaza_selected_user"
_SYNC_KEY = "plaza_sync_selector"
_uids = [int(x) for x in df["user_id"].tolist()]
_info = {int(r["user_id"]): r for r in df.to_dict("records")}
_default_uid = _uids[-1]
_cur = st.session_state.get("result")
if _cur and _cur.get("ok") and int(_cur.get("user_id", -1)) in _uids:
    _default_uid = int(_cur["user_id"])

# 组件回传的选中：在 selectbox 实例化前同步它的 widget state
if _SYNC_KEY in st.session_state:
    st.session_state[_SEL_KEY] = st.session_state.pop(_SYNC_KEY)
if st.session_state.get(_SEL_KEY) not in _uids:
    _old = st.session_state.get(_SEL_KEY)
    st.session_state[_SEL_KEY] = _default_uid
    if _old is not None:
        st.session_state["plaza_fallback_note"] = (
            "原定位用户 #%s 已不在用户列表中，已回到当前可用的一个用户。" % _old)


def _user_label(uid):
    rec = _info.get(uid, {})
    name = rec.get("姓名") or ("用户%d" % uid)
    school = rec.get("学校") or "学校未填"
    major = rec.get("专业") or "专业未填"
    return "#%s %s（%s · %s）" % (uid, name, school, major)


_selected = st.selectbox("🎯 定位用户", _uids, key=_SEL_KEY, format_func=_user_label)
st.caption("人物身份统一以 `user_id` 为主键；同名用户也会因编号/学校/专业不同而独立选中。")

# ---------------- 空间数据（按数据版本缓存；切换人物不重算 PCA） ----------------
space = profile_plaza.get_space(mode, axes, df)
if space.get("error"):
    st.warning(space["error"])
    with st.expander("📋 用户指标总表", expanded=False):
        theme.dataframe(df, hide_index=True)
        st.caption("GPA 与排名优秀度已归一到 0~1；排名优秀度 = 1 − 排名/总人数（越大越靠前）")
    st.stop()

_view_mode = "linked3d" if _view3d else "flat2d"
if space.get("dims", 3) < 3 and _view3d:
    st.info("PC3 不可用（有效秩不足），已自动降级为二维投影；不会补造第三个维度。")
payload = profile_plaza.build_payload(space, _selected, _view_mode)

_event = profile_plaza.render(payload)
_picked = profile_plaza.parse_event(_event, space)
if _picked and _picked != str(_selected):
    # 交给下一轮在 selectbox 实例化前同步 widget state；这里不直接改 widget state
    st.session_state[_SYNC_KEY] = int(_picked)
    st.rerun()

if st.session_state.get("plaza_fallback_note"):
    st.caption("ℹ️ " + st.session_state.pop("plaza_fallback_note"))

# ---------------- 未显示用户与口径 ----------------
_excluded = space.get("excluded") or []
with st.expander("👥 未显示用户与缺失原因（%d）" % len(_excluded), expanded=False):
    if _excluded:
        _rows = [{"用户": "#%s %s" % (e.get("user_id"), e.get("name") or ""),
                  "学校": e.get("school") or "",
                  "专业": e.get("major") or "",
                  "原因": e.get("reason") or "当前所选指标不足"} for e in _excluded]
        theme.dataframe(pd.DataFrame(_rows), hide_index=True)
        st.caption("三张图使用同一个有效集合：只要所选三轴有任一缺失，就在三图中一起排除，不补零、不猜值。")
    else:
        st.caption("当前所有用户都满足所选轴的完整数据，三图中均可见。")

# ---------------- 用户指标总表 ----------------
with st.expander("📋 用户指标总表", expanded=False):
    theme.dataframe(df, hide_index=True)
    st.caption("GPA 与排名优秀度已归一到 0~1；排名优秀度 = 1 − 排名/总人数（越大越靠前）。"
               "“GPA（归一）”不是原始绩点，未确定分制时不反算原始绩点。")
