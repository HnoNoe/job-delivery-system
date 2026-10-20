"""求职批量投递系统 —— 傻瓜式向导界面。

6 步逐步引导，每步点一个按钮即可，非技术用户照着操作也能成功：
① 确认信息 → ② 平台登录 → ③ 检索岗位 → ④ 准备材料 → ⑤ 逐条投递 → ⑥ 投递记录

交互逻辑：侧栏六步进度条 + 每步状态圆牌（✓已完成/●进行中/○待开始）；
按钮前置门控（条件不满足即禁用并给出引导），不再靠点了之后才警告。

视觉层统一走 theme.py（色彩令牌 / CSS 主题 / Plotly 模板），本文件不写裸颜色值。
"""
import json
import pandas as pd
import streamlit as st

import db
import schema
import config
import platforms
import session
import loop
import delivery
import feedback
import verification
import recommend
import pipeline
import theme
import viz


def _full_width_kwargs() -> dict:
    """表格全宽渲染参数（跨 Streamlit 版本自适应）。

    Streamlit ≥1.49 已弃用 use_container_width（2025-12-31 后移除），
    改用 width='stretch'；requirements.txt 允许 >=1.32，故旧版本回退。
    """
    try:
        major, minor = (int(x) for x in st.__version__.split(".")[:2])
        if (major, minor) >= (1, 49):
            return {"width": "stretch"}
    except Exception:
        pass
    return {"use_container_width": True}


def show_table(df, **kwargs):
    """统一的全宽表格渲染入口，避免 Streamlit 弃用告警。"""
    st.dataframe(df, **_full_width_kwargs(), **kwargs)


