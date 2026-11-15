"""Mock 站验证：投递现场恢复（分阶段翻页改造后保留的能力）。

全程对本地 mock 站发起真实 HTTP 请求，不碰真实平台。验证：

① 投递后「重启程序」（丢弃内存状态）→ `pipeline.latest_result()` 能从 SQLite 重建
   上次投递现场：任务数、岗位顺序、匹配分、简历内容、招呼语都不丢；
② 恢复是只读的：不新增用户/任务；
③ 画像反馈后历史匹配分不被改写；
④ 空库时返回 None（界面据此显示空态而不是报错）。

运行：.venv\\Scripts\\python.exe mock_restore_e2e.py
"""
import io
import sys
import time

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
import session  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("（%s）" % detail if detail and not cond else ""))
    if not cond:
        failures.append(name)
    return bool(cond)


def _count(table):
    with db.get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]


# ---------- 准备：mock 站 + 登录态（独立临时库） ----------
if mock_site.GREETS_FILE.exists():
    mock_site.GREETS_FILE.unlink()
srv = mock_site.start_in_background(port=0)
port = srv.server_address[1]
for key in ("login_url", "search_url", "api_url"):
    platforms.PLATFORMS["mock"][key] = platforms.PLATFORMS["mock"][key].replace(":5001/", ":%d/" % port)
time.sleep(0.5)
session.save_cookies("mock", [{"name": "mock_login", "value": "1"}])
db.init_db()

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

print("=== ① 检索 + 生成材料（mock 站真实 HTTP） ===")
jobs = crawler.search_via_requests("mock", "后端", city="北京", pages=1)
check("检索到岗位", bool(jobs), "jobs=%d" % len(jobs))
config.SAFE_MODE = True
result = pipeline.run_full_pipeline(USER, jobs=jobs)
check("材料生成成功", result.get("ok") and result.get("task_count", 0) > 0,
      str(result.get("errors")))
uid = result["user_id"]
task_ids = [j["task_id"] for j in result["target_jobs"]]
original_order = [j["job_id"] for j in result["target_jobs"]]
original_scores = {j["task_id"]: j["score"] for j in result["target_jobs"]}

print("=== ② 投递（关闭安全模式，走 mock API） ===")
config.SAFE_MODE = False
config.DELIVER_INTERVAL = 0
sc = config.DATA_DIR / "send_count.txt"
if sc.exists():
    sc.unlink()
batch = delivery.deliver_batch(task_ids=task_ids)
check("mock 站收到投递", batch["成功数"] > 0, str(batch))
check("mock greets 落盘", len(mock_site._read_greets()) > 0)

print("=== ③ 标注一条画像反馈（改变权重，模拟使用一段时间后重启） ===")
ok, _w = feedback.mark_result(task_ids[0], 1)
check("进面试标注成功", ok)

print("=== ④ 模拟重启：丢弃内存现场，从数据库恢复 ===")
restored = pipeline.latest_result()
check("恢复出结果", bool(restored and restored.get("ok")))
check("带 restored 标记", bool(restored and restored.get("restored")))
check("用户一致", restored and restored["user_id"] == uid)
check("任务数一致", restored and restored["task_count"] == len(task_ids),
      "%s vs %s" % (restored and restored["task_count"], len(task_ids)))
check("岗位顺序沿用匹配分（job_id 序列一致）",
      [j["job_id"] for j in restored["target_jobs"]] == original_order)
check("匹配分与投递时一致",
      all(abs(restored["target_jobs"][i]["score"] - original_scores[j["task_id"]]) < 1e-9
          for i, j in enumerate(restored["target_jobs"])))
check("简历内容已恢复", all(j.get("简历内容") for j in restored["target_jobs"]))
check("招呼语已恢复", all(d.get("招呼语") for d in restored["delivery_report"]))
check("匹配分构成含 s/δ/p", all(
    {"余弦相似度s", "间隔特征δ", "匹配分p"} <= set(j["匹配分构成"])
    for j in restored["target_jobs"]))
check("任务状态来自数据库", all(j.get("状态") in ("待投递", "投递中", "待核实", "已投递", "已完成")
                          for j in restored["delivery_report"]))
check("画像摘要已恢复", bool(restored["画像摘要"].get("技能标签")))
check("恢复不新增用户", _count("user_records") == 1, "users=%d" % _count("user_records"))
check("恢复不新增任务", _count("delivery_tasks") == len(task_ids))

print("=== ⑤ 空库边界 ===")
with db.get_conn() as conn:
    conn.execute("DELETE FROM delivery_tasks")
check("无任务时 latest_result 返回 None", pipeline.latest_result() is None)

mock_site.stop_server()

print()
if failures:
    print("=== Mock 站验证失败：%s ===" % "；".join(failures))
    sys.exit(1)
print("=== Mock 站验证通过：投递现场恢复（只读重建，不改数据） ===")
