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

import pandas as pd
import streamlit as st

import config
import data_reset
import db
import platforms
import recommend as _recommend
import replies
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

CLEAR_DIALOG_KEY = "_show_clear_dialog"


def _reset_ui_state():
    """清空界面会话状态（不动数据库/文件）。"""
    for k in list(st.session_state.keys()):
        if (k in ("info_confirmed", "confirmed_info", "confirmed_user_data",
                  "wizard_page", "_wizard_flash", "_login_flash",
                  "logged_in", "jobs", "result", "parsed",
                  "resume_pdf", "resume_text", "parsed_pdf_hash",
                  "rematch", "rematch_old", "prepared_user_data",
                  "selected_platforms", "qr_login_pk", "_qr_closing",
                  "reply_check_result", "reply_check_platform", "reply_pick")
                or k.startswith(("l0_", "l2_", "l3_", "sel_"))
                or k in ("l1_iw", "l1_proj")):
            st.session_state.pop(k, None)
    st.session_state.pop("login_report", None)
    st.session_state.pop("_restored_info_notice", None)
    st.session_state.pop("_auto_reply_outcome", None)
    st.session_state.pop("_auto_reply_attempted", None)
    st.session_state["_no_auto_restore"] = True
    st.session_state[ui.PAGE_KEY] = 0


def _do_clear(clear_login):
    """执行清空（数据库 + 文件 [ + 登录态 ]），并重置界面。"""
    summary = data_reset.reset_all(clear_login=clear_login)
    _reset_ui_state()
    st.session_state["_clear_done"] = summary
    st.session_state.pop(CLEAR_DIALOG_KEY, None)


def _clear_confirm_body():
    st.warning("以下数据会被**永久删除**，无法撤销：")
    st.markdown(
        "- 用户信息、L2 经历、画像权重与画像快照\n"
        "- 岗位、目标岗位、投递任务、反馈样本\n"
        "- HR 回应记录与收件箱\n"
        "- 生成的简历 PDF、投递材料包、发件箱\n"
        "- Mock 投递/回复记录、自动检查状态与计数")
    st.caption("保留：数据库表结构、主题偏好、代码与配置。")
    _clear_login = st.checkbox("同时清除平台登录态（需要重新扫码）",
                               value=False, key="_clear_login_too")
    _ok = st.checkbox("我确认清空本机数据（不可撤销）", value=False, key="_clear_confirmed")
    c1, c2 = st.columns(2)
    if c1.button("取消", key="_clear_cancel"):
        st.session_state.pop(CLEAR_DIALOG_KEY, None)
        st.rerun()
    if c2.button("🧹 确认清空", key="_clear_do", type="primary", disabled=not _ok):
        _do_clear(_clear_login)
        st.rerun()


def _clear_data_dialog():
    _clear_confirm_body()


if hasattr(st, "dialog"):
    _clear_data_dialog = st.dialog("确认清空本机数据")(_clear_data_dialog)


def _clear_data_inline():
    with st.container(border=True):
        st.markdown("**🧹 清空本机数据**")
        _clear_confirm_body()


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

_clear_summary = st.session_state.pop("_clear_done", None)
if _clear_summary:
    _cleared_tables = sum(1 for v in (_clear_summary.get("database") or {}).values() if v)
    _cleared_files = len(_clear_summary.get("files") or [])
    st.success("🧹 已清空本机数据：%d 张表有数据被删除，清理 %d 个文件/目录%s。"
               % (_cleared_tables, _cleared_files,
                  "，平台登录态已清除（需重新扫码）" if _clear_summary.get("clear_login")
                  else "（平台登录态保留）"))

# ---------------- 启动自动检查 HR 回复（每个会话一次，带冷却期） ----------------
_auto_uid = ((st.session_state.get("result") or {}).get("user_id")
             or ui.persisted_progress().get("user_id"))
_auto_tasks = []
if _auto_uid:
    with db.get_conn() as _auto_conn:
        _auto_tasks = [dict(r) for r in _auto_conn.execute(
            "SELECT task_id, job_name, unit_name, status FROM delivery_tasks "
            "WHERE user_id=? ORDER BY task_id", (_auto_uid,))]
_auto_candidates = getattr(config, "AUTO_CHECK_PLATFORMS", ["boss"])
_auto_pks = [pk for pk in _auto_candidates
             if platforms.get(pk) and session.has_session(pk) and replies.supports_chat(pk)]

if (not st.session_state.get("_auto_reply_attempted")
        and st.session_state.get("auto_reply_enabled", config.AUTO_CHECK_REPLIES)
        and _auto_pks and _auto_tasks):
    st.session_state["_auto_reply_attempted"] = True
    _remain = replies.cooldown_remaining()
    if _remain <= 0:
        _names = "、".join(platforms.get(pk)["name"] for pk in _auto_pks)
        with st.spinner("启动自动检查：正在读取 %s 的消息列表（只读，约 20 秒/平台）…" % _names):
            st.session_state["_auto_reply_outcome"] = replies.auto_check_multi(
                _auto_pks, _auto_tasks)
    else:
        st.session_state["_auto_reply_outcome"] = {
            "ran": False,
            "reason": "冷却中：约 %.0f 分钟后可再次自动检查" % _remain,
            "added": 0, "results": []}
    st.rerun()

