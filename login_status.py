"""登录态检测：应用启动 / 页面刷新时检查各平台的登录情况。

为什么要单独一层：`session.has_session()` 只判断"有没有保存过 cookie 文件"，
文件在 ≠ 还能用（Boss 的会话 cookie 过期、浏览器被关掉后都会失效）。
本模块给出分级结论：

    logged_in  联网验证通过（或本地有会话 cookie 且未过期）
    saved      本地有登录态文件，但未联网验证 / 无法验证
    expired    明确过期（cookie 全部过期，或探测被跳到登录页）
    blocked    探测被反爬/验证码拦截，无法判断（不代表未登录）
    absent     没有任何登录态
    unknown    探测异常

联网探测是可选的（config.LOGIN_CHECK_ONLINE）；只对有登录态文件的平台发起
一次短超时请求，且不会写入数据库、不会触发任何投递动作。
"""
from datetime import datetime

import config
import platforms
import session

# 探测结果判定用到的关键字
LOGIN_URL_MARKERS = ("login", "passport", "web/user", "signin", "登录")
BLOCK_MARKERS = ("security verification", "aliyun_waf", "访问验证", "滑动验证",
                 "安全验证", "请稍候", "正在验证")

STATE_LABEL = {
    "logged_in": ("ok", "已登录"),
    "saved": ("warn", "已保存登录态"),
    "expired": ("bad", "登录已过期"),
    "blocked": ("warn", "无法判断（被拦截）"),
    "absent": ("off", "未登录"),
    "unknown": ("warn", "检测失败"),
}


def _now():
    return datetime.now().strftime("%H:%M:%S")


def _cookie_expiry(cookie):
    """取 cookie 的过期时间（兼容 DrissionPage 的 expires/expiry 字段）。"""
    for key in ("expires", "expiry", "expirationDate"):
        value = cookie.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _local_state(platform_key):
    """只看本地登录态文件，得到 (state, detail)。"""
    p = platforms.get(platform_key) or {}
    cookies = session.load_session(platform_key) or []
    profile = session.profile_dir(platform_key)
    has_profile = bool(profile and profile.is_dir() and any(profile.iterdir()))

    if not cookies and not has_profile:
        return "absent", "没有保存的登录态（未扫码登录）"

    check = p.get("login_check", {})
    if check.get("type") == "cookie" and check.get("name"):
        names = {c.get("name") for c in cookies}
        if check["name"] not in names:
            return "expired", "缺少关键登录 cookie「%s」，请重新扫码" % check["name"]

    expiries = [_cookie_expiry(c) for c in cookies]
    known = [e for e in expiries if e]
    if known and all(e < datetime.now().timestamp() for e in known) and not has_profile:
        return "expired", "保存的 cookie 已全部过期，请重新扫码"
    if cookies:
        return "saved", "本地有 %d 个 cookie（未联网验证）" % len(cookies)
    return "saved", "本地有浏览器登录目录（未联网验证）"


def _probe(platform_key, cookies):
    """联网验证：带 cookie 访问一个需要登录的页面，按跳转/内容判断。"""
    p = platforms.get(platform_key) or {}
    probe = p.get("auth_probe")
    if not probe:
        return None
    import requests

    cookie_dict = {c["name"]: c["value"] for c in cookies if c.get("value")}
    try:
        r = requests.get(probe["url"], cookies=cookie_dict,
                         headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-CN,zh;q=0.9"},
                         timeout=config.LOGIN_CHECK_TIMEOUT, allow_redirects=True)
    except Exception as exc:  # 超时/断网/DNS
        return "unknown", "联网检测失败：%s" % str(exc)[:60]

    text = (r.text or "")[:4000].lower()
    final = (r.url or "").lower()
    if any(m in final for m in LOGIN_URL_MARKERS):
        return "expired", "访问被跳转到登录页（%s）" % r.url[:60]
    if any(m in text for m in BLOCK_MARKERS):
        return "blocked", "被平台验证页拦截，无法联网判断"
    if r.status_code in (401, 403):
        return "expired", "平台返回 %d（未授权）" % r.status_code
    if 200 <= r.status_code < 400:
        return "logged_in", "联网验证通过（HTTP %d）" % r.status_code
    return "unknown", "平台返回 HTTP %d" % r.status_code


def check_platform(platform_key, online=True):
    """检测单个平台，返回 dict（key/name/state/label/kind/detail/method/checked_at）。"""
    state, detail = _local_state(platform_key)
    method = "local"
    if online and state == "saved":
        probed = _probe(platform_key, session.load_session(platform_key) or [])
        if probed:
            state, detail = probed
            method = "online"
    kind, label = STATE_LABEL.get(state, ("warn", "未知"))
    return {
        "key": platform_key,
        "name": (platforms.get(platform_key) or {}).get("name", platform_key),
        "state": state,
        "label": label,
        "kind": kind,
        "detail": detail,
        "method": method,
        "checked_at": _now(),
    }


def check_all(online=None):
    """检测全部受支持平台。online=None 时取 config.LOGIN_CHECK_ONLINE。"""
    if online is None:
        online = config.LOGIN_CHECK_ONLINE
    return [check_platform(key, online=online) for key in platforms.PLATFORMS]


def summary(statuses):
    """汇总：{已登录, 已保存, 过期, 未登录, 无法判断}。"""
    counts = {}
    for s in statuses or []:
        counts[s["state"]] = counts.get(s["state"], 0) + 1
    return counts
