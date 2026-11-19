"""HR 回应登记（人工登记 + 方案 B 自动识别结果落库）。

定位：
- 平台没有公开 API，登录态下读私信又有风控与合规风险，因此默认走**人工登记**：
  在第⑥阶段登记「已查看 / 邀面试 / 不合适 / 无回复 / 其他」+ 备注；
- 方案 B 的「检查新回复」识别出的候选，经用户勾选后也写入本表（source='auto'）；
- 只写本地 SQLite，不外传、不联网；同一任务可登记多条，形成回应时间线；
- 用 (task_id, kind, content_hash) 唯一索引做幂等，重复登记不会写重复行。

与画像反馈的关系：
- `delivery_tasks.result`（进面试/未进面试）是**画像反馈**，会触发式五权重更新；
- 本表的 `kind` 是**HR 回应事实**，只做记录与统计，不自动改画像，避免两种口径互相污染。
  需要把「邀面试」升级为画像反馈时，由用户在第⑤阶段手动点「✅ 进面试」。
"""
import hashlib
import json

import db

KINDS = ("已查看", "邀面试", "线上交流邀请", "不合适", "需补充资料", "待定", "无回复", "其他")

# 展示提示（供界面使用）
KIND_HINT = {
    "邀面试": "对方明确约面试（含时间/形式），建议在第⑤阶段标注「进面试」",
    "线上交流邀请": "对方愿意线上沟通（聊一聊/方便吗/加微信），尚未约面试",
    "不合适": "对方明确不合适，可标注「未进面试」",
    "需补充资料": "对方要简历附件/作品集/成绩单等，建议尽快补齐",
    "待定": "对方说稍后回复/内部评估中，过几天再跟进",
    "已查看": "对方查看了简历/消息，尚未回复",
    "无回复": "超过期望时间仍无回应",
    "其他": "其他情况，可写备注",
}


def _hash(kind, content):
    return hashlib.sha256(("%s|%s" % (kind, content or "")).encode("utf-8")).hexdigest()[:16]


def add_response(task_id, kind, content="", source="manual", platform=""):
    """登记一条 HR 回应。返回 (ok, message, resp_id)。

    幂等：同任务 + 同类型 + 同内容重复登记时返回 (False, 说明, 已有 resp_id)。
    """
    if kind not in KINDS:
        return False, "回应类型须为：%s" % "、".join(KINDS), None
    content = (content or "").strip()[:500]
    with db.get_conn() as conn:
        task = conn.execute("SELECT task_id, job_name FROM delivery_tasks WHERE task_id=?",
                            (task_id,)).fetchone()
        if task is None:
            return False, "任务不存在", None
        h = _hash(kind, content)
        dup = conn.execute(
            "SELECT resp_id FROM hr_responses WHERE task_id=? AND kind=? AND content_hash=?",
            (task_id, kind, h)).fetchone()
        if dup:
            return False, "同样的回应已登记过（#%d）" % dup["resp_id"], dup["resp_id"]
        cur = conn.execute(
            "INSERT INTO hr_responses (task_id, platform, kind, content, content_hash, source)"
            " VALUES (?,?,?,?,?,?)",
            (task_id, platform or "", kind, content, h, source or "manual"))
        resp_id = cur.lastrowid
    return True, "已登记「%s」" % kind, resp_id


def list_responses(user_id):
    """某用户的全部回应（按登记时间倒序），带岗位信息。"""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT r.*, d.job_name, d.unit_name FROM hr_responses r "
            "JOIN delivery_tasks d ON d.task_id=r.task_id "
            "WHERE d.user_id=? ORDER BY r.resp_id DESC", (user_id,)).fetchall()
    return [dict(r) for r in rows]


def by_task(user_id):
    """按任务分组的回应：{task_id: [回应, ...]}（组内按登记时间正序）。"""
    grouped = {}
    for row in reversed(list_responses(user_id)):
        grouped.setdefault(row["task_id"], []).append(row)
    return grouped


def latest_by_task(user_id):
    """每个任务的最新一条回应：{task_id: 回应}。"""
    return {tid: rows[-1] for tid, rows in by_task(user_id).items() if rows}


def summary(user_id):
    """回应统计：总数 + 各类型计数。"""
    counts = {k: 0 for k in KINDS}
    rows = list_responses(user_id)
    for row in rows:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    return {"总数": len(rows), "分类": counts}


def export_rows(user_id):
    """导出用扁平结构（供 CSV）。"""
    return [{
        "任务": r["task_id"], "岗位": r["job_name"], "单位": r["unit_name"],
        "回应": r["kind"], "内容": r["content"], "来源": r["source"],
        "登记时间": r["first_seen"],
    } for r in list_responses(user_id)]


def dumps(rows):
    """调试用：稳定 JSON 输出。"""
    return json.dumps(rows, ensure_ascii=False, indent=2)
