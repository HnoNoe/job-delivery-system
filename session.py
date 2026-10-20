"""浏览器会话管理：扫码登录 + 会话持久化 + 复用登录态检索。

扫码登录流程（真实）：
1. 启动浏览器（可见或后台）打开平台登录页
2. 平台展示二维码，截图保存供界面展示
3. 用户手机扫码（演示平台自动模拟登录）
4. 检测登录态（cookie/元素/URL），成功后保存会话
5. 后续检索复用已保存会话，无需重复登录
"""
import pickle
import time
from pathlib import Path

import config
import platforms

SESSION_DIR = Path(config.BASE_DIR) / "sessions"
SESSION_DIR.mkdir(exist_ok=True)


def _new_driver(headless=True, window_size="1280,900", profile_dir=None):
    """创建浏览器驱动（自动识别 Chrome / Edge）。"""
    from selenium import webdriver
    profile_dir = str(profile_dir or "")
    is_edge = "Edge" in profile_dir
    if is_edge:
        from selenium.webdriver.edge.options import Options
        Driver = webdriver.Edge
    else:
        from selenium.webdriver.chrome.options import Options
        Driver = webdriver.Chrome
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
        opts.add_argument("--window-size=%s" % window_size)
    if profile_dir and not headless:
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
        (SESSION_DIR / ("%s.pkl" % platform_key)).write_bytes(pickle.dumps(cookies))
        return len(cookies)
    except Exception:
        return 0


def load_session(platform_key):
    path = SESSION_DIR / ("%s.pkl" % platform_key)
    if path.exists():
        return pickle.loads(path.read_bytes())
    return None


def has_session(platform_key):
    return (SESSION_DIR / ("%s.pkl" % platform_key)).exists()


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
    path = SESSION_DIR / ("%s.pkl" % platform_key)
    if path.exists():
        path.unlink()


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
    import browser_cookie3
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
    local = os.environ.get("LOCALAPPDATA", "")
    for c in (os.path.join(local, "Microsoft", "Edge", "User Data"),
              os.path.join(local, "Google", "Chrome", "User Data")):
        if os.path.isdir(c):
            return c
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
    (SESSION_DIR / ("%s.pkl" % platform_key)).write_bytes(pickle.dumps(cookies))
    return len(cookies)


def close_browser():
    """关闭 Edge/Chrome（用于释放用户目录，读取登录态）。"""
    import subprocess
    for exe in ("msedge.exe", "chrome.exe"):
        subprocess.run(["taskkill", "/IM", exe, "/F"],
                       capture_output=True, creationflags=0x08000000)
    time.sleep(2)


def finish_manual_login(platform_key):
    """读取真实浏览器登录态并保存会话（自动关浏览器）。返回 (成功?, 说明)。"""
    # 先试 browser_cookie3（无需关浏览器）
    cookies = read_real_cookies(platform_key)
    if cookies:
        n = save_cookies(platform_key, cookies)
        return True, "已读取 %d 个登录 cookie（无需关浏览器）" % n
    # 浏览器运行中会锁库，自动关闭后读取
    if browser_running():
        close_browser()
    cookies = read_cookies_via_profile(platform_key)
    if cookies:
        n = save_cookies(platform_key, cookies)
        return True, ("✅ 已读取 %d 个登录 cookie，登录成功。浏览器已关闭，请重新打开浏览器访问 http://localhost:8501 继续"
                      % n)
    return False, "未读取到登录 cookie，请确认已在浏览器完成登录后重试"


# ---- DrissionPage 抗反爬方案（真实平台）----
_DPAGES = {}  # platform_key -> ChromiumPage（登录后保持打开，检索复用）


def is_active(platform_key):
    """平台当前是否可用：已保存登录态，或登录浏览器页面仍开着。

    公共访问器：外部模块不应直接读私有 `_DPAGES`。
    """
    return has_session(platform_key) or platform_key in _DPAGES


def _dpage_port(platform_key):
    """每个平台固定一个调试端口（auto_port + user_data_path 组合有 bug，用固定端口规避）。"""
    return {"boss": 9333, "zhilian": 9334, "lagou": 9335, "liepin": 9336, "job51": 9337}.get(platform_key, 9400)


def _kill_orphan_browser(port):
    """按调试端口清理孤儿 Chromium 进程（Streamlit 重启后残留的浏览器）。"""
    import subprocess
    try:
        out = subprocess.run(
            ["wmic", "process", "where",
             "Name like '%chrome%' or Name like '%msedge%'",
             "get", "ProcessId,CommandLine", "/format:list"],
            capture_output=True, text=True, timeout=20).stdout
        pid = None
        block, cur = "", None
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("CommandLine="):
                cur = line[len("CommandLine="):]
            elif line.startswith("ProcessId="):
                pid = line[len("ProcessId="):]
                if cur and ("--remote-debugging-port=%d" % port) in cur:
                    try:
                        subprocess.run(["taskkill", "/F", "/PID", pid],
                                       capture_output=True, timeout=10)
                    except Exception:
                        pass
                cur = None
    except Exception:
        pass


