"""六个阶段的页面内容（分阶段翻页向导）。

app.py 只负责外壳（侧栏、进度、页面切换、底部导航）；
每个 `render_step_N` 只渲染当前阶段要展示的内容，不再把 ①~⑥ 全部铺在一页。

自动翻页规则：
① 确认信息 → ② 登录成功 → ③ 检索到岗位 → ④ 材料生成 完成后自动进入下一阶段；
⑤ 是可反复操作的投递/反馈工作台，投递与标注完成后用底部「下一页」进入 ⑥，
避免刚投完一个岗位就被自动弹走。
"""
import copy
import hashlib
import json

import pandas as pd
import streamlit as st

import config
import db
import delivery
import feedback
import loop
import persona
import pipeline
import platforms
import recommend
import replies
import responses
import schema
import session
import theme
import verification
import viz
import workbench
from runtime_paths import resolve_resume
import wizard_ui as ui


def _ensure_result():
    """第⑤⑥阶段：session 里没有 result 时，从数据库恢复上次投递现场（只读）。

    刷新页面 / 重启程序后 `st.session_state` 会清空，但投递任务、简历、匹配分都在
    SQLite 里；这里用 `pipeline.latest_result()` 重建，避免“数据库有记录、界面却说没有”。
    """
    r = st.session_state.get("result")
    if r and r.get("ok"):
        return r
    try:
        restored = pipeline.latest_result()
    except Exception as exc:  # 恢复失败不应阻断页面
        st.warning("恢复上次投递记录失败：%s" % exc)
        return None
    if restored:
        st.session_state["result"] = restored
        st.session_state.setdefault("prepared_user_data", restored.get("user_data"))
        st.session_state["_restored_notice"] = (
            "📂 已从本机数据库恢复上次投递现场（用户 #%d，%d 个岗位）。"
            % (restored["user_id"], restored["task_count"]))
    return restored


def _show_restore_notice():
    msg = st.session_state.pop("_restored_notice", None)
    if msg:
        st.info(msg)


