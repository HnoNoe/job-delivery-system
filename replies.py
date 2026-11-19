"""HR 回复检查（方案 B：手动触发、只读会话列表）。

设计原则：
- **只读**：只打开/读取消息页与会话列表，不发送任何内容、不点「立即沟通」；
- **手动触发**：由用户在第⑥阶段点「检查新回复」跑一次，不做后台常驻轮询（风控/合规）；
- **不猜测结果**：接口结构可能随平台改版变化，拿不到结构化数据时如实返回“未识别”，
  并把原始样本写到 `data/chat_probe_<平台>.json`，便于对照平台改版调整字段映射；
- **落库分离**：识别结果只是“候选”，由用户勾选后才写入 `hr_responses`（source='auto'）。
"""
import json
import re
import threading
import time
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import config
import platforms
import responses
import session

# 会话记录的统一字段
FIELDS = ("单位名称", "岗位名称", "HR", "最后消息", "时间", "未读")

# 消息文本 -> 回应类型（顺序即优先级：明确邀面 > 明确拒绝 > 要资料 > 待定 > 已查看）
KIND_PATTERNS = (
    # 明确约面试：必须有“面试”或明确的面试形式/时间
    ("邀面试", ("面试", "面谈", "约面", "终面", "初面", "二面", "三面", "视频面",
                "电话面", "面试时间", "什么时候方便面试", "安排面试")),
    # 愿意线上沟通（还没有约面试）
    ("线上交流邀请", ("聊一聊", "聊聊", "聊下", "沟通一下", "沟通下", "方便吗",
                     "方便聊聊", "在线聊", "私聊", "加个微信", "加微信", "可以聊",
                     "电话沟通", "电话聊")),
    ("不合适", ("不合适", "不太合适", "暂不考虑", "已招满", "招满了", "招到人", "不匹配",
                "不招", "已停止招聘", "岗位关闭", "抱歉", "遗憾", "暂不")),
    ("需补充资料", ("简历附件", "作品集", "成绩单", "学历证明", "补充", "发我一份",
                    "提供一下", "发份简历", "个人作品", "项目链接", "在线简历链接")),
    ("待定", ("稍后回复", "晚点回复", "考虑一下", "再看看", "待定", "内部评估",
              "评估中", "有消息通知", "等通知")),
    ("已查看", ("已查看", "查看了你的", "已读", "已阅")),
)

# 自动检查时可以直接落库的类型（「其他/已查看」不入库，避免噪音）
AUTO_KINDS = ("邀面试", "线上交流邀请", "不合适", "需补充资料", "待定")

# 通用结构提取用的字段别名（真实平台字段名会变，尽量宽松）
_COMPANY_KEYS = ("brandname", "companyname", "company", "companyfullname", "company_name",
                 "单位名称", "公司", "公司名称")
_JOB_KEYS = ("jobname", "positionname", "position", "job", "jobtitle",
             "岗位名称", "岗位", "职位")
_MSG_KEYS = ("lastmessage", "lastmsg", "lastcontent", "lasttext", "content", "message",
             "text", "msg", "最后消息")
_TIME_KEYS = ("lasttime", "lasttimestamp", "time", "timestamp", "updatetime", "时间")
_UNREAD_KEYS = ("unread", "unreadcount", "未读")

MATCH_THRESHOLD = 0.45

# 我方发出的招呼语特征：会话列表里「最后一条是我发的」不算 HR 回复
SELF_MARKERS = ("你已发送招呼语", "简历已发", "已发送简历", "已投递简历")


def is_self_message(text):
    """判断会话最后一条是不是我们自己发的（避免把招呼语当成 HR 回复）。"""
    t = str(text or "")
    return any(m in t for m in SELF_MARKERS)


def _norm(text):
    """归一化：小写、去掉空白与常见标点，便于“公司名/岗位名”比较。"""
    return re.sub(r"[\s\-_·•,，。;；:：/\\|()（）\[\]【】]+", "", str(text or "").lower())


def classify(text):
    """按关键词把消息文本归到回应类型；识别不出返回「其他」。"""
    t = str(text or "")
    if not t.strip():
        return "其他"
    for kind, words in KIND_PATTERNS:
        if any(w in t for w in words):
            return kind
    return "其他"


def _pick(d, keys):
    low = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        if k in low and low[k] not in (None, ""):
            return low[k]
    return ""


