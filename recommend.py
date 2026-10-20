"""多维度匹配分析与推荐理由（专利步骤二第(5)点：挖掘字段间语义关联，指导信息匹配）。

在式二（余弦）+ 式三（逻辑斯谛）核心打分之外，提供可解释的匹配维度分析，
让每个推荐岗位附带「为什么推荐」，而非只有一个分数。
"""
import re

# 常见技术关键词（用于从岗位名称里提取技能词，补充 skills 字段）
TECH_KEYWORDS = {
    "python", "java", "c++", "cpp", "c#", "csharp", "go", "golang", "javascript", "js",
    "typescript", "php", "ruby", "rust", "scala", "kotlin", "swift", "shell",
    "前端", "后端", "全栈", "大数据", "算法", "机器学习", "深度学习", "nlp", "cv",
    "推荐系统", "数据", "爬虫", "量化", "嵌入式", "测试", "运维", "devops", "sre",
    "android", "ios", "小程序", "区块链", "云原生", "微服务", "高并发", "分布式",
    "mysql", "redis", "mongodb", "elasticsearch", "es", "docker", "kubernetes", "k8s",
    "spring", "flask", "django", "react", "vue", "node", "pytorch", "tensorflow",
    "linux", "git", "ai", "llm", "大模型", "aigc", "gpt",
}

# 学历等级（用于学历匹配：用户等级 >= 岗位要求等级）
_DEGREE_RANK = {"不限": 0, "专科": 1, "本科": 2, "硕士": 3, "博士": 4}


def _norm(s):
    return (s or "").strip().lower()


def extract_user_skills(l2_exps):
    """从用户 L2 经历的技术工具字段提取技能标签集合。"""
    skills = set()
    for exp in (l2_exps or []):
        tech = exp.get("技术工具", "") or ""
        for t in re.split(r"[,，;；/、\s]+", tech):
            t = t.strip().lower()
            if t and t != "无":
                skills.add(t)
        # 也把经历名称里的技术词纳入（如「Python后端实习生」）
        for kw in TECH_KEYWORDS:
            if kw in (exp.get("名称", "") or "").lower():
                skills.add(kw)
    return skills


def extract_job_skills(job):
    """从岗位的技能字段 + 岗位名称提取技能标签集合。"""
    skills = set()
    raw = job.get("技能", "")
    if isinstance(raw, list):
        for s in raw:
            s = str(s).strip().lower()
            if s:
                skills.add(s)
    elif raw:
        for s in re.split(r"[,，;；/、\s]+", str(raw)):
            s = s.strip().lower()
            if s:
                skills.add(s)
    # 从岗位名称提取技术关键词
    name = _norm(job.get("岗位名称", ""))
    for kw in TECH_KEYWORDS:
        if kw in name:
            skills.add(kw)
    return skills


def _degree_match(user_degree, job_degree):
    """学历匹配：用户学历等级 >= 岗位要求等级，或岗位不限。"""
    jd = _norm(job_degree)
    ud = _norm(user_degree)
    if not jd or jd == "学历不限" or "不限" in jd:
        return True
    jrank = None
    for k, v in _DEGREE_RANK.items():
        if k in jd:
            jrank = v
            break
    if jrank is None:
        return True  # 岗位学历要求无法识别，不据此否定
    urank = None
    for k, v in _DEGREE_RANK.items():
        if k in ud:
            urank = v
            break
    if urank is None:
        return True
    return urank >= jrank


def _salary_match(expect, job_salary):
    """薪资匹配：期望薪资下限是否落在岗位薪资范围内（粗匹配，无法解析则不据此否定）。"""
    if not expect or not job_salary:
        return None  # 缺信息，无法判断
    # 期望薪资取数值（如 15k/月 -> 15，单位 k）
    m = re.search(r"(\d+(?:\.\d+)?)\s*[kK千]", str(expect))
    if not m:
        return None
    exp_k = float(m.group(1))
    # 岗位薪资取范围（15-30K -> [15,30]；50-1000元/天 -> 按天，难比较，跳过）
    m2 = re.search(r"(\d+)\s*-\s*(\d+)\s*[kK千]", str(job_salary))
    if m2:
        lo, hi = float(m2.group(1)), float(m2.group(2))
        return exp_k <= hi  # 期望下限不超过岗位上限即可
    return None


# 岗位方向关键词（从意向岗位里提取，用于方向匹配）
DIRECTION_KEYWORDS = ["后端", "前端", "算法", "数据", "测试", "运维", "产品", "嵌入式",
                      "量化", "机器学习", "深度学习", "全栈", "安卓", "android", "ios", "golang", "go"]


