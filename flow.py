"""投递工作台流程控制器 —— 无头可测的完整投递流程内核。

桌面端「投递工作台」页只负责调用本模块；本模块串起原有引擎：
登录态 → 检索(loop) → 核检+画像+匹配+建任务+生成材料(pipeline) →
逐条/批量投递(delivery) → 反馈回写(feedback, 式五)。

全部读写都在本地 SQLite（默认后端）；需要账号/共享时由上层显式 use_cloud。
"""
import json

import config
import db
import delivery
import feedback
import login_status
import loop
import pipeline
import platforms
import session
import tasks


def available_platforms(include_mock=True):
    """平台注册表：[{key, name, domain}]；mock 仅测试用。"""
    out = []
    for k, p in platforms.PLATFORMS.items() if hasattr(platforms, "PLATFORMS") else []:
        out.append({"key": k, "name": p.get("name", k), "domain": p.get("domain", "")})
    if not out:  # platforms.get 是统一入口时兜底
        for k in ("boss", "zhilian", "liepin", "job51", "lagou", "mock"):
            p = platforms.get(k)
            if p:
                out.append({"key": k, "name": p.get("name", k), "domain": p.get("domain", "")})
    if not include_mock:
        out = [x for x in out if x["key"] != "mock"]
    return out


def login_states(online=False):
    """各平台登录态：{key: {name, state, label, detail}}。online=True 做联网探活（慢）。"""
    keys = [p["key"] for p in available_platforms()]
    raw = {s["key"]: s for s in login_status.check_all(online=online)}
    out = {}
    for k in keys:
        st = raw.get(k) or {}
        p = platforms.get(k) or {}
        out[k] = {"name": p.get("name", k),
                  "state": st.get("state", "未知"),
                  "label": st.get("label", ""),
                  "detail": st.get("detail", "")}
    return out


def start_login(platform_key, headless=False):
    """打开指定平台登录浏览器窗口（真实浏览器，用户扫码/输密码）。

    用 open_login：driver 由 session.ACTIVE_DRIVERS 持有，
    否则函数返回后 driver 被回收，浏览器窗口会直接关闭。
    """
    session.open_login(platform_key, headless=headless)


def finish_login(platform_key):
    """用户完成登录后调用：保存会话并返回登录态。"""
    ok = session.finish_login(platform_key)
    st = login_status.check_platform(platform_key, online=False)
    return ok, st.get("state", "未知")


def cancel_login(platform_key):
    try:
        session.close_login(platform_key)
    except Exception:
        pass


def search(user_data, platform_keys, keyword, pages=2):
    """在已登录平台检索岗位。返回 (jobs, logs)。"""
    city = ((user_data.get("l3") or {}).get("意向城市", "北京") or "北京").replace("，", ",").split(",")[0].strip()
    return loop.search_logged_in_platforms(platform_keys, keyword, city=city, pages=int(pages))


def run_pipeline(user_data, jobs):
    """核检→画像→匹配→建任务→生成简历→准备材料。返回 pipeline 结果 dict。"""
    return loop.run_closed_loop(user_data, jobs=jobs)


def restore_scene():
    """恢复本地最近一次的投递现场（重启后接着用）。"""
    return pipeline.latest_result()


def list_tasks(user_id):
    """任务总表：tasks.list_tasks 的 JSON 安全版。"""
    return tasks.list_tasks(user_id)


def task_detail(task_id):
    """单任务详情：岗位字段 + 简历内容（job_field_map）+ 招呼语预览。"""
    conn = db.get_conn()
    t = conn.execute("SELECT * FROM delivery_tasks WHERE task_id=?", (task_id,)).fetchone()
    if t is None:
        conn.close()
        return None
    d = {k: t[k] for k in t.keys()} if hasattr(t, "keys") else dict(t)
    fm = conn.execute("SELECT fields FROM job_field_map WHERE task_id=?", (task_id,)).fetchone()
    d["简历内容"] = json.loads(fm["fields"]) if fm else {}
    # 招呼语预览（安全模式 deliver_one 会再算一次；这里只读展示用）
    try:
        import recommend
        job = conn.execute("SELECT fields FROM jobs WHERE job_id=?", (d["job_id"],)).fetchone()
        job_fields = json.loads(job["fields"]) if job else {}
        l2_rows = conn.execute(
            "SELECT fields FROM experience_items WHERE user_id=? ORDER BY exp_index",
            (d["user_id"],)).fetchall()
        rec = conn.execute("SELECT l0, l3 FROM user_records WHERE user_id=?",
                           (d["user_id"],)).fetchone()
        l0 = json.loads(rec["l0"]) if rec and rec["l0"] else {}
        l2 = [json.loads(r["fields"]) for r in l2_rows]
        l3 = json.loads(rec["l3"]) if rec and rec["l3"] else {}
        d["招呼语"] = recommend.personalized_greeting({"l0": l0, "l2": l2, "l3": l3},
                                                      job_fields, config.GREETING_TEMPLATE)
    except Exception:
        d["招呼语"] = ""
    finally:
        conn.close()
    return d


def deliver_one(task_id):
    """单条投递（安全模式返回材料+招呼语，不真实发送）。"""
    return delivery.deliver_one(task_id)


def deliver_batch(task_ids=None, all_pending=False):
    """批量投递（受 SAFE_MODE/每日上限/批次上限/风控停止保护）。"""
    return delivery.deliver_batch(task_ids=task_ids, all_pending=all_pending)


def confirm_manual(task_id):
    """用户手动在平台完成投递后确认登记。"""
    return delivery.record_manual_delivery(task_id)


def mark_feedback(task_id, result):
    """标注投递结果：进面试/不合适/无回复/其他 → 式五回写权重。"""
    ok, msg = feedback.mark_result(task_id, result)
    out = {"ok": ok, "msg": msg}
    if ok:
        t = db.get_conn().execute("SELECT user_id FROM delivery_tasks WHERE task_id=?",
                                  (task_id,)).fetchone()
        uid = t["user_id"] if t else None
        if uid is not None:
            out["stats"] = feedback.get_stats(uid)
            out["evolution"] = feedback.get_profile_evolution(uid)
    return out


def profile_stats(user_id):
    return {"stats": feedback.get_stats(user_id),
            "evolution": feedback.get_profile_evolution(user_id),
            "quality": feedback.get_quality(user_id) if hasattr(feedback, "get_quality") else None}


def safe_mode():
    return bool(config.SAFE_MODE)


def user_data_of(user_id=None):
    """本地最近确认的用户数据（pipeline.latest_user_data）。"""
    return pipeline.latest_user_data()
