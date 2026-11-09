"""浏览器会话管理：扫码登录 + 会话持久化 + 复用登录态检索。

扫码登录流程（真实）：
1. 启动浏览器（可见或后台）打开平台登录页
2. 平台展示二维码，截图保存供界面展示
3. 用户手机扫码（演示平台自动模拟登录）
4. 检测登录态（cookie/元素/URL），成功后保存会话
5. 后续检索复用已保存会话，无需重复登录
"""
import pickle
import io
import json
import sys
import time
from pathlib import Path

import config
import platforms

SESSION_DIR = Path(config.RUNTIME_DIR) / "sessions"
SESSION_DIR.mkdir(parents=True, exist_ok=True)


def _new_driver(headless=True, window_size="1280,900", profile_dir=None):
    """创建浏览器驱动（自动识别 Chrome / Edge）。"""
    from selenium import webdriver
    from browser_runtime import find_browser
    binary, kind = find_browser()
    profile_dir = str(profile_dir or "")
    is_edge = kind == "edge"
    if is_edge:
        from selenium.webdriver.edge.options import Options
        Driver = webdriver.Edge
    else:
        from selenium.webdriver.chrome.options import Options
        Driver = webdriver.Chrome
    opts = Options()
    opts.binary_location = binary
    if headless:
        opts.add_argument("--headless=new")
        opts.add_argument("--window-size=%s" % window_size)
    if profile_dir:
        # 仅在有头模式使用持久化用户目录（无头 + user-data-dir 会让浏览器崩溃）
        Path(profile_dir).mkdir(parents=True, exist_ok=True)
        opts.add_argument("--user-data-dir=%s" % profile_dir)
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--exclude-switches=enable-automation")
    opts.add_argument("--disable-features=AutomationControlled")
    opts.add_argument("--lang=zh-CN")
    opts.add_argument("--disable-infobars")
    driver = Driver(options=opts)
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        })
    except Exception:
        pass
    return driver


def _profile_dir(platform_key):
    return SESSION_DIR / "profiles" / platform_key


def profile_dir(platform_key):
    """公开访问器：该平台 DrissionPage 的浏览器持久化目录（登录态检测用）。"""
    return SESSION_DIR / "dprofiles" / platform_key


