"""岗位入库：高强度校验（harsh）+ 内容哈希去重 + 上下架标记。

从 matching.store_jobs 裁剪而来——去掉向量嵌入（画像/匹配已删除），
只保留「入库即合法、不合法就拒绝并留痕」的校验与幂等去重。
"""
import json

import db
import schema


def store_jobs(jobs, user_id=None):
    """把检索/采集到的岗位写入 jobs 表（幂等）。返回入库（含复用）数量。

    高强度校验：每条先过 schema.validate_job_fields；关键字段缺损/未知字段等
    「不可核对」违规直接拒收并留痕，绝不写入脏数据。
    """
    skipped = 0
    with db.get_conn() as conn:
        conn.execute("UPDATE jobs SET active=0")
        ids = []
        for raw in jobs:
            from crawler import normalize_fields
            f = normalize_fields(raw)
            violations, f = schema.validate_job_fields(f)
            fatal = [v for v in violations if v.startswith("关键字段") or v.startswith("未知字段")]
            if fatal:
                skipped += 1
                print("[store_jobs] 拒收 1 条岗位：%s" % "；".join(fatal))
                continue
            for v in violations:
                print("[store_jobs] 警告：%s（已按规范词/原样入库）" % v)
            fields = json.dumps(f, ensure_ascii=False, sort_keys=True)
            row = conn.execute("SELECT job_id FROM jobs WHERE fields=? LIMIT 1", (fields,)).fetchone()
            if row:
                job_id = row["job_id"]
                conn.execute("UPDATE jobs SET active=1 WHERE job_id=?", (job_id,))
            else:
                cur = conn.execute("INSERT INTO jobs (fields, active) VALUES (?,1)", (fields,))
                job_id = cur.lastrowid
            if job_id not in ids:
                ids.append(job_id)
        if user_id is not None:
            conn.execute("INSERT OR IGNORE INTO user_job_scopes VALUES (?)", (user_id,))
            conn.execute("DELETE FROM user_jobs WHERE user_id=?", (user_id,))
            conn.executemany("INSERT INTO user_jobs VALUES (?,?)", [(user_id, jid) for jid in ids])
        return len(ids)
