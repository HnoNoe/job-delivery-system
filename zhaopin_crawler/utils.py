# -*- coding: utf-8 -*-
"""
utils.py —— 公共工具
=====================
日志、随机延时、文本清洗、薪资字符串解析、时间戳。
"""

import logging
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# 控制台编码：Windows 下避免中文乱码
# ---------------------------------------------------------------------------
def fix_console_encoding():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 日志：同时输出到控制台和文件
# ---------------------------------------------------------------------------
def get_logger(out_dir: Path, name: str = "boss") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%H:%M:%S")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(out_dir / "运行日志.log", encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass

    return logger


def human_sleep(low: float, high: float, reason: str = "", logger=None):
    """随机休眠，模拟真人翻页节奏。"""
    seconds = random.uniform(low, high)
    if logger:
        logger.debug(f"等待 {seconds:.1f} 秒 {reason}")
    time.sleep(seconds)


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now().strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# 文本清洗
# ---------------------------------------------------------------------------
def clean(text) -> str:
    """去掉多余空白，None 转空串。"""
    if text is None:
        return ""
    if isinstance(text, (list, tuple)):
        return " / ".join(clean(x) for x in text if clean(x))
    return re.sub(r"\s+", " ", str(text)).strip()


# ---------------------------------------------------------------------------
# 薪资解析：把 "15-25K·13薪" 这类文字变成可计算的数字
# ---------------------------------------------------------------------------
_SALARY_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*[-~—至]\s*(\d+(?:\.\d+)?)")
_SALARY_SINGLE = re.compile(r"(\d+(?:\.\d+)?)")
_MONTHS = re.compile(r"(\d{1,2})\s*薪")

# 默认一个月按 21.75 个工作日折算日薪
WORKDAYS_PER_MONTH = 21.75


def parse_salary(desc: str) -> dict:
    """
    解析薪资描述，统一换算成「K/月（千元每月）」。

    支持：15-25K·13薪 / 8-12K / 1.5-2.5万 / 200-300元/天 / 30-50元/时 / 面议

    返回 dict：
        salary_min / salary_max / salary_mid : 月薪下限/上限/中值（K）
        salary_months                        : 一年发几个月（默认 12）
        salary_annual                        : 年薪估算（万元）
        salary_band                          : 薪资档位（用于分类统计）
    """
    result = {
        "salary_min": None,
        "salary_max": None,
        "salary_mid": None,
        "salary_months": 12,
        "salary_annual": None,
        "salary_band": "薪资面议",
    }
    if not desc:
        return result

    s = clean(desc).replace(" ", "")
    if not s or "面议" in s or "议" == s:
        return result

    # 先抠出「13薪」这样的月份信息，并从字符串里删掉，避免干扰数字解析
    m_months = _MONTHS.search(s)
    if m_months:
        try:
            months = int(m_months.group(1))
            if 12 <= months <= 24:
                result["salary_months"] = months
        except ValueError:
            pass
        s = _MONTHS.sub("", s)

    unit = "K"          # 统一到 K/月
    if "元/天" in s or "元／天" in s:
        unit = "元/天"
    elif "元/时" in s or "元／时" in s or "元/小时" in s:
        unit = "元/时"
    elif "万" in s:
        unit = "万"

    m = _SALARY_RANGE.search(s)
    if m:
        low, high = float(m.group(1)), float(m.group(2))
    else:
        m = _SALARY_SINGLE.search(s)
        if not m:
            return result
        low = high = float(m.group(1))

    if unit == "万":                       # 1.5-2.5 万/月 -> 15-25K
        low, high = low * 10, high * 10
    elif unit == "元/天":                  # 250 元/天 -> 5.4K/月
        low = low * WORKDAYS_PER_MONTH / 1000
        high = high * WORKDAYS_PER_MONTH / 1000
    elif unit == "元/时":                  # 40 元/时 -> 约 7K/月（按 8h*21.75d）
        low = low * 8 * WORKDAYS_PER_MONTH / 1000
        high = high * 8 * WORKDAYS_PER_MONTH / 1000

    if low > high:                         # 偶尔出现顺序颠倒
        low, high = high, low

    mid = round((low + high) / 2, 2)
    result.update(
        salary_min=round(low, 2),
        salary_max=round(high, 2),
        salary_mid=mid,
        salary_annual=round(mid * result["salary_months"] / 10, 2),  # K*月 -> 万元
        salary_band=salary_band(mid),
    )
    return result


def salary_band(mid) -> str:
    """月薪中值 -> 档位标签。"""
    if mid is None:
        return "薪资面议"
    if mid < 10:
        return "10K以下"
    if mid < 15:
        return "10-15K"
    if mid < 20:
        return "15-20K"
    if mid < 30:
        return "20-30K"
    if mid < 50:
        return "30-50K"
    return "50K以上"


# ---------------------------------------------------------------------------
# 经验 / 学历 归一化
# ---------------------------------------------------------------------------
def experience_level(exp: str) -> str:
    e = clean(exp)
    if not e:
        return "不限"
    if "应届" in e or "在校" in e:
        return "应届/在校"
    if "1年以内" in e:
        return "1年以内"
    if "1-3" in e or "1—3" in e:
        return "1-3年"
    if "3-5" in e or "3—5" in e:
        return "3-5年"
    if "5-10" in e or "5—10" in e:
        return "5-10年"
    if "10年" in e:
        return "10年以上"
    if "经验不限" in e or "不限" in e:
        return "不限"
    return e


def degree_level(degree: str) -> str:
    d = clean(degree)
    if not d or "不限" in d:
        return "不限"
    for key, label in [
        ("博士", "博士"),
        ("硕士", "硕士"),
        ("本科", "本科"),
        ("大专", "大专"),
        ("中专", "中专及以下"),
        ("高中", "中专及以下"),
        ("初中", "中专及以下"),
    ]:
        if key in d:
            return label
    return d
