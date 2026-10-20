"""模型层1-用户画像（步骤二）。

职责：字段注入与汇总、构造硬约束、经历向量化、构造用户表示（式一）、
生成约束提示词。
"""
import json
import numpy as np
import config
import db
import schema
import embedding
from formulas import formula_1_user_representation


def build_profile(user_id):
    """构造硬约束、经历向量、经历权重与用户表示。返回 dict。"""
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM user_records WHERE user_id=?", (user_id,)).fetchone()
    l0 = json.loads(row["l0"])
    l3 = json.loads(row["l3"])

    # (2) 构造硬约束（集合意义约束，用于过滤，非打分）
    hard_constraints = {
        "意向城市": _split(l3.get("意向城市", "")),
        "意向行业": _split(l3.get("意向行业", "")),
        "禁忌公司": _split(l3.get("禁忌公司", "")),
    }

    # (3) 经历向量化
    exps = conn.execute(
        "SELECT * FROM experience_items WHERE user_id=? ORDER BY exp_index", (user_id,)
    ).fetchall()
    K = len(exps)
    vectors = []
    for e in exps:
        if e["embedding"]:
            vectors.append(np.asarray(json.loads(e["embedding"])))
        else:
            vec = embedding.embed(_exp_text(json.loads(e["fields"])))
            vectors.append(vec)
            conn.execute("UPDATE experience_items SET embedding=? WHERE exp_id=?",
                         (json.dumps(vec.tolist()), e["exp_id"]))
    conn.commit()

    # 经历权重（未写入时取单纯形均匀初值 1/K）
    weights = _load_weights(conn, user_id, K)

    # (4) 构造用户表示（式一）
    user_vec = formula_1_user_representation(vectors, weights)

    conn.close()
    return {
        "user_id": user_id,
        "hard_constraints": hard_constraints,
        "experience_vectors": vectors,
        "weights": weights,
        "user_vec": user_vec,
        "K": K,
        "l0": l0, "l3": l3,
    }


def _load_weights(conn, user_id, K):
    if K == 0:
        return np.array([])
    rows = conn.execute(
        "SELECT exp_index, weight FROM profile_weights WHERE user_id=? ORDER BY exp_index",
        (user_id,),
    ).fetchall()
    if len(rows) == K:
        return np.array([r["weight"] for r in rows])
    # 均匀初值
    w = np.full(K, 1.0 / K)
    for i, val in enumerate(w):
        conn.execute("INSERT OR REPLACE INTO profile_weights VALUES (?,?,?)",
                     (user_id, i, float(val)))
    conn.commit()
    return w


def _split(s):
    return [x.strip() for x in (s or "").replace("，", ",").split(",") if x.strip()]


def _exp_text(fields: dict) -> str:
    return " ".join(str(fields.get(k, "")) for k in schema.L2_FIELDS)
