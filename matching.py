"""操作层1-信息匹配（步骤三）。

职责：短任务采集岗位、硬约束过滤、打分排序（式二、式三）→ 目标岗位统计表。
"""
import json
import numpy as np
import config
import db
import schema
import embedding
from formulas import formula_2_cosine, formula_3_match_score, interval_feature


def _desc_str(f):
    """岗位描述字段可能是字符串或列表（如 jobLabels），统一转字符串用于嵌入。"""
    d = f.get("岗位描述", "") or ""
    if isinstance(d, list):
        return " ".join(str(x) for x in d)
    return str(d)


def store_jobs(jobs):
    """把外部检索/采集到的岗位写入 jobs 表（幂等）。返回数量。"""
    conn = db.get_conn()
    conn.execute("DELETE FROM jobs")
    for f in jobs:
        vec = embedding.embed((f.get("岗位名称", "") or "") + " " + _desc_str(f))
        conn.execute("INSERT INTO jobs (fields, embedding) VALUES (?,?)",
                     (json.dumps(f, ensure_ascii=False), json.dumps(vec.tolist())))
    conn.commit()
    conn.close()
    return len(jobs)


def collect_jobs():
    """短任务采集岗位记录（仅真实数据源，无虚构兜底）。

    仅使用 config.CRAWLER_SOURCES 配置的真实数据源；未配置或抓取失败时返回空，
    绝不回退到虚构示例岗位。
    """
    jobs = []
    if getattr(config, "CRAWLER_SOURCES", None):
        import crawler
        try:
            jobs = crawler.collect_from_sources(config.CRAWLER_SOURCES)
        except Exception as e:  # noqa
            print("[collect_jobs] 爬虫采集失败:", e)

    conn = db.get_conn()
    conn.execute("DELETE FROM jobs")  # 幂等，避免重复插入
    for f in jobs:
        vec = embedding.embed((f.get("岗位名称", "") or "") + " " + _desc_str(f))
        conn.execute("INSERT INTO jobs (fields, embedding) VALUES (?,?)",
                     (json.dumps(f, ensure_ascii=False), json.dumps(vec.tolist())))
    conn.commit()
    conn.close()
    return len(jobs)


def determine_target_jobs(profile):
    """硬约束过滤 + 打分排序 → 目标岗位统计表。返回 list[dict]。"""
    conn = db.get_conn()
    jobs = conn.execute("SELECT * FROM jobs").fetchall()

    hard = profile["hard_constraints"]
    user_vec = profile["user_vec"]

    # 读取岗位正负中心（步骤七写入，两类均非空才使用）
    c = conn.execute("SELECT c_pos, c_neg FROM job_centers WHERE user_id=?",
                     (profile["user_id"],)).fetchone()
    has_center = bool(c and c["c_pos"] and c["c_neg"])
    c_pos = np.asarray(json.loads(c["c_pos"])) if has_center else None
    c_neg = np.asarray(json.loads(c["c_neg"])) if has_center else None

    candidates = []
    for job in jobs:
        f = json.loads(job["fields"])
        jv = np.asarray(json.loads(job["embedding"])) if job["embedding"] else None

        # 关键字段缺损检查
        if any(not f.get(k) for k in schema.JOB_KEY_FIELDS):
            continue

        # 硬约束过滤（集合过滤，非打分）。字段缺失时不据此过滤（缺失视为未知，宁多勿漏）
        if hard["意向城市"] and f.get("城市") and f.get("城市") not in hard["意向城市"]:
            continue
        if hard["意向行业"] and f.get("行业") and f.get("行业") not in hard["意向行业"]:
            continue
        if hard["禁忌公司"] and f.get("公司") and any(str(t) in str(f.get("公司")) for t in hard["禁忌公司"]):
            continue
        # 已沟通过的岗位跳过（避免重复投递骚扰）
        if str(f.get("已沟通", "")).lower() in ("true", "1"):
            continue

        # 打分（式二、式三）
        s = formula_2_cosine(user_vec, jv) if jv is not None else 0.0
        delta = interval_feature(jv, c_pos, c_neg) if has_center else 0.0
        p = formula_3_match_score(s, delta, config.W_S, config.W_DELTA, has_center)
        candidates.append({"job": f, "job_id": job["job_id"], "score": p, "s": s,
                           "delta": delta, "has_center": has_center})

    candidates.sort(key=lambda x: x["score"], reverse=True)

    # 写回目标岗位统计表
    conn.execute("DELETE FROM target_jobs")
    for x in candidates:
        conn.execute("INSERT INTO target_jobs (job_id, score, entry_type, entry_addr) VALUES (?,?,?,?)",
                     (x["job_id"], x["score"], x["job"].get("投递入口类型"),
                      x["job"].get("投递入口地址")))
    conn.commit()
    conn.close()
    return candidates