_auto_out = st.session_state.get("_auto_reply_outcome")
if _auto_out:
    if _auto_out.get("ran"):
        _auto_sum = _auto_out.get("summary") or {}
        _auto_results = _auto_out.get("results") or []
        st.success("🤖 启动自动检查完成：%d 个平台 · 读取 %d 条会话 · 匹配 %d 个岗位 · "
                   "自动登记 %d 条 HR 回应 · 收件箱 +%d 条。"
                   % (len(_auto_results), _auto_sum.get("records", 0),
                      _auto_sum.get("candidates", 0), _auto_sum.get("added", 0),
                      _auto_sum.get("inbox_added", 0)))
        _auto_lines = []
        for _item in _auto_results:
            _pk = _item["platform"]
            _entry = next((e for e in (_auto_sum.get("platforms") or [])
                           if e.get("platform") == _pk), {})
            _status = "✅" if _entry.get("ok") else "⚠️"
            _auto_lines.append("%s %s：读取 %d 条，匹配 %d，登记 %d%s"
                               % (_status, (platforms.get(_pk) or {}).get("name", _pk),
                                  _entry.get("records", 0), _entry.get("candidates", 0),
                                  _entry.get("added", 0),
                                  ("（%s）" % _entry["error"]) if _entry.get("error") else ""))
        st.caption("；".join(_auto_lines))
        _auto_unmatched = [u for _item in _auto_results
                           for u in ((_item.get("result") or {}).get("unmatched") or [])]
        if _auto_unmatched:
            with st.expander("🤖 未匹配到投递任务的会话（仅参考）", expanded=False):
                theme.dataframe(pd.DataFrame([{
                    "单位": u["单位"] or "—", "HR": u["HR"] or "—",
                    "建议类型": u["建议类型"],
                    "最后消息": (u["最后消息"] or "")[:60], "时间": u["时间"] or "—",
                } for u in _auto_unmatched]), hide_index=True)
    else:
        st.caption("🤖 自动检查跳过：" + (_auto_out.get("reason") or ""))

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
            _reset_ui_state()
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

    if st.button("🧹 清空本机数据", key="btn_clear_data",
                 help="删除用户信息、投递记录、HR 回应、生成的简历与材料；需要二次确认"):
        st.session_state[CLEAR_DIALOG_KEY] = True
        st.rerun()
    st.divider()

    def _save_auto_toggle():
        replies.set_auto_enabled(bool(st.session_state.get("auto_reply_toggle")))

    st.toggle(
        "启动时自动检查 HR 回复",
        value=replies.auto_enabled(),
        key="auto_reply_toggle",
        on_change=_save_auto_toggle,
        help="每次启动读取一次消息列表，并自动登记能判断类型的 HR 回应；"
             "冷却 %d 分钟内不会重复检查（防触发平台风控）。" % config.AUTO_CHECK_COOLDOWN_MIN,
    )
    _last_auto = replies.last_auto_check()
    if _last_auto:
        st.caption("上次自动检查：%s · 读取 %d 条 · 新登记 %d 条 · 收件箱 +%d%s"
                   % (_last_auto.get("at", ""), _last_auto.get("records", 0),
                      _last_auto.get("added", 0), _last_auto.get("inbox_added", 0),
                      (" · " + _last_auto["error"]) if _last_auto.get("error") else ""))
        for _entry in (_last_auto.get("platforms") or []):
            st.caption("　· %s：读取 %d · 匹配 %d · 登记 %d%s"
                       % ((platforms.get(_entry.get("platform")) or {}).get(
                              "name", _entry.get("platform")),
                          _entry.get("records", 0), _entry.get("candidates", 0),
                          _entry.get("added", 0),
                          ("（%s）" % _entry["error"]) if _entry.get("error") else ""))
    _remain = replies.cooldown_remaining()
    if _remain > 0:
        st.caption("自动检查冷却中：约 %.0f 分钟后可再次自动执行" % _remain)
    if _auto_pks and _auto_tasks:
        if st.button("🔄 立即检查一次", key="auto_now",
                     help="忽略冷却，立即读取一次已登录平台的消息列表（只读）"):
            with st.spinner("正在读取 %s 的消息列表（只读，约 20 秒/平台）…"
                            % "、".join(platforms.get(pk)["name"] for pk in _auto_pks)):
                st.session_state["_auto_reply_outcome"] = replies.auto_check_multi(
                    _auto_pks, _auto_tasks, cooldown_minutes=0)
            st.rerun()
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

# ---------------- 清空本机数据：二次确认（弹窗） ----------------
if st.session_state.get(CLEAR_DIALOG_KEY):
    if hasattr(st, "dialog"):
        _clear_data_dialog()
    else:
        _clear_data_inline()

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