def _direction_keywords(intent_jobs):
    """从意向岗位里提取方向关键词（如「后端开发」→「后端」）。"""
    dirs = set()
    for intent in intent_jobs:
        low = intent.lower()
        for kw in DIRECTION_KEYWORDS:
            if kw in low:
                dirs.add(kw)
    return dirs


def analyze_match(user_data, job):
    """多维度匹配分析。返回 {维度名: 匹配详情}，用于生成推荐理由。"""
    l0 = user_data.get("l0", {})
    l2 = user_data.get("l2", [])
    l3 = user_data.get("l3", {})

    common = sorted(extract_user_skills(l2) & extract_job_skills(job))

    job_name = job.get("岗位名称", "") or ""
    intent_jobs = [x.strip() for x in re.split(r"[,，;；]", l3.get("意向岗位", "") or "") if x.strip()]
    dir_kws = _direction_keywords(intent_jobs)
    dir_hit = [kw for kw in dir_kws if kw in job_name.lower()]

    degree_ok = _degree_match(l0.get("学历阶段", ""), job.get("学历", ""))
    salary_ok = _salary_match(l3.get("期望薪资", ""), job.get("薪资", ""))

    return {
        "技能": common,
        "岗位方向": dir_hit,
        "学历": degree_ok,
        "薪资": salary_ok,
    }


def profile_summary(user_data):
    """画像摘要（专利步骤二第(5)点「约束提示词」的离线实现）。

    从用户信息提取关键特征，形成可供匹配与展示的画像全貌。
    """
    l0 = user_data.get("l0", {})
    l2 = user_data.get("l2", [])
    l3 = user_data.get("l3", {})
    skills = sorted(extract_user_skills(l2))
    return {
        "技能标签": skills,
        "意向岗位": [x.strip() for x in re.split(r"[,，;；]", l3.get("意向岗位", "") or "") if x.strip()],
        "意向行业": [x.strip() for x in re.split(r"[,，;；]", l3.get("意向行业", "") or "") if x.strip()],
        "意向城市": [x.strip() for x in re.split(r"[,，;；]", l3.get("意向城市", "") or "") if x.strip()],
        "学历": l0.get("学历阶段", ""),
        "学校": l0.get("学校", ""),
        "专业": l0.get("专业", ""),
        "经历数": len(l2 or []),
    }


def match_grade(user_data, job):
    """匹配等级 A/B/C（参考 auto-job-apply 评分体系，硬约束不过不能强行高）。

    A（强匹配）：技能+方向高度命中；B（有机会）：部分命中；C（不推荐）。
    返回 (等级, 百分制分数)。
    """
    a = analyze_match(user_data, job)
    l3 = user_data.get("l3", {})
    score = 0
    if a["技能"]:
        score += 40
    if a["岗位方向"]:
        score += 25
    if a["学历"] is True:
        score += 15
    elif a["学历"] is False:
        score -= 15
    if a["薪资"] is True:
        score += 10
    elif a["薪资"] is False:
        score -= 10
    ind = job.get("行业", "")
    if ind and ind in (l3.get("意向行业", "") or ""):
        score += 5
    city = job.get("城市", "")
    if city and city in (l3.get("意向城市", "") or ""):
        score += 5
    score = max(0, min(100, score))
    if score >= 60:
        return "A", score
    if score >= 40:
        return "B", score
    return "C", score


def personalized_greeting(user_data, job, fallback_template=None):
    """个性化招呼语：根据技能匹配/岗位方向匹配动态生成（比固定模板更针对）。

    - 技能匹配命中：强调匹配的技能
    - 岗位方向匹配：强调求职方向
    - 都不命中：回退到通用模板
    """
    a = analyze_match(user_data, job)
    l0 = user_data.get("l0", {})
    name = l0.get("姓名", "")
    school = l0.get("学校", "")
    major = l0.get("专业", "")
    job_name = job.get("岗位名称", "")

    if a["技能"]:
        skills = "、".join(a["技能"][:3])
        return ("您好，我是%s（%s%s），我有 %s 相关经验，看到贵司「%s」岗位与我的技能高度匹配，"
                "简历已发，希望能进一步沟通，期待您的回复。" % (name, school, major, skills, job_name))
    if a["岗位方向"]:
        d = "、".join(a["岗位方向"][:2])
        return ("您好，我是%s（%s%s），一直深耕 %s 方向，看到贵司「%s」岗位与我的求职方向一致，"
                "简历已发，期待您的回复。" % (name, school, major, d, job_name))
    if fallback_template:
        return fallback_template.format(姓名=name, 学校=school, 专业=major, 岗位=job_name)
    return "您好，我是%s（%s%s），看到贵司「%s」岗位与我的经历很匹配，简历已发，期待您的回复。" % (
        name, school, major, job_name)


