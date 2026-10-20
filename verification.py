"""步骤一 —— 用户信息采集与核检（用户输入层）。

核检规则：必填项非空；手机 11 位；邮箱有效；日期格式；L1 某类型条数为 N 时，
L2 该类型填报卡片数须为 N，不一致则停留在填写页。
"""
import re
import schema


def verify(user_data) -> tuple:
    """核检用户信息。返回 (通过?, 错误列表)。"""
    errors = []
    l0 = user_data.get("l0", {})
    l1 = user_data.get("l1", {})
    l2 = user_data.get("l2", [])
    l3 = user_data.get("l3", {})

    # 必填项
    for f in schema.L0_REQUIRED:
        if not str(l0.get(f, "")).strip():
            errors.append(f"L0 必填项「{f}」为空")
    for f in schema.L3_REQUIRED:
        if not str(l3.get(f, "")).strip():
            errors.append(f"L3 必填项「{f}」为空")

    # 手机 11 位
    phone = str(l0.get("手机", ""))
    if phone and not re.fullmatch(r"1\d{10}", phone):
        errors.append("手机须为 11 位有效号码")

    # 邮箱
    email = str(l0.get("邮箱", ""))
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        errors.append("邮箱格式无效")

    # 日期格式 YYYY-MM-DD
    for f in ["出生日期"]:
        v = str(l0.get(f, ""))
        if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            errors.append(f"日期「{f}」格式须为 YYYY-MM-DD")

    # 经历卡片关键字段非空（名称或事项至少填一项，避免空经历进入画像）
    for item in l2:
        if not str(item.get("名称", "")).strip() and not str(item.get("事项", "")).strip():
            errors.append("经历「%s」的「名称」或「事项」至少填一项" % item.get("类型", ""))

    # L1 条数与 L2 填报卡片数一致性
    l2_by_type = {}
    for item in l2:
        t = item.get("类型", "")
        l2_by_type[t] = l2_by_type.get(t, 0) + 1
    for t in schema.L1_TYPES:
        n = int(l1.get(t, 0) or 0)
        if l2_by_type.get(t, 0) != n:
            errors.append(f"L1「{t}」条数为 {n}，但 L2 填报卡片数为 {l2_by_type.get(t, 0)}，须一致")

    return (len(errors) == 0), errors
