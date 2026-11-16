"""统一字段数据库 —— 字段 schema 定义。

专利核心：字段名全局唯一、字段值可核对。所有模块以本文件定义的字段名为基准。
"""

# ---------- L0 身份骨架 ----------
L0_FIELDS = [
    "姓名", "性别", "出生日期", "手机", "邮箱", "政治面貌", "民族",
    "现居", "籍贯", "学历阶段", "学校", "学院", "专业",
    "入学年月", "毕业年月", "GPA", "专业排名",
]

L0_REQUIRED = [
    "姓名", "性别", "出生日期", "手机", "邮箱", "政治面貌", "民族",
    "现居", "籍贯", "学历阶段", "学校", "学院", "专业", "入学年月", "毕业年月",
]

# ---------- L1 经历盘点（类型 -> 条数） ----------
L1_TYPES = ["实习/工作", "项目", "竞赛", "论文", "专利", "学生工作", "证书", "作品链接"]

# ---------- L2 经历深挖（公共字段） ----------
L2_FIELDS = ["类型", "名称", "角色", "时间起", "时间止", "事项", "结果", "技术工具", "挂靠", "证据"]

# 简历生成时允许填写的字段（专利步骤五明示）
RESUME_ALLOWED_FIELDS = ["姓名", "学校", "专业", "手机", "邮箱"]
RESUME_ALLOWED_L2 = ["名称", "角色", "时间起", "时间止", "事项", "结果", "技术工具"]

# ---------- L3 求职偏好 ----------
L3_FIELDS = ["意向城市", "意向岗位", "意向行业", "到岗时间", "期望薪资", "投递策略", "能否出差", "禁忌公司"]
L3_REQUIRED = ["意向城市", "意向岗位", "意向行业", "到岗时间", "投递策略", "能否出差"]

# ---------- 岗位字段（短任务采集） ----------
JOB_FIELDS = ["岗位名称", "单位名称", "岗位链接", "投递入口类型", "投递入口地址",
              "岗位描述", "城市", "行业", "公司", "薪资", "学历", "经验", "技能", "已沟通"]

JOB_KEY_FIELDS = ["岗位名称", "单位名称"]  # 关键字段缺损即剔除（岗位描述/jobLabels 真实数据可能为空，不作硬要求）

# ---------- 投递任务字段 ----------
TASK_FIELDS = ["任务编号", "岗位名称", "单位名称", "岗位链接", "投递入口类型",
               "投递入口地址", "针对性简历文件路径", "任务状态"]
TASK_STATUS = ["待生成", "待检查", "待投递", "投递中", "待核实", "已投递", "已完成"]

# 已进入（或可能已进入）真实投递流程的状态：不允许再生成材料、也不允许被重置回「待投递」，
# 否则「已发出/可能已发出」的任务会被当成新任务二次投递。
TASK_LOCKED = ["投递中", "待核实", "已投递", "已完成"]

# ---------- 投递入口类型 ----------
ENTRY_TYPES = ["Web表单", "邮件", "API", "半自动"]

# ---------- 统一字段数据库·高强度校验（harsh validation） ----------
# 设计目标（专利「字段值可核对」）：入库即合法，不合法就拒绝并留痕，绝不留脏数据。
EDU_VOCAB = ["学历不限", "大专以下", "大专", "本科", "硕士", "博士"]
EDU_ALIASES = {"高中": "大专以下", "中专/中技": "大专以下", "初中及以下": "大专以下",
               "中专及以下": "大专以下"}

EXP_VOCAB = ["经验不限", "应届", "1年以内", "1-3年", "3-5年", "5-10年", "10年以上"]
EXP_ALIASES = {"在校/应届": "应届", "应届生": "应届", "应届/在校": "应届",
               "不限": "经验不限"}

# 非空时必须是下列取值的字段（投递入口类型按 ENTRY_TYPES 校）
FLAG_FIELDS = {"已沟通": ["是", "否"]}


def canonical_value(field, value):
    """单值规范化：空值按词表默认补全，别名映射到规范词；无法识别原样返回。"""
    v = str(value or "").strip()
    if field == "学历":
        if not v:
            return "学历不限"
        return EDU_ALIASES.get(v, v)
    if field == "经验":
        if not v:
            return "经验不限"
        return EXP_ALIASES.get(v, v)
    if field == "已沟通":  # Boss 接口 contact 是布尔：True/1 → 是，其余 → 否
        return "是" if v.lower() in ("true", "1", "是") else "否"
    return v


def validate_job_fields(fields):
    """高强度校验统一字段记录。返回 (violations, cleaned)：
    - violations: list[str]，逐条违规描述（空列表 = 完全合法）；
    - cleaned: 规范词映射 + 字段裁剪后的副本（不改传入对象）。
    规则：字段名必须在白名单内；关键字段不得为空；学历/经验/投递入口类型/已沟通
    取值必须在规范词表内；薪资含文字时必须是「面议」或含数字。"""
    import re as _re
    violations, cleaned = [], dict(fields)
    allowed = set(JOB_FIELDS)
    for k in list(cleaned):
        if k not in allowed:
            violations.append("未知字段「%s」（不在统一字段白名单）" % k)
            del cleaned[k]
    for k in JOB_FIELDS:
        cleaned.setdefault(k, "")
    for k in JOB_KEY_FIELDS:  # 关键字段缺损 = 该记录不可核对，拒绝
        if not str(cleaned.get(k, "")).strip():
            violations.append("关键字段「%s」为空" % k)
    for k in ("学历", "经验"):
        canon = canonical_value(k, cleaned.get(k))
        vocab = EDU_VOCAB if k == "学历" else EXP_VOCAB
        if canon not in vocab:
            violations.append("「%s」取值「%s」不在规范词表 %s 内" % (k, canon, "/".join(vocab)))
        cleaned[k] = canon
    et = str(cleaned.get("投递入口类型", "")).strip()
    if et and et not in ENTRY_TYPES:
        violations.append("「投递入口类型」取值「%s」非法（可选：%s）" % (et, "/".join(ENTRY_TYPES)))
    for k, vocab in FLAG_FIELDS.items():
        v = str(cleaned.get(k, "")).strip()
        if v and v not in vocab:
            violations.append("「%s」取值「%s」非法（可选：%s）" % (k, v, "/".join(vocab)))
    sal = str(cleaned.get("薪资", "")).strip()
    if sal and sal != "面议" and not _re.search(r"\d", sal):
        violations.append("「薪资」取值「%s」无法核对（应为区间含数字或「面议」）" % sal)
    return violations, cleaned