def score_breakdown(user_data, job):
    """等级分构成明细（可解释性）：返回 [(维度, 得分, 说明)]。

    让用户看懂 A/B/C 等级分是怎么加出来的（技能40+方向25+学历15+薪资10+行业5+城市5）。
    """
    a = analyze_match(user_data, job)
    l3 = user_data.get("l3", {})
    parts = []
    if a["技能"]:
        parts.append(("技能匹配", 40, "、".join(a["技能"])))
    else:
        parts.append(("技能匹配", 0, "无匹配技能"))
    if a["岗位方向"]:
        parts.append(("岗位方向", 25, "、".join(a["岗位方向"])))
    else:
        parts.append(("岗位方向", 0, "未命中意向岗位"))
    if a["学历"] is True:
        parts.append(("学历", 15, "符合要求"))
    elif a["学历"] is False:
        parts.append(("学历", -15, "低于岗位要求"))
    else:
        parts.append(("学历", 0, "无法判断"))
    if a["薪资"] is True:
        parts.append(("薪资", 10, "符合期望"))
    elif a["薪资"] is False:
        parts.append(("薪资", -10, "低于期望"))
    else:
        parts.append(("薪资", 0, "无法判断"))
    ind = job.get("行业", "")
    parts.append(("行业", 5 if (ind and ind in (l3.get("意向行业", "") or "")) else 0, ind or "无"))
    city = job.get("城市", "")
    parts.append(("城市", 5 if (city and city in (l3.get("意向城市", "") or "")) else 0, city or "无"))
    return parts


def explain_match_score():
    """匹配分（式二 + 式三）的数学解释。"""
    return ("匹配分 = σ(w_s·余弦相似度 + w_δ·间隔特征)，经逻辑斯谛映射到(0,1)。"
            "余弦相似度 = 用户表示（各条经历向量的加权凸组合，式一）与岗位向量的语义接近程度；"
            "间隔特征 = 该岗位更靠近「进面试岗位中心 c_+」还是「未进面试岗位中心 c_-」（式三），"
            "两类历史样本都非空时才启用。")


def explain_weights(evolution):
    """经历权重的数学解释（式一 + 式五）。"""
    return ("经历权重 α_k = 第 k 条经历在用户表示中的强调程度（式一凸组合）。"
            "投递后按式五更新：α_k ← α_k·e^{η·z·I_k} 再归一化——"
            "进面试(z=1)且写入简历(I_k=1)的经历权重增大，未进面试(z=0)不变；权重恒非负且和为1。")


