"""用户自助登录：用户在自己的浏览器里手动登录，程序从本机浏览器 cookie 库读出登录态存盘。

为什么不用受控浏览器：BOSS 直聘等平台会检测 Selenium 驱动的浏览器，
检测到就把登录页弹走/无限刷新（反爬），对着干是打地鼠。
用户用日常浏览器登录后，cookie 已从本机浏览器读出复用，平台看到的全是正常请求。

注意：Edge/Chrome 新版（App-Bound 加密）读 cookie 需要管理员权限；
普通读取失败时会明确提示用户以管理员身份运行一次。
"""
import platforms


def open_in_user_browser(platform_key):
    """用系统默认浏览器（用户日常浏览器）打开平台登录页。返回 (成功, 提示)。"""
    import webbrowser
    p = platforms.get(platform_key)
    if not p:
        return False, "未知平台：%s" % platform_key
    webbrowser.open(p["login_url"])
    return True, "已在你的浏览器打开 %s 登录页，请在那里扫码/登录，完成后回来点「完成登录」" % p.get("name", platform_key)


def _convert(cj):
    """http.cookiejar -> selenium add_cookie 格式（与 session.load_session 兼容）。"""
    out = []
    for c in cj:
        item = {"name": c.name, "value": c.value or "",
                "domain": c.domain or "", "path": c.path or "/",
                "secure": bool(c.secure), "httpOnly": bool(getattr(c, "_rest", {}) and
                                                          (c._rest or {}).get("HttpOnly") or False)}
        if c.expires:
            item["expiry"] = int(c.expires)
        out.append(item)
    return out


def grab_cookies(domain):
    """从本机 Edge/Chrome 读取指定域 cookie。

    返回 (cookies_list, None) 或 (None, 错误说明)。
    Edge 优先（Windows 默认浏览器）；App-Bound 加密读不了时会说明需要管理员。
    """
    try:
        import browser_cookie3
    except ImportError:
        return None, "缺少 browser_cookie3 库（pip install browser-cookie3）"
    notes = []
    for label, fn in (("Edge", browser_cookie3.edge), ("Chrome", browser_cookie3.chrome)):
        try:
            cj = fn(domain_name=domain)
            cookies = _convert(cj)
            if cookies:
                return cookies, None
            notes.append("%s 里没有 %s 的登录态" % (label, domain))
        except Exception as e:
            ename = type(e).__name__
            msg = str(e)[:80]
            if "Admin" in ename or "admin" in msg.lower():
                notes.append("%s 需要管理员权限才能读取" % label)
            else:
                notes.append("%s 读取失败：%s" % (label, msg))
    return None, "；".join(notes)


def is_admin():
    """当前进程是否管理员权限。"""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False