def _launch_dpage(platform_key):
    """启动 DrissionPage 浏览器（持久化 profile + 孤儿清理 + 重试），失败返回 None。"""
    from DrissionPage import ChromiumPage, ChromiumOptions
    prof = SESSION_DIR / "dprofiles" / platform_key
    prof.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        co = ChromiumOptions()
        co.set_local_port(_dpage_port(platform_key))
        co.set_argument("--no-sandbox")
        co.set_user_data_path(str(prof))
        try:
            return ChromiumPage(co)
        except Exception:
            _kill_orphan_browser(_dpage_port(platform_key))
            import time as _t
            _t.sleep(1)
    return None


def dpage_open(platform_key):
    """打开 DrissionPage 浏览器到平台登录页（持久化 profile，登录态保存）。"""
    p = platforms.get(platform_key)

    # 复用已保持打开的浏览器（登录态/会话 cookie 驻留其中）
    page = _DPAGES.get(platform_key)
    if page is not None:
        try:
            page.get(p["login_url"])
            page.wait(2)
            # 用平台的 login_check 配置判断登录态（不再硬编码 Boss 路径）
            cfg = p.get("login_check", {})
            logged_in = False
            if cfg.get("type") == "url_not_contains":
                logged_in = cfg["value"] not in page.url
            elif cfg.get("type") == "cookie":
                logged_in = any(c.get("name") == cfg["name"] for c in page.cookies())
            if logged_in:
                return True, "已登录（无需扫码），可直接去第③步检索"
            return True, "已复用登录浏览器，请在浏览器里扫码登录"
        except Exception:
            _DPAGES.pop(platform_key, None)

    page = _launch_dpage(platform_key)
    if page is None:
        return False, "浏览器启动失败，请重试"
    page.get(p["login_url"])
    page.wait(3)
    _DPAGES[platform_key] = page
    return True, "已打开登录页（登录态持久保存）"


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
    from DrissionPage import ChromiumPage, ChromiumOptions
    from crawler import normalize_fields, _dig

    p = platforms.get(platform_key)
    # 城市名 -> 平台城市码
    search_city = platforms.city_code(platform_key, city) if city else \
        (platforms.city_code(platform_key, "北京") if platform_key == "boss" else "")
    page = _DPAGES.get(platform_key)
    own = page is None
    if own:
        page = _launch_dpage(platform_key)
        if page is None:
            return []
        # 登录态已持久化在 profile 里，直接导航即可。
        # 不再注入 boss.pkl 会话级 cookie（会覆盖 profile 登录态，导致被重定向到登录页、薪资被隐藏）。
        _DPAGES[platform_key] = page  # 保持浏览器打开，会话级登录 cookie 才不会丢失

    jobs = []
    debug = []
    try:
        api_kw = p.get("api_listen_kw", "joblist.json")
        page.listen.start(api_kw)
        url = p["search_url"]
        for k, v in {"keyword": keyword, "city": search_city, "page": 1}.items():
            url = url.replace("{" + k + "}", str(v))
        page.get(url)
        page.wait(3)
        debug.append("URL: %s" % page.url[:120])
        # 登录态失效检测：导航后被重定向到登录页（用平台 login_check 配置判断，不再硬编码 Boss 路径）
        _cfg = p.get("login_check", {})
        _expired = False
        if _cfg.get("type") == "url_not_contains":
            _expired = _cfg["value"] in page.url
        if _expired:
            debug.append("登录态失效，已重定向到登录页")
            return []
        # 滚动触发无限滚动翻页（Boss直聘靠滚动加载更多）
        for i in range(max(1, int(pages))):
            try:
                page.run_js("window.scrollTo(0, document.body.scrollHeight);")
                page.wait(1)
            except Exception:
                break
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
                if item.get("contact"):  # 已沟通过，跳过（避免重复投递）
                    continue
                raw = {}
                for std, src in p.get("api_field_map", {}).items():
                    raw[std] = _dig(item, src)
                link = raw.get("岗位链接", "")
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
    except Exception as e:
        debug.append("检索异常: %s" % e)
    finally:
        try:
            page.listen.stop()  # 释放网络监听（浏览器保持打开，供下次复用）
        except Exception:
            pass
        try:
            (Path(config.BASE_DIR) / "data" / ("search_debug_%s.log" % platform_key)).write_text(
                "\n".join(debug), encoding="utf-8")
        except Exception:
            pass
        # 不 quit：保持浏览器打开（登录态/会话 cookie 依赖浏览器驻留），供下次检索与扫码复用
    return jobs


def dpage_quit(platform_key):
    page = _DPAGES.pop(platform_key, None)
    if page:
        try:
            page.quit()
        except Exception:
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
        return True, r
    except Exception as e:
        return False, str(e)