def _parse_experiences(text):
    """从简历文本保守提取经历段落（按时间范围识别）。返回 L2 字典列表。"""
    exps = []
    lines = [ln.strip() for ln in text.splitlines()]
    time_re = re.compile(
        r"(\d{4}(?:[.年/\-]\d{1,2})?)\s*[-~—–－～〜到至]\s*(至今|\d{4}(?:[.年/\-]\d{1,2})?)"
    )
    for i, line in enumerate(lines):
        m = time_re.search(line)
        if not m:
            continue
        # 跳过教育经历（上一行是「教育经历/教育背景」标题）
        if i > 0 and ("教育经历" in lines[i - 1] or "教育背景" in lines[i - 1]):
            continue
        start = m.group(1)
        end = m.group(2)
        # 经历名称：去掉时间范围后的剩余文本，或上一行（公司/岗位名）
        name = time_re.sub("", line).strip(" -—–|·：:").strip()
        name = re.sub(r"^(项目经历|竞赛经历|论文经历|专利经历|实习经历|工作经历|校园经历|学生工作经历)\s*[:：]\s*", "", name)
        name = re.sub(r"^(项目|竞赛|论文|专利|实习|工作|学生工作|作品|证书)\s*[:：]\s*", "", name)
        if not name and i > 0:
            name = re.sub(r"^(项目经历|实习经历|工作经历|校园经历|竞赛经历)\s*[:：]\s*",
                          "", lines[i - 1].strip())
        # 事项：紧邻的后续行（直到空行或下一个时间范围）
        desc = []
        for j in range(i + 1, min(i + 5, len(lines))):
            ln = lines[j].strip()
            if not ln or time_re.search(ln):
                break
            desc.append(ln)
        tech = sorted({kw for kw in TECH_KEYWORDS if kw in (" ".join([line] + desc)).lower()})
        # 结果：从事项里提取量化成果（提升/降低/增长/优化 + 数字，或 QPS/上线/响应 等指标）
        result = ""
        result_re = re.compile(
            r"(?:提升|降低|增长|减少|提高|优化|缩短)[^\d。，,]{0,6}\d+(?:%|％|倍)?|"
            r"(?:QPS|TPS|响应时间|转化率|点击率|留存|GMV|DAU|UV|PV)\s*[:：]?\s*\d+"
        )
        for d in desc:
            rm = result_re.search(d)
            if rm:
                result = rm.group(0)
                break
        if name or desc or tech:
            # 类型：项目/project → 项目；竞赛/比赛/大赛 → 竞赛；论文/paper → 论文；专利 → 专利；否则实习/工作
            _is_proj = "项目" in line or "project" in line.lower()
            _is_comp = any(k in line for k in ("竞赛", "比赛", "大赛"))
            _is_paper = "论文" in line or "paper" in line.lower()
            _is_patent = "专利" in line
            _is_campus = any(k in line for k in ("学生会", "社团", "学生工作", "班委", "团委", "校园"))
            if i > 0:
                _prev_l = lines[i - 1]
                _prev = _prev_l.lower()
                if not _is_proj:
                    _is_proj = "项目" in _prev_l or "project" in _prev
                if not _is_comp:
                    _is_comp = any(k in _prev_l for k in ("竞赛", "比赛", "大赛"))
                if not _is_paper:
                    _is_paper = "论文" in _prev_l or "paper" in _prev
                if not _is_patent:
                    _is_patent = "专利" in _prev_l
                if not _is_campus:
                    _is_campus = any(k in _prev_l for k in ("学生会", "社团", "学生工作", "班委", "团委", "校园"))
            if _is_proj:
                typ = "项目"
            elif _is_comp:
                typ = "竞赛"
            elif _is_paper:
                typ = "论文"
            elif _is_patent:
                typ = "专利"
            elif _is_campus:
                typ = "学生工作"
            else:
                typ = "实习/工作"
            # 角色：从名称里识别（实习生/负责人/组长/部长/主席/成员）
            role = "成员"
            for _rk in ("实习生", "负责人", "负责", "组长", "部长", "主席", "成员", "工程师"):
                if _rk in (name or ""):
                    role = _rk
                    break
            exps.append({
                "类型": typ, "名称": (name or "经历")[:40], "角色": role,
                "时间起": start, "时间止": end,
                "事项": (" ".join(desc))[:120], "结果": result,
                "技术工具": ", ".join(tech), "挂靠": "独立", "证据": "无",
            })
    return exps


