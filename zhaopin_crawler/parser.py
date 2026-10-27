# -*- coding: utf-8 -*-
"""
parser.py —— 把智联返回的岗位数据整理成统一字段
=================================================
数据来源：检索页里 `window.__INITIAL_STATE__.positionList`（每页 20 条）。
字段名是智联自己的叫法，这里统一映射成我们自己的字段，便于换平台。

实测字段对照（2026-10-25）：
    name            岗位名称
    salary60        薪资展示串（1.4-2.8万 / 6000-12000元 / 1.7-1.9万·13薪 / 150-300元）
    salaryReal      薪资数字区间（14001-28000，单位「元/月」）
    workingExp      经验要求          education      学历要求
    companyName     公司名            companySize    公司规模
    industryName    行业              propertyName   公司性质（国企/民营/事业单位）
    workCity/cityDistrict/streetName  城市/区/街道
    publishTime     发布时间           positionUrl    岗位详情链接
    jobSkillTags    技能标签 [{name}]  welfareLabel   福利标签
    number          岗位编号（唯一，用于去重）
"""

import re

from config import DETAIL_URL
from utils import clean, now_str, salary_band

# 技能标签 / 福利标签里可能出现 dict 或 str，统一处理
def _label_values(value):
    out = []
    if not value:
        return out
    if isinstance(value, (list, tuple)):
        for v in value:
            if isinstance(v, dict):
                v = v.get("name") or v.get("value") or v.get("label") or ""
            v = clean(v)
            if v:
                out.append(v)
    elif isinstance(value, str):
        out = [clean(x) for x in re.split(r"[,，/|、;；\s]+", value) if clean(x)]
    return out


def parse_salary(salary60: str, salary_real: str) -> dict:
    """
    薪资解析。优先用 salaryReal（数字区间，单位元/月）。

    返回：salary_min/max/mid（K/月）、salary_months、salary_annual（万元）、
          salary_band（档位）、salary_unit（计薪单位）
    """
    out = {
        "salary_min": None,
        "salary_max": None,
        "salary_mid": None,
        "salary_months": 12,
        "salary_annual": None,
        "salary_band": "薪资面议",
        "salary_unit": "月",
    }
    s60 = clean(salary60)
    if not s60 and not clean(salary_real):
        return out
    if "面议" in s60:
        return out

    months = 12
    m = re.search(r"(\d{1,2})\s*薪", s60)
    if m:
        try:
            v = int(m.group(1))
            if 12 <= v <= 24:
                months = v
        except ValueError:
            pass
    out["salary_months"] = months

    lo = hi = None
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", clean(salary_real))]
    if len(nums) >= 2:
        lo, hi = nums[0], nums[1]
        if max(lo, hi) < 2000:
            # 太小，基本是「元/次（课时）」或日薪，不并入月薪统计，避免污染平均值
            out["salary_unit"] = "元/次"
            out["salary_band"] = "按次计薪"
            return out
        lo, hi = lo / 1000.0, hi / 1000.0          # 元 -> K
    else:
        m2 = re.search(r"(\d+(?:\.\d+)?)\s*[-~—至]\s*(\d+(?:\.\d+)?)", s60)
        if not m2:
            return out
        lo, hi = float(m2.group(1)), float(m2.group(2))
        if "万" in s60:
            lo, hi = lo * 10, hi * 10               # 万/月 -> K/月
        elif "元" in s60 and hi >= 1000:
            lo, hi = lo / 1000.0, hi / 1000.0       # 元/月 -> K/月

    if lo > hi:
        lo, hi = hi, lo
    mid = round((lo + hi) / 2, 2)
    out.update(
        salary_min=round(lo, 2),
        salary_max=round(hi, 2),
        salary_mid=mid,
        salary_annual=round(mid * months / 10, 2),
        salary_band=salary_band(mid),
    )
    return out


def parse_position(item: dict, keyword: str = "", source_city: str = "") -> dict:
    """把一条智联岗位转成统一记录。"""
    salary = parse_salary(item.get("salary60"), item.get("salaryReal"))

    skills = _label_values(item.get("jobSkillTags")) or _label_values(item.get("skillLabel"))
    welfare = _label_values(item.get("welfareLabel"))

    city = clean(item.get("workCity")) or clean(source_city)
    area = clean(item.get("cityDistrict"))
    street = clean(item.get("streetName"))

    job_no = clean(item.get("number"))
    link = clean(item.get("positionUrl")) or (DETAIL_URL.format(job_no) if job_no else "")

    record = {
        "job_name": clean(item.get("name")),
        "salary_desc": clean(item.get("salary60")),
        "city": city,
        "area": area,
        "street": street,
        "company": clean(item.get("companyName")),
        "industry": clean(item.get("industryName")),
        "company_type": clean(item.get("propertyName")),
        "scale": clean(item.get("companySize")),
        "stage": clean(item.get("financingStage")),
        "experience": clean(item.get("workingExp")),
        "degree": clean(item.get("education")),
        "skills": skills[:12],
        "welfare": welfare[:12],
        "publish_time": clean(item.get("publishTime")),
        "job_no": job_no,
        "job_link": link,
        "keyword": clean(keyword),
        "source_city": clean(source_city),
        "crawl_time": now_str(),
        "is_demo": bool(item.get("is_demo", False)),
    }
    record.update(salary)
    return record


def dedupe_key(record: dict) -> str:
    """去重键：岗位编号优先，其次岗位名+公司+薪资。"""
    if record.get("job_no"):
        return f"no:{record['job_no']}"
    return "sig:{}-{}-{}".format(
        record.get("job_name", ""), record.get("company", ""), record.get("salary_desc", "")
    )


def is_meaningful(record: dict) -> bool:
    return bool(record.get("job_name")) and bool(record.get("company"))
