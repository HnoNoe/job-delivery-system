"""操作层2-建立任务（步骤四）。

职责：为每个目标岗位生成一条投递任务（一岗一条），组成投递任务表，
并提供可视化勾选。
"""
import db


def create_tasks(user_id, target_jobs):
    """目标岗位 → 投递任务表。返回任务编号列表。"""
    conn = db.get_conn()
    task_ids = []
    for i, x in enumerate(target_jobs):
        job = x["job"]
        cur = conn.execute(
            "INSERT INTO delivery_tasks (job_id, user_id, job_name, unit_name, job_link,"
            " entry_type, entry_addr, status) VALUES (?,?,?,?,?,?,?,?)",
            (x["job_id"], user_id, job.get("岗位名称"), job.get("单位名称"),
             job.get("岗位链接"), job.get("投递入口类型"), job.get("投递入口地址"),
             "待生成"),
        )
        task_ids.append(cur.lastrowid)
    conn.commit()
    conn.close()
    return task_ids


def list_tasks(user_id):
    """读取投递任务表（供面板展示与勾选）。"""
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM delivery_tasks WHERE user_id=? ORDER BY task_id", (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_task_status(task_id, status):
    conn = db.get_conn()
    conn.execute("UPDATE delivery_tasks SET status=? WHERE task_id=?", (status, task_id))
    conn.commit()
    conn.close()
