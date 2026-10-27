# -*- coding: utf-8 -*-
"""
check_env.py —— 环境自检
=========================
第一次用之前先跑它，能提前发现「缺包 / 浏览器起不来 / 抓不到数据」的问题。

    python check_env.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def ok(msg):
    print(f"  [通过] {msg}")


def warn(msg):
    print(f"  [注意] {msg}")


def fail(msg):
    print(f"  [失败] {msg}")


def check_python():
    print("\n[1/5] Python 环境")
    print(f"  版本：{sys.version.split()[0]}  路径：{sys.executable}")
    if sys.version_info < (3, 9):
        fail("需要 Python 3.9 及以上版本。")
        return False
    ok("Python 版本可用。")
    return True


def check_packages():
    print("\n[2/5] 依赖库")
    missing = []
    for mod in ("playwright", "openpyxl", "requests"):
        try:
            m = __import__(mod)
            ok(f"{mod} 已安装（{getattr(m, '__version__', '?')}）")
        except ImportError:
            fail(f"{mod} 未安装 -> 请执行：pip install {mod}")
            missing.append(mod)
    return not missing


def check_browser():
    print("\n[3/5] 浏览器")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        for channel in ("msedge", "chrome"):
            try:
                b = p.chromium.launch(channel=channel, headless=True)
                b.close()
                ok(f"可以使用本机 {channel}。")
                return True
            except Exception:
                continue
        try:
            b = p.chromium.launch(headless=True)
            b.close()
            ok("可以使用 Playwright 自带 Chromium。")
            return True
        except Exception as e:  # noqa: BLE001
            fail(f"没有可用浏览器：{e}")
            warn("解决办法：安装 Edge/Chrome，或执行 python -m playwright install chromium")
            return False


def check_network():
    print("\n[4/5] 网络")
    try:
        import requests

        r = requests.get("https://sou.zhaopin.com/", timeout=15,
                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                                "Chrome/140.0.0.0 Safari/537.36"})
        if r.status_code == 200:
            ok(f"可以访问 sou.zhaopin.com（HTTP {r.status_code}）")
            return True
        warn(f"访问返回 HTTP {r.status_code}")
        return False
    except Exception as e:  # noqa: BLE001
        fail(f"无法访问 sou.zhaopin.com：{e}")
        return False


def check_crawl():
    print("\n[5/5] 实际抓取测试（北京 · Python）")
    from config import Settings
    from scraper import ZhaopinScraper
    from utils import fix_console_encoding, get_logger

    fix_console_encoding()
    log = get_logger(ROOT, "check")
    log.handlers = [h for h in log.handlers if h.__class__.__name__ != "StreamHandler"]

    settings = Settings(keywords=["Python"], cities=["北京"], max_jobs=20)
    scraper = ZhaopinScraper(settings, ROOT, log)
    try:
        scraper._start_browser()
        items, url = scraper._fetch_combo("Python", "530")
        if items:
            ok(f"抓取正常：拿到 {len(items)} 条岗位，示例「{items[0].get('name')}」"
               f"（{items[0].get('salary60')}）")
            return True
        fail("没有拿到数据，可能被反爬拦截或网络异常。")
        warn("建议：等 10 分钟再试；或先跑 python main.py --demo 确认导出流程没问题。")
        return False
    except Exception as e:  # noqa: BLE001
        fail(f"抓取测试失败：{e}")
        return False
    finally:
        scraper._shutdown()


def main():
    try:
        from utils import fix_console_encoding
        fix_console_encoding()
    except Exception:
        pass
    print("=" * 60)
    print("  智联招聘采集工具 · 环境自检")
    print("=" * 60)

    results = [("Python", check_python())]
    pk_ok = check_packages()
    results.append(("依赖库", pk_ok))
    if not pk_ok:
        print("\n请先安装缺失的依赖，再重新运行本脚本。")
        return 1

    results.append(("浏览器", check_browser()))
    results.append(("网络", check_network()))
    results.append(("抓取", check_crawl()))

    print("\n" + "=" * 60)
    print("  自检结果")
    print("=" * 60)
    for name, good in results:
        print(f"  {name:<6}：{'正常' if good else '需处理'}")

    if all(g for _, g in results):
        print("\n环境正常，可以运行：python main.py")
        return 0
    print("\n请按上面的提示处理后再试。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
