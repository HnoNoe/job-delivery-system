# -*- coding: utf-8 -*-
"""
config.py —— 全局配置
======================
只想改"搜什么、搜哪些城市"的话，改 DEFAULT_KEYWORDS 和 DEFAULT_CITIES 就够了。
"""

SEARCH_URL = "https://sou.zhaopin.com/"
DETAIL_URL = "https://www.zhaopin.com/jobdetail/{}.htm"

# ---------------------------------------------------------------------------
# 城市名 -> 智联招聘 city 编码（jl 参数）
# 全部在 2026-10-25 实测确认过（用真实浏览器逐个打开核对返回的城市名）
# 想加城市：浏览器打开智联搜索页、切到该城市，地址栏 jl= 后面那三位数字就是
# ---------------------------------------------------------------------------
CITY_CODES = {
    "北京": "530",
    "上海": "538",
    "广州": "763",
    "深圳": "765",
    "杭州": "653",
    "成都": "801",
    "武汉": "736",
    "南京": "635",
    "西安": "854",
    "苏州": "639",
    "长沙": "749",
    "郑州": "719",
    "重庆": "551",
    "天津": "531",
    "合肥": "664",
    "厦门": "682",
    "济南": "702",
    "宁波": "654",
    "佛山": "768",
    "珠海": "766",
}

# ---------------------------------------------------------------------------
# 默认搜索关键词 / 城市
# 每个「关键词 × 城市」组合返回 20 条，所以组合越多抓得越多
# ---------------------------------------------------------------------------
DEFAULT_KEYWORDS = ["Python", "Java", "前端", "数据分析", "产品经理", "运营", "测试", "算法"]

DEFAULT_CITIES = ["北京", "上海", "深圳", "杭州", "广州", "成都", "武汉", "南京"]

# 每个组合固定 20 条（智联这个检索页不支持翻页，实测 hasMore=False）
PER_COMBO = 20

# 输出位置（相对于本文件夹）
OUTPUT_XLSX = "output/智联招聘岗位数据.xlsx"
OUTPUT_CSV = "output/智联招聘岗位数据.csv"
RAW_JSON = "raw/原始数据.json"
LOG_FILE = "运行日志.log"
BROWSER_PROFILE = "browser_data"


class Settings:
    """一次采集任务的参数，由 main.py 根据命令行生成。"""

    def __init__(self, keywords=None, cities=None, max_jobs=600, min_delay=1.0,
                 max_delay=2.5, headless=False, max_retry=2):
        self.keywords = list(keywords or DEFAULT_KEYWORDS)
        self.cities = list(cities or DEFAULT_CITIES)
        self.max_jobs = max(1, int(max_jobs))
        self.min_delay = float(min_delay)
        self.max_delay = float(max_delay)
        self.headless = bool(headless)
        self.max_retry = int(max_retry)

    def queries(self):
        """展开成 [(关键词, 城市名, 城市编码), ...]。"""
        out = []
        for kw in self.keywords:
            for city in self.cities:
                code = CITY_CODES.get(city)
                if not code:
                    raise ValueError(
                        f"未知城市：{city}。请到 config.py 的 CITY_CODES 里补充其编码。"
                    )
                out.append((kw, city, code))
        return out

    def summary(self):
        n = len(self.keywords) * len(self.cities)
        return (
            f"关键词 {len(self.keywords)} 个：{'、'.join(self.keywords)}\n"
            f"城市 {len(self.cities)} 个：{'、'.join(self.cities)}\n"
            f"共 {n} 个组合 × 每组合 {PER_COMBO} 条（理论上限 {n * PER_COMBO} 条），"
            f"总数上限 {self.max_jobs} 条"
        )
