"""人物画像（Persona）—— 把用户画像从向量翻译成一眼看懂的人话。

与 `user_profile.py` 的分工：
- `user_profile.build_profile(user_id)` 产出**数学对象**（经历向量、权重 α、用户向量 u），供匹配/生成使用；
- 本模块产出**展示对象**（身份、技能标签、求职方向、偏好、一句话画像、优势/短板），
  只读 `user_data` 与匹配结果，不写库、不改变任何打分。

刻意保持纯函数：不依赖数据库、不依赖 Streamlit，便于回归测试与复用。
"""
import re

import recommend

# 六维名称 -> 满分（与 viz.DIM_MAXS / recommend.score_breakdown 一致）
DIM_MAX = {"技能匹配": 40, "岗位方向": 25, "学历": 15, "薪资": 10, "行业": 5, "城市": 5}
# 能力维度（用于优势/短板）；学历/薪资/行业/城市属于“条件”，单独给出契合度
ABILITY_DIMS = ["技能匹配", "岗位方向"]
CONDITION_DIMS = ["学历", "薪资", "行业", "城市"]
DIM_ORDER = ABILITY_DIMS + CONDITION_DIMS


def _split(text):
    """把「后端开发,算法工程师」这类多值字段切成列表。"""
    return [x.strip() for x in re.split(r"[,，;；/、]", text or "") if x.strip()]


def _ordered_skills(l2):
    """技能标签按「技术工具里出现的先后」排序，名称命中的关键词排在后面。"""
    ordered, seen = [], set()
    for exp in l2 or []:
        for token in re.split(r"[,，;；/、\s]+", str(exp.get("技术工具", "") or "")):
            token = token.strip().lower()
            if token and token != "无" and token not in seen:
                seen.add(token)
                ordered.append(token)
    for skill in sorted(recommend.extract_user_skills(l2)):
        if skill not in seen:
            seen.add(skill)
            ordered.append(skill)
    return ordered


def _dim_ratios(targets):
    """所有目标岗位的六维平均达成率（0~1，负分按 0 计）。返回 {维度: 比例}。"""
    if not targets:
        return {}
    sums = {k: 0.0 for k in DIM_ORDER}
    for job in targets:
        for name, score, *_ in (job.get("分数明细") or []):
            if name in sums:
                sums[name] += max(0.0, float(score))
    n = float(len(targets))
    return {k: (sums[k] / n) / DIM_MAX[k] for k in DIM_ORDER}


def build_persona(user_data, targets=None, weights=None):
    """构造人物画像。返回可直接渲染的字典（全部为字符串/列表，不抛异常）。

    user_data: 表单结构 {l0, l1, l2, l3}
    targets:   匹配结果 list（用于算优势/短板；可为 None）
    weights:   经历权重 α（可为 None；用于展示画像是否已被反馈修正）
    """
    user_data = user_data or {}
    l0 = user_data.get("l0") or {}
    l2 = user_data.get("l2") or []
    l3 = user_data.get("l3") or {}

    name = (l0.get("姓名") or "未填写").strip()
    school = (l0.get("学校") or "").strip()
    major = (l0.get("专业") or "").strip()
    degree = (l0.get("学历阶段") or "").strip()

    skills = _ordered_skills(l2)
    directions = _split(l3.get("意向岗位", ""))

    city = (l3.get("意向城市") or "").strip()
    industry = (l3.get("意向行业") or "").strip()
    salary = (l3.get("期望薪资") or "").strip()
    onboard = (l3.get("到岗时间") or "").strip()

    ratios = _dim_ratios(targets or [])
    ranked = sorted(((k, ratios[k]) for k in ABILITY_DIMS if k in ratios),
                    key=lambda kv: kv[1], reverse=True)
    strengths = [k for k, v in ranked if v >= 0.6]
    gaps = [k for k, v in ranked if v < 0.4]
    cond_vals = [ratios[k] for k in CONDITION_DIMS if k in ratios]
    condition_fit = round(100 * sum(cond_vals) / len(cond_vals)) if cond_vals else None
    ability = {k: round(100 * ratios[k]) for k in ABILITY_DIMS if k in ratios}
    ability_text = "　｜　".join(
        "%s %d%%" % (k.replace("匹配", ""), v) for k, v in ability.items()) or "—"

    # 一句话画像：身份 + 方向 + 技能 + 规模
    edu = "·".join(x for x in (degree, (school + major).strip()) if x) or "学历/专业未填写"
    dir_text = "、".join(directions[:2]) or "方向未填写"
    skill_text = "、".join(skills[:3]) or "技能待补充"
    one_line = "%s｜主攻 %s｜技能：%s｜%d 段经历" % (edu, dir_text, skill_text, len(l2))

    # 画像规模：经历数 + 权重集中度（max α；均匀 = 1/K 表示还没被反馈修正过）
    scale = "%d 段经历" % len(l2)
    if weights is not None and len(weights) > 0:
        peak = max(float(w) for w in weights)
        uniform = peak <= (1.0 / len(weights)) + 1e-9
        scale += "·权重%s" % ("未修正" if uniform else "已修正（最大 %.2f）" % peak)

    prefs = "｜".join(x for x in [
        ("城市 " + city) if city else "",
        ("行业 " + industry) if industry else "",
        ("期望 " + salary) if salary else "",
        ("到岗 " + onboard) if onboard else "",
    ] if x) or "未填写"

    return {
        "姓名": name,
        "身份": edu,
        "技能标签": skills,
        "求职方向": directions,
        "求职偏好": prefs,
        "一句话": one_line,
        "优势": strengths,
        "短板": gaps,
        "能力匹配": ability,
        "能力匹配文案": ability_text,
        "条件契合": condition_fit,
        "画像规模": scale,
        "技能数": len(skills),
        "经历数": len(l2),
    }


def advantage_line(persona):
    """把优势/短板拼成一行说明（无数据时返回空串）。"""
    persona = persona or {}
    parts = []
    if persona.get("优势"):
        parts.append("优势维度：" + "、".join(persona["优势"]))
    if persona.get("短板"):
        parts.append("待补维度：" + "、".join(persona["短板"]))
    return "　｜　".join(parts)
