"""分阶段翻页向导的共享 UI / 运行时工具。

交互模型（本轮改版）：
- 主界面不再把 ①~⑥ 全部铺在一页里，而是一次只显示一个阶段（一页）；
- 完成当前阶段的要求后自动翻到下一页；
- 侧栏保留进度条与阶段跳转，页面底部提供「上一页 / 下一页」兜底导航。

本模块只放跨步骤共享的东西：登录态检测、扫码面板、表单回填、六步状态、
页面状态与翻页、示例数据。各步骤的具体内容在 wizard_steps.py。
"""
import json
import time

import streamlit as st

import db
import feedback
import login_status
import platforms
import schema
import session

LOGIN_CHECK_TTL = 300  # 秒：页面交互时复用检测结果，避免每次点击都联网

PAGE_KEY = "wizard_page"
FLASH_KEY = "_wizard_flash"

STEP_SHORT = ["① 信息", "② 登录", "③ 检索", "④ 材料", "⑤ 投递", "⑥ 记录"]
STEP_TITLES = ["确认我的信息", "平台与登录", "检索岗位", "准备投递材料",
               "逐条投递与反馈", "投递记录与画像统计"]

# 示例用户信息（预填，可改）
SAMPLE = {
    "l0": {
        "姓名": "张三", "性别": "男", "出生日期": "2001-05-01", "手机": "13800138000",
        "邮箱": "zhangsan@example.com", "政治面貌": "共青团员", "民族": "汉族",
        "现居": "北京-海淀区", "籍贯": "江苏-南京", "学历阶段": "本科在读",
        "学校": "示例大学", "学院": "计算机学院", "专业": "软件工程",
        "入学年月": "2020-09", "毕业年月": "2024-06", "GPA": "3.7/4.0", "专业排名": "5/120",
    },
    "l2": [
        {"类型": "实习/工作", "名称": "后端实习生", "角色": "后端实习生",
         "时间起": "2023-06", "时间止": "2023-09",
         "事项": "参与服务端接口开发；优化数据库查询性能", "结果": "接口响应提升30%",
         "技术工具": "Python, MySQL", "挂靠": "独立", "证据": "无"},
        {"类型": "项目", "名称": "校园招聘信息聚合平台", "角色": "负责人",
         "时间起": "2023-03", "时间止": "2023-08",
         "事项": "设计爬虫采集多来源岗位；搭建推荐排序模块", "结果": "上线稳定运行",
         "技术工具": "Python, Flask", "挂靠": "独立", "证据": "github.com/example"},
    ],
}


def login_report():
    """登录态检测结果（启动/刷新时自动检测，交互期间缓存 5 分钟）。"""
    cached = st.session_state.get("login_report")
    if cached:
        ts, data = cached
        if time.time() - ts < LOGIN_CHECK_TTL:
            return data
    data = login_status.check_all()
    st.session_state["login_report"] = (time.time(), data)
    return data


def rerun_app():
    """从 fragment/弹窗里触发整页重跑（旧版本没有 scope 参数时降级）。"""
    try:
        st.rerun(scope="app")
    except TypeError:
        st.rerun()


# ---------------- 网页内扫码登录（二维码实时弹窗） ----------------
import inspect as _inspect

# run_every 周期刷新需要 streamlit>=1.47；旧版回退为手动刷新按钮
_FRAGMENT_EVERY = hasattr(st, "fragment") and "run_every" in _inspect.signature(st.fragment).parameters