# ======================================================================
# ① 确认信息
# ======================================================================
def render_step_1(states):
    theme.section("①", "确认我的信息",
                  "下面是示例占位信息，请点开改成你的真实信息（姓名/学校/专业/手机/邮箱/经历）",
                  status=states[0])
    with st.expander("查看 / 修改我的信息", expanded=True):
        # 刷新 / 重开页面后，会话里的表单会回到示例数据；支持从本机数据库一键回填
        try:
            _saved_user = pipeline.latest_user_data()
        except Exception:
            _saved_user = None
        if _saved_user:
            _saved_name = (_saved_user.get("l0") or {}).get("姓名") or "未命名"
            st.caption("本机已保存过用户 #%d（%s）。刷新或重开后可用一键回填，再点下方确认。"
                       % (_saved_user["user_id"], _saved_name))
            if st.button("📂 载入上次填写的信息", key="btn_restore_user"):
                ui.apply_saved_user(_saved_user)
                st.session_state.pop("_no_auto_restore", None)
                st.rerun()

        # 粘贴简历自动解析（减少手填）
        with st.expander("📋 粘贴简历文本自动填充（可选）"):
            resume_text = st.text_area(
                "把简历内容粘贴到这里，点解析自动提取姓名/手机/邮箱/学校/专业/技能",
                key="resume_text", height=100)
            if st.button("🔍 解析文本并填充", key="btn_parse"):
                p = recommend.resume_parse(resume_text)
                if p:
                    st.session_state["parsed"] = p
                    # 清除 L0/L2/L3/段数 widget 状态，让它们按解析结果重新创建
                    for _k in list(st.session_state.keys()):
                        if _k.startswith(("l0_", "l2_", "l3_")) or _k in ("l1_iw", "l1_proj"):
                            st.session_state.pop(_k, None)
                    _scalar = {k: v for k, v in p.items() if not isinstance(v, list)}
                    _n_exp = len(p.get("经历", []))
                    _n_skill = len(p.get("技能", []))
                    st.success("已提取：%s%s%s" % (
                        "、".join("%s=%s" % (k, v) for k, v in _scalar.items()),
                        "；经历 %d 段" % _n_exp if _n_exp else "",
                        "；技能 %d 个" % _n_skill if _n_skill else "",
                    ))
                    st.rerun()
                else:
                    st.session_state.pop("parsed", None)
                    st.warning("未能解析，请检查简历文本格式")
            uploaded = st.file_uploader("或上传简历 PDF 自动解析", type=["pdf"], key="resume_pdf")
            pdf_hash = hashlib.sha256(uploaded.getvalue()).hexdigest() if uploaded is not None else None
            if uploaded is not None and pdf_hash != st.session_state.get("parsed_pdf_hash"):
                try:
                    import pdfplumber
                    st.session_state["parsed_pdf_hash"] = pdf_hash
                    uploaded.seek(0)
                    with pdfplumber.open(uploaded) as pdf:
                        pdf_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                    p = recommend.resume_parse(pdf_text)
                    if p:
                        st.session_state["parsed"] = p
                        for _k in list(st.session_state.keys()):
                            if _k.startswith(("l0_", "l2_", "l3_")) or _k in ("l1_iw", "l1_proj"):
                                st.session_state.pop(_k, None)
                        _scalar = {k: v for k, v in p.items() if not isinstance(v, list)}
                        _n_exp = len(p.get("经历", []))
                        _n_skill = len(p.get("技能", []))
                        st.success("已从 PDF 提取：%s%s%s" % (
                            "、".join("%s=%s" % (k, v) for k, v in _scalar.items()),
                            "；经历 %d 段" % _n_exp if _n_exp else "",
                            "；技能 %d 个" % _n_skill if _n_skill else "",
                        ))
                        st.rerun()
                    else:
                        st.warning("PDF 内容未能识别，请改用手动填写或粘贴文本")
                except ImportError:
                    st.warning("PDF 解析需安装 pdfplumber（pip install pdfplumber），请改用粘贴文本或手动填写")
                except Exception as e:
                    st.warning("PDF 解析失败：" + str(e))

        parsed = st.session_state.get("parsed", {}) or {}
        l0 = {}
        _edu_start = schema.L0_FIELDS.index("学历阶段")
        st.markdown("**👤 基本信息**")
        c = st.columns(2)
        for i, f in enumerate(schema.L0_FIELDS[:_edu_start]):
            l0[f] = c[i % 2].text_input(f, value=parsed.get(f, ui.SAMPLE["l0"].get(f, "")),
                                        key="l0_" + f)
        st.markdown("**🎓 教育信息**")
        c = st.columns(2)
        for i, f in enumerate(schema.L0_FIELDS[_edu_start:]):
            l0[f] = c[i % 2].text_input(f, value=parsed.get(f, ui.SAMPLE["l0"].get(f, "")),
                                        key="l0_" + f)

        parsed_exps = parsed.get("经历", []) if isinstance(parsed.get("经历"), list) else []
        l1 = {}
        iw_default = sum(1 for x in parsed_exps if x.get("类型") == "实习/工作") if parsed_exps else 1
        proj_default = sum(1 for x in parsed_exps if x.get("类型") == "项目") if parsed_exps else 1
        l1["实习/工作"] = st.number_input("实习/工作段数", 0, max(5, iw_default), iw_default, key="l1_iw")
        l1["项目"] = st.number_input("项目段数", 0, max(5, proj_default), proj_default, key="l1_proj")
        for t in schema.L1_TYPES:
            l1.setdefault(t, 0)

        st.markdown("**🎯 求职意向**")
        l3 = {}
        c3 = st.columns(2)
        l3["意向城市"] = c3[0].text_input("意向城市", value=parsed.get("现居", "") or "北京,上海", key="l3_city")
        l3["意向行业"] = c3[1].text_input("意向行业", value="互联网,人工智能", key="l3_industry")
        l3["意向岗位"] = c3[0].text_input("意向岗位", value=parsed.get("意向岗位", "") or "后端开发,算法工程师", key="l3_job")
        l3["禁忌公司"] = c3[1].text_input("禁忌公司", value="", key="l3_taboo")
        l3["投递策略"] = c3[0].selectbox("投递策略", ["海投", "精投"], index=0, key="l3_strategy",
                                         help="海投=保留A/B级岗位；精投=只保留A级强匹配")
        l3["期望薪资"] = c3[1].text_input("期望薪资（如15k/月）", value="15k/月", key="l3_salary")
        l3["到岗时间"] = c3[0].text_input("到岗时间（如2024-07）", value="2024-07", key="l3_onboard")
        l3["能否出差"] = c3[1].selectbox("能否出差", ["是", "否"], index=0, key="l3_trip")

        # 经历编辑：按段数动态生成卡片
        l2 = []
        _sample = {"实习/工作": [x for x in ui.SAMPLE["l2"] if x["类型"] == "实习/工作"],
                   "项目": [x for x in ui.SAMPLE["l2"] if x["类型"] == "项目"]}
        _has_parsed = bool(parsed)
        with st.expander("✏️ 编辑经历（实习/项目）", expanded=bool(parsed_exps)):
            for typ in ("实习/工作", "项目"):
                n = int(l1.get(typ, 0) or 0)
                parsed_typ = [x for x in parsed_exps if x.get("类型") == typ]
                for idx in range(n):
                    if idx < len(parsed_typ):
                        src = parsed_typ[idx]
                    elif _has_parsed:
                        src = {}
                    else:
                        src = _sample[typ][idx] if idx < len(_sample[typ]) else {}
                    st.markdown(f"**{typ}经历 {idx + 1}**")
                    item = {"类型": typ, "挂靠": "独立", "证据": "无"}
                    c2 = st.columns(2)
                    item["名称"] = c2[0].text_input("名称", value=src.get("名称", ""), key=f"l2_{typ}_{idx}_name")
                    item["角色"] = c2[1].text_input("角色", value=src.get("角色", ""), key=f"l2_{typ}_{idx}_role")
                    item["时间起"] = c2[0].text_input("开始(YYYY-MM)", value=src.get("时间起", ""), key=f"l2_{typ}_{idx}_from")
                    item["时间止"] = c2[1].text_input("结束(YYYY-MM)", value=src.get("时间止", ""), key=f"l2_{typ}_{idx}_to")
                    item["事项"] = st.text_input("事项（做了什么）", value=src.get("事项", ""), key=f"l2_{typ}_{idx}_what")
                    item["结果"] = st.text_input("结果（量化成果）", value=src.get("结果", ""), key=f"l2_{typ}_{idx}_result")
                    item["技术工具"] = st.text_input("技术工具", value=src.get("技术工具", "") or ", ".join(parsed.get("技能", [])), key=f"l2_{typ}_{idx}_tech")
                    l2.append(item)

    user_data = {"l0": l0, "l1": l1, "l2": l2, "l3": l3}
    _current_info = json.dumps(user_data, ensure_ascii=False, sort_keys=True)
    if st.session_state.get("confirmed_info") not in (None, _current_info):
        st.session_state["info_confirmed"] = False
        st.caption("信息已修改，请重新确认后检索和生成材料。")
    if st.session_state.get("info_confirmed"):
        st.caption("✅ 当前信息已确认；如果修改了上面的内容，需要重新确认。")

    if not l2:
        st.warning("⚠️ 还没有填写任何经历：画像技能为空，「技能匹配（40 分）」会全部拿不到分，"
                   "匹配分也会固定为 0.5。建议至少填 1 段实习/项目经历，并在「技术工具」里写 "
                   "Python、Flask、MySQL 等关键词。")

    if st.button("✅ 确认信息，进入下一步", type="primary"):
        ok, errors = verification.verify(user_data)
        if not ok:
            st.error("❌ 信息核检未通过，请修改后再确认：")
            for e in errors:
                st.warning("· " + e)
        else:
            st.session_state["info_confirmed"] = True
            st.session_state["confirmed_info"] = _current_info
            st.session_state["confirmed_user_data"] = json.loads(_current_info)
            st.session_state.pop("_no_auto_restore", None)  # 新信息已确认，恢复正常自动回填
            ui.goto(1, "✅ 信息已确认，进入第 ② 阶段：平台与登录")