def launch_login(platform_key, headless=None):
    """打开登录页，等待二维码渲染，截图返回 (driver, screenshot_path)。

    headless 传 None 时按平台的 headless_ok 自动选择（真实平台默认有头）。
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    p = platforms.get(platform_key)
    if not p:
        raise ValueError("未知平台: %s" % platform_key)
    if headless is None:
        headless = p.get("headless_ok", False)  # 真实平台默认有头

    driver = _new_driver(headless=headless, profile_dir=_profile_dir(platform_key))
    driver.get(p["login_url"])

    qr_sel = p.get("login_qr_selector", "img, canvas")
    # 等待二维码元素渲染
    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, qr_sel))
        )
    except Exception:
        pass
    time.sleep(2)  # 等二维码数据加载

    shot = SESSION_DIR / ("%s_qrcode.png" % platform_key)
    # 优先只截取二维码元素
    try:
        qr = driver.find_element(By.CSS_SELECTOR, qr_sel)
        qr.screenshot(str(shot))
    except Exception:
        driver.save_screenshot(str(shot))  # 兜底：整页截图
    return driver, str(shot)


def check_logged_in(driver, platform_key):
    """检测登录态（按平台配置的 cookie/element/url 方式）。任何异常都视为未登录。"""
    p = platforms.get(platform_key)
    cfg = p.get("login_check", {})
    t = cfg.get("type", "cookie")
    try:
        if t == "cookie":
            for c in driver.get_cookies():
                if c.get("name") == cfg.get("name"):
                    return True
        elif t == "element":
            from selenium.webdriver.common.by import By
            driver.find_element(By.CSS_SELECTOR, cfg["selector"])
            return True
        elif t == "url":
            return cfg.get("contains", "") in driver.current_url
        elif t == "url_not_contains":
            # 登录成功后 URL 不再包含登录标识（如 login）
            return cfg.get("value", "login") not in driver.current_url
    except Exception:
        return False
    return False


def is_alive(driver):
    """判断浏览器会话是否仍然有效（用户可能已手动关闭窗口）。"""
    try:
        driver.current_url
        return True
    except Exception:
        return False


def safe_quit(driver):
    """安全关闭浏览器（忽略会话已失效/窗口已关闭的情况）。"""
    try:
        driver.quit()
    except Exception:
        pass


def save_session(platform_key, driver):
    try:
        cookies = driver.get_cookies()
        return save_cookies(platform_key, cookies)
    except Exception:
        return 0


def load_session(platform_key):
    if not platforms.get(platform_key):
        return None
    path = SESSION_DIR / ("%s.json" % platform_key)
    legacy = SESSION_DIR / ("%s.pkl" % platform_key)
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        elif legacy.exists():
            class CookieUnpickler(pickle.Unpickler):
                def find_class(self, module, name):
                    raise pickle.UnpicklingError("Cookie files may contain only plain data")
            data = CookieUnpickler(io.BytesIO(legacy.read_bytes())).load()
        else:
            return None
        if not isinstance(data, list) or not all(isinstance(c, dict) and isinstance(c.get("name"), str)
                                                and isinstance(c.get("value"), str) for c in data):
            return None
        return data
    except (OSError, pickle.UnpicklingError, EOFError, ValueError, TypeError, ImportError, AttributeError):
        return None
    return None


def has_session(platform_key):
    return bool(load_session(platform_key))


def get_logged_in_browser(platform_key, headless=True):
    """获取带登录态的浏览器（复用已保存会话 + 持久化用户目录）。"""
    driver = _new_driver(headless=headless, profile_dir=_profile_dir(platform_key))
    cookies = load_session(platform_key)
    if cookies:
        p = platforms.get(platform_key)
        # 先访问域名，再注入 cookie
        try:
            driver.get(p["login_url"])
            for c in cookies:
                try:
                    driver.add_cookie(c)
                except Exception:
                    pass
        except Exception:
            pass
    return driver


def clear_session(platform_key):
    if not platforms.get(platform_key):
        return
    for suffix in ("json", "pkl"):
        (SESSION_DIR / ("%s.%s" % (platform_key, suffix))).unlink(missing_ok=True)


# ---- 非阻塞登录（用户主导节奏）----
ACTIVE_DRIVERS = {}  # platform_key -> driver（跨 Streamlit 重跑保持，登录中）

def open_login(platform_key, headless=None):
    """打开登录页，driver 保留在 ACTIVE_DRIVERS，返回截图路径（无头时）。

    headless 传 None 时按平台 headless_ok 自动选择。
    """
    # 若该平台已有登录中的 driver，先安全关闭，避免用户目录被锁
    old = ACTIVE_DRIVERS.pop(platform_key, None)
    if old:
        safe_quit(old)
    driver, shot = launch_login(platform_key, headless=headless)
    ACTIVE_DRIVERS[platform_key] = driver
    return shot


def finish_login(platform_key):
    """用户主动触发：检测登录态，成功则保存会话并关闭浏览器。返回 (成功?, 说明)。"""
    driver = ACTIVE_DRIVERS.pop(platform_key, None)
    if driver is None:
        return False, "未找到登录会话，请先「打开登录页」"
    try:
        if not is_alive(driver):
            return False, "浏览器窗口已被关闭"
        if check_logged_in(driver, platform_key):
            n = save_session(platform_key, driver)
            return True, "登录成功（保存 %d 个 cookie）" % n
        return False, "尚未检测到登录，请确认已扫码并完成登录"
    finally:
        safe_quit(driver)


def close_login(platform_key):
    """取消登录并关闭浏览器。"""
    driver = ACTIVE_DRIVERS.pop(platform_key, None)
    if driver:
        safe_quit(driver)


def is_logging_in(platform_key):
    return platform_key in ACTIVE_DRIVERS


# ---- 真实浏览器手动登录（不被自动化检测）----
def manual_login(platform_key):
    """用用户真实默认浏览器打开平台登录页（非自动化，不会被反爬拦截）。"""
    import webbrowser
    p = platforms.get(platform_key)
    if not p:
        return False, "未知平台"
    webbrowser.open(p["login_url"])
    return True, "已用真实浏览器打开登录页，请在浏览器里扫码/登录"


def read_real_cookies(platform_key):
    """读取用户真实浏览器（Chrome/Edge）中该平台的登录 cookie。"""
    try:
        import browser_cookie3
    except ImportError:
        return []
    domain = platforms.cookie_domain(platform_key)
    if not domain:
        return []
    cookies = []
    for loader in (browser_cookie3.chrome, browser_cookie3.edge):
        try:
            cj = loader(domain_name=domain)
            for c in cj:
                if c.value:  # 跳过空值（App-Bound 加密导致读不到）
                    cookies.append({"name": c.name, "value": c.value,
                                    "domain": c.domain, "path": c.path})
            if cookies:
                break
        except Exception:
            continue
    return cookies


def real_chrome_profile():
    """检测用户真实浏览器用户目录（优先 Edge，其次 Chrome）。"""
    import os
    import sys
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = (Path(local) / "Microsoft/Edge/User Data", Path(local) / "Google/Chrome/User Data") if local else ()
    elif sys.platform == "darwin":
        candidates = (Path.home() / "Library/Application Support/Microsoft Edge", Path.home() / "Library/Application Support/Google/Chrome")
    else:
        candidates = tuple(Path.home() / ".config" / name for name in ("microsoft-edge", "google-chrome", "chromium"))
    for c in candidates:
        if os.path.isdir(c):
            return str(c)
    return None


def browser_running():
    """检测 Chrome/Edge 是否正在运行（占用用户目录时无法复用）。"""
    import subprocess
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True)
        return ("chrome.exe" in out.stdout) or ("msedge.exe" in out.stdout)
    except Exception:
        return False


def read_cookies_via_profile(platform_key):
    """用真实 Chrome 用户目录启动浏览器，经 CDP 读取登录 cookie（Chrome 内部解密，绕过 App-Bound 加密）。"""
    profile = real_chrome_profile()
    if not profile:
        return []
    driver = None
    try:
        driver = _new_driver(headless=False, profile_dir=profile)
        data = driver.execute_cdp_cmd("Network.getAllCookies", {})
        domain = platforms.cookie_domain(platform_key)
        result = []
        for c in data.get("cookies", []):
            d = c.get("domain") or ""
            if domain and domain in d:
                result.append({"name": c["name"], "value": c["value"],
                               "domain": d, "path": c.get("path", "/")})
        return result
    except Exception:
        return []
    finally:
        if driver:
            safe_quit(driver)


def save_cookies(platform_key, cookies):
    if not platforms.get(platform_key):
        raise ValueError("未知平台：%s" % platform_key)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    (SESSION_DIR / ("%s.json" % platform_key)).write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")
    return len(cookies)


def close_browser():
    """只关闭本应用创建的浏览器，不终止用户其他窗口。"""
    for platform_key in list(ACTIVE_DRIVERS):
        close_login(platform_key)
    for platform_key in list(_DPAGES):
        dpage_quit(platform_key)


def finish_manual_login(platform_key):
    """读取真实浏览器登录态并保存会话（自动关浏览器）。返回 (成功?, 说明)。"""
    # 先试 browser_cookie3（无需关浏览器）
    cookies = read_real_cookies(platform_key)
    if cookies:
        n = save_cookies(platform_key, cookies)
        return True, "已读取 %d 个登录 cookie（无需关浏览器）" % n
    # Do not terminate the user's unrelated browser windows to unlock a profile.
    if browser_running():
        return False, "浏览器用户目录正在使用，请保存工作并自行关闭 Chrome/Edge 后重试"
    cookies = read_cookies_via_profile(platform_key)
    if cookies:
        n = save_cookies(platform_key, cookies)
        return True, ("✅ 已读取 %d 个登录 cookie，登录成功。浏览器已关闭，请重新打开浏览器访问 http://localhost:8501 继续"
                      % n)
    return False, "未读取到登录 cookie，请确认已在浏览器完成登录后重试"


# ---- DrissionPage 抗反爬方案（真实平台）----
_DPAGES = {}  # platform_key -> ChromiumPage（登录后保持打开，检索复用）
_LAST_SEARCH_ERROR = {}  # platform_key -> 最近一次检索失败的真实原因（供界面显示）
_HIDDEN_LAUNCH = set()  # 以“屏幕外窗口”启动的平台（检索静默用）


def is_active(platform_key):
    """平台是否已有保存的 cookie 快照（严格口径，检索接口/API 路径使用）。"""
    return has_session(platform_key)


def profile_available(platform_key):
    """本地是否已有该平台的浏览器用户目录（可能仍处于登录态，也可能已失效）。"""
    try:
        path = profile_dir(platform_key)
        return bool(path and path.is_dir() and any(path.iterdir()))
    except OSError:
        return False


def can_search(platform_key):
    """界面门控口径：有 cookie 快照，或本地已有浏览器登录目录。

    浏览器目录不保证登录仍有效；检索时由 dpage_search 记录真实原因
    （“登录态失效，已重定向到登录页”），界面会提示回第②步重新扫码。
    """
    return has_session(platform_key) or profile_available(platform_key)


def last_search_error(platform_key):
    """最近一次检索失败的原因（无失败返回空串）。"""
    return _LAST_SEARCH_ERROR.get(platform_key, "")


def _port_file(platform_key):
    return SESSION_DIR / ("%s.devtools_port" % platform_key)


def _port_open(port, timeout=0.3):
    import socket
    with socket.socket() as sock:
        sock.settimeout(timeout)
        return sock.connect_ex(("127.0.0.1", int(port))) == 0


def _page_alive(page):
    """浏览器对象是否仍然可用（用户关闭窗口 / 进程重启后为 False）。"""
    try:
        page.url
        return True
    except Exception:
        return False


def _attach_existing(platform_key):
    """尝试接管上次启动、且现在仍在运行的浏览器。

    应用重启（改代码、手动重启 Streamlit）后，进程内 `_DPAGES` 会清空，
    但浏览器进程仍在运行并锁着 profile；此时直接再启动会失败。
    调试端口优先读自己记录的端口文件，其次读 Chrome 在 profile 里写的
    DevToolsActivePort，这样旧版本启动的浏览器也能被接管，登录态不会丢。
    """
    try:
        from DrissionPage import ChromiumPage
    except ImportError:
        # 未安装浏览器依赖时交给 _launch_dpage 给出可读的安装提示
        return None

    candidates = []
    try:
        candidates.append(int(_port_file(platform_key).read_text(encoding="utf-8").strip()))
    except (OSError, ValueError):
        pass
    try:
        active = SESSION_DIR / "dprofiles" / platform_key / "DevToolsActivePort"
        candidates.append(int(active.read_text(encoding="utf-8").splitlines()[0].strip()))
    except (OSError, ValueError, IndexError):
        pass
    for port in dict.fromkeys(candidates):
        if not _port_open(port):
            continue
        try:
            page = ChromiumPage("127.0.0.1:%d" % port)
            if _page_alive(page):
                return page
        except Exception:
            continue
    return None


def _browser_windows(pid, main_only=False):
    """列出某个进程的顶层窗口句柄（仅 Windows；其他平台返回空）。

    main_only=True 只返回浏览器主窗口（Chrome_WidgetWin_1 且有标题），
    避免把 Chrome 的隐藏辅助窗口一起显示出来。
    """
    if sys.platform != "win32" or not pid:
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    handles = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid:
            return True
        if main_only:
            name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, name, 256)
            if name.value != "Chrome_WidgetWin_1":
                return True
            if user32.GetWindowTextLengthW(hwnd) == 0:
                return True
        handles.append(hwnd)
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return handles


def _set_browser_visible(page, visible):
    """隐藏/显示浏览器窗口（Windows；无需 pywin32，用 ctypes 调 user32）。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        pid = getattr(getattr(page, "browser", None), "process_id", None)
        windows = _browser_windows(pid, main_only=bool(visible))
        if not windows:
            return False
        user32 = ctypes.windll.user32
        for hwnd in windows:
            user32.ShowWindow(hwnd, 5 if visible else 0)  # SW_SHOW / SW_HIDE
        return True
    except Exception:
        return False


