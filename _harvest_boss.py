"""真实 Boss 岗位采集：多关键词 x 每词多页，DrissionPage 旁听浏览器接口（规避 code:37）。

运行：python _harvest_boss.py
（复用 sessions/boss.json 持久化 profile 的登录浏览器；词间限速 4 秒；
 store_jobs 只调一次，避免旧批次被置 inactive）
"""
import time

import matching
import session

KEYWORDS = ["Python", "Java", "前端", "后端", "算法", "数据分析",
            "测试", "产品", "运营", "机械", "财务", "销售", "设计", "嵌入式"]

all_jobs = []
for kw in KEYWORDS:
    try:
        jobs = session.dpage_search("boss", kw, pages=3)
    except Exception as e:  # noqa
        print("[失败]", kw, e)
        jobs = []
    print("%-8s 抓到 %d 个" % (kw, len(jobs)), flush=True)
    all_jobs.extend(jobs)
    if jobs:
        time.sleep(4)

print("原始合计:", len(all_jobs))
n = matching.store_jobs(all_jobs) if all_jobs else 0
print("去重入库:", n)