# ======================================================================
# ② 平台与登录
# ======================================================================
def render_step_2(states):
    theme.section("②", "平台与登录",
                  "勾选要用的平台并扫码登录；登录一次后状态自动保存，下次不用再扫",
                  status=states[1])
    _status_by_key = {s["key"]: s for s in ui.login_report()}

    keys = list(platforms.PLATFORMS.keys())
    cols = st.columns(len(keys))
    selected = []
    for i, k in enumerate(keys):
        p = platforms.get(k)
        with cols[i]:
            if st.checkbox(p["name"], key="sel_" + k, value=(k == "boss")):
                selected.append(k)
            _st = _status_by_key.get(k, {})
            st.markdown(theme.pill(_st.get("kind", "off"), _st.get("label", "未登录")),
                        unsafe_allow_html=True)
    st.session_state["selected_platforms"] = selected

    if selected:
        for k in selected:
            p = platforms.get(k)
            if session.has_session(k):
                st.markdown("🟢 " + p["name"] + "（已登录，已保存 cookie）")
            elif session.profile_available(k):
                st.markdown("🟡 " + p["name"] + "（有本地登录目录，未验证；若检索提示失效请重新扫码）")
            else:
                st.markdown("⚪ " + p["name"] + "（未登录）")
        c1, c2, c3 = st.columns(3)
        if c1.button("🌐 打开登录页", key="btn_real_open"):
            for k in selected:
                ok, msg = session.dpage_open(k)
                st.info(f"{platforms.get(k)['name']}：{msg}")
            st.caption("👉 在弹出的浏览器里扫码登录（如出现滑块请手动拖动，登录后回来点右侧）")
        if c2.button("✅ 我已完成登录", key="btn_real_finish"):
            saved, failed = [], []
            for k in selected:
                ok, msg = session.dpage_finish(k)
                if ok:
                    saved.append(platforms.get(k)["name"])
                else:
                    failed.append("%s：%s" % (platforms.get(k)["name"], msg))
            if saved:
                # 登录态刚变化，清掉 5 分钟的检测缓存并重跑，让侧栏/②状态牌立即更新
                st.session_state.pop("login_report", None)
                _msg = "、".join(saved) + "：登录成功，状态已刷新"
                if failed:
                    _msg += "；" + "；".join(failed)
                if ui.any_selected_logged_in():
                    ui.goto(2, _msg + "；进入第 ③ 阶段：检索岗位")
                st.session_state["_login_flash"] = _msg
                st.rerun()
            for _line in failed:
                st.warning(_line)
        with c3:
            _qr_target = selected[0] if len(selected) == 1 else st.selectbox(
                "扫码平台", selected,
                format_func=lambda _k: platforms.get(_k)["name"],
                key="qr_pk_choice", label_visibility="collapsed")
            if st.button("📱 网页内扫码", key="btn_qr_open",
                         help="浏览器在后台隐藏运行不弹窗，二维码实时显示在本页弹窗里"):
                with st.spinner("正在后台打开登录页…"):
                    _ok, _msg = session.qr_login_start(_qr_target)
                if _ok:
                    st.session_state["qr_login_pk"] = _qr_target
                    st.rerun()
                else:
                    st.error("%s：%s" % (platforms.get(_qr_target)["name"], _msg))

    logged_in = [k for k in selected if session.can_search(k)]
    if logged_in:
        st.success("🔍 可用于检索的平台：" + "、".join(platforms.get(k)["name"] for k in logged_in))
        st.caption("登录完成后会自动进入第 ③ 阶段；也可以点页面底部「下一页」。")
    elif selected:
        st.caption("🔒 至少完成一个平台的登录后，才会进入第 ③ 阶段检索岗位。")

    # 网页内扫码面板（点「📱 网页内扫码」后触发）
    if st.session_state.get("qr_login_pk"):
        ui.qr_panel(st.session_state["qr_login_pk"])


