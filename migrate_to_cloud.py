"""一次性迁移：本机 SQLite 数据 → 云端 MySQL 统一字段数据库。

用法：python migrate_to_cloud.py
只搬数据（用户记录/经历/权重/岗位池/画像快照），不搬任务执行类表
（delivery_tasks/target_jobs 等属于单机现场，让各客户端自己生成）。
幂等：按主键冲突跳过（INSERT IGNORE）。
"""
import json
import os
import sqlite3
import sys

os.environ["JOBDELIVERY_DB_URL"] = "sqlite"          # 源：本机
import config                                        # noqa: E402
import db                                            # noqa: E402

TABLES = ["user_records", "experience_items", "profile_weights",
          "jobs", "profile_pool", "job_centers", "history_samples"]


def main():
    src = sqlite3.connect(config.DB_PATH)
    src.row_factory = sqlite3.Row
    os.environ["JOBDELIVERY_DB_URL"] = ""             # 目标：云端（env 置空回退 config.CLOUD_DB_URL）
    db.DB_URL = db._resolve_url()
    db.init_db()
    dst = db.get_conn()
    for t in TABLES:
        rows = src.execute("SELECT * FROM %s" % t).fetchall()
        if not rows:
            print("%-20s 空表，跳过" % t)
            continue
        cols = rows[0].keys()
        sql = "INSERT IGNORE INTO %s (%s) VALUES (%s)" % (
            t, ",".join(cols), ",".join(["?"] * len(cols)))
        dst.executemany(sql, [tuple(r) for r in rows])
        dst.commit()
        print("%-20s 迁移 %d 条" % (t, len(rows)))
    # 行数对账
    for t in TABLES:
        a = src.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        b = dst.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        flag = "OK" if a == b else "MISMATCH"
        print("对账 %-18s 本地 %d / 云端 %d  %s" % (t, a, b, flag))
    src.close()
    dst.close()


if __name__ == "__main__":
    sys.exit(main())
