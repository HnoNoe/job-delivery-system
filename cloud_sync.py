"""云端共享岗位池同步。

定位（与本地库严格分工）：
- 本地 SQLite：完整投递流程的唯一工作库（简历/检索/匹配/投递/反馈），零网络依赖；
- 云端 MySQL：只存「全队去重后的岗位池」这一份共享数据。

同步语义：
- push：把本地新抓取的岗位推到云端，按「岗位链接」去重，标注提交者 owner；
- pull：把云端岗位池中本地没有的岗位拉回本地（仍走本地核检与匹配流程）；
- 任何一端失败都不影响本地主流程。
"""
import hashlib
import json

import db


def _link_of(fields: dict) -> str:
    """去重键：优先岗位链接；缺失时用 名称+单位+城市 的指纹。"""
    link = (fields.get("岗位链接") or "").strip()
    if link:
        return link
    raw = "%s|%s|%s" % (fields.get("岗位名称", ""), fields.get("单位名称", ""), fields.get("城市", ""))
    return "nolink:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _rows_of(conn) -> list:
    """读取 jobs 表全部 (fields, embedding, active) 并关闭连接由调用方决定。"""
    out = []
    for r in conn.execute("SELECT fields, embedding, active FROM jobs"):
        f = json.loads(r["fields"] if hasattr(r, "keys") else r[0] or "{}")
        emb = (r["embedding"] if hasattr(r, "keys") else r[1])
        active = (r["active"] if hasattr(r, "keys") else r[2])
        out.append((f, emb, active))
    return out


def _local_active() -> list:
    """本地在库岗位：[(fields, embedding)]。"""
    conn = db.get_conn()
    try:
        return [(f, emb) for f, emb, active in _rows_of(conn) if active]
    finally:
        conn.close()


def push_jobs(owner: str) -> dict:
    """本地 → 云端。返回 {新增, 云端已有, 本地岗位数}。"""
    local = _local_active()
    with db.use_cloud():
        conn = db.get_conn()
        try:
            cloud_links = {_link_of(f) for f, _emb, _a in _rows_of(conn)}
            new_rows = []
            for f, emb in local:
                key = _link_of(f)
                if key not in cloud_links:
                    new_rows.append((json.dumps(f, ensure_ascii=False), emb, owner))
                    cloud_links.add(key)
            if new_rows:
                conn.executemany(
                    "INSERT INTO jobs (fields, embedding, active, owner) VALUES (?, ?, 1, ?)",
                    new_rows)
                conn.commit()
            return {"新增": len(new_rows), "云端已有": len(cloud_links) - len(new_rows),
                    "本地岗位数": len(local)}
        finally:
            conn.close()


def pull_jobs() -> dict:
    """云端 → 本地。按链接去重插入本地岗位池。返回 {拉回}。"""
    local_links = {_link_of(f) for f, _emb in _local_active()}
    rows = []
    with db.use_cloud():
        conn = db.get_conn()
        try:
            for f, emb, active in _rows_of(conn):
                if not active:
                    continue
                key = _link_of(f)
                if key not in local_links:
                    local_links.add(key)
                    rows.append((json.dumps(f, ensure_ascii=False), emb))
        finally:
            conn.close()
    if rows:
        conn = db.get_conn()
        try:
            conn.executemany("INSERT INTO jobs (fields, embedding, active) VALUES (?, ?, 1)", rows)
            conn.commit()
        finally:
            conn.close()
    return {"拉回": len(rows)}


def pool_counts() -> dict:
    """两端岗位数概览。"""
    conn = db.get_conn()
    try:
        local_n = conn.execute("SELECT COUNT(*) FROM jobs WHERE active = 1").fetchone()[0]
    finally:
        conn.close()
    with db.use_cloud():
        conn = db.get_conn()
        try:
            cloud_n = conn.execute("SELECT COUNT(*) FROM jobs WHERE active = 1").fetchone()[0]
        finally:
            conn.close()
    return {"本地": local_n, "云端": cloud_n}