def _windows_by_title(hint):
    """按窗口标题关键字找 Chrome 主窗口（进程 pid 拿不到时的兜底）。"""
    if sys.platform != "win32" or not hint:
        return []
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        handles = []
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, _):
            name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, name, 256)
            if name.value != "Chrome_WidgetWin_1":
                return True
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            if hint in buf.value:
                handles.append(hwnd)
            return True

        user32.EnumWindows(enum_proc(callback), 0)
        return handles
    except Exception:
        return []


def _show_page_window(page, left=120, top=80, title_hint=""):
    """把窗口恢复为可见并拉回屏幕内。

    检索时窗口可能是“屏幕外启动/被 SW_HIDE”的；应用重启后 _HIDDEN_LAUNCH
    会丢，光看这个集合判断是否恢复并不可靠，所以这里直接用 CDP 强制设置窗口边界。
    """
    moved = False
    try:
        info = page.run_cdp("Browser.getWindowForTarget") or {}
        window_id = info.get("windowId")
        if window_id is not None:
            page.run_cdp("Browser.setWindowBounds", windowId=window_id,
                         bounds={"left": left, "top": top, "windowState": "normal"})
            moved = True
    except Exception:
        pass
    if not moved:
        try:
            page.set.window.normal()
            page.set.window.location(left, top)
            moved = True
        except Exception:
            pass
    # 再尝试把窗口取消隐藏、移到屏幕内并提到前台
    if sys.platform == "win32":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            pid = getattr(getattr(page, "browser", None), "process_id", None)
            windows = _browser_windows(pid, main_only=True) if pid else []
            if not windows:
                windows = _windows_by_title(title_hint or (page.title or ""))
            for hwnd in windows:
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.MoveWindow(hwnd, left, top, 1100, 800, True)
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
    return moved


