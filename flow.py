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
    """打开指定平台登录页（真实浏览器，用户扫码/输密码）。

    真实平台：用用户自己的浏览器打开（webbrowser），不弹受控窗口——
    BOSS 直聘等平台会检测 Selenium 并弹走登录页，用户日常浏览器无此问题。
    登录完成后由 finish_login 从本机浏览器 cookie 库读出登录态。
    mock 平台保留受控浏览器流程（本地测试站，需要模拟扫码）。
    """
    if platform_key != "mock":
        import grab_login
        return grab_login.open_in_user_browser(platform_key)
    session.open_login(platform_key, headless=headless)
    return True, "已打开登录窗口，完成扫码后回来点「完成登录」"


def finish_login(platform_key):
    """用户完成登录后调用：保存会话并返回登录态。

    真实平台：从本机浏览器（Edge/Chrome）cookie 库抓取该平台 cookie 存盘。
    mock：沿用受控浏览器检测。
    """
    if platform_key != "mock":
        import grab_login
        from urllib.parse import urlparse
        host = urlparse((platforms.get(platform_key) or {}).get("login_url", "")).hostname or ""
        domain = ".".join(host.split(".")[-2:]) if host else ""
        cookies, err = grab_login.grab_cookies(domain)
        if not cookies:
            hint = ""
            if not grab_login.is_admin():
                hint = "（Edge/Chrome 新版加密需要管理员权限：请右键本程序→以管理员身份运行，再点一次「完成登录」）"
            return False, "没能从本机浏览器读到 %s 的登录态：%s%s" % (platform_key, err, hint)
        n = session.save_cookies(platform_key, cookies)
        st = login_status.check_platform(platform_key, online=False)
        return True, "已保存 %d 个 cookie，登录态：%s（若显示未登录，请确认在浏览器里登录成功）" % (n, st.get("state", "未知"))
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
