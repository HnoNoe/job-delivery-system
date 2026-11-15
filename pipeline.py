"""七步处理流程编排器。

采集 → 画像 → 匹配 → 建任务 → 生成 → 投递 → 回写 → 修正（闭环）。
每一步的输出作为下一步的输入。
"""
import json
import numpy as np
import config
import db
import verification
import user_profile as profile_mod
import matching
import tasks
import generation
import delivery
import feedback
import recommend
from formulas import formula_2_cosine, formula_3_match_score, interval_feature


def store_user(user_data):
    """步骤一：核检通过后写库，返回 user_id。"""
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO user_records (l0, l1, l3) VALUES (?,?,?)",
            (json.dumps(user_data["l0"], ensure_ascii=False),
             json.dumps(user_data["l1"], ensure_ascii=False),
             json.dumps(user_data["l3"], ensure_ascii=False)),
        )
        user_id = cur.lastrowid
        # L2 经历深挖写入 experience_items
        for idx, item in enumerate(user_data["l2"]):
            conn.execute(
                "INSERT INTO experience_items (user_id, exp_index, fields) VALUES (?,?,?)",
                (user_id, idx, json.dumps(item, ensure_ascii=False)),
            )
        return user_id


def latest_user_data():
    """最近一次保存的用户信息（用于刷新/重开页面后回填表单）。没有记录返回 None。"""
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_records ORDER BY user_id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        exps = [json.loads(r["fields"]) for r in conn.execute(
            "SELECT fields FROM experience_items WHERE user_id=? ORDER BY exp_index",
            (row["user_id"],))]
    return {
        "user_id": row["user_id"],
        "l0": json.loads(row["l0"]),
        "l1": json.loads(row["l1"]),
        "l3": json.loads(row["l3"]),
        "l2": exps,
    }


def run_full_pipeline(user_data, llm=None, jobs=None):
    """执行完整流程：采集→画像→匹配→建任务→生成→准备投递材料。

    不自动投递、不伪造反馈。投递由用户逐条手动确认（避免骚扰真实HR），
    反馈由用户手动标注结果后回写权重（式五）。
    """
    db.init_db()

    # 步骤一：核检
    ok, errors = verification.verify(user_data)
    if not ok:
        return {"ok": False, "errors": errors}

    user_id = store_user(user_data)

    # 步骤二：构造硬约束与用户表示（式一）
    prof = profile_mod.build_profile(user_id)

    # 步骤三：岗位采集（外部检索结果优先）
    if jobs is not None:
        matching.store_jobs(jobs, user_id=user_id)
    else:
        matching.collect_jobs(user_id=user_id)
    target_jobs = matching.determine_target_jobs(prof)

    # 投递策略：精投只保留 A 级（强匹配），海投保留 B 级以上（去掉 C 级不推荐）
    strategy = user_data.get("l3", {}).get("投递策略", "海投")
    if strategy == "精投":
        target_jobs = [x for x in target_jobs
                       if recommend.match_grade(user_data, x["job"])[0] == "A"]
    else:
        target_jobs = [x for x in target_jobs
                       if recommend.match_grade(user_data, x["job"])[0] in ("A", "B")]

    # 步骤四：建立投递任务（一岗一条）
    task_ids = tasks.create_tasks(user_id, target_jobs)

    # 步骤五：按岗分配经历（式四）+ 受限简历生成
    gen_results = generation.generate_resumes(user_id, prof, task_ids, llm=llm)

    # 写入经历（式四分配后实际纳入简历的经历，供展示）
    included_map = {g["task_id"]: g["included"] for g in gen_results if "included" in g}
    gamma_map = {g["task_id"]: g["gammas"] for g in gen_results if "gammas" in g}
    exp_names = [e.get("名称", "经历%d" % i) for i, e in enumerate(user_data.get("l2", []))]

    # 步骤六：准备投递材料（简历PDF+个性化招呼语，不自动发送）
    report = delivery.prepare_batch(user_id, task_ids, user_data=user_data)

    # 读简历内容（job_field_map，供「简历检查」环节）
    conn = db.get_conn()
    field_maps = {}
    if task_ids:
        field_maps = {r["task_id"]: json.loads(r["fields"]) for r in conn.execute(
            "SELECT * FROM job_field_map WHERE task_id IN (%s)" % ",".join("?" * len(task_ids)),
            task_ids).fetchall()}
    conn.close()

    job_list = []
    for tid, x in zip(task_ids, target_jobs):
        job = x["job"]
        grade, grade_score = recommend.match_grade(user_data, job)
        job_list.append({
            "task_id": tid,
            "job_id": x["job_id"],
            "岗位名称": job.get("岗位名称", ""),
            "单位名称": job.get("单位名称", ""),
            "薪资": job.get("薪资", ""),
            "行业": job.get("行业", ""),
            "学历": job.get("学历", ""),
            "岗位链接": job.get("岗位链接", ""),
            "score": round(x["score"], 4),
            "匹配分构成": {
                "余弦相似度s": round(float(x.get("s", 0)), 4),
                "间隔特征δ": round(float(x.get("delta", 0)), 4),
                "w_s": config.W_S,
                "w_δ": config.W_DELTA if x.get("has_center") else 0,
                "匹配分p": round(float(x["score"]), 4),
            },
            "等级": grade,
            "等级分": grade_score,
            "推荐理由": recommend.recommend_reasons(user_data, job),
            "分数明细": recommend.score_breakdown(user_data, job),
            "简历内容": field_maps.get(tid, {}),
            "写入经历": [exp_names[i] for i in included_map.get(tid, []) if i < len(exp_names)],
            "写入经历索引": included_map.get(tid, []),
            "经历分配": [(exp_names[i], gamma_map.get(tid, [])[i])
                        for i in range(min(len(exp_names), len(gamma_map.get(tid, []))))],
        })

    return {
        "ok": True,
        "user_id": user_id,
        "weights": prof["weights"].tolist(),
        "target_jobs": job_list,
        "task_count": len(task_ids),
        "delivery_report": report,
        "画像摘要": recommend.profile_summary(user_data),
    }


