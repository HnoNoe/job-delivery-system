"""AI 辅助简历解析 —— 规则解析 + 生成式 AI 补全的混合抽取。

设计沿用专利约束：短任务切分 + 字段白名单 + 核对回写。
- 规则解析（recommend.resume_parse）：确定性、离线可用，对规整排版准确率高；
- DeepSeek（OpenAI 兼容接口）：只负责「从非结构化文本抽取白名单字段」，
  其输出经 schema 白名单过滤、类型核对、格式归一后才进入自动填写链路；
- 合并策略：标量字段以 AI 抽取为准、规则结果补空；技能取并集；经历 AI 优先。

未配置密钥或调用失败时自动回退纯规则解析，功能不受影响。
"""
import json
import re
import urllib.request

import config
import schema

_L0 = set(schema.L0_FIELDS)
_L2 = set(schema.L2_FIELDS)
_TYPES = set(schema.L1_TYPES)


def _post_chat(prompt, system, timeout=45):
    """调用 DeepSeek Chat（OpenAI 兼容），返回消息文本；失败抛异常。"""
    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("未配置 DeepSeek API Key")
    body = json.dumps({
        "model": config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + config.DEEPSEEK_API_KEY},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read().decode("utf-8"))
    return resp["choices"][0]["message"]["content"]


_SYSTEM = (
    "你是简历信息抽取器。只能从给定简历原文中提取信息，不得编造、不得推测；"
    "原文没有的字段一律省略或填空字符串。严格只输出 JSON 对象，不要输出任何其他文字。"
)


def _build_prompt(text):
    fields_desc = "、".join(schema.L0_FIELDS)
    types_desc = "、".join(schema.L1_TYPES)
    l2_desc = "、".join(["名称", "角色", "时间起", "时间止", "事项", "结果", "技术工具"])
    return (
        "从以下简历文本中提取信息，输出一个 JSON 对象，字段要求：\n"
        "1) 基本信息字段（均为字符串，没有则省略）：%s\n"
        "   其中 出生日期 形如 2002-03-15；入学年月/毕业年月 形如 2021-09；"
        "政治面貌 只能是 中共党员/共青团员/群众；学历阶段 取值 博士/硕士/本科/大专/专科。\n"
        "2) 意向岗位：字符串，取「求职意向/期望职位」内容。\n"
        "3) 技能：字符串数组，每项一个技能关键词（如 Python、MySQL）。\n"
        "4) 经历：对象数组，每段经历的 类型 只能是：%s；"
        "可用键：类型、%s（时间起/时间止 形如 2023-06，至今写 至今）。\n"
        "只提取有明确依据的内容，宁缺勿滥。\n\n"
        "简历文本：\n%s" % (fields_desc, types_desc, l2_desc, text[:12000])
    )


def _norm_date(s):
    """归一化时间为 YYYY-MM / YYYY-MM-DD；失败返回空。"""
    if not s:
        return ""
    s = str(s).strip().replace("年", "-").replace("月", "").replace("日", "").replace("/", "-").replace(".", "-")
    m = re.match(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?", s)
    if not m:
        return ""
    out = "%s-%s" % (m.group(1), m.group(2).zfill(2))
    if m.group(3):
        out += "-%s" % m.group(3).zfill(2)
    return out


def _cap(s, n=200):
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s[:n]


_TYPE_ALIAS = {
    "实习": "实习/工作", "工作": "实习/工作", "实习经历": "实习/工作", "工作经历": "实习/工作",
    "全职": "实习/工作", "兼职": "实习/工作",
    "项目经历": "项目", "科研项目": "项目",
    "比赛": "竞赛", "竞赛经历": "竞赛", "获奖": "竞赛",
    "论文发表": "论文", "学术论文": "论文",
    "社团": "学生工作", "学生组织": "学生工作", "班干部": "学生工作", "学生会": "学生工作",
    "奖项": "证书", "荣誉": "证书", "资格证书": "证书", "奖学金": "证书",
    "作品集": "作品链接", "个人主页": "作品链接", "GitHub": "作品链接", "github": "作品链接",
}


def _norm_type(s):
    s = _cap(s, 20)
    if s in _TYPES:
        return s
    return _TYPE_ALIAS.get(s, "")


def _clean_experience(items):
    """AI 经历输出核对：类型白名单/别名归一 + L2 字段白名单 + 时间格式核对。"""
    out = []
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        typ = _norm_type(it.get("类型", ""))
        if typ not in _TYPES:
            continue  # 类型不可核对，整段丢弃（防止臆造经历进入链路）
        exp = {"类型": typ, "挂靠": "独立", "证据": "无"}
        for k in ("名称", "角色", "事项", "结果"):
            v = _cap(it.get(k, ""), 200)
            if v:
                exp[k] = v
        tools = it.get("技术工具")
        if isinstance(tools, list):
            tools = "、".join(_cap(x, 30) for x in tools if _cap(x, 30))
        v = _cap(tools or "", 200)
        if v:
            exp["技术工具"] = v
        for k in ("时间起", "时间止"):
            v = _norm_date(it.get(k, ""))
            if v:
                exp[k] = v
        if len(exp) > 3:  # 至少除类型/挂靠/证据外还有实质内容
            out.append(exp)
    return out[:20]


def parse_with_ai(text):
    """DeepSeek 抽取 → 白名单核对后的字段字典；任何失败返回 {}。"""
    if not text or not config.DEEPSEEK_API_KEY:
        return {}
    try:
        raw = _post_chat(_build_prompt(text), _SYSTEM)
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        return {}
    out = {}
    for k in schema.L0_FIELDS:
        v = data.get(k)
        if isinstance(v, (str, int, float)):
            v = _cap(v, 50)
            if v:
                out[k] = v
    v = data.get("意向岗位")
    if isinstance(v, (str, int, float)) and _cap(v, 30):
        out["意向岗位"] = _cap(v, 30)
    skills = data.get("技能")
    if isinstance(skills, list):
        out["技能"] = [ _cap(s, 20) for s in skills if _cap(s, 20) ][:30]
    exps = _clean_experience(data.get("经历"))
    if exps:
        out["经历"] = exps
    return out


def smart_parse(text):
    """规则 + AI 混合解析：AI 抽取为准、规则补空，技能取并集，经历 AI 优先。

    返回与 recommend.resume_parse 同构的字典，供向导自动填写链路直接使用。
    """
    import recommend
    rule = recommend.resume_parse(text) or {}
    try:
        ai = parse_with_ai(text)
    except Exception:
        ai = {}
    merged = dict(rule)
    for k, v in ai.items():
        if k in ("技能", "经历"):
            continue
        if v:  # AI 值非空则覆盖
            merged[k] = v
    if ai.get("技能"):
        merged["技能"] = sorted(set(rule.get("技能", [])) | set(ai["技能"]))
    if ai.get("经历"):
        merged["经历"] = ai["经历"]
    return merged