def _launch_dpage(platform_key, hidden=False):
    """启动 DrissionPage 浏览器（持久化 profile + 空闲调试端口），失败给出说明。

    hidden=True 时把窗口移到屏幕外：检索不弹窗，但仍是有头浏览器（不易被识别为无头）。
    """
    try:
        from DrissionPage import ChromiumPage, ChromiumOptions
    except ImportError as exc:
        raise RuntimeError("浏览器功能依赖缺失，请安装 requirements-browser.txt") from exc
    from browser_runtime import find_browser
    binary, _ = find_browser()
    prof = SESSION_DIR / "dprofiles" / platform_key
    prof.mkdir(parents=True, exist_ok=True)
    co = ChromiumOptions()
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    co.set_local_port(port)
    co.set_browser_path(binary)
    co.set_argument("--no-sandbox")
    co.headless(config.HEADLESS)
    if hidden and not config.HEADLESS:
        # 屏幕外渲染：任务栏和桌面都不会弹窗，URL 仍可正常访问
        co.set_argument("--window-position=-32000,-32000")
        co.set_argument("--window-size=1280,900")
    co.set_user_data_path(str(prof))
    try:
        page = ChromiumPage(co)
    except Exception as exc:
        raise RuntimeError("浏览器启动失败，请检查浏览器配置及该平台窗口是否仍在运行：%s" % exc) from exc
    # 配置目录被另一窗口占用时，浏览器会立刻退出：此时对象不可用，必须明确报错
    time.sleep(0.6)
    if not _page_alive(page):
        raise RuntimeError("浏览器启动后立即退出：配置目录 %s 可能正被另一个浏览器窗口占用，"
                           "请关闭该窗口后重试" % prof)
    try:
        _port_file(platform_key).write_text(str(port), encoding="utf-8")
    except OSError:
        pass
    if hidden and not config.HEADLESS:
        # 屏幕外 + 隐藏窗口：桌面和任务栏都不出现浏览器
        _set_browser_visible(page, False)
    return page


