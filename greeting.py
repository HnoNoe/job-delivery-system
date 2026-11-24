"""投递招呼语：模板 + 技能/方向个性化（自包含，不依赖画像/匹配模块）。

从 recommend.personalized_greeting 裁剪：原实现依赖 analyze_match 打分体系（已删除），
这里保留对外行为——技能命中强调技能，方向一致强调方向，都不中走通用模板。
"""
import config


def personalized_greeting(user_data, job, fallback_template=None):
    """user_data: {"l0": {...}, "l2": [...], "l3": {...}}；job: 岗位字段 dict。"""
    l0 = user_data.get("l0") or {}
    l2 = user_data.get("l2") or []
    l3 = user_data.get("l3") or {}
    name = l0.get("姓名", "")
    school = l0.get("学校", "")
    major = l0.get("专业", "")
    job_name = job.get("岗位名称", "")

    # 用户技术工具全集（L2 各经历的技术工具）
    user_skills = set()
    for item in l2:
        tools = item.get("技术工具", "") or ""
        for t in str(tools).replace("，", "、").replace(",", "、").split("、"):
            t = t.strip()
            if t:
                user_skills.add(t.lower())

    job_skills = job.get("技能", "") or ""
    if isinstance(job_skills, list):
        job_skills = "、".join(str(x) for x in job_skills)
    hits = [s.strip() for s in str(job_skills).replace("，", "、").replace(",", "、").split("、")
            if s.strip() and s.strip().lower() in user_skills]

    if hits:
        skills = "、".join(hits[:3])
        return ("您好，我是%s（%s%s），我有 %s 相关经验，看到贵司「%s」岗位与我的技能高度匹配，"
                "简历已发，希望能进一步沟通，期待您的回复。" % (name, school, major, skills, job_name))
    direction = (l3.get("意向岗位", "") or "").replace("，", "、").split("、")
    direction = [d.strip() for d in direction if d.strip()]
    if direction and any(d and d in job_name for d in direction):
        d = "、".join(direction[:2])
        return ("您好，我是%s（%s%s），一直深耕 %s 方向，看到贵司「%s」岗位与我的求职方向一致，"
                "简历已发，期待您的回复。" % (name, school, major, d, job_name))
    tpl = fallback_template or config.GREETING_TEMPLATE
    return tpl.format(姓名=name, 学校=school, 专业=major, 岗位=job_name)