def _wizard_states():
    """六步完成状态（done/active/todo），驱动侧栏进度条与步骤头状态牌。

    active = 第一个未完成的步骤（用户当前该做的事）。
    """
    r = st.session_state.get("result")
    s4 = bool(r and r.get("ok"))
    delivered = feedback_given = False
    if s4:
        conn = db.get_conn()
        row = conn.execute(
            "SELECT SUM(status='已投递') AS d, SUM(result<>'') AS f "
            "FROM delivery_tasks WHERE user_id=?", (r["user_id"],)).fetchone()
        conn.close()
        delivered = bool(row and row["d"])
        feedback_given = bool(row and row["f"])
    done = [
        bool(st.session_state.get("info_confirmed")),     # ① 确认信息
        any(session.is_active(pk) for pk in platforms.PLATFORMS),  # ② 平台登录
        bool(st.session_state.get("jobs")),               # ③ 检索岗位
        s4,                                               # ④ 准备材料
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

st.set_page_config(page_title="求职批量投递系统", page_icon="🎯", layout="wide")
theme.apply()

db.init_db()
_states = _wizard_states()

# ---------------- 顶部 ----------------
theme.hero()

# ---------------- 侧边栏：进度 + 重置 + 状态 ----------------
with st.sidebar:
    st.markdown("**操作说明**")
    st.caption("按 ①→⑥ 顺序，每步点一个按钮即可。")
    theme.stepper(list(zip(
        ["①信息", "②登录", "③检索", "④材料", "⑤投递", "⑥记录"], _states)))
    if st.button("🔄 重新开始"):
        # 先清平台会话与浏览器，再清界面状态，最后一次性刷新
        #（st.rerun 会中断本次执行，写在它后面的代码永远跑不到）
        for pk in platforms.PLATFORMS:
            session.clear_session(pk)
            session.dpage_quit(pk)  # 同时关闭保持打开的浏览器
        for k in list(st.session_state.keys()):
            if (k in ("info_confirmed", "logged_in", "jobs", "result", "parsed",
                      "resume_pdf", "resume_text")
                    or k.startswith(("l0_", "l2_", "l3_")) or k in ("l1_iw", "l1_proj")):
                st.session_state.pop(k, None)
        st.rerun()
    st.divider()
    st.caption("平台登录状态")
    for pk, name in platforms.names():
        _logged = session.has_session(pk)
        st.markdown(theme.pill("ok" if _logged else "off",
                               ("● 已登录 · " if _logged else "○ 未登录 · ") + name),
                    unsafe_allow_html=True)
    st.divider()
    with st.expander("📐 数学说明（分数怎么算）"):
        st.caption(recommend.explain_match_score())
        st.caption(recommend.explain_weights(None))
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

# ================= 步骤① 确认我的信息 =================
theme.section("①", "确认我的信息",
              "下面是示例占位信息，请点开改成你的真实信息（姓名/学校/专业/手机/邮箱/经历）",
              status=_states[0])
with st.expander("查看 / 修改我的信息", expanded=True):
    # 粘贴简历自动解析（减少手填）
    with st.expander("📋 粘贴简历文本自动填充（可选）"):
        resume_text = st.text_area("把简历内容粘贴到这里，点解析自动提取姓名/手机/邮箱/学校/专业/技能",
                                   key="resume_text", height=100)
        if st.button("🔍 解析文本并填充", key="btn_parse"):
            p = recommend.resume_parse(resume_text)
            if p:
                st.session_state["parsed"] = p
                # 清除 L0/L2/L3/段数 widget 状态，让它们按解析结果重新创建（避免残留示例数据）
                for _k in list(st.session_state.keys()):
                    if _k.startswith(("l0_", "l2_", "l3_")) or _k in ("l1_iw", "l1_proj"):
                        st.session_state.pop(_k, None)
                # 只显示标量字段，技能/经历列表单独格式化
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
        if uploaded is not None:
            try:
                import pdfplumber
                with pdfplumber.open(uploaded) as pdf:
                    pdf_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                p = recommend.resume_parse(pdf_text)
                if p:
                    st.session_state["parsed"] = p
                    for _k in list(st.session_state.keys()):
                        if _k.startswith(("l0_", "l2_", "l3_")) or _k in ("l1_iw", "l1_proj"):
                            st.session_state.pop(_k, None)
                    # 只显示标量字段，技能/经历列表单独格式化
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
    # 分列容器会先于穿插的标题渲染，因此按分组各建一组 columns，标题才能落在正确位置
    _edu_start = schema.L0_FIELDS.index("学历阶段")
    st.markdown("**👤 基本信息**")
    c = st.columns(2)
    for i, f in enumerate(schema.L0_FIELDS[:_edu_start]):
        l0[f] = c[i % 2].text_input(f, value=parsed.get(f, SAMPLE["l0"].get(f, "")), key="l0_" + f)
    st.markdown("**🎓 教育信息**")
    c = st.columns(2)
    for i, f in enumerate(schema.L0_FIELDS[_edu_start:]):
        l0[f] = c[i % 2].text_input(f, value=parsed.get(f, SAMPLE["l0"].get(f, "")), key="l0_" + f)
    parsed_exps = parsed.get("经历", []) if isinstance(parsed.get("经历"), list) else []
    l1 = {}
    iw_default = sum(1 for x in parsed_exps if x.get("类型") == "实习/工作") if parsed_exps else 1
    proj_default = sum(1 for x in parsed_exps if x.get("类型") == "项目") if parsed_exps else 1
    l1["实习/工作"] = st.number_input("实习/工作段数", 0, 5, iw_default, key="l1_iw")
    l1["项目"] = st.number_input("项目段数", 0, 5, proj_default, key="l1_proj")
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

    # 经历编辑：按段数动态生成卡片（折叠展示，界面更清爽）
    l2 = []
    _sample = {"实习/工作": [x for x in SAMPLE["l2"] if x["类型"] == "实习/工作"],
               "项目": [x for x in SAMPLE["l2"] if x["类型"] == "项目"]}
    _has_parsed = bool(parsed)  # 是否粘贴/上传过简历
    with st.expander("✏️ 编辑经历（实习/项目）", expanded=bool(parsed_exps)):
        for typ in ("实习/工作", "项目"):
            n = int(l1.get(typ, 0) or 0)
            parsed_typ = [x for x in parsed_exps if x.get("类型") == typ]
            for idx in range(n):
                # 默认值优先级：解析经历 > 空(粘贴过但无经历，避免示例误导) > 示例(未粘贴时演示)
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

if st.button("✅ 确认信息，进入下一步", type="primary"):
    ok, errors = verification.verify(user_data)
    if not ok:
        st.error("❌ 信息核检未通过，请修改后再确认：")
        for e in errors:
            st.warning("· " + e)
    else:
        st.session_state["info_confirmed"] = True
        st.success("✅ 信息已确认")
        st.info("👉 下一步：在第 ② 步勾选平台并扫码登录")

# ================= 步骤② 平台与登录 =================
st.markdown("---")
theme.section("②", "平台与登录", "勾选要用的平台并扫码登录；登录一次后状态自动保存，下次不用再扫",
              status=_states[1])

keys = list(platforms.PLATFORMS.keys())
cols = st.columns(len(keys))
selected = []
for i, k in enumerate(keys):
    p = platforms.get(k)
    with cols[i]:
        if st.checkbox(p["name"], key="sel_" + k, value=(k == "boss")):
            selected.append(k)
        st.markdown(theme.pill("ok" if session.has_session(k) else "off",
                               "已登录" if session.has_session(k) else "未登录"),
                    unsafe_allow_html=True)

if selected:
    for k in selected:
        p = platforms.get(k)
        logged = session.is_active(k)
        st.markdown(("🟢 " if logged else "⚪ ") + p["name"] + ("（已登录）" if logged else "（未登录）"))
    c1, c2 = st.columns(2)
    if c1.button("🌐 打开登录页", key="btn_real_open"):
        for k in selected:
            ok, msg = session.dpage_open(k)
            st.info(f"{platforms.get(k)['name']}：{msg}")
        st.caption("👉 在弹出的浏览器里扫码登录（如出现滑块请手动拖动，登录后回来点右侧）")
    if c2.button("✅ 我已完成登录", key="btn_real_finish"):
        for k in selected:
            ok, msg = session.dpage_finish(k)
            if ok:
                st.success(f"{platforms.get(k)['name']}：{msg}")
            else:
                st.warning(f"{platforms.get(k)['name']}：{msg}")

logged_in = [k for k in selected if session.has_session(k)]
if logged_in:
    st.success("🟢 已登录平台：" + "、".join(platforms.get(k)["name"] for k in logged_in))

# ================= 步骤③ 检索岗位 =================
st.markdown("---")
theme.section("③", "检索岗位", "输入关键词，在已登录平台检索", status=_states[2])
kw = st.text_input("检索关键词", value="Python 后端", key="kw")
pages = st.number_input("检索页数（每页约15岗）", 1, 3, 2, key="pages",
                        help="单次最多3页，防平台限流封号")
# 前置门控：信息未确认 / 平台未登录时禁用按钮并给出引导，而不是点了才警告
_info_ok = bool(st.session_state.get("info_confirmed"))
_login_ok = any(session.is_active(k) for k in selected)
if not _info_ok:
    st.caption("🔒 先在第 ① 步点「✅ 确认信息，进入下一步」")
elif not _login_ok:
    st.caption("🔒 先在第 ② 步勾选平台并完成扫码登录")
if st.button("🔍 开始检索", type="primary", disabled=not (_info_ok and _login_ok)):
    # 取意向城市第一个，映射为平台城市码
    city = (user_data["l3"].get("意向城市", "北京") or "北京").split(",")[0].strip()
    st.caption("⏳ 首次检索需启动浏览器并真实搜索，约 30~60 秒，请稍候…")
    with st.spinner("正在真实检索各平台岗位..."):
        jobs, logs = loop.search_logged_in_platforms(logged_in, kw, city=city, pages=int(pages))
    st.session_state["jobs"] = jobs
    for k, msg in logs:
        st.caption(f"{platforms.get(k)['name']}：{msg}")
    st.success(f"✅ 共检索到 {len(jobs)} 个岗位")
    st.info("👉 下一步：点击第 ④ 步的「🚀 准备投递材料」")
if st.session_state.get("jobs") is not None:
    _jobs_df = pd.DataFrame(st.session_state["jobs"])
    _cols = [c for c in ["岗位名称", "单位名称", "城市", "薪资", "学历", "经验", "行业"] if c in _jobs_df.columns]
    show_table(_jobs_df[_cols] if _cols else _jobs_df, hide_index=True)
else:
    theme.empty_state("🔍", "还没有检索结果",
                      "填好关键词后点「开始检索」，岗位列表会显示在这里")

# ================= 步骤④ 准备投递材料 =================
st.markdown("---")
theme.section("④", "准备投递材料",
              "系统自动：画像 → 匹配 → 建任务 → 生成针对性简历+招呼语（不自动发送，你逐条确认）",
              status=_states[3])
_has_jobs = bool(st.session_state.get("jobs"))
_material_ready = bool(st.session_state.get("result") and st.session_state["result"].get("ok"))
if not _has_jobs:
    st.caption("🔒 先在第 ③ 步完成检索")
if _material_ready:
    st.info("✅ 已生成过投递材料，请在第 ⑤ 步查看；如需重新生成，先点侧边栏「🔄 重新开始」")
if st.button("🚀 准备投递材料", type="primary", disabled=(not _has_jobs) or _material_ready):
    with st.spinner("正在画像、匹配、生成简历与招呼语..."):
        result = loop.run_closed_loop(user_data, jobs=st.session_state.get("jobs"))
    if not result["ok"]:
        st.error("❌ 信息核检未通过，请回到第 ① 步检查信息：")
        for e in result["errors"]:
            st.warning("· " + e)
    else:
        st.session_state["result"] = result
        st.success(f"✅ 已为 {result['task_count']} 个岗位准备好针对性简历和招呼语")
        st.info("👉 下一步：在第 ⑤ 步逐条确认投递（不会自动群发，不会骚扰 HR）")

# ================= 步骤⑤ 逐条投递 + 反馈 =================
st.markdown("---")
theme.section("⑤", "逐条投递与反馈", status=_states[4])
r = st.session_state.get("result")
if r and r.get("ok"):
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
        st.session_state["rematch"] = pipeline.re_match(r["user_id"], user_data)
        st.session_state["rematch_old"] = {j["岗位名称"]: j.get("score") for j in r["target_jobs"]}
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
                _old = round(float(_old_map.get(_name, 0)), 4)
                _new = round(float(x["score"]), 4)
                _delta = round(float(x["delta"]), 4)
                st.caption(f"{_name}：匹配分 {_old} → {_new}（δ={_delta}）")
            # 匹配分进化柱状图（反馈前 vs 反馈后，式三 δ 生效可视化）
            _fig = viz.evolution_bar(_rm, _old_map)
            if _fig is not None:
                theme.chart(_fig)
                st.caption("式三间隔特征 δ 生效：更靠近「进面试」岗位中心者分数升、更靠近「未进面试」者分数降")
    # 建 task_id -> 招呼语 映射
    greet_map = {d["task_id"]: d.get("招呼语", "") for d in r.get("delivery_report", [])}
    # 批量查询任务状态（避免每个岗位单独查库）
    _conn = db.get_conn()
    _task_states = {t["task_id"]: (t["status"], t["result"])
                    for t in _conn.execute(
                        "SELECT task_id, status, result FROM delivery_tasks WHERE user_id=?",
                        (r["user_id"],)).fetchall()}
    _conn.close()
    # 批量投递（一口气投多个，Boss 直聘「立即沟通」通道）
    _pending_tids = [tid for tid, (st_, _res) in _task_states.items() if st_ != "已投递"]
    if _pending_tids:
        st.markdown("**🚀 批量投递（Boss 直聘）**")
        st.caption("按匹配分顺序一键投递 %d 个岗位；受每日上限 %d / 单次批次 %d / 间隔 %d 秒保护，触发风控会自动停止。"
                   % (len(_pending_tids), config.DAILY_SEND_LIMIT, config.BATCH_SEND_LIMIT, config.DELIVER_INTERVAL))
        if st.button("🚀 批量投递（%d 个）" % len(_pending_tids), key="batch_deliver"):
            with st.spinner("批量投递中（每条间隔 %d 秒，防封号）..." % config.DELIVER_INTERVAL):
                _batch = delivery.deliver_batch()
            st.success("✅ 批量投递完成：成功 %d / 失败 %d" % (_batch["成功数"], _batch["失败数"]))
            if _batch["停止原因"]:
                st.warning("⚠️ " + _batch["停止原因"])
            for _tid, _ok, _msg in _batch["明细"]:
                if not _ok:
                    st.caption(f"· 任务{_tid}：{_msg}")
            st.rerun()
    # ---- 数学分析可视化（图表构造全部在 viz.py，这里只做布局） ----
    with st.expander("📊 数学分析可视化（等级分布·匹配分·画像适配）", expanded=True):
        _targets = r["target_jobs"]
        # KPI 概览卡
        _delivered_n = sum(1 for _s, _r2 in _task_states.values() if _s == "已投递")
        _avg_score = round(sum(float(j["score"]) for j in _targets) / len(_targets), 3) if _targets else 0
        _a_count = sum(1 for j in _targets if j["等级"] == "A")
        _k1, _k2, _k3, _k4 = st.columns(4)
        _k1.metric("目标岗位", len(_targets))
        _k2.metric("平均匹配分", _avg_score)
        _k3.metric("A 级强匹配", _a_count)
        _k4.metric("已投递", _delivered_n)
        _v1, _v2 = st.columns(2)
        with _v1:
            _fig = viz.grade_donut(_targets)
            theme.chart(_fig) if _fig is not None else st.caption("暂无岗位")
        with _v2:
            _fig = viz.score_bar(_targets)
            if _fig is not None:
                theme.chart(_fig)
        # 画像六维适配（第一名岗位：雷达图 + 柱状图）
        _top = _targets[0] if _targets else None
        _radar = viz.six_dim_radar(_top) if _top else None
        _bars = viz.six_dim_bars(_top) if _top else None
        if _radar is not None and _bars is not None:
            _a1, _a2 = st.columns([1, 1.3])
            with _a1:
                theme.chart(_radar)
            with _a2:
                theme.chart(_bars)
            st.caption("维度权重：技能40 + 方向25 + 学历15 + 薪资10 + 行业5 + 城市5（合计100）；负分表示不满足项")
        # 所有岗位六维适配对比（堆叠柱状图）
        _fig = viz.stacked_dims(_targets)
        if _fig is not None:
            theme.chart(_fig)
        # 技能覆盖分析（用户技能 vs 岗位要求技能）
        _fig, _skills = viz.skill_coverage(_targets, user_data.get("l2", []))
        if _fig is not None:
            theme.chart(_fig)
            st.caption("用户技能 %s" % ("、".join(_skills) or "无"))
        # 投递漏斗（检索→匹配→投递→进面试 转化）
        _retrieved = len(st.session_state.get("jobs", []))
        _delivered = sum(1 for _s, _r2 in _task_states.values() if _s == "已投递")
        _interviewed = sum(1 for _s, _r2 in _task_states.values() if _r2 == "进面试")
        _fig = viz.delivery_funnel(_retrieved, len(_targets), _delivered, _interviewed)
        if _fig is not None:
            theme.chart(_fig)
            st.caption("转化率：匹配 %d%% → 投递 %d%% → 进面试 %d%%（相对上一环节）"
                       % viz.funnel_rates(_retrieved, len(_targets), _delivered, _interviewed))
        # 岗位语义空间（PCA 降维散点图）：你的画像离哪些岗位最近
        _fig = viz.pca_scatter(r["user_id"])
        if _fig is not None:
            theme.chart(_fig)
    for job in r["target_jobs"]:
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3.4, 1, 1, 1])
            # 卡片头：等级徽章 + 岗位/单位 + 薪资等级分 + 匹配分进度条（theme 构件）
            c1.markdown(theme.job_card_header(job), unsafe_allow_html=True)
            # 推荐理由 + 分数明细 + 招呼语 + 链接折叠展示，界面更清爽
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
                    # 交互式勾选（专利步骤五「展示供用户修改勾选」）
                    st.caption("**✏️ 修改写入经历（勾选后重新生成）**：")
                    written_names = set(job.get("写入经历", []))
                    selected = []
                    for n, g in alloc:
                        if st.checkbox("%s（γ=%s）" % (n, g), value=(n in written_names),
                                       key=f"sel_{job['task_id']}_{n}"):
                            selected.append(n)
                    if st.button("🔄 按勾选重新生成简历", key=f"regen_{job['task_id']}"):
                        import profile as profile_mod
                        import generation
                        prof = profile_mod.build_profile(r["user_id"])
                        included_idx = [i for i, (n, g) in enumerate(alloc) if n in selected]
                        generation.regenerate_one(r["user_id"], prof, job["task_id"], included_idx)
                        # 同步 r 里的简历内容与写入经历，让界面立即反映勾选结果
                        conn = db.get_conn()
                        fm = conn.execute("SELECT fields FROM job_field_map WHERE task_id=?",
                                          (job["task_id"],)).fetchone()
                        conn.close()
                        if fm:
                            job["简历内容"] = json.loads(fm["fields"])
                        job["写入经历"] = [n for i, (n, g) in enumerate(alloc) if i in included_idx]
                        st.success("已按勾选重新生成简历")
                        st.rerun()
                link = job.get("岗位链接", "")
                if link:
                    st.markdown(f"[打开岗位详情]({link})")
            # 用批量查询的任务状态，让按钮反映真实状态（投递后/反馈后禁用）
            _status, _result = _task_states.get(job["task_id"], ("待生成", None))
            if c2.button("📤 已投递" if _status == "已投递" else "📤 投递", key=f"del_{job['task_id']}",
                         disabled=(_status == "已投递")):
                ok, msg = delivery.deliver_one(job["task_id"])
                if ok:
                    st.success("✅ 已记录投递（招呼语见上方折叠区）")
                else:
                    st.warning(msg)
                st.rerun()
            if c3.button("✅ 进面试", key=f"fb1_{job['task_id']}", disabled=(_result == "进面试")):
                ok, msg = feedback.mark_result(job["task_id"], 1)
                st.success("已标记进面试，画像权重已更新") if ok else st.warning(msg)
                st.rerun()
            if c4.button("❌ 未进面试", key="fb0_%s" % job["task_id"], disabled=(_result == "未进面试")):
                ok, msg = feedback.mark_result(job["task_id"], 0)
                st.success("已标记未进面试，画像权重已更新") if ok else st.warning(msg)
                st.rerun()