def latest_result():
    """从数据库重建最近一次投递现场（刷新页面 / 重启程序后恢复第⑤⑥阶段用）。

    只读不写：不新建用户、不建任务、不生成简历、不触发投递。
    岗位顺序沿用建任务时的匹配分（`delivery_tasks.match_score` 降序，缺失时按任务号）。
    s / δ 用当前画像与岗位向量**重算**（画像可能已被式五更新），匹配分 p 优先取
    入库时记录的历史值，保证「上次投递时看到的名次」不被反馈悄悄改写。

    返回与 `run_full_pipeline` 同构的 dict；没有历史记录时返回 None。
    """
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM delivery_tasks ORDER BY task_id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        user_id = row["user_id"]
        u = conn.execute("SELECT * FROM user_records WHERE user_id=?", (user_id,)).fetchone()
        if u is None:
            return None
        l0, l1, l3 = json.loads(u["l0"]), json.loads(u["l1"]), json.loads(u["l3"])
        exps = [json.loads(r["fields"]) for r in conn.execute(
            "SELECT fields FROM experience_items WHERE user_id=? ORDER BY exp_index",
            (user_id,))]
        user_data = {"l0": l0, "l1": l1, "l2": exps, "l3": l3}

        task_rows = conn.execute(
            "SELECT * FROM delivery_tasks WHERE user_id=? "
            "ORDER BY COALESCE(match_score, -1) DESC, task_id", (user_id,)).fetchall()
        field_maps = {r["task_id"]: json.loads(r["fields"]) for r in conn.execute(
            "SELECT m.* FROM job_field_map m JOIN delivery_tasks d ON d.task_id=m.task_id "
            "WHERE d.user_id=?", (user_id,))}
        indicators = {r["task_id"]: json.loads(r["indicator"]) for r in conn.execute(
            "SELECT i.* FROM task_indicators i JOIN delivery_tasks d ON d.task_id=i.task_id "
            "WHERE d.user_id=?", (user_id,))}
        job_rows = {}
        for t in task_rows:
            j = conn.execute("SELECT fields, embedding FROM jobs WHERE job_id=?",
                             (t["job_id"],)).fetchone()
            if j is not None:
                job_rows[t["job_id"]] = (json.loads(j["fields"]), j["embedding"])
        center = conn.execute("SELECT c_pos, c_neg FROM job_centers WHERE user_id=?",
                              (user_id,)).fetchone()

    prof = profile_mod.build_profile(user_id)
    has_center = bool(center and center["c_pos"] and center["c_neg"])
    c_pos = np.asarray(json.loads(center["c_pos"])) if has_center else None
    c_neg = np.asarray(json.loads(center["c_neg"])) if has_center else None
    exp_names = [e.get("名称", "经历%d" % i) for i, e in enumerate(exps)]

    job_list, report = [], []
    for t in task_rows:
        job_fields, emb = job_rows.get(t["job_id"], ({}, None))
        jv = np.asarray(json.loads(emb)) if emb else None
        s = formula_2_cosine(prof["user_vec"], jv) if jv is not None else 0.0
        delta = interval_feature(jv, c_pos, c_neg) if (jv is not None and has_center) else 0.0
        if t["match_score"] is not None:
            p = float(t["match_score"])
        else:
            p = float(formula_3_match_score(s, delta, config.W_S, config.W_DELTA, has_center))
        gammas = []
        if jv is not None and prof["K"]:
            gammas, _sims = generation.allocate_experiences(prof, jv, prof["weights"])
        indicator = indicators.get(t["task_id"])
        included = ([i for i, v in enumerate(indicator) if v and i < len(exp_names)]
                    if indicator else [])
        grade, grade_score = recommend.match_grade(user_data, job_fields)
        greet = recommend.personalized_greeting(user_data, job_fields, config.GREETING_TEMPLATE)
        job_list.append({
            "task_id": t["task_id"],
            "job_id": t["job_id"],
            "岗位名称": job_fields.get("岗位名称", t["job_name"] or ""),
            "单位名称": job_fields.get("单位名称", t["unit_name"] or ""),
            "薪资": job_fields.get("薪资", ""),
            "行业": job_fields.get("行业", ""),
            "学历": job_fields.get("学历", ""),
            "岗位链接": job_fields.get("岗位链接", t["job_link"] or ""),
            "score": round(p, 4),
            "匹配分构成": {
                "余弦相似度s": round(float(s), 4),
                "间隔特征δ": round(float(delta), 4),
                "w_s": config.W_S,
                "w_δ": config.W_DELTA if has_center else 0,
                "匹配分p": round(p, 4),
            },
            "等级": grade,
            "等级分": grade_score,
            "推荐理由": recommend.recommend_reasons(user_data, job_fields),
            "分数明细": recommend.score_breakdown(user_data, job_fields),
            "简历内容": field_maps.get(t["task_id"], {}),
            "写入经历": [exp_names[i] for i in included],
            "写入经历索引": included,
            "经历分配": [(exp_names[i], gammas[i])
                        for i in range(min(len(exp_names), len(gammas)))],
        })
        report.append({"task_id": t["task_id"],
                       "岗位": job_list[-1]["岗位名称"],
                       "单位": job_list[-1]["单位名称"],
                       "岗位链接": job_list[-1]["岗位链接"],
                       "状态": t["status"],
                       "招呼语": greet})

    return {
        "ok": True,
        "restored": True,
        "user_id": user_id,
        "weights": prof["weights"].tolist(),
        "target_jobs": job_list,
        "task_count": len(job_list),
        "delivery_report": report,
        "画像摘要": recommend.profile_summary(user_data),
        "user_data": user_data,
    }


def re_match(user_id, user_data, jobs=None):
    """用更新后的画像重新匹配岗位（专利闭环「再画像 → 再匹配」）。

    与 run_full_pipeline 的区别：不重新建任务、不重新生成简历，
    只用式五修正后的经历权重 + 式三的正负岗位中心，对岗位重新打分排序。
    这一步让式三的间隔特征 δ = cos(j,c_+) - cos(j,c_-) 在反馈形成中心后真正生效
    （冷启动无中心时 δ=0，反馈后 δ≠0，匹配分随之闭环进化）。

    返回 list[dict]，每项含 job/job_id/score/s/delta/has_center，供界面展示对比。
    """
    prof = profile_mod.build_profile(user_id)
    if jobs is not None:
        matching.store_jobs(jobs, user_id=user_id)
    target = matching.determine_target_jobs(prof)

    # 投递策略过滤（与 run_full_pipeline 一致）
    strategy = user_data.get("l3", {}).get("投递策略", "海投")
    if strategy == "精投":
        target = [x for x in target if recommend.match_grade(user_data, x["job"])[0] == "A"]
    else:
        target = [x for x in target if recommend.match_grade(user_data, x["job"])[0] in ("A", "B")]
    return target