# ======================================================================
# ③ 检索岗位
# ======================================================================
def render_step_3(states):
    theme.section("③", "检索岗位", "输入关键词，在已登录平台检索", status=states[2])
    user_data = st.session_state.get("confirmed_user_data") or {}
    selected = ui.selected_platforms()
    logged_in = [k for k in selected if session.can_search(k)]

    kw = st.text_input("检索关键词", value="Python 后端", key="kw")
    pages = st.number_input("检索页数（每页约15岗）", 1, 3, 2, key="pages",
                            help="单次最多3页，防平台限流封号")

    _info_ok = bool(st.session_state.get("info_confirmed"))
    _login_ok = bool(logged_in)
    _blockers = []
    if not selected:
        _blockers.append("第②阶段未勾选平台")
    if not _info_ok:
        _blockers.append("第①阶段信息未确认")
    if not _login_ok:
        _blockers.append("第②阶段没有可用登录态")
    if not _info_ok:
        st.caption("🔒 先回到第 ① 阶段点「✅ 确认信息，进入下一步」")
    elif not _login_ok:
        st.caption("🔒 先回到第 ② 阶段勾选平台并完成扫码登录")

    if st.button("🔍 开始检索", type="primary",
                 disabled=not (_info_ok and _login_ok),
                 help="；".join(_blockers) if _blockers else "在已登录平台检索岗位"):
        city = ((user_data.get("l3") or {}).get("意向城市", "北京") or "北京").replace("，", ",").split(",")[0].strip()
        st.caption("⏳ 首次检索需启动浏览器并真实搜索，约 30~60 秒，请稍候…")
        with st.spinner("正在真实检索各平台岗位..."):
            jobs, logs = loop.search_logged_in_platforms(logged_in, kw, city=city, pages=int(pages))
        st.session_state["jobs"] = jobs
        for _key in ("result", "rematch", "rematch_old", "prepared_user_data"):
            st.session_state.pop(_key, None)
        _log_txt = "；".join("%s：%s" % (platforms.get(k)["name"], msg) for k, msg in logs)
        _login_fail = [k for k in logged_in if "登录" in (session.last_search_error(k) or "")]
        if _login_fail:
            st.warning("登录态已失效：%s。请回第②阶段重新扫码，并点「✅ 我已完成登录」后再检索。"
                       % "、".join(platforms.get(k)["name"] for k in _login_fail))
            st.caption(_log_txt)
        elif jobs:
            ui.goto(3, "✅ 检索完成：共 %d 个岗位，进入第 ④ 阶段准备投递材料。%s"
                    % (len(jobs), _log_txt[:220]))
        else:
            st.warning("本次检索结果为 0 条，请检查关键词/城市或登录态。")
            if _log_txt:
                st.caption(_log_txt)

    if st.session_state.get("jobs") is not None:
        _jobs = st.session_state["jobs"]
        if _jobs:
            st.markdown(theme.jobs_table(_jobs), unsafe_allow_html=True)
            st.caption("共 %d 个岗位；检索完成后会自动进入下一阶段，可点底部「上一页」回看。" % len(_jobs))
        else:
            st.caption("本次检索结果为 0 条")
    else:
        theme.empty_state("🔍", "还没有检索结果",
                          "填好关键词后点「开始检索」，岗位列表会显示在这里")


# ======================================================================
# ④ 准备投递材料
# ======================================================================
def render_step_4(states):
    theme.section("④", "准备投递材料",
                  "系统自动：画像 → 匹配 → 建任务 → 生成针对性简历+招呼语（不自动发送，你逐条确认）",
                  status=states[3])
    user_data = st.session_state.get("confirmed_user_data") or {}
    _info_ok = bool(st.session_state.get("info_confirmed"))
    _has_jobs = bool(st.session_state.get("jobs"))
    _material_ready = bool(st.session_state.get("result") and st.session_state["result"].get("ok"))

    if not _info_ok or not user_data:
        st.warning("第①阶段的信息尚未确认（或页面刷新后丢失），请先回到第①阶段确认信息。")
        if st.button("⬅️ 回到第①阶段", key="step4_back_info"):
            ui.goto(0)
        return
    if not _has_jobs:
        st.caption("🔒 先在第③阶段完成检索")
        if st.button("⬅️ 回到第③阶段检索", key="step4_back_search"):
            ui.goto(2)
        return

    st.caption("本机已检索到 %d 个岗位，点击下方按钮后会批量生成画像、匹配分和针对性简历。"
               % len(st.session_state.get("jobs") or []))
    if _material_ready:
        st.info("✅ 已生成过投递材料，可直接进入第⑤阶段；如需重新生成，先点侧边栏「🔄 重新开始」。")
        if st.button("进入第⑤阶段：逐条投递 →", type="primary", key="step4_next"):
            ui.goto(4)
        return

    if st.button("🚀 准备投递材料", type="primary", disabled=not _info_ok):
        with st.spinner("正在画像、匹配、生成简历与招呼语..."):
            result = loop.run_closed_loop(user_data, jobs=st.session_state.get("jobs"))
        if not result["ok"]:
            st.error("❌ 信息核检未通过，请回到第①阶段检查信息：")
            for e in result["errors"]:
                st.warning("· " + e)
        else:
            st.session_state["result"] = result
            st.session_state["prepared_user_data"] = copy.deepcopy(user_data)
            ui.goto(4, "✅ 已为 %d 个岗位准备好针对性简历和招呼语，进入第 ⑤ 阶段。"
                    % result["task_count"])