else:
    theme.empty_state("📮", "还没有可投递的岗位",
                      "完成第 ④ 步「准备投递材料」后，匹配岗位会列在这里，供你逐条投递和标注反馈")

# ================= 步骤⑥ 投递记录（集中回写跟踪） =================
st.markdown("---")
theme.section("⑥", "投递记录与画像统计", status=_states[5])
_r = st.session_state.get("result")
if _r and _r.get("ok"):
    conn = db.get_conn()
    tasks = conn.execute(
        "SELECT * FROM delivery_tasks WHERE user_id=? ORDER BY task_id", (_r["user_id"],)
    ).fetchall()
    conn.close()
    if tasks:
        rows = [{"岗位": t["job_name"], "单位": t["unit_name"],
                 "投递状态": t["status"], "回应/结果": t["result"] or "—"} for t in tasks]
        show_table(pd.DataFrame(rows), hide_index=True)
        st.download_button("📥 导出投递记录 CSV",
                           data=pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig"),
                           file_name="投递记录.csv", mime="text/csv")
        stats = feedback.get_quality(_r["user_id"])
        _s1, _s2, _s3, _s4, _s5 = st.columns(5)
        _s1.metric("累计投递", stats["累计投递"])
        _s2.metric("进面试", stats["进面试"])
        _s3.metric("进面试率", "%d%%" % stats["进面试率%"], help="进面试 ÷ 已标注结果（真实转化质量）")
        _s4.metric("反馈率", "%d%%" % stats["反馈率%"], help="已标注 ÷ 已投递（标注配合度）")
        _s5.metric("画像快照", stats["快照数"], help="每次反馈后画像自动优化")
        if stats["已投递平均匹配分"]:
            st.caption("📐 已投递岗位的平均匹配分（式三 p）：%s" % stats["已投递平均匹配分"])
        # 画像演进可视化（画像池快照：经历权重随反馈变化）
        ev = feedback.get_profile_evolution(_r["user_id"])
        if len(ev) >= 2:
            with st.expander("📈 画像演进（经历权重随反馈变化）", expanded=True):
                import json as _json
                exp_names = [e.get("名称", "经历%d" % i) for i, e in enumerate(user_data.get("l2", []))]
                w_rows = []
                for i, e in enumerate(ev):
                    w = _json.loads(e["weights"])
                    row = {"快照": i + 1}
                    for j, name in enumerate(exp_names):
                        row[name] = round(float(w[j]), 4) if j < len(w) else 0
                    row["正负中心"] = "已形成" if (e["pos_center"] and e["neg_center"]) else "未形成"
                    w_rows.append(row)
                show_table(pd.DataFrame(w_rows), hide_index=True)
                st.caption("权重增大 = 该经历更受认可（进面试）；权重减小 = 相对不受认可。正负中心 = 岗位正/负样本均值（式三间隔特征用）")
        # 数学统计可视化：投递结果饼图 + 经历权重饼图
        import json as _json
        _res = [t["result"] for t in tasks if t["result"]]
        _has_ev = bool(ev) and bool(_json.loads(ev[-1]["weights"])) if ev else False
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
                        _lastw = _json.loads(ev[-1]["weights"])
                        _expn = [e.get("名称", "经历%d" % i) for i, e in enumerate(user_data.get("l2", []))]
                        _fig = viz.weight_pie(_lastw, _expn)
                        if _fig is not None:
                            theme.chart(_fig)
                    else:
                        st.caption("暂无画像快照")
else:
    theme.empty_state("🗂️", "还没有投递记录",
                      "完成第 ④ 步「准备投递材料」后，所有投递任务的状态与结果会集中展示在这里")
