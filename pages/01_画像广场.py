"""用户画像广场 —— 汇总所有用户，自选维度轴 2D/3D 定位用户画像。

数据源：统一字段数据库（user_records / experience_items / delivery_tasks / profile_pool）。
两种空间：
- 自选指标轴：GPA、排名优秀度、经历段数、技能数、累计投递、进面试率、平均匹配分 任选 2~3 个；
- 语义空间：式一用户表示 u = Σ α_k·v_k 的 PCA 降维（PC1/PC2/PC3）。
"""
import streamlit as st

import db
import theme
import viz

st.set_page_config(page_title="用户画像广场", page_icon="🧭", layout="wide")
theme.apply()
db.init_db()

st.markdown(
    """
    <div class="hero">
      <div class="hero-inner">
        <div class="hero-title">🧭 用户画像广场</div>
        <div class="hero-sub">汇总所有用户的画像数据 · 自选维度轴绘制 2D/3D 空间 · 定位当前用户位置</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

df = viz.user_feature_table()

if df.empty:
    theme.empty_state("🧭", "还没有用户数据",
                      "回到主页完成 ①→④ 步后，用户画像会出现在这里；多用几个人的信息跑几轮，广场就热闹了")
    st.stop()

# ---------------- 总览 KPI ----------------
_n = len(df)
_k1, _k2, _k3, _k4 = st.columns(4)
_k1.metric("用户总数", _n)
_k2.metric("平均 GPA", "%.2f" % df["GPA"].mean() if df["GPA"].notna().any() else "—")
_k3.metric("总投递", int(df["累计投递"].sum()))
_k4.metric("平均匹配分",
           "%.3f" % df["平均匹配分"].mean() if df["平均匹配分"].notna().any() else "—")

# ---------------- 定位用户选择 ----------------
_cur = st.session_state.get("result")
_default_uid = (_cur["user_id"] if _cur and _cur.get("ok")
                else int(df["user_id"].max()))
_uids = df["user_id"].tolist()
_uid = st.selectbox(
    "🎯 定位哪个用户（星形/菱形高亮）",
    _uids, index=_uids.index(_default_uid) if _default_uid in _uids else len(_uids) - 1,
    format_func=lambda i: "#%s %s（%s · %s）" % (
        i, df.loc[df["user_id"] == i, "姓名"].iloc[0],
        df.loc[df["user_id"] == i, "学校"].iloc[0],
        df.loc[df["user_id"] == i, "专业"].iloc[0]))

# ---------------- 空间模式 ----------------
_m1, _m2 = st.columns([2, 1])
_mode = _m1.radio("空间模式", ["自选指标轴", "语义空间（式一 PCA）"], horizontal=True)
_3d = _m2.toggle("3D 模式", value=True)

if _mode == "自选指标轴":
    _dims = 3 if _3d else 2
    _cs = st.columns(_dims)
    _x = _cs[0].selectbox("X 轴", viz.USER_AXES, index=0)
    _y = _cs[1].selectbox("Y 轴", viz.USER_AXES,
                          index=3 if len(viz.USER_AXES) > 3 else 0)
    _z = _cs[2].selectbox("Z 轴", viz.USER_AXES, index=2) if _3d else None
    _fig = viz.user_space_chart(df, _x, _y, _z, _uid)
    if _fig is None:
        st.warning("所选轴上没有足够数据（存在空值），换一组轴试试")
    else:
        _need = [c for c in (_x, _y, _z) if c]
        if _uid not in df.dropna(subset=_need)["user_id"].values:
            st.warning("⚠️ 定位用户在所选轴上缺数据（如从未投递），未能在图中标出；"
                       "换「GPA / 排名优秀度 / 经历段数 / 技能数」这类人人有的轴即可")
else:
    _fig = viz.user_semantic_space(_uid, three_d=_3d)
    st.caption("语义空间：每个用户由式一 u = Σ α_k·v_k（经历加权凸组合）表示，PCA 降维后越近越相似")
    if _fig is None:
        st.warning("语义向量不足（需要至少 2 个有画像快照的用户）")

if _fig is not None:
    theme.chart(_fig)

# ---------------- 指标总表 ----------------
with st.expander("📋 用户指标总表", expanded=False):
    st.dataframe(df, hide_index=True, **theme.full_width_kwargs())
    st.caption("GPA 与排名优秀度已归一到 0~1；排名优秀度 = 1 − 排名/总人数（越大越靠前）")