def qr_panel(pk):
    """网页内扫码面板（内嵌步骤②）：二维码每 2 秒自动刷新；登录成功面板自动收起。"""
    p = platforms.get(pk)
    with st.container(border=True):
        st.markdown("**📱 %s · 扫码登录**" % p["name"])
        st.caption("二维码每 2 秒自动刷新；登录成功后本面板自动收起。")

        def _live():
            if st.session_state.get("qr_login_pk") != pk or st.session_state.get("_qr_closing"):
                return  # 已收尾（或正在收尾），停止刷图防重入
            if session.qr_login_status(pk):
                st.session_state["_qr_closing"] = True  # 先上锁再做 2 秒的登录保存
                _ok, _msg = session.dpage_finish(pk)
                st.session_state.pop("qr_login_pk", None)
                st.session_state.pop("_qr_closing", None)
                st.session_state.pop("login_report", None)
                st.session_state["_login_flash"] = (
                    "%s：%s" % (p["name"], _msg) if _ok
                    else "%s：登录检测异常，请查看侧栏状态" % p["name"])
                if _ok and any_selected_logged_in():
                    st.session_state[PAGE_KEY] = 2  # 自动翻到第③阶段
                rerun_app()
                return
            ok, payload = session.qr_login_shot(pk)
            if ok:
                try:
                    with open(payload, "rb") as _f:
                        st.image(_f.read(), caption="用手机 %s App 扫码" % p["name"], width=260)
                except OSError:
                    st.info("二维码加载中…")
            else:
                st.warning(payload)

        if _FRAGMENT_EVERY:
            st.fragment(_live, run_every=2)()
        else:
            _live()
            st.button("🔄 刷新二维码", key="qr_manual_refresh")
            st.caption("扫码完成后点上方「✅ 我已完成登录」")

        c1, c2 = st.columns(2)
        if c1.button("♻️ 二维码过期？换一张", key="qr_reload"):
            session.qr_login_shot(pk, reload=True)
            st.rerun()
        if c2.button("❌ 取消", key="qr_cancel"):
            st.session_state.pop("qr_login_pk", None)
            st.rerun()
        if p.get("demo_scan_text"):
            if st.button("🤖 演示站专用：模拟手机扫码", key="qr_demo_scan"):
                session.qr_login_demo_scan(pk)
                st.rerun()


def normalize_user_data(saved):
    """把数据库里的历史用户信息补齐成第①阶段表单产出的同一形状。

    老记录可能缺字段（例如早期版本没有 GPA/专业排名，或只存了部分 L1 类型）；
    不补齐的话，第①阶段比较 `confirmed_info` 时会立刻判定“信息已修改”，
    自动恢复的“已确认”状态会当场失效。
    """
    l0 = saved.get("l0") or {}
    l1_raw = saved.get("l1") or {}
    l3 = saved.get("l3") or {}
    l1 = {t: int(l1_raw.get(t, 0) or 0) for t in schema.L1_TYPES}
    l2 = []
    for item in (saved.get("l2") or []):
        row = {f: (item.get(f, "") if item.get(f) is not None else "") for f in schema.L2_FIELDS}
        row["类型"] = item.get("类型") or ""
        # 表单里「挂靠/证据」是固定值，用户不可编辑；这里强制对齐，否则“已确认”会误判失效
        row["挂靠"] = "独立"
        row["证据"] = "无"
        l2.append(row)
    l3 = {f: str(l3.get(f, "") or "") for f in schema.L3_FIELDS}
    # 与第①阶段下拉框的默认值保持一致（空值会被控件回填成默认选项）
    if l3["投递策略"] not in ("海投", "精投"):
        l3["投递策略"] = "海投"
    if l3["能否出差"] not in ("是", "否"):
        l3["能否出差"] = "是"
    return {
        "l0": {f: str(l0.get(f, "") or "") for f in schema.L0_FIELDS},
        "l1": l1,
        "l2": l2,
        "l3": l3,
    }