def _get_page(platform_key, hidden=False):
    """取一个可用的浏览器：进程内缓存 → 接管旧浏览器 → 新启动。

    hidden=True 只在“需要新开浏览器”时生效；能复用已打开的登录浏览器时不会弹窗，
    也不会把它移走。
    """
    page = _DPAGES.get(platform_key)
    if page is not None and not _page_alive(page):
        _DPAGES.pop(platform_key, None)
        page = None
    if page is None:
        page = _attach_existing(platform_key)
        if page is not None:
            _HIDDEN_LAUNCH.discard(platform_key)
        else:
            page = _launch_dpage(platform_key, hidden=hidden)
            if hidden and not config.HEADLESS:
                _HIDDEN_LAUNCH.add(platform_key)
        _DPAGES[platform_key] = page
    return page


def _write_debug(platform_key, lines):
    """把检索过程写进 data/search_debug_<平台>.log，便于排查「0 个岗位」。"""
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (config.DATA_DIR / ("search_debug_%s.log" % platform_key)).write_text(
            "\n".join(lines), encoding="utf-8")
    except Exception:
        pass


def dpage_open(platform_key):
    """打开 DrissionPage 浏览器到平台登录页（持久化 profile，登录态保存）。"""
    p = platforms.get(platform_key)

    if not p:
        return False, "未知平台：%s" % platform_key

    # 复用已保持打开的浏览器（登录态/会话 cookie 驻留其中）；
    # 进程重启后缓存为空，但旧浏览器可能还在运行 → _get_page 会先尝试接管它。
    try:
        page = _get_page(platform_key)
    except RuntimeError as exc:
        return False, str(exc)
    if page is None:
        return False, "浏览器启动失败，请重试"
    # 第②步要扫码：窗口可能是检索时“屏幕外/隐藏启动”的（应用重启后标记会丢），
    # 因此不依赖 _HIDDEN_LAUNCH，直接把窗口恢复成可见并拉回屏幕。
    if not config.HEADLESS:
        _set_browser_visible(page, True)
        _show_page_window(page, title_hint=p.get("name", ""))
        _HIDDEN_LAUNCH.discard(platform_key)
    try:
        page.get(p["login_url"])
        page.wait(2)
        cfg = p.get("login_check", {})
        logged_in = False
        if cfg.get("type") == "url_not_contains":
            logged_in = cfg["value"] not in page.url
        elif cfg.get("type") == "cookie":
            logged_in = any(c.get("name") == cfg["name"] for c in page.cookies())
        if logged_in:
            return True, "已登录（无需扫码），可直接去第③步检索"
        return True, "已打开/复用登录浏览器，请在浏览器里扫码登录"
    except Exception as exc:
        _DPAGES.pop(platform_key, None)
        return False, "无法打开登录页：%s" % exc