# ======================================================================
# ⑤ 逐条投递 + 反馈
# ======================================================================
def render_step_5(states):
    theme.section("⑤", "逐条投递与反馈", status=states[4])
    r = _ensure_result()
    _show_restore_notice()
    if not (r and r.get("ok")):
        theme.empty_state("📮", "还没有可投递的岗位",
                          "完成第④阶段「准备投递材料」后，匹配岗位会列在这里")
        if st.button("⬅️ 返回第④阶段准备材料", key="step5_back"):
            ui.goto(3)
        return

    prepared_data = (st.session_state.get("prepared_user_data")
                     or st.session_state.get("confirmed_user_data") or {})
    summ = r.get("画像摘要", {})
    if summ:
        def _j(x):
            return "、".join(x) or "无"
        st.markdown("🧠 **你的画像**：技能 `%s` · 意向岗位 `%s` · 意向行业 `%s` · 城市 `%s`"
                    % (_j(summ.get("技能标签", [])), _j(summ.get("意向岗位", [])),
                       _j(summ.get("意向行业", [])), _j(summ.get("意向城市", []))))
    if config.SAFE_MODE:
        st.warning("🔒 安全模式已开启：投递不会自动发送，只生成招呼语供你复制手动发送（能力在代码里，改 config.SAFE_MODE=False 才会自动投递）")
    else:
        st.info("自动投递已开启（有封号风险）")

    # 画像闭环：反馈后「用新画像重新匹配」，让式三间隔特征 δ 真正生效
    if st.button("🔄 用新画像重新匹配", key="btn_rematch",
                 help="标注进面试/未进面试后，用式五修正的权重 + 正负岗位中心重新打分排序"):
        st.session_state["rematch"] = pipeline.re_match(r["user_id"], prepared_data)
        st.session_state["rematch_old"] = {j.get("job_id", j["岗位名称"]): j.get("score")
                                           for j in r["target_jobs"]}
    _rm = st.session_state.get("rematch")
    if _rm is not None:
        with st.expander("📈 重新匹配结果（画像闭环进化）", expanded=True):
            _old_map = st.session_state.get("rematch_old", {})
            _has_center = any(x.get("has_center") for x in _rm)
            if _has_center:
                st.success("✅ 式三间隔特征已启用：匹配分已依据「进面试/未进面试」岗位中心闭环更新")
            else:
                st.caption("正负岗位中心尚未形成（需各标注至少一个进面试与未进面试），间隔特征暂未启用，匹配分不变")
            for x in _rm:
                _job = x["job"]
                _name = _job.get("岗位名称", "")
                _old = round(float(_old_map.get(x.get("job_id", _name), 0)), 4)
                _new = round(float(x["score"]), 4)
                _delta = round(float(x["delta"]), 4)
                st.caption(f"{_name}：匹配分 {_old} → {_new}（δ={_delta}）")
            _fig = viz.evolution_bar(_rm, _old_map)
            if _fig is not None:
                theme.chart(_fig)
                st.caption("式三间隔特征 δ 生效：更靠近「进面试」岗位中心者分数升、更靠近「未进面试」者分数降")

    greet_map = {d["task_id"]: d.get("招呼语", "") for d in r.get("delivery_report", [])}
    _conn = db.get_conn()
    _task_states = {}
    _task_entries = {}
    for _t in _conn.execute(
            "SELECT task_id, status, result, entry_type, entry_addr FROM delivery_tasks "
            "WHERE user_id=?", (r["user_id"],)).fetchall():
        _task_states[_t["task_id"]] = (_t["status"], _t["result"])
        _task_entries[_t["task_id"]] = delivery.classify_entry(_t["entry_type"], _t["entry_addr"])
    _conn.close()

    _pending_tids = [tid for tid, (st_, _res) in _task_states.items() if st_ == "待投递"]
    if _pending_tids:
        _pending_by_entry = {}
        for _tid in _pending_tids:
            _k = _task_entries.get(_tid, "半自动")
            _pending_by_entry[_k] = _pending_by_entry.get(_k, 0) + 1
        _entry_txt = " · ".join("%s %d" % (k, v) for k, v in sorted(_pending_by_entry.items()))
        _remaining_today = max(0, config.DAILY_SEND_LIMIT - delivery._daily_sends())
        _all_cap = min(len(_pending_tids), _remaining_today)
        _batch_n = min(config.BATCH_SEND_LIMIT, len(_pending_tids), _remaining_today)
        st.markdown("**🚀 批量投递（全部渠道）**")
        st.caption("待投递 **%d** 个（%s）· 今日已成功 **%d** 条 · 今日剩余额度 **%d** 条"
                   "（每日上限 %d）"
                   % (len(_pending_tids), _entry_txt or "—",
                      config.DAILY_SEND_LIMIT - _remaining_today,
                      _remaining_today, config.DAILY_SEND_LIMIT))
        st.caption("单批模式：每次最多 %d 个、间隔 %d 秒；全部模式：把**今日剩余额度**一次投完，"
                   "间隔 %d 秒。额度用完需明天继续，或调高 config.py 的 DAILY_SEND_LIMIT（有封号风险）。"
                   % (config.BATCH_SEND_LIMIT, config.DELIVER_INTERVAL,
                      config.DELIVER_INTERVAL_ALL))
        _b1, _b2 = st.columns(2)
        with _b1:
            if st.button("🚀 投递 %d 个" % _batch_n, key="batch_deliver",
                         disabled=config.SAFE_MODE or not _pending_tids,
                         help="按匹配分顺序投 %d 个（单批上限），间隔 %d 秒"
                              % (config.BATCH_SEND_LIMIT, config.DELIVER_INTERVAL)):
                with st.spinner("批量投递中（每条间隔 %d 秒，防封号）..." % config.DELIVER_INTERVAL):
                    _batch = delivery.deliver_batch(task_ids=_pending_tids)
                st.session_state["_batch_result"] = _batch
                st.rerun()
        with _b2:
            if st.button("🌊 全部投递（今日 %d 个）" % _all_cap, key="batch_deliver_all",
                         disabled=config.SAFE_MODE or _all_cap <= 0,
                         help="今日剩余额度 %d 条；待投递共 %d 个，超出部分需明天继续。间隔 %d 秒"
                              % (_all_cap, len(_pending_tids), config.DELIVER_INTERVAL_ALL)):
                _eta = max(1, int(round(_all_cap * config.DELIVER_INTERVAL_ALL / 60.0)))
                with st.spinner("全部投递中：%d 个岗位，每条间隔 %d 秒（约 %d 分钟）..."
                                % (_all_cap, config.DELIVER_INTERVAL_ALL, _eta)):
                    _batch = delivery.deliver_batch(task_ids=_pending_tids,
                                                    limit=_all_cap,
                                                    interval=config.DELIVER_INTERVAL_ALL,
                                                    all_pending=True)
                st.session_state["_batch_result"] = _batch
                st.rerun()

        _batch = st.session_state.pop("_batch_result", None)
        if _batch:
            st.success("✅ 投递完成：成功 %d / 失败 %d" % (_batch["成功数"], _batch["失败数"]))
            if _batch.get("按渠道"):
                st.caption("按渠道：" + " · ".join("%s %d" % (k, v)
                                                   for k, v in sorted(_batch["按渠道"].items())))
            if _batch["停止原因"]:
                st.warning("⚠️ " + _batch["停止原因"])
            for _tid, _ok, _msg in _batch["明细"]:
                if not _ok:
                    st.caption(f"· 任务{_tid}：{_msg}")

    _targets = r["target_jobs"]
    _delivered_n = sum(1 for _s, _r2 in _task_states.values() if _s == "已投递")
    _avg_score = round(sum(float(j["score"]) for j in _targets) / len(_targets), 3) if _targets else 0
    _a_count = sum(1 for j in _targets if j["等级"] == "A")
    _k1, _k2, _k3, _k4 = st.columns(4)
    _k1.metric("目标岗位", len(_targets))
    _k2.metric("平均匹配分", _avg_score)
    _k3.metric("A 级强匹配", _a_count)
    _k4.metric("已投递", _delivered_n)

    _persona = persona.build_persona(prepared_data, targets=_targets, weights=r.get("weights"))
    workbench.render(_targets, _persona, key_prefix="ms")

    for job in r["target_jobs"]:
        with st.container(border=True):
            _status, _result = _task_states.get(job["task_id"], ("待生成", None))
            c1, c2, c3, c4 = st.columns([3.4, 1, 1, 1])
            c1.markdown(theme.job_card_header(job), unsafe_allow_html=True)
            with c1.expander("🔎 推荐理由 & 分数明细"):
                reasons = job.get("推荐理由", [])
                if reasons:
                    st.markdown("· " + "；".join(reasons))
                breakdown = job.get("分数明细", [])
                if breakdown:
                    st.caption("**等级分构成**（技能40+方向25+学历15+薪资10+行业5+城市5）：")
                    for dim, s, note in breakdown:
                        st.caption(f"　· {dim}：{'+' if s >= 0 else ''}{s}分（{note}）")
                mc = job.get("匹配分构成", {})
                if mc:
                    st.caption(f"**匹配分（式三）**：p = σ({mc['w_s']}×{mc['余弦相似度s']} + {mc['w_δ']}×{mc['间隔特征δ']}) = {mc['匹配分p']}")
                g = greet_map.get(job["task_id"], "")
                if g:
                    st.code(g, language=None)
                resume = job.get("简历内容", {})
                if resume:
                    st.caption("**📄 简历内容（检查）**：")
                    resume_txt = "　".join(f"{k}：{v}" for k, v in resume.items() if v)
                    if resume_txt:
                        st.code(resume_txt, language=None)
                written = job.get("写入经历", [])
                if written:
                    st.caption("**✍️ 写入简历的经历（式四分配）**：" + "、".join(written))
                alloc = job.get("经历分配", [])
                if alloc:
                    alloc_str = "；".join("%s（γ=%s）" % (n, g) for n, g in alloc)
                    st.caption("**⚖️ 式四分配系数 γ**（指数倾斜）：" + alloc_str)
                    st.caption("**✏️ 修改写入经历（勾选后重新生成）**：")
                    written_names = set(job.get("写入经历", []))
                    written_indices = job.get("写入经历索引")
                    included_idx = []
                    for _idx, (n, g) in enumerate(alloc):
                        if st.checkbox("%s（γ=%s）" % (n, g),
                                       value=(_idx in written_indices if written_indices is not None else n in written_names),
                                       key=f"sel_{job['task_id']}_{_idx}"):
                            included_idx.append(_idx)
                    if st.button("🔄 按勾选重新生成简历", key=f"regen_{job['task_id']}",
                                 disabled=_status in schema.TASK_LOCKED):
                        import user_profile as profile_mod
                        import generation
                        prof = profile_mod.build_profile(r["user_id"])
                        generation.regenerate_one(r["user_id"], prof, job["task_id"], included_idx)
                        delivery.prepare_batch(r["user_id"], [job["task_id"]], user_data=prepared_data)
                        conn = db.get_conn()
                        fm = conn.execute("SELECT fields FROM job_field_map WHERE task_id=?",
                                          (job["task_id"],)).fetchone()
                        conn.close()
                        if fm:
                            job["简历内容"] = json.loads(fm["fields"])
                        job["写入经历"] = [n for i, (n, g) in enumerate(alloc) if i in included_idx]
                        job["写入经历索引"] = included_idx
                        st.success("已按勾选重新生成简历")
                        st.rerun()
                link = str(job.get("岗位链接", "") or "")
                if link.lower().startswith(("http://", "https://")):
                    st.markdown(f"[打开岗位详情]({link})")
                elif link:
                    st.caption("岗位链接格式无效，已忽略：%s" % link[:60])
                with db.get_conn() as _download_conn:
                    _file_row = _download_conn.execute(
                        "SELECT resume_path FROM delivery_tasks WHERE task_id=?",
                        (job["task_id"],)).fetchone()
                _file = resolve_resume(_file_row["resume_path"]) if _file_row else None
                if _file:
                    st.download_button("📥 下载针对性简历", data=_file.read_bytes(),
                                       file_name=_file.name, key=f"download_{job['task_id']}")

            if _status == "已投递":
                _deliver_label, _can_deliver = "📤 已投递", False
            elif _status in ("投递中", "待核实"):
                _deliver_label, _can_deliver = "⏳ 待核实（请人工确认）", False
            elif _status == "待投递":
                _deliver_label = "查看投递材料" if config.SAFE_MODE else "📤 投递"
                _can_deliver = True
            else:
                _deliver_label, _can_deliver = "📤 投递", False
            if c2.button(_deliver_label, key=f"del_{job['task_id']}", disabled=not _can_deliver):
                ok, msg = delivery.deliver_one(job["task_id"])
                if ok:
                    st.success(msg)
                else:
                    st.warning(msg)
            if c2.button("确认已手动投递", key=f"manual_{job['task_id']}",
                         disabled=_status not in ("待投递", "待核实", "投递中")):
                delivery.record_manual_delivery(job["task_id"])
                st.rerun()
            if c3.button("✅ 进面试", key=f"fb1_{job['task_id']}",
                         disabled=(_result == "进面试" or _status != "已投递")):
                ok, msg = feedback.mark_result(job["task_id"], 1)
                st.success("已标记进面试，画像权重已更新") if ok else st.warning(msg)
                st.rerun()
            if c4.button("❌ 未进面试", key="fb0_%s" % job["task_id"],
                         disabled=(_result == "未进面试" or _status != "已投递")):
                ok, msg = feedback.mark_result(job["task_id"], 0)
                st.success("已标记未进面试，画像权重已更新") if ok else st.warning(msg)
                st.rerun()

    if _delivered_n:
        st.caption("💡 投递与反馈操作完成后，点页面底部「下一页 ➡️」进入第⑥阶段查看投递记录。")
    else:
        st.caption("💡 投递、标注反馈都可以在这里反复操作；想先看历史记录，点底部「下一页 ➡️」或侧栏「⑥ 记录」。")


