"""按账号隔离的数据访问层。

隐私边界（桌面端强制）：
- 简历（user_records + experience_items）、权重、投递记录：只可见/可操作 owner=自己 的行；
- 岗位池 jobs：全队共享（去重汇聚是设计目标），所有人可读，无人可删他人的；
- 画像广场 profile_pool：visibility='public' 的快照作为对比数据公开可见，
  私有画像与未发布快照只有本人可见。
"""
import json
import functools

import db


def _cloud(fn):
    """mydata 全部走云端共享库；本地库不在此层访问。"""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        with db.use_cloud():
            return fn(*a, **kw)
    return wrapper

# ---------- 我的简历 ----------

@_cloud
def get_my_user_id(owner, create=True):
    """当前账号的简历主记录 user_id；没有且允许时创建空记录。"""
    row = db.get_conn().execute(
        "SELECT user_id FROM user_records WHERE owner = ? ORDER BY user_id LIMIT 1",
        (owner,)).fetchone()
    if row is not None:
        return row[0]
    if not create:
        return None
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO user_records (l0, l1, l3, owner) VALUES ('{}', '{}', '{}', ?)",
        (owner,))
    conn.commit()
    return cur.lastrowid


@_cloud
def load_resume(owner):
    """读取我的简历：L0 字段 + 经历明细。无记录返回 None。"""
    row = db.get_conn().execute(
        "SELECT user_id, l0, l1, l3 FROM user_records WHERE owner = ? ORDER BY user_id LIMIT 1",
        (owner,)).fetchone()
    if row is None:
        return None
    uid = row[0]
    l0 = json.loads(row["l0"] or "{}") if isinstance(row, dict) else json.loads(row[1] or "{}")
    l1 = json.loads(row["l1"] or "{}") if isinstance(row, dict) else json.loads(row[2] or "{}")
    l3 = json.loads(row["l3"] or "{}") if isinstance(row, dict) else json.loads(row[3] or "{}")
    exps = []
    for r in db.get_conn().execute(
            "SELECT fields FROM experience_items WHERE user_id = ? ORDER BY exp_index", (uid,)):
        f = json.loads(r["fields"] or "{}") if isinstance(r, dict) else json.loads(r[0] or "{}")
        exps.append(f)
    return {"user_id": uid, "l0": l0, "l1": l1, "l3": l3, "experiences": exps}


@_cloud
def save_resume(owner, parsed):
    """保存/覆盖我的简历。

    parsed 与 recommend.resume_parse / resume_ai.smart_parse 同构：
    {L0字段…, '意向岗位': str, '技能': [..], '经历': [{类型,名称,…}]}
    """
    l0 = {k: str(v) for k, v in parsed.items()
          if k not in ("技能", "经历", "意向岗位") and v is not None}
    l1 = {}
    for e in parsed.get("经历", []) or []:
        if isinstance(e, dict) and e.get("类型"):
            l1[e["类型"]] = l1.get(e["类型"], 0) + 1
    l3 = {"意向岗位": parsed.get("意向岗位", "")}
    uid = get_my_user_id(owner)
    conn = db.get_conn()
    conn.execute(
        "UPDATE user_records SET l0 = ?, l1 = ?, l3 = ? WHERE user_id = ?",
        (json.dumps(l0, ensure_ascii=False), json.dumps(l1, ensure_ascii=False),
         json.dumps(l3, ensure_ascii=False), uid))
    conn.execute("DELETE FROM experience_items WHERE user_id = ?", (uid,))
    import embedding
    for i, e in enumerate(parsed.get("经历", []) or []):
        if not isinstance(e, dict):
            continue
        text = " ".join(str(e.get(k, "")) for k in ("名称", "角色", "事项", "结果", "技术工具"))
        vec = list(embedding.embed(text)) if text.strip() else None
        conn.execute(
            "INSERT INTO experience_items (user_id, exp_index, fields, embedding) VALUES (?, ?, ?, ?)",
            (uid, i, json.dumps(e, ensure_ascii=False),
             json.dumps(vec) if vec is not None else None))
    conn.commit()
    return uid


# ---------- 画像广场（公开=对比数据） ----------

@_cloud
def list_public_profiles(exclude_owner=None):
    """公开的画像快照（每人最新一条），用于对比视图。返回 [{owner, weights, user_vec, ts}]。"""
    sql = ("SELECT owner, weights, user_vec, ts FROM profile_pool p "
           "WHERE visibility = 'public'")
    params = []
    if exclude_owner:
        sql += " AND owner != ?"
        params.append(exclude_owner)
    sql += " AND snap_id = (SELECT MAX(snap_id) FROM profile_pool WHERE owner = p.owner)"
    out = []
    for r in db.get_conn().execute(sql, tuple(params)):
        g = lambda k, i: (r[k] if isinstance(r, dict) else r[i])
        out.append({"owner": g("owner", 0), "weights": g("weights", 1),
                    "user_vec": g("user_vec", 2), "ts": g("ts", 3)})
    return out


@_cloud
def list_my_profiles(owner):
    return [r for r in db.get_conn().execute(
        "SELECT snap_id, visibility, ts, delivered_count, interview_count FROM profile_pool "
        "WHERE owner = ? ORDER BY snap_id DESC", (owner,))]


@_cloud
def set_profile_visibility(snap_id, owner, visibility):
    """仅本人可改自己的快照可见性。"""
    db.get_conn().execute(
        "UPDATE profile_pool SET visibility = ? WHERE snap_id = ? AND owner = ?",
        (visibility, snap_id, owner))
    db.get_conn().commit()


@_cloud
def publish_snapshot(owner, user_id):
    """把我当前的画像快照发布为公开对比数据（复制最新快照为 public）。"""
    row = db.get_conn().execute(
        "SELECT weights, user_vec, pos_center, neg_center, delivered_count, interview_count "
        "FROM profile_pool WHERE user_id = ? ORDER BY snap_id DESC LIMIT 1", (user_id,)).fetchone()
    if row is None:
        return False
    g = lambda k, i: (row[k] if isinstance(row, dict) else row[i])
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO profile_pool (user_id, weights, user_vec, pos_center, neg_center, "
        "delivered_count, interview_count, owner, visibility) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'public')",
        (user_id, g("weights", 0), g("user_vec", 1), g("pos_center", 2), g("neg_center", 3),
         g("delivered_count", 4), g("interview_count", 5), owner))
    conn.commit()
    return True


# ---------- 共享岗位池 ----------

@_cloud
def list_jobs(limit=500):
    """共享岗位池（全队去重汇聚），只读浏览。"""
    out = []
    for r in db.get_conn().execute(
            "SELECT job_id, fields FROM jobs WHERE active = 1 ORDER BY job_id DESC LIMIT ?",
            (limit,)):
        f = json.loads(r["fields"] or "{}") if isinstance(r, dict) else json.loads(r[1] or "{}")
        f["job_id"] = r["job_id"] if isinstance(r, dict) else r[0]
        out.append(f)
    return out


@_cloud
def pool_stats():
    c = db.get_conn()
    jobs = c.execute("SELECT COUNT(*) FROM jobs WHERE active = 1").fetchone()[0]
    accounts = c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    public = c.execute("SELECT COUNT(DISTINCT owner) FROM profile_pool WHERE visibility = 'public'").fetchone()[0]
    return {"jobs": jobs, "accounts": accounts, "public_profiles": public}