def dpage_finish(platform_key):
    """检测登录态并保存 cookie（浏览器保持打开，供检索复用）。"""
    page = _DPAGES.get(platform_key)
    if not page:
        return False, "未找到登录会话，请先「打开登录页」"
    p = platforms.get(platform_key)
    cfg = p.get("login_check", {})
    ok = False
    try:
        page.wait(2)  # 等扫码后浏览器跳转完成
        if cfg.get("type") == "url_not_contains":
            ok = cfg["value"] not in page.url
        elif cfg.get("type") == "cookie":
            ok = any(c.get("name") == cfg["name"] for c in page.cookies())
    except Exception:
        ok = False
    if not ok:
        return False, "尚未检测到登录，请确认已在浏览器完成扫码/登录"
    n = save_cookies(platform_key, page.cookies(all_info=True))
    return True, "已保存 %d 个 cookie，登录成功" % n


def dpage_search(platform_key, keyword, city="", pages=1):
    """正确做法：用 DrissionPage 旁听浏览器自己发的搜索接口响应，拿明文岗位数据。

    不自己发请求（规避 code:37 反爬），不用 DOM 提取（规避字体反爬）。
    """
    import json as _json
    from crawler import normalize_fields, _dig

    p = platforms.get(platform_key)
    if not p:
        return []
    # 猎聘/51job 是前端渲染，接口里也拿不到明文岗位：直接用浏览器渲染后的 DOM 解析
    prefer_dom = bool(p.get("dom_parse")) or not p.get("api_field_map")
    # 城市名 -> 平台城市码
    search_city = platforms.city_code(platform_key, city) if city else \
        (platforms.city_code(platform_key, "北京") if platform_key == "boss" else "")
    _LAST_SEARCH_ERROR.pop(platform_key, None)
    try:
        # 检索默认不弹窗：能复用登录浏览器就复用，需新开则放到屏幕外
        page = _get_page(platform_key, hidden=config.SEARCH_HIDDEN)
    except RuntimeError as exc:
        _LAST_SEARCH_ERROR[platform_key] = str(exc)
        _write_debug(platform_key, ["浏览器启动失败: %s" % exc])
        return []
    # 检索期间把浏览器窗口藏起来：即使复用的是当前可见的登录窗口，也不会「弹」在用户面前
    if config.SEARCH_HIDDEN and not config.HEADLESS:
        if _set_browser_visible(page, False):
            _HIDDEN_LAUNCH.add(platform_key)

    jobs = []
    debug = []
    reason = ""
    try:
        api_kw = p.get("api_listen_kw", "joblist.json")
        try:
            page.listen.start(api_kw)
        except Exception as exc:
            if "浏览器未开启或已关闭" not in str(exc):
                raise
            # 浏览器已被关闭（或应用重启后残留失效引用）：丢弃引用、接管/重启浏览器后重试一次
            _DPAGES.pop(platform_key, None)
            debug.append("浏览器已关闭，尝试重启后重试")
            page = _get_page(platform_key, hidden=config.SEARCH_HIDDEN)
            page.listen.start(api_kw)
        url = platforms.search_url(platform_key, keyword, city, 1)
        page.get(url)
        page.wait(3)
        debug.append("URL: %s" % page.url[:120])
        # 登录态失效检测：导航后被重定向到登录页（用平台 login_check 配置判断，不再硬编码 Boss 路径）
        _cfg = p.get("login_check", {})
        _expired = False
        if _cfg.get("type") == "url_not_contains":
            _expired = _cfg["value"] in page.url
        if _expired:
            clear_session(platform_key)
            reason = "登录态已失效（被重定向到登录页），请回第②步重新扫码登录"
            debug.append("登录态失效，已重定向到登录页")
            return []
        # 滚动触发无限滚动翻页（Boss直聘靠滚动加载更多）
        for i in range(max(1, int(pages))):
            try:
                page.run_js("window.scrollTo(0, document.body.scrollHeight);")
                page.wait(1)
            except Exception:
                break
        if prefer_dom:
            from crawler import jobs_from_zhilian_state, parse_job_cards
            jobs = []
            if platform_key == "zhilian":
                try:
                    state = page.run_js("return window.__INITIAL_STATE__ || null;")
                except Exception:
                    state = None
                jobs = jobs_from_zhilian_state(state)
                debug.append("页面状态解析岗位数: %d" % len(jobs))
            if not jobs:
                jobs = parse_job_cards(page.html, platform_key, page.url)
                debug.append("DOM 解析岗位数: %d" % len(jobs))
            if not jobs:
                reason = ("页面未解析到岗位：可能被验证码/登录墙拦截，"
                          "或平台页面结构已变化")
            return jobs
        # 收集 joblist 接口响应（每页一个包；count==1 时 wait 返回单个 DataPacket，归一为列表）
        want = max(1, int(pages))
        packets = page.listen.wait(count=want, timeout=5 + want * 3, fit_count=False)
        if packets is False or packets is None:
            packets = []
        elif not isinstance(packets, (list, tuple)):
            packets = [packets]  # 单个 DataPacket 也归一为列表
        debug.append("捕获接口响应数: %d" % len(packets))
        seen = set()
        for packet in packets:
            try:
                body = packet.response.body
            except Exception:
                continue
            if isinstance(body, (str, bytes)):
                try:
                    body = _json.loads(body)
                except Exception:
                    continue
            job_list = _dig(body, p.get("api_jobs_path", "zpData.jobList"))
            if not isinstance(job_list, list):
                continue
            for item in job_list:
                if str(item.get("contact", "")).lower() in ("true", "1"):
                    continue
                raw = {}
                for std, src in p.get("api_field_map", {}).items():
                    raw[std] = _dig(item, src)
                link = raw.get("岗位链接", "")
                raw["岗位链接"] = platforms.job_url(platform_key, link)
                if link and not str(link).startswith("http"):
                    # 按平台拼岗位详情链接（各平台 jobId -> 详情页规则不同）
                    _link_rules = {
                        "boss": "https://www.zhipin.com/job_detail/%s.html",
                        "lagou": "https://www.lagou.com/jobs/%s.html",
                        "job51": "https://jobs.51job.com/all/%s.html",
                    }
                    if platform_key in _link_rules:
                        raw["岗位链接"] = _link_rules[platform_key] % link
                raw.setdefault("投递入口类型", "")
                norm = normalize_fields(raw)
                key = norm.get("岗位链接") or norm.get("岗位名称")
                if key and key in seen:
                    continue
                seen.add(key)
                jobs.append(norm)
        debug.append("去重后岗位数: %d" % len(jobs))
        if not jobs and not reason:
            reason = ("未捕获到搜索接口响应：页面可能被风控/验证码拦截，"
                      "或搜索页未加载完成，请重试")
    except Exception as e:
        debug.append("检索异常: %s" % e)
        reason = "检索异常：%s" % e
    finally:
        try:
            page.listen.stop()  # 释放网络监听（浏览器保持打开，供下次复用）
        except Exception:
            pass
        _write_debug(platform_key, debug)
        if jobs:
            _LAST_SEARCH_ERROR.pop(platform_key, None)
        else:
            _LAST_SEARCH_ERROR[platform_key] = reason or (debug[-1] if debug else "未获取到岗位")
        # 不 quit：保持浏览器打开（登录态/会话 cookie 依赖浏览器驻留），供下次检索与扫码复用
    return jobs