# ======================================================================
# ⑥ 投递记录与画像统计
# ======================================================================
def render_step_6(states):
    theme.section("⑥", "投递记录与画像统计", status=states[5])
    _r = _ensure_result()
    _show_restore_notice()
    if not (_r and _r.get("ok")):
        theme.empty_state("🗂️", "还没有投递记录",
                          "完成第④阶段「准备投递材料」后，所有投递任务的状态与结果会集中展示在这里")
        if st.button("⬅️ 返回第④阶段准备材料", key="step6_back"):
            ui.goto(3)
        return

    _record_data = (st.session_state.get("prepared_user_data")
                    or st.session_state.get("confirmed_user_data") or {})
    conn = db.get_conn()
    tasks = conn.execute(
        "SELECT * FROM delivery_tasks WHERE user_id=? ORDER BY task_id", (_r["user_id"],)
    ).fetchall()
    conn.close()
    if not tasks:
        st.caption("当前还没有投递任务。")
        return

    # ---- HR 回应（手动 + 方案 B 识别；只写本机 SQLite，不联网、不外传） ----
    uid = _r["user_id"]
    _latest_resp = responses.latest_by_task(uid)
    _resp_stat = responses.summary(uid)

    rows = [{"岗位": t["job_name"], "单位": t["unit_name"],
             "投递状态": t["status"],
             "最新HR回应": (_latest_resp.get(t["task_id"]) or {}).get("kind", "—"),
             "回应时间": (_latest_resp.get(t["task_id"]) or {}).get("first_seen", "—"),
             "画像反馈": t["result"] or "—"} for t in tasks]
    theme.dataframe(pd.DataFrame(rows), hide_index=True)
    st.download_button("📥 导出投递记录 CSV",
                       data=pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig"),
                       file_name="投递记录.csv", mime="text/csv")

    with st.expander("📝 登记 HR 回应（手动，本地保存）", expanded=False):
        st.caption("平台没有公开 API，回应由你手动登记或由下面的「检查新回复」识别；"
                   "共 %d 条记录，只写本机数据库。" % _resp_stat["总数"])
        _labels = {t["task_id"]: "%s @ %s" % (t["job_name"] or "", t["unit_name"] or "")
                   for t in tasks if t["status"] not in ("待生成",)}
        if not _labels:
            st.caption("还没有已生成的投递任务。")
        else:
            c1, c2 = st.columns([2, 1])
            _tid = c1.selectbox("选择岗位", list(_labels),
                                format_func=lambda x: "#%d %s" % (x, _labels[x]), key="resp_task")
            _kind = c2.selectbox("回应类型", list(responses.KINDS), key="resp_kind")
            st.caption(responses.KIND_HINT.get(_kind, ""))
            _note = st.text_input("备注（可选，如 HR 约的面试时间/渠道）", key="resp_note")
            if st.button("➕ 登记回应", key="resp_add", type="primary"):
                ok, msg, _rid = responses.add_response(_tid, _kind, _note)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.warning(msg)

    with st.expander("🔎 检查新回复（方案 B：手动触发，只读会话列表）", expanded=False):
        st.caption("用已登录浏览器打开消息页，只读取会话列表，不发送任何内容；"
                   "识别结果需要你勾选后才写入回应记录。请勿高频点击（平台有风控）。")
        _logged = [k for k in platforms.PLATFORMS if session.can_search(k)]
        if not _logged:
            st.caption("🔒 先在第②阶段完成至少一个平台的登录。")
        else:
            _pk = st.selectbox("平台", _logged,
                               format_func=lambda x: platforms.get(x)["name"], key="reply_pk")
            if st.button("🔎 检查新回复", key="reply_check", type="primary"):
                with st.spinner("正在读取消息页（只读，约 10~20 秒）..."):
                    _check = replies.check(_pk, [dict(t) for t in tasks])
                # 注意：不能写 st.session_state["reply_check"]——那是按钮的 widget key，
                # 控件实例化后不可修改，会抛 StreamlitWidgetAlreadyInstantiatedError。
                st.session_state["reply_check_result"] = _check
                st.session_state["reply_check_platform"] = _pk
                st.rerun()

            _check = st.session_state.get("reply_check_result")
            if _check:
                if _check.get("error"):
                    st.warning(_check["error"])
                if _check.get("debug"):
                    with st.expander("调试信息", expanded=False):
                        for _line in _check["debug"]:
                            st.caption("· " + _line)
                _cands = _check.get("candidates") or []
                st.caption("识别到 %d 条会话记录，匹配到 %d 个投递岗位。"
                           % (len(_check.get("records") or []), len(_cands)))
                if _check.get("probe"):
                    st.info("未识别到结构化会话，原始样本已保存：%s"
                            "（可据此调整 platforms.py 里的 chat 字段映射）" % _check["probe"])
                if _cands:
                    _df = pd.DataFrame([{
                        "任务": c["task_id"], "岗位": c["岗位"], "单位": c["单位"],
                        "建议类型": c["建议类型"], "匹配度": c["匹配度"],
                        "最后消息": (c["最后消息"] or "")[:60], "时间": c["时间"],
                    } for c in _cands])
                    theme.dataframe(_df, hide_index=True)
                    _labels = ["#%d %s @ %s（%s）" % (c["task_id"], c["岗位"], c["单位"],
                                                     c["建议类型"]) for c in _cands]
                    _pick = st.multiselect("选择要登记为 HR 回应的条目", _labels,
                                           default=_labels, key="reply_pick")
                    if st.button("📥 登记选中回应", key="reply_register"):
                        _chosen = [c for c, lb in zip(_cands, _labels) if lb in _pick]
                        _added, _dup, _details = replies.register(
                            _chosen, platform_key=st.session_state.get("reply_check_platform", ""))
                        st.success("新增 %d 条，重复 %d 条" % (_added, _dup))
                        if _added:
                            st.rerun()

                _unmatched = _check.get("unmatched") or []
                if _unmatched:
                    st.markdown("**未匹配到投递任务的会话**（可能是别处投递/非本系统记录，仅供参考）")
                    _udf = pd.DataFrame([{
                        "单位": u["单位"] or "—", "岗位": u["岗位"] or "—", "HR": u["HR"] or "—",
                        "建议类型": u["建议类型"], "最后消息": (u["最后消息"] or "")[:60],
                        "时间": u["时间"] or "—",
                    } for u in _unmatched])
                    theme.dataframe(_udf, hide_index=True)

    _resp_rows = responses.list_responses(uid)
    if _resp_rows:
        st.markdown("**📨 HR 回应时间线**（最新在上）")
        _timeline = [{"时间": r["first_seen"], "岗位": r["job_name"], "单位": r["unit_name"],
                      "回应": r["kind"], "备注": r["content"] or "—",
                      "来源": "手动" if r["source"] == "manual" else r["source"]}
                     for r in _resp_rows]
        theme.dataframe(pd.DataFrame(_timeline), hide_index=True)
        st.download_button("📥 导出 HR 回应 CSV",
                           data=pd.DataFrame(responses.export_rows(uid)).to_csv(index=False).encode("utf-8-sig"),
                           file_name="hr回应记录.csv", mime="text/csv")

    _inbox = replies.list_inbox(50)
    if _inbox:
        with st.expander("📥 检查到的 HR 消息（含未匹配任务，本机全部账号）", expanded=False):
            theme.dataframe(pd.DataFrame([{
                "时间": r["first_seen"], "单位": r["company"] or "—", "HR": r["hr"] or "—",
                "类型": r["kind"], "消息": (r["message"] or "")[:60],
                "关联任务": ("#%d" % r["task_id"]) if r["task_id"] else "—",
            } for r in _inbox]), hide_index=True)
            st.caption("收件箱只记录本机读到的会话（幂等去重），不联网、不外传。")

    stats = feedback.get_quality(_r["user_id"])
    _s1, _s2, _s3, _s4, _s5 = st.columns(5)
    _s1.metric("累计投递", stats["累计投递"])
    _s2.metric("进面试", stats["进面试"])
    _s3.metric("进面试率", "%d%%" % stats["进面试率%"], help="进面试 ÷ 已标注结果（真实转化质量）")
    _s4.metric("反馈率", "%d%%" % stats["反馈率%"], help="已标注 ÷ 已投递（标注配合度）")
    _s5.metric("画像快照", stats["快照数"], help="每次反馈后画像自动优化")
    if stats["已投递平均匹配分"]:
        st.caption("📐 已投递岗位的平均匹配分（式三 p）：%s" % stats["已投递平均匹配分"])
    _kc = _resp_stat["分类"]
    st.caption("📨 已登记 HR 回应 %d 条：邀面试 %d · 不合适 %d · 已查看 %d · 无回复 %d · 其他 %d"
               % (_resp_stat["总数"], _kc.get("邀面试", 0), _kc.get("不合适", 0),
                  _kc.get("已查看", 0), _kc.get("无回复", 0), _kc.get("其他", 0)))

    ev = feedback.get_profile_evolution(_r["user_id"])
    if len(ev) >= 2:
        with st.expander("📈 画像演进（经历权重随反馈变化）", expanded=True):
            exp_names = [e.get("名称", "经历%d" % i) for i, e in enumerate(_record_data.get("l2", []))]
            w_rows = []
            for i, e in enumerate(ev):
                w = json.loads(e["weights"])
                row = {"快照": i + 1}
                for j, name in enumerate(exp_names):
                    row[name] = round(float(w[j]), 4) if j < len(w) else 0
                row["正负中心"] = "已形成" if (e["pos_center"] and e["neg_center"]) else "未形成"
                w_rows.append(row)
            theme.dataframe(pd.DataFrame(w_rows), hide_index=True)
            st.caption("权重增大 = 该经历更受认可（进面试）；权重减小 = 相对不受认可。正负中心 = 岗位正/负样本均值（式三间隔特征用）")

    _res = [t["result"] for t in tasks if t["result"] in feedback.RESULTS]
    _has_ev = bool(ev) and bool(json.loads(ev[-1]["weights"])) if ev else False
    if _res or _has_ev:
        with st.expander("📊 数学统计可视化（投递结果·经历权重）", expanded=True):
            _w1, _w2 = st.columns(2)
            with _w1:
                _fig = viz.result_pie(_res)
                if _fig is not None:
                    theme.chart(_fig)
                else:
                    st.caption("暂无反馈结果")
            with _w2:
                if _has_ev:
                    _lastw = json.loads(ev[-1]["weights"])
                    _expn = [e.get("名称", "经历%d" % i) for i, e in enumerate(_record_data.get("l2", []))]
                    _fig = viz.weight_pie(_lastw, _expn)
                    if _fig is not None:
                        theme.chart(_fig)
                else:
                    st.caption("暂无画像快照")
    st.caption("🎉 已完成全部阶段。如需重新开始，点侧边栏「🔄 重新开始」。")
