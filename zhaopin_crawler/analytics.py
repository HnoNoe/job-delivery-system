# -*- coding: utf-8 -*-
"""
analytics.py —— 统计汇总
=========================
把岗位列表算成一组"看得懂"的结论：各分类多少岗、平均薪资多少、
哪个城市岗位最多、哪些技能最抢手。
"""

from collections import Counter
from statistics import median

from utils import clean

SALARY_BAND_ORDER = ["10K以下", "10-15K", "15-20K", "20-30K", "30-50K", "50K以上", "薪资面议"]


def _salary_values(records):
    return [float(r["salary_mid"]) for r in records if r.get("salary_mid") is not None]


def category_stats(records):
    """一级分类：[{分类, 岗位数, 占比%, 平均月薪K}]，按岗位数降序。"""
    total = len(records) or 1
    bucket = {}
    for r in records:
        l1 = r.get("category_l1") or "其他"
        item = bucket.setdefault(l1, {"count": 0, "salaries": []})
        item["count"] += 1
        if r.get("salary_mid") is not None:
            item["salaries"].append(float(r["salary_mid"]))

    rows = []
    for l1, item in bucket.items():
        rows.append({
            "分类": l1,
            "岗位数": item["count"],
            "占比%": round(item["count"] / total * 100, 1),
            "平均月薪K": round(sum(item["salaries"]) / len(item["salaries"]), 1) if item["salaries"] else None,
        })
    return sorted(rows, key=lambda x: -x["岗位数"])


def sub_category_stats(records):
    """二级分类：[{一级分类, 二级分类, 岗位数, 平均月薪K}]。"""
    bucket = {}
    for r in records:
        key = (r.get("category_l1") or "其他", r.get("category_l2") or "未分类")
        item = bucket.setdefault(key, {"count": 0, "salaries": []})
        item["count"] += 1
        if r.get("salary_mid") is not None:
            item["salaries"].append(float(r["salary_mid"]))
    rows = []
    for (l1, l2), item in bucket.items():
        rows.append({
            "一级分类": l1,
            "二级分类": l2,
            "岗位数": item["count"],
            "平均月薪K": round(sum(item["salaries"]) / len(item["salaries"]), 1) if item["salaries"] else None,
        })
    return sorted(rows, key=lambda x: (x["一级分类"], -x["岗位数"]))


def city_stats(records):
    """城市统计：[{城市, 岗位数, 平均月薪K, 最高月薪K}]。"""
    bucket = {}
    for r in records:
        city = clean(r.get("city")) or "未知"
        item = bucket.setdefault(city, {"count": 0, "salaries": []})
        item["count"] += 1
        if r.get("salary_mid") is not None:
            item["salaries"].append(float(r["salary_mid"]))
    rows = []
    for city, item in bucket.items():
        sals = item["salaries"]
        rows.append({
            "城市": city,
            "岗位数": item["count"],
            "平均月薪K": round(sum(sals) / len(sals), 1) if sals else None,
            "最高月薪K": max(sals) if sals else None,
        })
    return sorted(rows, key=lambda x: -x["岗位数"])


def salary_stats(records):
    """薪资分布 + 总体统计。"""
    values = _salary_values(records)
    distribution = Counter(r.get("salary_band") or "薪资面议" for r in records)
    dist_rows = [
        {"薪资档位": band, "岗位数": distribution.get(band, 0)}
        for band in SALARY_BAND_ORDER
    ]

    overall = {
        "岗位总数": len(records),
        "有效薪资样本": len(values),
        "平均月薪K": round(sum(values) / len(values), 1) if values else None,
        "月薪中位数K": round(median(values), 1) if values else None,
        "月薪最高K": round(max(values), 1) if values else None,
        "月薪最低K": round(min(values), 1) if values else None,
    }
    return dist_rows, overall


def skill_stats(records, top=30):
    """技能词频。"""
    counter = Counter()
    for r in records:
        for s in r.get("skills") or []:
            s = clean(s)
            if s and len(s) <= 20:
                counter[s] += 1
    return [{"技能标签": k, "出现岗位数": v} for k, v in counter.most_common(top)]


def company_stats(records, top=20):
    """招聘量最大的公司。"""
    counter = Counter(clean(r.get("company")) for r in records if clean(r.get("company")))
    rows = []
    for name, cnt in counter.most_common(top):
        sals = [float(r["salary_mid"]) for r in records
                if clean(r.get("company")) == name and r.get("salary_mid") is not None]
        rows.append({
            "公司": name,
            "在招岗位数": cnt,
            "平均月薪K": round(sum(sals) / len(sals), 1) if sals else None,
        })
    return rows


def dimension_stats(records, field, order=None):
    """通用维度统计：经验、学历等。"""
    counter = Counter(clean(r.get(field)) or "未标注" for r in records)
    rows = [{"项目": k, "岗位数": v} for k, v in counter.most_common()]
    if order:
        rows.sort(key=lambda x: order.index(x["项目"]) if x["项目"] in order else 99)
    return rows


def build_all(records):
    """一次性算出全部统计结果。"""
    dist_rows, overall = salary_stats(records)
    return {
        "overall": overall,
        "category": category_stats(records),
        "sub_category": sub_category_stats(records),
        "city": city_stats(records),
        "salary_dist": dist_rows,
        "skills": skill_stats(records),
        "companies": company_stats(records),
        "experience": dimension_stats(
            records, "exp_level",
            ["应届/在校", "1年以内", "1-3年", "3-5年", "5-10年", "10年以上", "不限"]),
        "degree": dimension_stats(
            records, "degree_level", ["博士", "硕士", "本科", "大专", "中专及以下", "不限"]),
    }


def print_summary(stats, logger):
    """控制台打印结论。"""
    o = stats["overall"]
    logger.info("=" * 62)
    logger.info(f"采集完成：共 {o['岗位总数']} 个岗位（有效薪资样本 {o['有效薪资样本']} 个）")
    if o["平均月薪K"]:
        logger.info(
            f"薪资水平：平均 {o['平均月薪K']}K/月，中位数 {o['月薪中位数K']}K/月，"
            f"区间 {o['月薪最低K']}K ~ {o['月薪最高K']}K"
        )
    logger.info("分类分布（Top 8）：")
    for row in stats["category"][:8]:
        avg = f"平均{row['平均月薪K']}K" if row["平均月薪K"] else "薪资面议"
        logger.info(f"  {row['分类']:<10} {row['岗位数']:>4} 个  ({row['占比%']:>4.1f}%)  {avg}")
    logger.info("城市分布（Top 5）：")
    for row in stats["city"][:5]:
        avg = f"平均{row['平均月薪K']}K" if row["平均月薪K"] else "薪资面议"
        logger.info(f"  {row['城市']:<8} {row['岗位数']:>4} 个  {avg}")
    if stats["skills"]:
        logger.info("最热技能：" + "、".join(f"{s['技能标签']}({s['出现岗位数']})" for s in stats["skills"][:10]))
    logger.info("=" * 62)