def _walk(obj, out, depth=0):
    """深度遍历 JSON，挑出“像会话”的 dict（有消息文本 + 公司/岗位之一）。"""
    if depth > 8:
        return
    if isinstance(obj, dict):
        msg = _pick(obj, _MSG_KEYS)
        company = _pick(obj, _COMPANY_KEYS)
        job = _pick(obj, _JOB_KEYS)
        if isinstance(msg, str) and msg.strip() and (company or job):
            out.append({
                "单位名称": str(company or "").strip(),
                "岗位名称": str(job or "").strip(),
                "HR": str(_pick(obj, ("bossname", "hrname", "boss", "hr")) or "").strip(),
                "最后消息": msg.strip(),
                "时间": str(_pick(obj, _TIME_KEYS) or "").strip(),
                "未读": _pick(obj, _UNREAD_KEYS),
            })
        for v in obj.values():
            _walk(v, out, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, out, depth + 1)


def extract_conversations(payloads):
    """从接口响应里提取会话记录（真实平台用；结构未知时尽力而为）。"""
    out = []
    for payload in payloads or []:
        if isinstance(payload, (str, bytes)):
            try:
                payload = json.loads(payload)
            except Exception:
                continue
        _walk(payload, out)
    return _dedupe(out)


def records_from_api(payload, field_map, path=""):
    """按平台配置的路径/字段映射取会话（Mock 站等结构稳定的接口走这里）。"""
    from crawler import _dig
    items = _dig(payload, path) if path else payload
    if isinstance(items, dict):
        items = list(items.values())
    out = []
    for item in (items or []):
        if not isinstance(item, dict):
            continue
        rec = {}
        for std, src in (field_map or {}).items():
            val = _dig(item, src) if src else ""
            rec[std] = val
        if not (rec.get("单位名称") or rec.get("岗位名称")):
            continue
        rec = {f: ("" if rec.get(f) is None else rec.get(f)) for f in FIELDS}
        if str(rec.get("最后消息") or "").strip():
            out.append(rec)
    return _dedupe(out)


def records_from_dom(texts, tasks=None):
    """DOM 兜底：会话列表每条文本当作一条记录（消息 = 整段文本）。

    结构未知，所以只保留原文；若给了任务列表，就从文本里反查公司名/岗位名，
    让匹配至少能对上——识别结果仍由用户确认。
    """
    out = []
    norms = [(_norm(t.get("unit_name")), t.get("unit_name") or "",
              _norm(t.get("job_name")), t.get("job_name") or "") for t in (tasks or [])]
    for text in texts or []:
        text = str(text or "").strip()
        if not text:
            continue
        rec = {"单位名称": "", "岗位名称": "", "HR": "",
               "最后消息": text[:300], "时间": "", "未读": ""}
        ntext = _norm(text)
        for nu, unit, nj, job in norms:
            if not rec["单位名称"] and nu and nu in ntext:
                rec["单位名称"] = unit
            if not rec["岗位名称"] and nj and nj in ntext:
                rec["岗位名称"] = job
        out.append(rec)
    return _dedupe(out)


def _dedupe(records):
    seen, out = set(), []
    for rec in records:
        key = (_norm(rec.get("单位名称")), _norm(rec.get("岗位名称")),
               _norm(rec.get("最后消息"))[:80])
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


