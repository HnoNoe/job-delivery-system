"""求职批量投递系统 —— 分阶段翻页向导。

六阶段不再全部铺在同一页里，而是一次只显示一页：
① 确认信息 → ② 平台登录 → ③ 检索岗位 → ④ 准备材料 → ⑤ 逐条投递 → ⑥ 投递记录

交互逻辑：
- 完成当前阶段的要求后自动翻到下一页（①→②→③→④→⑤）；
- ⑤ 是可反复操作的投递/反馈工作台，完成投递与标注后点底部「下一页」进入 ⑥，
  避免刚投完一个岗位就被自动弹走；
- 侧栏进度条 + 阶段跳转按钮，页面底部保留「上一页 / 下一页」兜底导航；
- 每页只渲染当前阶段的内容，减少长页面滚动。

本文件是外壳（侧栏、进度、页面切换、底部导航）；
各阶段内容在 wizard_steps.py，共享工具在 wizard_ui.py。
"""
import json

import streamlit as st

import config
import db
import platforms
import recommend as _recommend
import session
import theme
import wizard_steps as steps
import wizard_ui as ui


def _full_width_kwargs() -> dict:
    """表格全宽渲染参数（跨 Streamlit 版本自适应）。

    Streamlit ≥1.49 已弃用 use_container_width（2025-12-31 后移除），
    改用 width='stretch'；requirements 允许 >=1.46，故旧版本回退。
    """
    try:
        major, minor = (int(x) for x in st.__version__.split(".")[:2])
        if (major, minor) >= (1, 49):
            return {"width": "stretch"}
    except Exception:
        pass
    return {"use_container_width": True}


st.set_page_config(page_title="求职批量投递系统", page_icon="🎯", layout="wide")
theme.apply()
db.init_db()

# 兼容旧会话：上一版只保存了 confirmed_info（JSON 字符串），没有 confirmed_user_data
if ("confirmed_user_data" not in st.session_state
        and st.session_state.get("confirmed_info")):
    try:
        st.session_state["confirmed_user_data"] = json.loads(st.session_state["confirmed_info"])
    except Exception:
        pass

# 刷新 / 重启后自动恢复「上次确认的信息」，避免翻页向导又把用户卡回第①阶段
ui.bootstrap_confirmed_info()

_states = ui.wizard_states()
if ui.PAGE_KEY not in st.session_state:
    st.session_state[ui.PAGE_KEY] = ui.default_page(_states)
page = max(0, min(len(ui.STEP_SHORT) - 1, int(st.session_state.get(ui.PAGE_KEY, 0))))

# ---------------- 顶部 ----------------
theme.hero()
ui.consume_flash()
_notice = st.session_state.pop("_restored_info_notice", None)
if _notice:
    st.info(_notice)

