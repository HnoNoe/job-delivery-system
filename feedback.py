"""结果输出层 —— 结果回写与语义回归修正（步骤七）。

职责：样本累积、结果定义、经历权重更新（式五）、岗位中心更新、写回闭环。
"""
import json
import numpy as np
import db
import config
from formulas import formula_5_weight_update, formula_1_user_representation


def poll_results(user_id):
    """反馈轮询：投递后跟踪各任务状态（不伪造面试结果）。

    真实平台无法主动轮询到「进入面试」等结果，只如实记录当前投递状态；
    后续由用户手动标注单位回应，再回写权重（式五）。
    """
    conn = db.get_conn()
    tasks = conn.execute(
        "SELECT * FROM delivery_tasks WHERE user_id=? ORDER BY task_id", (user_id,)
    ).fetchall()
    out = []
    for t in tasks:
        if t["entry_type"] == "邮件":
            reply = "已发送，待回复"
        elif t["entry_type"] == "半自动":
            reply = "材料包已生成，待手动投递"
        else:
            reply = "已投递，待单位回复"
        out.append({
            "task_id": t["task_id"], "岗位": t["job_name"], "单位": t["unit_name"],
            "入口类型": t["entry_type"], "投递状态": reply,
        })
    conn.commit()
    conn.close()
    return out


def process_feedback(user_id, feedbacks, profile):
    """feedback: list[{task_id, result(z∈{0,1}), indicator(I_k 列表)}]。
    执行式五权重更新 + 岗位中心更新，写回统一字段数据库。"""
    conn = db.get_conn()
    # 读取当前权重与经历向量
    exps = conn.execute(
        "SELECT * FROM experience_items WHERE user_id=? ORDER BY exp_index", (user_id,)
    ).fetchall()
    K = len(exps)
    wrows = conn.execute(
        "SELECT exp_index, weight FROM profile_weights WHERE user_id=? ORDER BY exp_index",
        (user_id,),
    ).fetchall()
    weights = np.array([r["weight"] for r in wrows]) if wrows else np.full(K, 1.0 / K)

    # 从历史样本累积正负岗位向量（中心更新要两类都有，不能只看本次单条反馈）
    pos, neg = [], []
    hist = conn.execute(
        "SELECT job_embedding, result FROM history_samples WHERE user_id=?", (user_id,)
    ).fetchall()
    for h in hist:
        if h["job_embedding"]:
            v = np.asarray(json.loads(h["job_embedding"]))
            (pos if h["result"] == 1 else neg).append(v)

    for fb in feedbacks:
        z = int(fb["result"])
        ind = fb["indicator"]
        # (1) 样本累积
        task = conn.execute("SELECT * FROM delivery_tasks WHERE task_id=?", (fb["task_id"],)).fetchone()
        job = conn.execute("SELECT * FROM jobs WHERE job_id=?", (task["job_id"],)).fetchone()
        job_vec = json.loads(job["embedding"]) if job["embedding"] else None
        conn.execute(
            "INSERT INTO history_samples (user_id, job_embedding, result, write_indicator)"
            " VALUES (?,?,?,?)",
            (user_id, json.dumps(job_vec) if job_vec else None, z,
             json.dumps(ind)),
        )
        # (3) 经历权重更新（式五）
        weights = formula_5_weight_update(weights, z, ind, config.ETA)

        # 收集岗位中心样本
        if job_vec is not None:
            (pos if z == 1 else neg).append(np.asarray(job_vec))

    # 写回画像权重子表
    for i, w in enumerate(weights):
        conn.execute("INSERT OR REPLACE INTO profile_weights VALUES (?,?,?)",
                     (user_id, i, float(w)))

    # (4) 岗位中心更新：两类均非空才更新
    if pos and neg:
        c_pos = np.mean(pos, axis=0).tolist()
        c_neg = np.mean(neg, axis=0).tolist()
        conn.execute("INSERT OR REPLACE INTO job_centers VALUES (?,?,?)",
                     (user_id, json.dumps(c_pos), json.dumps(c_neg)))
    else:
        c_pos = c_neg = None

    # (5) 保存画像快照到画像池（供遍历比对 + 画像演进），含用户表示向量快照
    vecs = []
    for e in exps:
        if e["embedding"]:
            vecs.append(np.asarray(json.loads(e["embedding"])))
    user_vec = formula_1_user_representation(vecs, weights).tolist() if vecs else None
    conn.execute("INSERT INTO profile_pool (user_id, weights, user_vec, pos_center, neg_center) VALUES (?,?,?,?,?)",
                 (user_id, json.dumps(weights.tolist()),
                  json.dumps(user_vec) if user_vec is not None else None,
                  json.dumps(c_pos) if c_pos is not None else None,
                  json.dumps(c_neg) if c_neg is not None else None))

    conn.commit()
    conn.close()
    return weights.tolist()