def _similar(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    return SequenceMatcher(None, a, b).ratio()


def match_record(rec, tasks):
    """把单条会话匹配到任务，返回 (task, score)。"""
    best, best_score = None, 0.0
    for t in tasks:
        unit_s = _similar(rec.get("单位名称"), t.get("unit_name"))
        job_s = _similar(rec.get("岗位名称"), t.get("job_name"))
        score = 0.7 * unit_s + 0.3 * job_s if (rec.get("单位名称") or rec.get("岗位名称")) else 0.0
        if score > best_score:
            best, best_score = t, score
    return best, best_score


def match_tasks(records, tasks):
    """把会话记录匹配到投递任务（单位名权重 0.7、岗位名 0.3），返回候选列表。"""
    candidates = []
    for rec in records:
        if is_self_message(rec.get("最后消息")):
            continue  # 最后一条是我方招呼语 => 还没有 HR 回复
        best, best_score = match_record(rec, tasks)
        if best is None or best_score < MATCH_THRESHOLD:
            continue
        candidates.append({
            "task_id": best["task_id"],
            "岗位": best.get("job_name") or "",
            "单位": best.get("unit_name") or "",
            "会话岗位": rec.get("岗位名称") or "",
            "会话单位": rec.get("单位名称") or "",
            "最后消息": rec.get("最后消息") or "",
            "时间": rec.get("时间") or "",
            "建议类型": classify(rec.get("最后消息")),
            "匹配度": round(best_score, 2),
        })
    return candidates


def unmatched_records(records, tasks):
    """没有匹配到投递任务的会话（只读展示，避免“读到了却看不到”）。"""
    out = []
    for rec in records:
        if is_self_message(rec.get("最后消息")):
            continue
        _task, score = match_record(rec, tasks)
        if score >= MATCH_THRESHOLD:
            continue
        out.append({
            "单位": rec.get("单位名称") or "",
            "岗位": rec.get("岗位名称") or "",
            "HR": rec.get("HR") or "",
            "最后消息": rec.get("最后消息") or "",
            "时间": rec.get("时间") or "",
            "建议类型": classify(rec.get("最后消息")),
            "匹配度": round(score, 2),
        })
    return out


def _fetch_api(platform_key, url, timeout=15):
    """用已保存的 cookie 直接取会话接口（Mock 站/有稳定 JSON 的平台）。"""
    import requests
    from crawler import DEFAULT_HEADERS
    cookies = session.load_session(platform_key) or []
    cookie_dict = {c["name"]: c["value"] for c in cookies if c.get("value")}
    r = requests.get(url, cookies=cookie_dict, headers=DEFAULT_HEADERS, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError("会话接口返回 HTTP %d" % r.status_code)
    return r.json()


_CAPTURE_LOCK = threading.Lock()


def check(platform_key, tasks, timeout=12):
    """执行一次“检查新回复”（串行化：自动检查与手动检查不能并发开浏览器）。"""
    if not _CAPTURE_LOCK.acquire(timeout=120):
        return {"ok": False, "error": "另一个回复检查正在进行，请稍后重试",
                "records": [], "candidates": [], "unmatched": [], "debug": [], "probe": None}
    try:
        return _check_impl(platform_key, tasks, timeout=timeout)
    finally:
        _CAPTURE_LOCK.release()


def _check_impl(platform_key, tasks, timeout=12):
    """执行一次“检查新回复”。返回 dict：

    {ok, error, records, candidates, debug, probe}
    - records: 解析出的会话记录；candidates: 匹配到任务且超过阈值的候选
    """
    p = platforms.get(platform_key) or {}
    result = {"ok": False, "error": "", "records": [], "candidates": [],
              "debug": [], "probe": None}
    if not p:
        result["error"] = "未知平台"
        return result
    payloads, dom_items = [], []
    capture_ok = False
    if p.get("chat_api_url"):
        try:
            payload = _fetch_api(platform_key, p["chat_api_url"])
        except Exception as exc:
            result["error"] = "读取会话接口失败：%s" % exc
            return result
        capture_ok = True
        result["debug"].append("接口：%s" % p["chat_api_url"])
        result["records"] = records_from_api(
            payload, p.get("chat_field_map"), p.get("chat_jobs_path", ""))
    else:
        ok, payloads, dom_items, debug = session.chat_capture(
            platform_key, timeout=timeout, wait=p.get("chat_wait"))
        capture_ok = bool(ok)
        result["debug"].extend(debug)
        # DOM 结构化结果优先（Boss 的消息列表走 WebSocket，HTTP 旁听拿不到）
        dom_dicts = [d for d in dom_items if isinstance(d, dict)]
        dom_texts = [d for d in dom_items if isinstance(d, str)]
        if dom_dicts:
            result["records"] = _dedupe(
                [{f: (d.get(f, "") if d.get(f) is not None else "") for f in FIELDS}
                 for d in dom_dicts])
        if not result["records"]:
            result["records"] = extract_conversations(payloads)
        if not result["records"]:
            result["records"] = records_from_dom(dom_texts, tasks)
        if not ok:
            result["error"] = debug[-1] if debug else "读取消息页失败"

    if not result["records"] and (payloads or dom_items):
        # 拿不到结构化结果：落盘原始样本，方便按平台改版调整字段
        try:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            probe = Path(config.DATA_DIR) / ("chat_probe_%s.json" % platform_key)
            probe.write_text(json.dumps(
                {"payloads": payloads[:5], "dom": dom_items[:50]},
                ensure_ascii=False, indent=2), encoding="utf-8")
            result["probe"] = str(probe)
        except Exception:
            pass

    result["candidates"] = match_tasks(result["records"], tasks)
    result["unmatched"] = unmatched_records(result["records"], tasks)
    result["inbox_added"] = store_inbox(result["records"], tasks, platform_key)
    reclassify_inbox()
    result["ok"] = capture_ok
    return result


def register(candidates, platform_key=""):
    """把用户勾选的候选写入 hr_responses（source='auto'）。返回 (新增数, 重复数, 明细)。"""
    added, dup, details = 0, 0, []
    for c in candidates or []:
        ok, msg, _rid = responses.add_response(
            c["task_id"], c.get("建议类型") or "其他",
            c.get("最后消息", ""), source="auto", platform=platform_key)
        if ok:
            added += 1
        else:
            dup += 1
        details.append((c.get("task_id"), ok, msg))
    return added, dup, details


# ---------------- 启动时自动检查（冷却期控制） ----------------
_STATE_READY = False


def _ensure_tables():
    """首次写入前确保 app_state / hr_inbox 表存在（命令行/测试直接调用也安全）。"""
    global _STATE_READY
    if _STATE_READY:
        return
    try:
        import db
        db.init_db()
        _STATE_READY = True
    except Exception:
        pass


def _state_get(key):
    _ensure_tables()
    try:
        import db
        with db.get_conn() as conn:
            row = conn.execute("SELECT value FROM app_state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None
    except Exception:
        return None


def _state_set(key, value):
    _ensure_tables()
    try:
        import db
        with db.get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO app_state (key, value, updated_at) VALUES (?,?,?)",
                         (key, value, time.strftime("%Y-%m-%d %H:%M:%S")))
        return True
    except Exception:
        return False


def last_auto_check():
    """上一次自动检查的信息（dict）或 None。"""
    raw = _state_get("auto_reply_last")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def cooldown_remaining():
    """距离下次允许自动检查还有多少分钟（0 表示可以检查）。"""
    last = last_auto_check()
    cooldown = getattr(config, "AUTO_CHECK_COOLDOWN_MIN", 60)
    if not last or not cooldown:
        return 0.0
    try:
        elapsed = (datetime.now()
                   - datetime.strptime(last.get("at", ""), "%Y-%m-%d %H:%M:%S")).total_seconds()
    except Exception:
        return 0.0
    remain = cooldown * 60 - elapsed
    return max(0.0, remain / 60.0)


def supports_chat(platform_key):
    """该平台是否配置了回复检查（真实平台用消息页，Mock 用会话接口）。"""
    p = platforms.get(platform_key) or {}
    return bool(p.get("chat_url") or p.get("chat_api_url"))


def _check_one(platform_key, tasks, register_matched=True):
    """检查单个平台并落库，返回 (摘要 entry, 原始结果)。"""
    res = check(platform_key, tasks)
    added, details = 0, []
    if register_matched and res.get("ok"):
        chosen = [c for c in (res.get("candidates") or [])
                  if c.get("建议类型") in AUTO_KINDS]
        if chosen:
            added, _dup, details = register(chosen, platform_key=platform_key)
    entry = {
        "platform": platform_key,
        "ok": bool(res.get("ok")),
        "error": res.get("error") or "",
        "records": len(res.get("records") or []),
        "candidates": len(res.get("candidates") or []),
        "unmatched": len(res.get("unmatched") or []),
        "inbox_added": res.get("inbox_added", 0),
        "added": added,
    }
    res["auto"] = {"added": added, "details": details}
    return entry, res


def _cooldown_blocked(cooldown):
    last = last_auto_check()
    if not last or not cooldown:
        return None
    try:
        elapsed = (datetime.now()
                   - datetime.strptime(last.get("at", ""), "%Y-%m-%d %H:%M:%S")).total_seconds()
    except Exception:
        return None
    if elapsed < cooldown * 60:
        return "冷却中：%.0f 分钟前刚检查过（间隔 %d 分钟）" % (elapsed / 60, cooldown)
    return None


def auto_check(platform_key, tasks, cooldown_minutes=None, register_matched=True):
    """自动检查单个平台（带冷却）。返回 {ran, reason, added, result, summary}。"""
    cooldown = (getattr(config, "AUTO_CHECK_COOLDOWN_MIN", 60)
                if cooldown_minutes is None else cooldown_minutes)
    blocked = _cooldown_blocked(cooldown)
    if blocked:
        return {"ran": False, "reason": blocked, "added": 0, "result": None, "summary": None}

    entry, res = _check_one(platform_key, tasks, register_matched=register_matched)
    info = dict(entry)
    info["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    info["platforms"] = [entry]
    _state_set("auto_reply_last", json.dumps(info, ensure_ascii=False))
    return {"ran": True, "reason": "", "added": entry["added"],
            "result": res, "summary": info}


def auto_check_multi(platform_keys, tasks, cooldown_minutes=None, register_matched=True,
                     close_after=True):
    """自动检查多个已登录平台（一次冷却，逐个平台检查，失败不中断）。"""
    cooldown = (getattr(config, "AUTO_CHECK_COOLDOWN_MIN", 60)
                if cooldown_minutes is None else cooldown_minutes)
    blocked = _cooldown_blocked(cooldown)
    if blocked:
        return {"ran": False, "reason": blocked, "added": 0, "results": [], "summary": None}

    keys = [k for k in dict.fromkeys(platform_keys or []) if supports_chat(k)]
    if not keys:
        return {"ran": False, "reason": "没有已登录且支持回复检查的平台",
                "added": 0, "results": [], "summary": None}

    entries, results = [], []
    for pk in keys:
        try:
            entry, res = _check_one(pk, tasks, register_matched=register_matched)
        except Exception as exc:  # 单平台异常不影响其它平台
            entry, res = ({"platform": pk, "ok": False, "error": str(exc),
                           "records": 0, "candidates": 0, "unmatched": 0,
                           "inbox_added": 0, "added": 0}, {"ok": False, "error": str(exc),
                                                           "records": [], "candidates": [],
                                                           "unmatched": [], "debug": []})
        entries.append(entry)
        results.append({"platform": pk, "result": res})
        if close_after:
            # 自动检查不应长期占用多个浏览器（每开一个约 300~800MB）
            try:
                session.dpage_quit(pk)
            except Exception:
                pass

    info = {
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "platforms": entries,
        "added": sum(e.get("added", 0) for e in entries),
        "records": sum(e.get("records", 0) for e in entries),
        "candidates": sum(e.get("candidates", 0) for e in entries),
        "unmatched": sum(e.get("unmatched", 0) for e in entries),
        "inbox_added": sum(e.get("inbox_added", 0) for e in entries),
        "error": "；".join("%s: %s" % (e["platform"], e["error"])
                           for e in entries if e.get("error")),
    }
    _state_set("auto_reply_last", json.dumps(info, ensure_ascii=False))
    return {"ran": True, "reason": "", "added": info["added"],
            "results": results, "summary": info}


def auto_enabled():
    """自动检查开关（持久化到 app_state；没设置过时取 config 默认）。"""
    raw = _state_get("auto_reply_enabled")
    if raw is None:
        return bool(getattr(config, "AUTO_CHECK_REPLIES", True))
    return raw == "1"


def set_auto_enabled(flag):
    return _state_set("auto_reply_enabled", "1" if flag else "0")


# ---------------- 会话收件箱：读到的消息都留下来（含未匹配任务） ----------------
def _msg_hash(platform_key, company, message):
    import hashlib
    raw = "%s|%s|%s" % (platform_key or "", _norm(company), _norm(message))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def store_inbox(records, tasks, platform_key=""):
    """把本次读到的会话（非我方消息）写入 hr_inbox（幂等）。返回新增条数。"""
    _ensure_tables()
    import db
    added = 0
    try:
        with db.get_conn() as conn:
            for rec in records or []:
                msg = str(rec.get("最后消息") or "").strip()
                if not msg or is_self_message(msg):
                    continue
                task, score = match_record(rec, tasks)
                tid = task["task_id"] if (task is not None and score >= MATCH_THRESHOLD) else None
                h = _msg_hash(platform_key, rec.get("单位名称"), msg)
                cur = conn.execute(
                    "INSERT OR IGNORE INTO hr_inbox (task_id, platform, company, hr, message, kind, msg_hash)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (tid, platform_key or "", rec.get("单位名称") or "", rec.get("HR") or "",
                     msg[:500], classify(msg), h))
                added += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    except Exception:
        return added
    return added


def list_inbox(limit=50):
    """最近的会话收件箱（最新在前）。"""
    _ensure_tables()
    import db
    try:
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM hr_inbox ORDER BY inbox_id DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def reclassify_inbox():
    """按当前分类规则重算收件箱里的类型（规则升级后让旧消息也跟着更新）。"""
    _ensure_tables()
    import db
    changed = 0
    try:
        with db.get_conn() as conn:
            rows = conn.execute("SELECT inbox_id, message, kind FROM hr_inbox").fetchall()
            for row in rows:
                kind = classify(row["message"])
                if kind != row["kind"]:
                    conn.execute("UPDATE hr_inbox SET kind=? WHERE inbox_id=?", (kind, row["inbox_id"]))
                    changed += 1
    except Exception:
        return 0
    return changed