def apply_saved_user(saved, reset_confirmed=True):
    """把上次保存的信息写进表单 widget 状态（必须在控件创建前调用）。"""
    data = normalize_user_data(saved)
    l0, l2, l3 = data["l0"], data["l2"], data["l3"]
    for field in schema.L0_FIELDS:
        st.session_state["l0_" + field] = l0[field]

    for typ, key in (("实习/工作", "l1_iw"), ("项目", "l1_proj")):
        items = [x for x in l2 if x.get("类型") == typ][:5]
        st.session_state[key] = len(items)
        for idx, item in enumerate(items):
            for suffix, field in (("name", "名称"), ("role", "角色"), ("from", "时间起"),
                                  ("to", "时间止"), ("what", "事项"), ("result", "结果"),
                                  ("tech", "技术工具")):
                st.session_state["l2_%s_%d_%s" % (typ, idx, suffix)] = str(item.get(field, "") or "")

    st.session_state["l3_city"] = l3.get("意向城市", "")
    st.session_state["l3_industry"] = l3.get("意向行业", "")
    st.session_state["l3_job"] = l3.get("意向岗位", "")
    st.session_state["l3_taboo"] = l3.get("禁忌公司", "")
    st.session_state["l3_strategy"] = l3.get("投递策略") if l3.get("投递策略") in ("海投", "精投") else "海投"
    st.session_state["l3_salary"] = l3.get("期望薪资", "")
    st.session_state["l3_onboard"] = l3.get("到岗时间", "")
    st.session_state["l3_trip"] = l3.get("能否出差") if l3.get("能否出差") in ("是", "否") else "是"
    st.session_state.pop("parsed", None)
    if reset_confirmed:
        st.session_state["info_confirmed"] = False


def bootstrap_confirmed_info():
    """刷新 / 重启后自动恢复「上次确认的信息」。

    只在本会话还没有任何确认状态、且没有点过「重新开始」时执行；
    恢复后第①阶段显示为已完成，可直接跳转后续阶段。用户一旦修改表单，
    第①阶段原有的“信息已修改，请重新确认”逻辑仍会生效。
    """
    if st.session_state.get("_no_auto_restore"):
        return False
    if st.session_state.get("confirmed_user_data") or st.session_state.get("info_confirmed"):
        return False
    try:
        import pipeline as _pipeline
        saved = _pipeline.latest_user_data()
    except Exception:
        return False
    if not saved:
        return False
    data = normalize_user_data(saved)
    apply_saved_user(data, reset_confirmed=False)
    st.session_state["confirmed_user_data"] = data
    st.session_state["confirmed_info"] = json.dumps(data, ensure_ascii=False, sort_keys=True)
    st.session_state["info_confirmed"] = True
    st.session_state["_restored_info_notice"] = (
        "📂 已载入上次确认的信息（用户 #%d / %s），可直接进入后续阶段；"
        "如需修改请到第①阶段编辑并重新确认。"
        % (saved.get("user_id", 0), (data["l0"].get("姓名") or "未命名")))
    return True


def persisted_progress():
    """从数据库读取上次进度摘要（轻量查询，不重建 result）。"""
    summary = {"has_user": False, "has_tasks": False, "has_delivered": False,
               "has_feedback": False, "user_id": None}
    try:
        with db.get_conn() as conn:
            u = conn.execute("SELECT user_id FROM user_records ORDER BY user_id DESC LIMIT 1").fetchone()
            summary["has_user"] = bool(u)
            row = conn.execute(
                "SELECT user_id, COUNT(*) AS c, SUM(status='已投递') AS d,"
                " SUM(result IN ('进面试','未进面试')) AS f FROM delivery_tasks"
                " GROUP BY user_id ORDER BY MAX(task_id) DESC LIMIT 1").fetchone()
            if row:
                summary.update(user_id=row["user_id"], has_tasks=bool(row["c"]),
                               has_delivered=bool(row["d"]), has_feedback=bool(row["f"]))
    except Exception:
        pass
    return summary


