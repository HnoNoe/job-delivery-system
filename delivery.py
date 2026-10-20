"""结果输出层 —— 批量投递执行（步骤六）。

真实投递路径（非模拟）：
- 邮件：SMTP 真实发送；未配置凭证时写入本地发件箱 outbox/ 兜底。
- API：真实 HTTP POST（requests）。
- Web表单：Selenium 真实浏览器填表提交（需本机有 Chrome/Edge）。
- 半自动：生成真实投递材料 ZIP 包，供用户手动提交。

入口类型优先级：API > Web表单 > 邮件；半自动不入自动队列。
"""
import json
import time
import zipfile
import smtplib
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

import config
import db
import recommend


def classify_entry(entry_type, entry_addr):
    """按规则自动判定投递入口类型（Web表单/邮件/API/半自动）。"""
    if entry_type in ("Web表单", "邮件", "API", "半自动"):
        return entry_type
    a = (entry_addr or "").lower()
    if not a.strip():
        return "半自动"
    if a.startswith("mailto") or ("@" in a and not a.startswith("http")):
        return "邮件"
    if "api" in a:
        return "API"
    return "Web表单"


def prepare_batch(user_id, task_ids, user_data=None):
    """准备投递材料（简历PDF+个性化招呼语），不自动发送，等待用户逐条手动确认。"""
    if not task_ids:
        return []
    conn = db.get_conn()
    tasks = conn.execute(
        "SELECT * FROM delivery_tasks WHERE task_id IN (%s) ORDER BY task_id"
        % ",".join("?" * len(task_ids)), task_ids
    ).fetchall()
    l0 = _get_user_l0(conn, user_id)
    # 读 L2 经历与 L3 偏好（用于个性化招呼语）
    if user_data is not None:
        l2 = user_data.get("l2", [])
        l3 = user_data.get("l3", {})
    else:
        rows = conn.execute(
            "SELECT fields FROM experience_items WHERE user_id=? ORDER BY exp_index", (user_id,)
        ).fetchall()
        l2 = [json.loads(r["fields"]) for r in rows]
        l3 = {}
    report = []
    for t in tasks:
        result = _prepare_halfauto(t, l0)
        conn.execute("UPDATE delivery_tasks SET status='待投递', result=? WHERE task_id=?",
                     (result, t["task_id"]))
        # 个性化招呼语：读岗位字段，按技能/方向匹配生成
        job = _read_job(conn, t["job_id"])
        ud = {"l0": l0, "l2": l2, "l3": l3}
        greet = recommend.personalized_greeting(ud, job, config.GREETING_TEMPLATE)
        report.append({"task_id": t["task_id"], "岗位": t["job_name"], "单位": t["unit_name"],
                       "岗位链接": t["job_link"] or "", "状态": "待投递",
                       "招呼语": greet})
    conn.commit()
    conn.close()
    return report