def dpage_quit(platform_key):
    page = _DPAGES.pop(platform_key, None)
    _HIDDEN_LAUNCH.discard(platform_key)
    if page:
        try:
            page.quit()
        except Exception:
            pass
    try:
        _port_file(platform_key).unlink(missing_ok=True)
    except OSError:
        pass


def dpage_open_job(platform_key, job_link):
    """在登录的 DrissionPage 浏览器打开岗位详情页（供用户手动投递）。"""
    page = _DPAGES.get(platform_key)
    if not page:
        return False, "登录浏览器未打开，无法打开详情页"
    if not job_link:
        return False, "缺少岗位详情链接"
    try:
        page.new_tab(job_link)
        return True, "已打开岗位详情页，请手动点击投递"
    except Exception as e:
        return False, str(e)


def dpage_deliver(platform_key, job_link):
    """在岗位详情页点击「立即沟通」按钮（真实选择器 a.btn-startchat）。

    返回 (ok, msg)；找不到按钮/登录失效/触发风控均返回 False 并给出可识别原因，
    供批量投递在检测到风控信号时立即停止。
    """
    page = _DPAGES.get(platform_key)
    if not page:
        return False, "登录浏览器未打开，无法投递"
    if not job_link:
        return False, "缺少岗位详情链接"
    try:
        page.get(job_link)
        page.wait(3)
        # 登录态失效检测：导航后被重定向到登录页
        if "/web/user" in page.url or "login" in page.url.lower():
            return False, "登录态失效，请重新扫码登录"
        r = page.run_js("""
            var btn = document.querySelector('a.btn-startchat') || document.querySelector('.btn-startchat');
            if (btn) { btn.click(); return '已点击立即沟通'; }
            var body = (document.body && document.body.innerText) || '';
            if (/验证|安全验证|滑块验证|风控/.test(body)) { return '风控验证'; }
            return '未找到立即沟通按钮';
        """)
        r = str(r)
        if "风控" in r:
            return False, "触发风控验证，请人工处理后再投递"
        if "未找到" in r:
            return False, "未找到立即沟通按钮（岗位可能已下线或需人工查看）"
        if r != "已点击立即沟通":
            return False, "未确认沟通按钮操作成功：%s" % r
        return True, r
    except Exception as e:
        return False, str(e)


def dpage_greet(platform_key, greeting):
    """点击立即沟通后，在聊天框输入招呼语并发送。"""
    import json as _json
    page = _DPAGES.get(platform_key)
    if not page:
        return False, "登录浏览器未打开"
    try:
        page.wait(3)  # 等聊天面板打开
        r = page.run_js("""
            function sendGreet(text){
                var inp = document.querySelector('.chat-input textarea') || document.querySelector('.chat-conversation textarea')
                       || document.querySelector('textarea') || document.querySelector('[contenteditable="true"]');
                if(!inp){ return '未找到聊天输入框'; }
                if(inp.tagName && inp.tagName.toLowerCase()==='textarea'){
                    inp.value = text;
                    inp.dispatchEvent(new Event('input',{bubbles:true}));
                } else {
                    inp.textContent = text;
                    inp.dispatchEvent(new Event('input',{bubbles:true}));
                }
                inp.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}));
                inp.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}));
                return '已尝试发送招呼语';
            }
            return sendGreet(%s);
        """ % _json.dumps(greeting, ensure_ascii=False))
        if r != "已尝试发送招呼语":
            return False, str(r)
        return False, "已尝试发送招呼语，请人工核对平台是否实际送达"
    except Exception as e:
        return False, str(e)