def wizard_states():
    """六步完成状态（done/active/todo），驱动侧栏进度条与步骤头状态牌。

    会话内状态优先；刷新/重启后回落到数据库里已有的进度，避免“明明投过却显示待开始”。
    """
    r = st.session_state.get("result")
    s4 = bool(r and r.get("ok"))
    persisted = persisted_progress()
    if st.session_state.get("_no_auto_restore"):
        persisted = {"has_user": False, "has_tasks": False, "has_delivered": False,
                     "has_feedback": False, "user_id": None}
    uid = r["user_id"] if s4 else persisted.get("user_id")
    delivered = bool(persisted.get("has_delivered"))
    feedback_given = bool(persisted.get("has_feedback"))
    if uid:
        conn = db.get_conn()
        row = conn.execute(
            "SELECT SUM(status='已投递') AS d, SUM(result IN ('进面试','未进面试')) AS f "
            "FROM delivery_tasks WHERE user_id=?", (uid,)).fetchone()
        conn.close()
        delivered = bool(row and row["d"])
        feedback_given = bool(row and row["f"])
    done = [
        bool(st.session_state.get("info_confirmed")),     # ① 确认信息
        any(session.can_search(pk) for pk in platforms.PLATFORMS),  # ② 平台登录
        bool(st.session_state.get("jobs")) or bool(persisted.get("has_tasks")),  # ③ 检索岗位
        s4 or bool(persisted.get("has_tasks")),           # ④ 准备材料
        delivered,                                        # ⑤ 投递与反馈
        feedback_given,                                   # ⑥ 记录与统计
    ]
    states, activated = [], False
    for d in done:
        if d:
            states.append("done")
        elif not activated:
            states.append("active")
            activated = True
        else:
            states.append("todo")
    return states


def first_pending(states):
    """第一个未完成阶段的索引（全部完成时返回最后一页）。"""
    for i, state in enumerate(states):
        if state != "done":
            return i
    return len(states) - 1


def default_page(states=None):
    """恢复现场后默认落在哪一页。

    只要数据库里有投递任务（= 恢复出了上次投递现场），就停在第⑤阶段
    「逐条投递与反馈」，方便继续投递/标注；不再直接跳到第⑥阶段。
    用户仍可从侧栏跳到⑥查看记录。
    """
    states = states if states is not None else wizard_states()
    if not st.session_state.get("_no_auto_restore") and persisted_progress().get("has_tasks"):
        return min(len(states) - 1, 4)
    return first_pending(states)


def max_reachable(states):
    """当前允许跳转到的最大页索引。

    完成到哪就能跳到哪；另外只要数据库里已有投递任务，第⑥阶段（投递记录）
    随时可看——记录是“查看历史”，不该被前置阶段的完成度卡住。
    """
    reach = first_pending(states)
    if not st.session_state.get("_no_auto_restore") and persisted_progress().get("has_tasks"):
        reach = max(reach, len(states) - 1)
    return min(reach, len(states) - 1)


def goto(page, flash=None):
    """翻到指定页；可选设置下页顶部提示。"""
    st.session_state[PAGE_KEY] = int(page)
    if flash:
        st.session_state[FLASH_KEY] = flash
    st.rerun()


def selected_platforms():
    """第②阶段勾选的平台（未初始化时默认 Boss）。"""
    selected = st.session_state.get("selected_platforms")
    return list(selected) if selected is not None else ["boss"]


def any_selected_logged_in():
    return any(session.can_search(pk) for pk in selected_platforms())


def consume_flash():
    """显示上一动作留下的成功提示（只显示一次）。"""
    for key in ("_login_flash", FLASH_KEY):
        msg = st.session_state.pop(key, None)
        if msg:
            st.success(msg)


def page_nav(page, next_enabled, next_hint=""):
    """页面底部兜底导航：上一页 / 下一页（自动翻页失败或回看时用）。"""
    st.markdown("---")
    c_prev, c_next = st.columns([1, 1])
    with c_prev:
        if page > 0:
            if st.button("⬅️ 上一页", key="nav_prev_%d" % page):
                goto(page - 1)
        else:
            st.caption("🏁 第一页")
    with c_next:
        if page < len(STEP_SHORT) - 1:
            if st.button("下一页 ➡️", key="nav_next_%d" % page, type="primary",
                         disabled=not next_enabled):
                goto(page + 1)
            if not next_enabled and next_hint:
                st.caption("🔒 " + next_hint)
        else:
            st.caption("🎉 已完成全部阶段")