def resume_parse(text):
    """从简历文本提取字段（离线规则解析），用于自动填充 L0/L2。

    提取：姓名（首行/开头）、手机、邮箱、学校、专业、技能标签、经历（含时间+技术工具）。
    """
    if not text:
        return {}
    t = text.strip()
    out = {}
    # 手机号
    m = re.search(r"1[3-9]\d{9}", t)
    if m:
        out["手机"] = m.group(0)
    # 邮箱
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", t)
    if m:
        out["邮箱"] = m.group(0)
    # 学校（优先"XX大学"，否则"XX学院"；避免把"计算机学院"等学院名误当学校）
    m = re.search(r"[\u4e00-\u9fff]{2,12}大学", t)
    if m:
        out["学校"] = m.group(0)
    else:
        m = re.search(r"[\u4e00-\u9fff]{2,12}学院", t)
        if m:
            out["学校"] = m.group(0)
    # 专业（"XX专业" 或 "专业：XX"）
    m = re.search(r"[\u4e00-\u9fff]{2,15}专业", t)
    if m:
        out["专业"] = m.group(0).replace("专业", "")
    else:
        m = re.search(r"专业\s*[:：]\s*([\u4e00-\u9fff]{2,15})", t)
        if m:
            out["专业"] = m.group(1)
    # 技能标签（技术关键词）
    skills = sorted({kw for kw in TECH_KEYWORDS if kw in t.lower()})
    out["技能"] = skills
    # 学历阶段
    for d in ("博士", "硕士", "本科", "大专", "专科", "中专", "高中"):
        if d in t:
            out["学历阶段"] = ("%s在读" % d) if ("在读" in t or "应届" in t) else d
            break
    # 性别
    m = re.search(r"性别\s*[:：]\s*(男|女)", t)
    if m:
        out["性别"] = m.group(1)
    # 现居（"现居：北京" 或 "居住地：北京"）
    m = re.search(r"(?:现居|居住地|现居住)\s*[:：]?\s*([\u4e00-\u9fff]{2,6})", t)
    if m:
        out["现居"] = m.group(1)
    # 籍贯
    m = re.search(r"籍贯\s*[:：]?\s*([\u4e00-\u9fff]{2,8})", t)
    if m:
        out["籍贯"] = m.group(1)
    # 政治面貌
    m = re.search(r"(?:政治面貌|面貌)\s*[:：]?\s*(中共党员|共青团员|群众|党员|团员)", t)
    if m:
        out["政治面貌"] = m.group(1)
    # 民族
    m = re.search(r"民族\s*[:：]\s*([\u4e00-\u9fff]{1,4})", t)
    if m:
        out["民族"] = m.group(1)
    # 出生日期（转成 YYYY-MM-DD）
    m = re.search(r"(?:出生|生日)\s*[:：]?\s*(\d{4})\s*[年./-]\s*(\d{1,2})\s*(?:[月./-]\s*(\d{1,2}))?\s*日?", t)
    if m:
        out["出生日期"] = "%s-%s-%s" % (m.group(1), m.group(2).zfill(2), (m.group(3) or "01").zfill(2))
    # GPA
    m = re.search(r"GPA\s*[:：]?\s*([\d.]+)", t, re.I)
    if m:
        out["GPA"] = m.group(1)
    # 专业排名（"前5%"、"5/120"、"第1名"）
    m = re.search(r"(?:专业排名|排名)\s*[:：]?\s*(前\s*\d+\s*%|\d+\s*/\s*\d+|第\s*\d+\s*名)", t)
    if m:
        out["专业排名"] = m.group(1)
    # 学院（"学院：XX"）
    m = re.search(r"学院\s*[:：]\s*([\u4e00-\u9fff]{2,10})", t)
    if m:
        out["学院"] = m.group(1)
    # 入学年月 / 毕业年月
    m = re.search(r"(\d{4})\s*[年./-]\s*(\d{1,2})?\s*[月]?\s*(?:入学|入校)", t)
    if m:
        out["入学年月"] = "%s-%s" % (m.group(1), (m.group(2) or "09").zfill(2))
    m = re.search(r"(\d{4})\s*[年./-]\s*(\d{1,2})?\s*[月]?\s*(?:毕业)", t)
    if m:
        out["毕业年月"] = "%s-%s" % (m.group(1), (m.group(2) or "06").zfill(2))
    # 意向岗位（L3 求职偏好，简历里常写「求职意向/意向岗位」）
    m = re.search(r"(?:求职意向|意向岗位|期望职位|应聘岗位)\s*[:：]\s*([^\s，,。；;]{2,20})", t)
    if m:
        out["意向岗位"] = m.group(1)
    # 姓名：优先「姓名：XXX」关键字，否则取第一个非空短行（若含"简历"则跳过）
    m = re.search(r"姓名\s*[:：]\s*([\u4e00-\u9fff·]{2,4})", t)
    if m:
        out["姓名"] = m.group(1)
    else:
        for line in t.splitlines():
            line = line.strip()
            if line and "简历" not in line and len(line) <= 6 and not re.search(r"[\d@：:]", line):
                out["姓名"] = line.split("|")[0].split("·")[0].strip()
                break
    # 经历（L2）：按时间范围提取（简历文本含"2023.06-2023.09"等段落时生效）
    exps = _parse_experiences(t)
    if exps:
        out["经历"] = exps
    return out


def recommend_reasons(user_data, job):
    """生成推荐理由列表（自然语言，可解释）。"""
    a = analyze_match(user_data, job)
    l3 = user_data.get("l3", {})
    reasons = []
    if a["技能"]:
        reasons.append("技能匹配：%s" % "、".join(a["技能"]))
    if a["岗位方向"]:
        reasons.append("岗位方向匹配：%s" % "、".join(a["岗位方向"]))
    if a["学历"] is True:
        reasons.append("学历符合要求")
    if a["学历"] is False:
        reasons.append("学历可能低于岗位要求")
    if a["薪资"] is True:
        reasons.append("薪资符合期望")
    if a["薪资"] is False:
        reasons.append("薪资低于期望")
    # 行业/城市是硬约束（已过滤通过），作为亮点展示
    ind = job.get("行业", "")
    if ind and ind in (l3.get("意向行业", "") or ""):
        reasons.append("行业匹配：%s" % ind)
    city = job.get("城市", "")
    if city and city in (l3.get("意向城市", "") or ""):
        reasons.append("城市匹配：%s" % city)
    return reasons
