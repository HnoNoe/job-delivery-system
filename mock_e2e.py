"""Mock Boss 全量端到端测试：检索 → 画像 → 匹配 → 生成简历 → 投递 → 反馈 → 画像演进。

全程对本地 mock 站（mock_site.py）发起真实 HTTP 请求，不碰真实 Boss 直聘。
"""
import sys
import io
import json
import time
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import config
import db
import session
import crawler
import pipeline
import delivery
import feedback
import mock_site

# ---------- 准备：启动 mock 站 + 造登录态 + 清库 ----------
if mock_site.GREETS_FILE.exists():
    mock_site.GREETS_FILE.unlink()
srv = mock_site.start_in_background()
time.sleep(0.5)
session.save_cookies("mock", [{"name": "mock_login", "value": "1"}])
db.init_db()

# ---------- ① 检索（真实 HTTP 请求到 mock 站） ----------
jobs = crawler.search_via_requests("mock", "后端", city="北京", pages=1)
print("① 检索 OK：%d 个岗位（首个：%s @ %s）" % (
    len(jobs), jobs[0]["岗位名称"] if jobs else "-", jobs[0]["单位名称"] if jobs else "-"))
assert jobs, "检索结果为空"

# ---------- ② 全流程（画像 → 匹配 → 建任务 → 生成简历 → 准备投递材料） ----------
config.SAFE_MODE = True
user_data = {
    "l0": {"姓名": "张三", "性别": "男", "出生日期": "2001-05-06", "手机": "13800138000",
           "邮箱": "zhangsan@example.com", "政治面貌": "共青团员", "民族": "汉族",
           "现居": "北京", "籍贯": "北京", "学历阶段": "本科在读", "学校": "示例大学",
           "学院": "计算机学院", "专业": "软件工程", "入学年月": "2020-09", "毕业年月": "2024-06"},
    "l1": {"实习/工作": 1, "项目": 1},
    "l2": [
        {"类型": "实习/工作", "名称": "字节跳动 Python后端实习生", "角色": "实习生",
         "时间起": "2023-06", "时间止": "2023-09", "事项": "负责订单系统接口开发，使用 Flask + MySQL",
         "结果": "接口响应提升30%", "技术工具": "Python, Flask, MySQL", "挂靠": "独立", "证据": "无"},
        {"类型": "项目", "名称": "电商秒杀系统", "角色": "成员",
         "时间起": "2023-01", "时间止": "2023-05", "事项": "基于 Spring Boot 实现秒杀",
         "结果": "QPS 1000", "技术工具": "Java, Spring, Redis", "挂靠": "独立", "证据": "无"},
    ],
    "l3": {"意向城市": "北京", "意向岗位": "后端开发", "意向行业": "互联网",
           "到岗时间": "2024-07", "期望薪资": "15k/月", "投递策略": "海投", "能否出差": "是"},
}
r = pipeline.run_full_pipeline(user_data, jobs=jobs)
print("② 全流程 OK：匹配 %d 岗，画像技能 %s" % (
    r["task_count"], "、".join(r["画像摘要"].get("技能标签", []))))
assert r["ok"] and r["task_count"] > 0, "全流程失败"

# ---------- ③ 投递（关闭安全模式，走 API 投递到 mock 站） ----------
config.SAFE_MODE = False
sc = Path(config.BASE_DIR) / "data" / "send_count.txt"
if sc.exists():
    sc.unlink()
batch = delivery.deliver_batch()
print("③ 投递 OK：成功 %d / 失败 %d（%s）" % (
    batch["成功数"], batch["失败数"], batch["停止原因"] or "无停止"))
assert batch["成功数"] > 0, "投递失败：" + str(batch)

# ---------- ④ 反馈（式五权重更新 + 画像演进） ----------
tid = r["target_jobs"][0]["task_id"]
ok, w = feedback.mark_result(tid, 1)
ev = feedback.get_profile_evolution(r["user_id"])
print("④ 反馈 OK：进面试，权重 [%s]，画像演进快照 %d" % (
    ", ".join("%.3f" % x for x in w), len(ev)))
assert ok and ev, "反馈失败"

# ---------- ⑤ 验证 mock 站确实收到投递 ----------
greets = mock_site._read_greets()
print("⑤ mock 站收到投递 %d 条（首条：%s）" % (
    len(greets), json.dumps(greets[0]["payload"], ensure_ascii=False)[:80] if greets else "-"))
assert len(greets) > 0, "mock 站未收到投递"

mock_site.stop_server()
print()
print("=== Mock Boss 全量端到端测试通过 ===")