def mark_result(task_id, result):
    """用户手动标注投递结果（进入面试及以上=1，否则=0），回写权重（式五）。"""
    conn = db.get_conn()
    task = conn.execute("SELECT * FROM delivery_tasks WHERE task_id=?", (task_id,)).fetchone()
    if task is None:
        conn.close()
        return False, "任务不存在"
    ind_row = conn.execute("SELECT indicator FROM task_indicators WHERE task_id=?", (task_id,)).fetchone()
    # 同步更新任务结果字段（供第⑥步投递记录展示「进面试/未进面试」）
    conn.execute("UPDATE delivery_tasks SET result=? WHERE task_id=?",
                 ("进面试" if int(result) == 1 else "未进面试", task_id))
    conn.commit()
    conn.close()
    if ind_row is None:
        return False, "该任务缺少写入指示"
    indicator = json.loads(ind_row["indicator"])
    new_weights = process_feedback(task["user_id"],
                                   [{"task_id": task_id, "result": int(result), "indicator": indicator}], None)
    return True, new_weights


def get_profile_evolution(user_id):
    """读取画像池快照（画像演进历史）。返回 list[dict]。"""
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM profile_pool WHERE user_id=? ORDER BY snap_id", (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats(user_id):
    """画像池统计：累计投递、进面试数、画像快照数（从实际数据表统计）。"""
    conn = db.get_conn()
    interviews = conn.execute(
        "SELECT COUNT(*) FROM history_samples WHERE user_id=? AND result=1", (user_id,)
    ).fetchone()[0]
    delivered = conn.execute(
        "SELECT COUNT(*) FROM delivery_tasks WHERE user_id=? AND status='已投递'", (user_id,)
    ).fetchone()[0]
    snaps = conn.execute(
        "SELECT COUNT(*) FROM profile_pool WHERE user_id=?", (user_id,)
    ).fetchone()[0]
    conn.close()
    return {"快照数": snaps, "累计投递": delivered, "进面试": interviews}


def get_quality(user_id):
    """投递质量评估：在 get_stats 基础上补反馈率 / 进面试率 / 已投递岗位平均匹配分。

    - 反馈率 = 有结果标注 ÷ 已投递（用户标注配合度）
    - 进面试率 = 进面试 ÷ 有结果标注（真实转化质量，分母不含未标注）
    - 平均匹配分 = 已投递岗位在 target_jobs 里的式三 p 均值（投递选择质量）
    """
    s = get_stats(user_id)
    conn = db.get_conn()
    answered = conn.execute(
        "SELECT COUNT(*) FROM delivery_tasks WHERE user_id=? AND result<>''", (user_id,)
    ).fetchone()[0]
    avg_score = conn.execute(
        "SELECT AVG(t.score) FROM target_jobs t JOIN delivery_tasks d "
        "ON t.job_id=d.job_id WHERE d.user_id=? AND d.status='已投递'", (user_id,)
    ).fetchone()[0]
    conn.close()
    delivered = s["累计投递"]
    s["已标注"] = answered
    s["反馈率%"] = round(100 * answered / delivered) if delivered else 0
    s["进面试率%"] = round(100 * s["进面试"] / answered) if answered else 0
    s["已投递平均匹配分"] = round(float(avg_score), 3) if avg_score is not None else 0
    return s