# ---------------- 侧边栏：进度 + 跳转 + 重置 + 状态 ----------------
with st.sidebar:
    st.markdown("**操作说明**")
    st.caption("按 ①→⑥ 分阶段操作；完成当前阶段后自动进入下一页。")
    theme.stepper(list(zip(ui.STEP_SHORT, _states)))

    st.caption("阶段跳转（已完成 / 当前阶段可点）")
    _reach = ui.max_reachable(_states)
    for _row in (0, 3):
        _jump_cols = st.columns(3)
        for _j in range(3):
            _idx = _row + _j
            if _idx >= len(ui.STEP_SHORT):
                break
            _label = ui.STEP_SHORT[_idx]
            if _idx == page:
                _label = "• " + _label
            if _jump_cols[_j].button(_label, key="jump_%d" % _idx, disabled=_idx > _reach):
                ui.goto(_idx)

    c_reset, c_safe = st.columns([1.15, 1])
    with c_reset:
        if st.button("🔄 重新开始"):
            # 先清平台会话与浏览器，再清界面状态，最后一次性刷新
            for pk in platforms.PLATFORMS:
                session.clear_session(pk)
                session.dpage_quit(pk)  # 同时关闭保持打开的浏览器
            for k in list(st.session_state.keys()):
                if (k in ("info_confirmed", "confirmed_info", "confirmed_user_data",
                          "wizard_page", "_wizard_flash", "_login_flash",
                          "logged_in", "jobs", "result", "parsed",
                          "resume_pdf", "resume_text", "parsed_pdf_hash",
                          "rematch", "rematch_old", "prepared_user_data",
                          "selected_platforms", "qr_login_pk", "_qr_closing")
                        or k.startswith(("l0_", "l2_", "l3_", "sel_"))
                        or k in ("l1_iw", "l1_proj")):
                    st.session_state.pop(k, None)
            st.session_state.pop("login_report", None)
            st.session_state.pop("_restored_info_notice", None)
            # 明确“从零开始”：本次会话不再自动回填上次确认的信息 / 进度，
            # 直到用户重新确认信息（第①阶段的确认按钮会清掉这个标记）。
            st.session_state["_no_auto_restore"] = True
            st.session_state[ui.PAGE_KEY] = 0
            st.rerun()
    with c_safe:
        st.caption("安全模式")
        _safe = st.toggle(
            "安全模式",
            value=bool(config.SAFE_MODE),
            key="safe_mode_toggle",
            label_visibility="collapsed",
            help="开启：投递只生成招呼语，不自动发消息给 HR；关闭：真实投递（有封号与合规风险）。",
        )
        config.SAFE_MODE = bool(_safe)
    if not config.SAFE_MODE:
        st.caption("⚠️ 安全模式已关闭：投递会真实发送，请自行确认风险。")
    st.divider()

    st.caption("平台登录状态（启动 / 刷新页面时自动检测）")
    _report = ui.login_report()
    for _s in _report:
        st.markdown(theme.pill(_s["kind"], "%s · %s" % (_s["label"], _s["name"])),
                    unsafe_allow_html=True)
        st.caption("　" + _s["detail"])
    if st.button("🔍 重新检测登录状态", key="btn_login_check"):
        st.session_state.pop("login_report", None)
        st.rerun()
    st.caption("检测时间 %s · 只检测登录态，不抓取数据、不触发投递" % _report[0]["checked_at"])
    st.divider()

    with st.expander("📐 数学说明（分数怎么算）"):
        st.caption(_recommend.explain_match_score())
        st.caption(_recommend.explain_weights(None))
        st.caption("当前超参数：w_s=%s（余弦权重）、w_δ=%s（间隔权重）、τ=%s（式四倾斜强度）、η=%s（式五学习步长）"
                   % (config.W_S, config.W_DELTA, config.TAU, config.ETA))
    st.divider()

    _sr = st.session_state.get("result")
    if _sr and _sr.get("ok") and _sr.get("画像摘要"):
        summ = _sr["画像摘要"]
        st.caption("**🧠 我的画像**")
        st.caption("技能：" + ("、".join(summ.get("技能标签", [])) or "无"))
        st.caption("意向岗位：" + ("、".join(summ.get("意向岗位", [])) or "无"))
        st.caption("意向行业：" + ("、".join(summ.get("意向行业", [])) or "无"))
        st.caption("城市：" + ("、".join(summ.get("意向城市", [])) or "无"))

# ---------------- 当前阶段进度 ----------------
st.progress((page + 1) / float(len(ui.STEP_SHORT)),
            text="阶段 %d / %d · %s" % (page + 1, len(ui.STEP_SHORT), ui.STEP_TITLES[page]))

# ---------------- 只渲染当前阶段 ----------------
if page == 0:
    steps.render_step_1(_states)
elif page == 1:
    steps.render_step_2(_states)
elif page == 2:
    steps.render_step_3(_states)
elif page == 3:
    steps.render_step_4(_states)
elif page == 4:
    steps.render_step_5(_states)
else:
    steps.render_step_6(_states)

# ---------------- 底部兜底导航 ----------------
_NEXT_HINTS = [
    "先确认信息",
    "先完成至少一个平台的登录",
    "先检索到岗位",
    "先生成投递材料",
    "",
    "",
]
_next_enabled = (page < len(ui.STEP_SHORT) - 1
                 and (_states[page] == "done"
                      or (page == 4 and bool(st.session_state.get("result")))))
ui.page_nav(page, _next_enabled, _NEXT_HINTS[page])
