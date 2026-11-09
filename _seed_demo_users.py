"""画像广场演示数据：造 6 个画像各异的用户，验证 2D/3D 空间图。

仅用于本地预览验证（跑完后可删 data/jobdelivery.db 恢复干净）。
"""
import json
import random

import db
import user_profile

random.seed(42)

DEMO = [
    ("张三", "示例大学", "软件工程", "3.7/4.0", "5/120", ["Python", "Flask", "MySQL"], 6, 4, 0.82),
    ("李四", "示例大学", "软件工程", "3.2/4.0", "30/120", ["Java", "Spring"], 4, 1, 0.61),
    ("王五", "理工大学", "计算机科学", "3.9/4.0", "2/100", ["Python", "PyTorch", "机器学习"], 8, 5, 0.88),
    ("赵六", "财经大学", "数据科学", "3.0/4.0", "45/110", ["SQL", "Excel"], 3, 0, 0.44),
    ("陈七", "示例大学", "信息管理", "3.5/4.0", "15/120", ["Python", "Vue", "JavaScript"], 5, 2, 0.70),
    ("刘八", "外语学院", "英语", "2.8/4.0", "60/100", ["翻译", "写作"], 2, 0, 0.35),
]


def seed():
    db.init_db()
    with db.get_conn() as conn:
        # 清掉旧演示数据（幂等重跑）
        for t in ("user_records", "experience_items", "delivery_tasks", "profile_pool",
                  "jobs", "target_jobs", "job_field_map", "task_indicators",
                  "history_samples", "job_centers", "profile_weights", "user_jobs",
                  "user_job_scopes", "delivery_attempts"):
            conn.execute("DELETE FROM %s" % t)
        # 岗位池（供 delivery_tasks 外键关联）
        job_ids = []
        for i in range(6):
            cur = conn.execute(
                "INSERT INTO jobs (fields) VALUES (?)",
                (json.dumps({"岗位名称": "演示岗位%d" % (i + 1), "单位名称": "演示公司"},
                            ensure_ascii=False),))
            job_ids.append(cur.lastrowid)
            conn.execute("INSERT INTO target_jobs (job_id, score) VALUES (?,?)",
                         (job_ids[-1], round(0.3 + i * 0.1, 2)))
        uids = []
        for uid_i, (name, school, major, gpa, rank, skills, n_exp, n_del, score) in enumerate(DEMO, 1):
            cur = conn.execute(
                "INSERT INTO user_records (l0, l1, l3) VALUES (?,?,?)",
                (json.dumps({"姓名": name, "学校": school, "专业": major, "GPA": gpa,
                             "专业排名": rank, "现居": "北京"}, ensure_ascii=False),
                 json.dumps({"实习/工作": 1, "项目": 1}, ensure_ascii=False),
                 json.dumps({"意向城市": "北京", "意向岗位": "后端开发"}, ensure_ascii=False)))
            uid = cur.lastrowid
            uids.append(uid)
            for k in range(n_exp):
                conn.execute(
                    "INSERT INTO experience_items (user_id, exp_index, fields) VALUES (?,?,?)",
                    (uid, k, json.dumps({
                        "类型": "项目", "名称": "%s的项目%d" % (name, k + 1),
                        "技术工具": ", ".join(skills), "事项": "演示",
                        "结果": "演示"}, ensure_ascii=False)))
            for j in range(n_del):
                conn.execute(
                    "INSERT INTO delivery_tasks (job_id, user_id, job_name, unit_name,"
                    " status, result, match_score) VALUES (?,?,?,?,?,?,?)",
                    (job_ids[j % len(job_ids)], uid, "演示岗位", "演示公司", "已投递",
                     "进面试" if random.random() < score else "未进面试",
                     round(score + random.uniform(-0.05, 0.05), 3)))
    # 注意：上一个 with 块退出才提交；build_profile 会另开连接，必须在提交后调用。
    # 且 build_profile 自己会写库，调用期间不能再持有别的连接（单写者锁）。
    snapshots = []
    for uid in uids:
        prof = user_profile.build_profile(uid)
        uv = prof.get("user_vec")
        snapshots.append((uid,
                          json.dumps([float(x) for x in prof["weights"]]),
                          json.dumps(uv.tolist()) if uv is not None else None))
    with db.get_conn() as conn:
        # 画像快照（含式一 user_vec，供语义空间 PCA）
        for uid, w_json, uv_json in snapshots:
            conn.execute(
                "INSERT INTO profile_pool (user_id, weights, user_vec) VALUES (?,?,?)",
                (uid, w_json, uv_json))
    print("演示数据就绪：%d 个用户" % len(DEMO))


if __name__ == "__main__":
    seed()