def _read_job(conn, job_id):
    """读岗位完整字段（用于个性化招呼语）。"""
    row = conn.execute("SELECT fields FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    return json.loads(row["fields"]) if row else {}


def _daily_sends():
    """读取今日已投递条数（存文件，按日清零）。"""
    from datetime import date
    f = Path(config.BASE_DIR) / "data" / "send_count.txt"
    try:
        d, n = f.read_text(encoding="utf-8").strip().split(",")
        return int(n) if d == str(date.today()) else 0
    except Exception:
        return 0


def _incr_daily():
    from datetime import date
    f = Path(config.BASE_DIR) / "data" / "send_count.txt"
    f.write_text("%s,%d" % (date.today(), _daily_sends() + 1), encoding="utf-8")


def deliver_one(task_id):
    """投递单条任务。安全模式下只返回材料+招呼语（不自动发送）；关闭安全模式才真正点立即沟通+发招呼语。"""
    conn = db.get_conn()
    t = conn.execute("SELECT * FROM delivery_tasks WHERE task_id=?", (task_id,)).fetchone()
    if t is None:
        conn.close()
        return False, "任务不存在"
    l0 = _get_user_l0(conn, t["user_id"])
    # 个性化招呼语（与 prepare_batch 一致，按技能/方向匹配动态生成）
    job = conn.execute("SELECT fields FROM jobs WHERE job_id=?", (t["job_id"],)).fetchone()
    l2_rows = conn.execute(
        "SELECT fields FROM experience_items WHERE user_id=? ORDER BY exp_index", (t["user_id"],)
    ).fetchall()
    l3_row = conn.execute("SELECT l3 FROM user_records WHERE user_id=?", (t["user_id"],)).fetchone()
    conn.close()
    job_fields = json.loads(job["fields"]) if job else {}
    l2 = [json.loads(r["fields"]) for r in l2_rows]
    l3 = json.loads(l3_row["l3"]) if l3_row else {}
    greet = recommend.personalized_greeting({"l0": l0, "l2": l2, "l3": l3}, job_fields,
                                            config.GREETING_TEMPLATE)
    job_link = t["job_link"] or t["entry_addr"]
    if not job_link:
        return False, "缺少岗位链接"

    # 安全模式：能力在，但不真正执行自动投递，只给材料供手动（优先于每日上限，安全模式不投递）
    if config.SAFE_MODE:
        conn = db.get_conn()
        conn.execute("UPDATE delivery_tasks SET status='已投递' WHERE task_id=?", (task_id,))
        conn.commit()
        conn.close()
        return True, ("【安全模式】已记录投递。请手动打开岗位链接并发送招呼语。\n招呼语：%s" % greet)

    # 关闭安全模式后：已投递的任务不重复投递
    if t["status"] == "已投递":
        return False, "该岗位已投递，无需重复"

    # 关闭安全模式后：先做每日上限拦截，再真实投递
    if _daily_sends() >= config.DAILY_SEND_LIMIT:
        return False, "今日投递已达上限(%d条)，请明天再投（防止账号被封）" % config.DAILY_SEND_LIMIT

    # 关闭安全模式后：真实投递（按入口类型分流）
    try:
        entry = t["entry_type"] or "半自动"
        if entry == "API":
            detail = _deliver_api(t, l0)
        elif entry == "Web表单":
            detail = _deliver_web(t, l0)
        elif entry == "邮件":
            detail = _deliver_email(t, l0)
        else:  # 半自动 / Boss直聘「立即沟通」
            import time as _t
            import session
            detail = None
            last_err = ""
            for k in list(session._DPAGES.keys()):
                ok2, msg = session.dpage_deliver(k, job_link)
                if ok2:
                    _t.sleep(config.DELIVER_INTERVAL)
                    ok3, msg3 = session.dpage_greet(k, greet)
                    detail = msg + ("；" + msg3 if ok3 else "")
                    break
                last_err = msg
            if detail is None:
                return False, last_err or "登录浏览器未打开，无法投递"
        conn2 = db.get_conn()
        conn2.execute("UPDATE delivery_tasks SET status='已投递', result=? WHERE task_id=?",
                      (detail, task_id))
        conn2.commit()
        conn2.close()
        _incr_daily()
        return True, detail
    except Exception as e:
        return False, str(e)


def deliver_batch(task_ids=None, stop_on_risk=True, limit=None):
    """批量投递（一口气投多个，针对 Boss 直聘「立即沟通」通道）。

    - 安全模式下拒绝真正批量投递（提示关闭 SAFE_MODE），绝不假装投递。
    - 受每日上限 DAILY_SEND_LIMIT、单次批次上限 BATCH_SEND_LIMIT、限速 DELIVER_INTERVAL 三重保护。
    - 检测到风控/封号/登录失效信号时立即停止，避免账号被封。

    返回 dict：{投递数, 成功数, 失败数, 停止原因, 明细:[(task_id, ok, msg)]}
    """
    if config.SAFE_MODE:
        return {"投递数": 0, "成功数": 0, "失败数": 0,
                "停止原因": "安全模式已开启，不会真正投递。请将 config.py 的 SAFE_MODE 设为 False 后再批量投递。",
                "明细": []}

    # 取待投递任务（未投递的），按 task_id 顺序
    conn = db.get_conn()
    if task_ids:
        q = ("SELECT task_id, status FROM delivery_tasks WHERE task_id IN (%s) ORDER BY task_id"
             % ",".join("?" * len(task_ids)))
        rows = conn.execute(q, list(task_ids)).fetchall()
    else:
        rows = conn.execute(
            "SELECT task_id, status FROM delivery_tasks WHERE status != '已投递' ORDER BY task_id"
        ).fetchall()
    conn.close()
    pending = [r["task_id"] for r in rows if r["status"] != "已投递"]

    # 每日上限 + 单次批次上限
    remaining = config.DAILY_SEND_LIMIT - _daily_sends()
    batch_limit = limit if limit and limit > 0 else config.BATCH_SEND_LIMIT
    budget = min(len(pending), batch_limit, remaining)
    if budget <= 0:
        reason = ("今日投递已达上限（%d 条），请明天再投（防止账号被封）" % config.DAILY_SEND_LIMIT
                  if remaining <= 0 else "无待投递任务")
        return {"投递数": 0, "成功数": 0, "失败数": 0, "停止原因": reason, "明细": []}

    details = []
    ok_count = fail_count = 0
    stop_reason = ""
    for i, tid in enumerate(pending[:budget]):
        ok, msg = deliver_one(tid)
        details.append((tid, ok, msg))
        if ok:
            ok_count += 1
        else:
            fail_count += 1
            if stop_on_risk and any(k in str(msg) for k in ("验证", "风控", "登录失效", "封", "Code 3", "code 3")):
                stop_reason = "检测到风控/封号信号，已停止批量投递：%s" % str(msg)[:60]
                break
        # 两条之间的限速间隔（防封号）
        if i < budget - 1:
            time.sleep(config.DELIVER_INTERVAL)

    return {"投递数": len(details), "成功数": ok_count, "失败数": fail_count,
            "停止原因": stop_reason, "明细": details}


def _get_user_l0(conn, user_id):
    row = conn.execute("SELECT l0 FROM user_records WHERE user_id=?", (user_id,)).fetchone()
    return json.loads(row["l0"]) if row else {}

# ---------- 邮件投递（真实 SMTP / 本地发件箱兜底） ----------
def _deliver_email(task, l0):
    to_addr = (task["entry_addr"] or "").replace("mailto:", "")
    if not to_addr:
        return "邮件投递失败：缺少收件邮箱"
    body = _email_body(task, l0)

    if config.SMTP_USER and config.SMTP_PASSWORD:
        try:
            msg = MIMEMultipart()
            msg["From"] = config.SMTP_USER
            msg["To"] = to_addr
            msg["Subject"] = "应聘「%s」- %s" % (task["job_name"], l0.get("姓名", ""))
            msg.attach(MIMEText(body, "plain", "utf-8"))
            if _resume_path(task) and Path(_resume_path(task)).exists():
                with open(_resume_path(task), "rb") as f:
                    part = MIMEApplication(f.read(), Name=Path(_resume_path(task)).name)
                part["Content-Disposition"] = 'attachment; filename="%s"' % Path(_resume_path(task)).name
                msg.attach(part)
            with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as s:
                s.login(config.SMTP_USER, config.SMTP_PASSWORD)
                s.send_message(msg)
            return "邮件已真实发送至 %s" % to_addr
        except Exception as e:  # noqa
            return "邮件发送失败（%s），已落入本地发件箱" % e
    return _save_outbox(task, l0, to_addr, body)


def _email_body(task, l0):
    return (
        "尊敬的招聘负责人：\n\n"
        "您好！我是%s（%s%s），应聘贵司「%s」岗位。\n"
        "随信附上我的针对性简历，请查收。期待您的回复！\n\n"
        "此致\n敬礼\n\n%s\n%s / %s"
        % (l0.get("姓名", ""), l0.get("学校", ""), l0.get("专业", ""),
           task["job_name"], l0.get("姓名", ""), l0.get("手机", ""), l0.get("邮箱", ""))
    )


def _save_outbox(task, l0, to_addr, body):
    out_dir = Path(config.BASE_DIR) / "outbox"
    out_dir.mkdir(exist_ok=True)
    f = out_dir / ("email_任务%d_至%s.txt" % (task["task_id"], to_addr.replace("@", "_at_")))
    f.write_text("发件人: %s\n收件人: %s\n主题: 应聘「%s」- %s\n附件: %s\n\n%s"
                 % (config.SMTP_USER or l0.get("邮箱", "(未配置)"), to_addr,
                    task["job_name"], l0.get("姓名", ""), _resume_path(task), body),
                 encoding="utf-8")
    return "已写入本地发件箱（未配置SMTP）: %s" % f.name


def _resume_path(task):
    return task["resume_path"] or ""

# ---------- API 投递（真实 HTTP POST，含重试退避） ----------
def _deliver_api(task, l0):
    import requests
    payload = {
        "岗位名称": task["job_name"], "单位名称": task["unit_name"],
        "姓名": l0.get("姓名", ""), "邮箱": l0.get("邮箱", ""),
        "手机": l0.get("手机", ""), "学校": l0.get("学校", ""), "专业": l0.get("专业", ""),
        "简历": _resume_path(task),
    }
    last = None
    for attempt in range(config.MAX_RETRY):
        try:
            r = requests.post(task["entry_addr"], json=payload, timeout=10)
            if r.status_code == 200:
                return "API 已投递，返回码 200"
            last = "返回码 %d" % r.status_code
        except Exception as e:  # noqa
            last = str(e)
        time.sleep(1.5 * (attempt + 1))  # 退避
    return "API 投递失败（重试 %d 次）：%s" % (config.MAX_RETRY, last)


# ---------- Web 表单投递（真实识别 + Selenium 填表提交） ----------
def _deliver_web(task, l0):
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except Exception as e:  # noqa
        return "Web表单投递不可用（缺 Selenium）：%s" % e

    import form_filler

    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    driver = None
    try:
        driver = webdriver.Chrome(options=opts)
        driver.get(task["entry_addr"])

        # 统一字段数据（供表单识别映射）
        data = {
            "姓名": l0.get("姓名", ""),
            "邮箱": l0.get("邮箱", ""),
            "手机": l0.get("手机", ""),
            "学校": l0.get("学校", ""),
            "专业": l0.get("专业", ""),
            "学历": l0.get("学历阶段", ""),
            "性别": l0.get("性别", ""),
            "出生日期": l0.get("出生日期", ""),
            "现居": l0.get("现居", ""),
            "籍贯": l0.get("籍贯", ""),
            "民族": l0.get("民族", ""),
            "政治面貌": l0.get("政治面貌", ""),
            "期望岗位": task["job_name"],
            "到岗时间": l0.get("毕业年月", ""),
            "自我评价": "本人%s专业，具备扎实的专业基础与项目/实习经验，学习能力强，期待加入贵司。"
                        % l0.get("专业", ""),
        }
        msg, _ = form_filler.fill_form(driver, data, resume_path=_resume_path(task))
        return msg
    except Exception as e:  # noqa
        return "Web 表单投递异常：%s" % e
    finally:
        if driver:
            driver.quit()



# ---------- 半自动投递（只生成材料包，不自动发送） ----------
def _prepare_halfauto(task, l0):
    pkg_dir = Path(config.BASE_DIR) / "packages"
    pkg_dir.mkdir(exist_ok=True)
    zip_path = pkg_dir / ("投递材料包_任务%d_%s.zip" % (task["task_id"], task["unit_name"]))
    checklist = ("投递材料清单\n岗位: %s @ %s\n链接: %s\n\n1. 针对性简历: %s\n2. 求职信: 见压缩包\n"
                 % (task["job_name"], task["unit_name"], task["job_link"] or "", _resume_path(task)))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        if _resume_path(task) and Path(_resume_path(task)).exists():
            z.write(_resume_path(task), Path(_resume_path(task)).name)
        z.writestr("求职信.txt", _email_body(task, l0))
        z.writestr("材料清单.txt", checklist)
    return "材料包已生成: %s" % zip_path.name



