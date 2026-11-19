"""城市 / 行业归一化匹配（硬约束过滤与等级分共用同一套口径）。

背景（实测 2026-11-18）：Boss 返回的城市常带区县（`北京 海淀`）、行业是细分标签
（`计算机软件`、`软件/IT服务`、`信息安全`…），而用户填的是 `北京`、`互联网`。
原实现用字符串精确相等，导致 19 个北京岗位、19 个互联网相关岗位被误杀。

规则：
- 城市按“核心城市名”匹配：`北京 海淀` → `北京`；`北京-海淀区` 也归一为 `北京`；
- 行业按别名组归并（`config.INDUSTRY_ALIASES` 可改）：
  `计算机软件/软件/IT服务/电子商务/信息安全…` 视为 `互联网`，
  `智能硬件/机器人/机器学习…` 视为 `人工智能`；
- 字段缺失一律视为“未知”，不据此过滤（宁多勿漏，与原逻辑一致）。
"""
import re

import config


def city_parts(city):
    """拆城市串：`北京 海淀` / `北京-海淀区` / `北京/海淀` → ['北京','海淀...']。"""
    return [p for p in re.split(r"[\s\-·/,，、]+", str(city or "").strip()) if p]


def city_core(city):
    """取城市核心名（第一段，去掉“市/地区”后缀）。"""
    parts = city_parts(city)
    if not parts:
        return ""
    return re.sub(r"(市|地区)$", "", parts[0])


def city_match(job_city, wanted):
    """岗位城市是否命中意向城市列表。wanted 为空/岗位城市缺失 → True（不过滤）。"""
    wanted = [w for w in (wanted or []) if str(w).strip()]
    if not wanted:
        return True
    if not str(job_city or "").strip():
        return True
    job_parts = city_parts(job_city)
    job_core = city_core(job_city)
    for w in wanted:
        w_core = city_core(w)
        if not w_core:
            continue
        if job_core == w_core:
            return True
        if w_core in job_parts:
            return True
        # 兼容“北京” vs “北京市”“北京地区”等写法
        if job_core.startswith(w_core) or w_core.startswith(job_core):
            return True
    return False


DEFAULT_INDUSTRY_ALIASES = {
    "互联网": ("互联网", "计算机软件", "软件", "it服务", "信息技术", "电子商务", "电商",
               "企业服务", "社交", "网络", "云计算", "大数据", "信息安全", "通信", "游戏"),
    "人工智能": ("人工智能", "ai", "智能硬件", "机器人", "机器学习", "计算机视觉",
                 "自然语言", "算法"),
}


def industry_groups():
    return getattr(config, "INDUSTRY_ALIASES", DEFAULT_INDUSTRY_ALIASES)


def canonical_industry(label):
    """把细分行业归并到别名组；未命中则返回小写原值。"""
    text = str(label or "").strip().lower()
    if not text:
        return ""
    for group, keys in industry_groups().items():
        for key in keys:
            if str(key).lower() in text:
                return group
    return text


def industry_match(job_industry, wanted):
    """岗位行业是否命中意向行业（按别名组比较）。缺失 → True（不过滤）。"""
    wanted = [w for w in (wanted or []) if str(w).strip()]
    if not wanted:
        return True
    if not str(job_industry or "").strip():
        return True
    job_group = canonical_industry(job_industry)
    return any(canonical_industry(w) == job_group for w in wanted)
