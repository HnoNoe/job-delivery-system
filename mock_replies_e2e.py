"""Mock 站验证：方案 B —— 手动触发「检查新回复」+ 登记 HR 回应。

全程只对本地 mock 站（127.0.0.1:随机端口）发起 HTTP 请求，不碰真实平台。验证：

① 投递后 mock 站产生会话列表（含「你已发送招呼语」）；
② 模拟两名 HR 回复（邀面试 / 已招满）后，`replies.check("mock", tasks)` 能读到会话、
   正确匹配到对应投递任务，并把消息分类为「邀面试 / 不合适」；
③ 勾选登记后写入 hr_responses（source=auto），重复登记幂等；
④ 检查过程是**只读**：不新增投递、不发送招呼语、不新增任务；
⑤ 未配置/接口异常时如实返回错误，不伪造结果。

运行：.venv\\Scripts\\python.exe mock_replies_e2e.py
"""
import io
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from test_support import isolate_test_environment  # noqa: E402

isolate_test_environment()

import config  # noqa: E402
import crawler  # noqa: E402
import db  # noqa: E402
import delivery  # noqa: E402
import feedback  # noqa: E402
import mock_site  # noqa: E402
import pipeline  # noqa: E402
import platforms  # noqa: E402
import replies  # noqa: E402
import responses  # noqa: E402
import session  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("（%s）" % detail if detail and not cond else ""))
    if not cond:
        failures.append(name)
    return bool(cond)


def get_json(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def post_json(url, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


USER = {
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

# ---------- 准备 ----------
for f in (mock_site.GREETS_FILE, mock_site.REPLIES_FILE):
    if f.exists():
        f.unlink()
srv = mock_site.start_in_background(port=0)
port = srv.server_address[1]
base = "http://127.0.0.1:%d" % port
for key in ("login_url", "search_url", "api_url", "chat_url", "chat_api_url"):
    platforms.PLATFORMS["mock"][key] = platforms.PLATFORMS["mock"][key].replace(":5001/", ":%d/" % port)
time.sleep(0.5)
session.save_cookies("mock", [{"name": "mock_login", "value": "1"}])
db.init_db()

print("=== ① 检索 → 生成材料 → 投递 3 个岗位 ===")
jobs = crawler.search_via_requests("mock", "后端", city="北京", pages=1)
check("检索到岗位", bool(jobs), "jobs=%d" % len(jobs))
config.SAFE_MODE = True
result = pipeline.run_full_pipeline(USER, jobs=jobs)
check("材料生成成功", result.get("ok") and result["task_count"] > 0)
uid = result["user_id"]
task_ids = [j["task_id"] for j in result["target_jobs"]][:3]
config.SAFE_MODE = False
config.DELIVER_INTERVAL = 0
sc = config.DATA_DIR / "send_count.txt"
if sc.exists():
    sc.unlink()
batch = delivery.deliver_batch(task_ids=task_ids)
check("投递成功", batch["成功数"] == len(task_ids), str(batch))
with db.get_conn() as conn:
    tasks = [dict(r) for r in conn.execute(
        "SELECT task_id, job_name, unit_name FROM delivery_tasks WHERE user_id=?", (uid,))]
greets_before = len(mock_site._read_greets())

print("=== ② 模拟两名 HR 回复（邀面试 / 已招满） ===")
t0, t1 = tasks[0], tasks[1]
post_json(base + "/api/hr_reply", {"单位名称": t0["unit_name"], "岗位名称": t0["job_name"],
                                   "text": "你好，简历通过了，方便周四下午 3 点视频面试吗？"})
post_json(base + "/api/hr_reply", {"单位名称": t1["unit_name"], "岗位名称": t1["job_name"],
                                   "text": "抱歉，这个岗位已经招满了，祝求职顺利。"})
check("mock 站记录到 2 条回复", len(mock_site._read_replies()) == 2)

print("=== ③ 方案 B：手动触发检查 → 匹配 → 分类 ===")
res = replies.check("mock", tasks)
check("检查成功", res.get("ok") and not res.get("error"), res.get("error"))
check("读到会话记录", len(res["records"]) >= 3, "records=%d" % len(res["records"]))
cands = res["candidates"]
check("匹配到 HR 回复的岗位", len(cands) == 2, json.dumps(cands, ensure_ascii=False)[:300])
by_task = {c["task_id"]: c for c in cands}
check("邀面试被正确分类", by_task.get(t0["task_id"], {}).get("建议类型") == "邀面试",
      str(by_task.get(t0["task_id"])))
check("不合适被正确分类", by_task.get(t1["task_id"], {}).get("建议类型") == "不合适",
      str(by_task.get(t1["task_id"])))
check("匹配度达到阈值", all(c["匹配度"] >= replies.MATCH_THRESHOLD for c in cands))

print("=== ④ 检查是只读的（不新增投递/任务/招呼语） ===")
check("投递数不变", len(mock_site._read_greets()) == greets_before,
      "%d -> %d" % (greets_before, len(mock_site._read_greets())))
with db.get_conn() as conn:
    n_after = conn.execute("SELECT COUNT(*) FROM delivery_tasks WHERE user_id=?", (uid,)).fetchone()[0]
check("任务数不变", n_after == len(tasks), "%d -> %d" % (len(tasks), n_after))

print("=== ⑤ 勾选登记 → 幂等 ===")
added, dup, details = replies.register(cands, platform_key="mock")
check("首次登记 2 条", added == 2 and dup == 0, str(details))
stat = responses.summary(uid)
check("回应统计正确", stat["总数"] == 2 and stat["分类"]["邀面试"] == 1
      and stat["分类"]["不合适"] == 1, str(stat))
auto_rows = [r for r in responses.list_responses(uid) if r["source"] == "auto"]
check("来源标记为 auto", len(auto_rows) == 2)
check("内容保存了消息原文", all(r["content"] for r in auto_rows))
added2, dup2, _ = replies.register(cands, platform_key="mock")
check("重复登记不再写入", added2 == 0 and dup2 == 2, "added=%d dup=%d" % (added2, dup2))

print("=== ⑥ 口径隔离：回应不改变画像反馈 ===")
check("进面试数仍为 0", feedback.get_quality(uid)["进面试"] == 0)

print("=== ⑦ DOM 兜底解析 ===")
dom = replies.records_from_dom([("%s %s 你好，方便聊聊吗 2026-11-17" % (t0["unit_name"], t0["job_name"]))], tasks)
check("DOM 文本可反查公司/岗位", bool(dom) and dom[0]["单位名称"] == t0["unit_name"], str(dom))
check("DOM 记录可参与匹配", len(replies.match_tasks(dom, tasks)) == 1)

print("=== ⑧ 异常与空数据边界 ===")
empty = replies.check("mock", [])
check("没有投递时检查不伪造候选", empty.get("ok") and empty["candidates"] == [])
bad = replies.check("不存在的平台", tasks)
check("未知平台返回错误", not bad.get("ok") and bad.get("error"))

mock_site.stop_server()

print()
if failures:
    print("=== Mock 站验证失败：%s ===" % "；".join(failures))
    sys.exit(1)
print("=== Mock 站验证通过：方案 B（检查新回复 + 候选登记） ===")
