"""flow.py + cloud_sync.py 联调测试（隔离环境，不污染真实本地库）。

- flow：mock 站走通 检索→全流程→任务列表→详情→安全投递→反馈回写→现场恢复；
- cloud_sync：push 2 条假岗位到云（owner=selftest）→ 删本地 → pull 回来 → 断言计数；
  测试结束后删除云端 owner='selftest' 的行，保持云库干净。
"""
import sys
import io
import json
import time
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from test_support import isolate_test_environment
isolate_test_environment()

import config
import db
import session
import platforms
import mock_site
import flow
import cloud_sync

# ---------- 准备：mock 站 + 登录态 ----------
if mock_site.GREETS_FILE.exists():
    mock_site.GREETS_FILE.unlink()
srv = mock_site.start_in_background(port=0)
for key in ("login_url", "search_url", "api_url"):
    platforms.PLATFORMS["mock"][key] = platforms.PLATFORMS["mock"][key].replace(":5001/", ":%d/" % srv.server_address[1])
time.sleep(0.5)
session.save_cookies("mock", [{"name": "mock_login", "value": "1"}])
db.init_db()

# ---------- ① flow 基础查询 ----------
plats = flow.available_platforms()
names = [p["key"] for p in plats]
assert "mock" in names, "平台注册表缺 mock：%s" % names
print("① 平台注册表 OK：%s" % "、".join(names))

states = flow.login_states(online=False)
assert "mock" in states, "登录态缺 mock"
print("   登录态 OK：mock=%s" % states["mock"]["state"])

# ---------- ② 检索 → 全流程 ----------
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
jobs, logs = flow.search(user_data, ["mock"], "后端", pages=1)
assert jobs, "flow.search 无结果"
print("② 检索 OK：%d 个岗位" % len(jobs))

r = flow.run_pipeline(user_data, jobs)
assert r["ok"] and r["task_count"] > 0, "run_pipeline 失败：%s" % r
uid = r["user_id"]
print("   全流程 OK：匹配 %d 岗，画像技能 %s" % (r["task_count"], "、".join(r["画像摘要"].get("技能标签", []))))

# ---------- ③ 任务列表 + 详情 ----------
tl = flow.list_tasks(uid)
assert tl, "任务列表为空"
tid = r["target_jobs"][0]["task_id"]
detail = flow.task_detail(tid)
assert detail is not None, "task_detail 返回 None"
assert detail.get("简历内容"), "详情缺简历内容"
print("③ 任务 OK：%d 条，详情含简历字段 %d 个，招呼语 %d 字" % (
    len(tl), len(detail["简历内容"]), len(detail.get("招呼语") or "")))

# ---------- ④ 安全模式单条投递 ----------
config.SAFE_MODE = True
ok, material = flow.deliver_one(tid)
assert ok, "安全模式投递失败"
print("④ 安全投递 OK：材料 %d 字" % len(str(material)))

# ---------- ⑤ 反馈回写 + 现场恢复 ----------
fb = flow.mark_feedback(tid, 1)
assert fb["ok"], "反馈失败：%s" % fb
print("⑤ 反馈 OK：stats=%s" % json.dumps(fb.get("stats") or {}, ensure_ascii=False)[:100])
scene = flow.restore_scene()
assert scene and scene.get("task_count") == r["task_count"], "现场恢复不一致"
print("   现场恢复 OK：task_count=%s" % scene["task_count"])

# ---------- ⑥ cloud_sync 双向（owner=selftest，完事清云） ----------
# 用本轮唯一标签构造稳定去重键，避免与历次测试/其它运行互相干扰
import time as _t
tag = "r%d" % int(_t.time())
conn = db.get_conn()
conn.execute("DELETE FROM jobs")  # 清掉 mock 检索岗位，只留自测数据做精确断言
fake_jobs = [
    {"岗位名称": "自测岗位A", "单位名称": "自测公司", "城市": "北京", "岗位链接": "https://selftest.example/%s/a" % tag},
    {"岗位名称": "自测岗位B", "单位名称": "自测公司", "城市": "上海", "岗位链接": "https://selftest.example/%s/b" % tag},
]
conn.executemany("INSERT INTO jobs (fields, embedding, active) VALUES (?, NULL, 1)",
                 [(json.dumps(f, ensure_ascii=False),) for f in fake_jobs])
conn.commit()
conn.close()

pushed = cloud_sync.push_jobs("selftest")
assert pushed["新增"] == 2, "push 新增数不对：%s" % pushed
print("⑥ 云同步 OK：push %s" % pushed)

# 再 push 一次应全部判重
again = cloud_sync.push_jobs("selftest")
assert again["新增"] == 0, "重复 push 未去重：%s" % again

# 删本地后 pull 回来（含其它 owner 的岗位也无妨，隔离库）
conn = db.get_conn()
conn.execute("DELETE FROM jobs")
conn.commit()
conn.close()
pulled = cloud_sync.pull_jobs()
assert pulled["拉回"] >= 2, "pull 数量不对：%s" % pulled
conn = db.get_conn()
back = conn.execute("SELECT COUNT(*) FROM jobs WHERE fields LIKE '%自测岗位%'").fetchone()[0]
conn.close()
assert back == 2, "pull 后自测岗位 missing：%d" % back
print("   pull OK：拉回 %d 条，自测岗位找回 %d 条" % (pulled["拉回"], back))
print("   pool_counts：%s" % cloud_sync.pool_counts())

# 清理云端 selftest 数据，保持云库干净
with db.use_cloud():
    conn = db.get_conn()
    conn.execute("DELETE FROM jobs WHERE owner='selftest'")
    conn.commit()
    left = conn.execute("SELECT COUNT(*) FROM jobs WHERE owner='selftest'").fetchone()[0]
    conn.close()
assert left == 0, "云端 selftest 未清干净"
print("   云端 selftest 数据已清理（残留 %d）" % left)

mock_site.stop_server()
print()
print("=== flow + cloud_sync 联调测试通过 ===")
