# -*- coding: utf-8 -*-
"""
main.py —— 程序入口
====================
在 PyCharm 里右键 Run 这个文件即可；也可以在终端里运行：

    python main.py                      # 正式采集（默认 8 关键词 × 8 城市，上限 600 条）
    python main.py --demo               # 演示模式：不联网，生成 600 条示例数据
    python main.py -k "Python,Java" -c "北京,上海" -m 300
    python main.py --open               # 跑完自动打开生成的 Excel
    python main.py --headless           # 无窗口运行（可能被反爬识别，不推荐）
"""

import argparse
import json
import sys
import time
from pathlib import Path

import analytics
import demo_data
import exporter
from classifier import enrich
from config import (CITY_CODES, DEFAULT_CITIES, DEFAULT_KEYWORDS, OUTPUT_CSV,
                    OUTPUT_XLSX, RAW_JSON, Settings)
from parser import dedupe_key, is_meaningful, parse_position
from scraper import ZhaopinScraper
from utils import fix_console_encoding, get_logger

ROOT = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="智联招聘岗位采集与分类分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python main.py -k Python,Java -c 北京,上海 -m 300",
    )
    p.add_argument("-k", "--keywords", default=",".join(DEFAULT_KEYWORDS),
                   help="搜索关键词，多个用英文逗号分隔（默认：%(default)s）")
    p.add_argument("-c", "--cities", default=",".join(DEFAULT_CITIES),
                   help="城市，多个用英文逗号分隔（默认：%(default)s）")
    p.add_argument("-m", "--max", type=int, default=600,
                   help="最多抓多少条（去重后，默认：%(default)s）")
    p.add_argument("--min-delay", type=float, default=1.0, help="两个组合之间的最小间隔秒数")
    p.add_argument("--max-delay", type=float, default=2.5, help="两个组合之间的最大间隔秒数")
    p.add_argument("--headless", action="store_true",
                   help="无头模式（不显示浏览器窗口）；可能被反爬识别，不推荐")
    p.add_argument("--demo", action="store_true",
                   help="演示模式：用示例数据跑通全流程，不访问网站")
    p.add_argument("--from-raw", action="store_true",
                   help="不联网，用上次抓到的 raw/原始数据.json 重新分类并导出（改了分类规则时用）")
    p.add_argument("--open", action="store_true", help="结束后自动打开生成的 Excel")
    return p


def parse_list(text: str):
    items = [x.strip() for x in str(text).replace("，", ",").split(",")]
    return [x for x in items if x]


def banner(log):
    log.info("=" * 62)
    log.info("  智联招聘 岗位采集 + 智能分类 工具")
    log.info("  仅供个人学习与求职分析使用，请控制频率、遵守网站规则")
    log.info("=" * 62)


def save_raw(records, meta):
    path = ROOT / RAW_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "records": records}, f, ensure_ascii=False, indent=1)
    return path


def main(argv=None) -> int:
    fix_console_encoding()
    args = build_parser().parse_args(argv)

    log = get_logger(ROOT)
    banner(log)

    keywords = parse_list(args.keywords)
    cities = parse_list(args.cities)
    unknown = [c for c in cities if c not in CITY_CODES]
    if unknown:
        log.error(f"不认识的城市：{'、'.join(unknown)}")
        log.error(f"可用城市：{'、'.join(CITY_CODES)}")
        return 1
    if not keywords:
        log.error("至少要给一个搜索关键词。")
        return 1

    settings = Settings(
        keywords=keywords,
        cities=cities,
        max_jobs=args.max,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        headless=args.headless,
    )
    started = time.time()

    # ---------------- 用上次的原始数据重新导出 ----------------
    if args.from_raw:
        path = ROOT / RAW_JSON
        if not path.exists():
            log.error(f"没找到 {RAW_JSON}，请先正常抓取一次。")
            return 1
        data = json.loads(path.read_text(encoding="utf-8"))
        records = [enrich(r) for r in data.get("records", [])]
        meta = data.get("meta", {}) or {}
        meta.setdefault("source", "智联招聘（sou.zhaopin.com）")
        meta["mode"] = meta.get("mode", "api")
        meta["elapsed"] = round(time.time() - started, 1)
        log.info(f"已从 {path.name} 载入 {len(records)} 条，按当前分类规则重新导出。")
        if not records:
            log.error("原始数据是空的。")
            return 1

    # ---------------- 演示模式 ----------------
    elif args.demo:
        log.info("演示模式：生成示例岗位数据（不访问智联招聘）。")
        count = max(50, args.max)
        records = demo_data.generate(count=count)
        meta = {
            "mode": "demo",
            "source": "示例数据（非真实在招岗位）",
            "is_demo": True,
            "elapsed": round(time.time() - started, 1),
            "params": f"演示数据 {count} 条",
        }
        log.info(f"已生成 {len(records)} 条示例岗位。")
    else:
        # ---------------- 正式采集 ----------------
        log.info(settings.summary())
        log.info("提示：智联的检索页不需要登录，工具会打开浏览器逐个组合抓取。")
        scraper = ZhaopinScraper(settings, ROOT, log)
        try:
            raw_records, meta = scraper.run()
        except Exception as e:  # noqa: BLE001
            log.error(f"采集失败：{e}")
            log.error("可以先用 `python main.py --demo` 验证导出流程。")
            return 1

        records = [enrich(r) for r in raw_records]
        meta["is_demo"] = False
        meta["source"] = "智联招聘（sou.zhaopin.com）"
        meta["params"] = (
            f"关键词：{'、'.join(keywords)}；城市：{'、'.join(cities)}；"
            f"上限 {settings.max_jobs} 条"
        )
        if not records:
            log.error("一条数据都没抓到。常见原因：")
            log.error("  1) 被反爬拦截（页面变成 Security Verification）—— 等 10 分钟再试；")
            log.error("  2) 网络不稳定 —— 重跑一次；")
            log.error("  3) 关键词太冷门 —— 换常见关键词试试。")
            return 1

    # ---------------- 分类 + 统计 ----------------
    records = [enrich(r) for r in records]
    stats = analytics.build_all(records)
    analytics.print_summary(stats, log)

    # ---------------- 导出 ----------------
    excel_path = exporter.export_excel(records, stats, meta, ROOT / OUTPUT_XLSX, log)
    csv_path = exporter.export_csv(records, ROOT / OUTPUT_CSV, log)
    raw_path = save_raw(records, meta)

    log.info("")
    log.info("已生成文件：")
    log.info(f"  Excel：{excel_path}")
    log.info(f"  CSV  ：{csv_path}")
    log.info(f"  原始数据：{raw_path}")
    log.info(f"总耗时：{time.time() - started:.1f} 秒")

    if meta.get("is_demo"):
        log.info("")
        log.info("注意：这是【演示数据】。要抓真实岗位，去掉 --demo 重新运行即可。")

    if args.open:
        try:
            import os
            target = excel_path if excel_path.exists() else excel_path.parent
            os.startfile(str(target))  # noqa: S606
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
