"""可视化数据源回归测试：六维分数明细 / 匹配分构成 / 权重演进结构正确性。

不启动浏览器、不联网，验证 app.py 可视化图表依赖的数据结构。
"""
import sys
import io
import json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import config, db, pipeline, recommend, feedback

config.SAFE_MODE = True
db.init_db()

user_data = {
    "l0": {"姓名": "张三", "性别": "男", "出生日期": "2001-05-06", "手机": "13912345678",
           "邮箱": "a@b.com", "政治面貌": "共青团员", "民族": "汉族", "现居": "北京",
           "籍贯": "江苏", "学历阶段": "本科在读", "学校": "北京理工大学", "学院": "计算机学院",
           "专业": "软件工程", "入学年月": "2020-09", "毕业年月": "2024-06"},
    "l1": {"实习/工作": 1, "项目": 1},
    "l2": [
        {"类型": "实习/工作", "名称": "Python后端实习生", "角色": "实习生", "时间起": "2023-06",
         "时间止": "2023-09", "事项": "接口开发 Flask+MySQL", "结果": "提升30%",
         "技术工具": "Python, Flask, MySQL", "挂靠": "独立", "证据": "无"},
        {"类型": "项目", "名称": "电商秒杀", "角色": "负责人", "时间起": "2023-01", "时间止": "2023-05",
         "事项": "Spring Boot 秒杀", "结果": "QPS1000", "技术工具": "Java, Spring, Redis",
         "挂靠": "独立", "证据": "无"},
    ],
    "l3": {"意向城市": "北京", "意向行业": "互联网", "意向岗位": "后端开发",
           "到岗时间": "2024-07", "期望薪资": "15k/月", "投递策略": "海投", "能否出差": "是"},
}
mock_jobs = [
    {"岗位名称": "Python后端开发工程师", "单位名称": "示例科技", "岗位链接": "https://e.com/1",
     "城市": "北京", "行业": "互联网", "公司": "示例科技", "薪资": "15k/月", "学历": "本科",
     "经验": "不限", "技能": "python,flask,mysql,后端", "已沟通": False, "岗位描述": "后端"},
    {"岗位名称": "前端开发工程师", "单位名称": "前端科技", "岗位链接": "https://e.com/2",
     "城市": "北京", "行业": "互联网", "公司": "前端科技", "薪资": "14k/月", "学历": "本科",
     "经验": "不限", "技能": "vue,javascript,前端", "已沟通": False, "岗位描述": "前端"},
]


def check(name, cond):
    print(("  PASS  " if cond else "  FAIL  ") + name)
    return bool(cond)


ok = True
r = pipeline.run_full_pipeline(user_data, jobs=mock_jobs)
targets = r["target_jobs"]
assert targets, "应有目标岗位"
top = targets[0]

# ① 六维分数明细（雷达图/堆叠柱状图数据源）
bd = top.get("分数明细")
ok &= check("六维分数明细维度名正确",
            [p[0] for p in bd] == ["技能匹配", "岗位方向", "学历", "薪资", "行业", "城市"])

# ② 等级分 = 六维得分之和（clamp 后）
sum_scores = sum(p[1] for p in bd)
ok &= check("等级分 == 六维得分之和", top["等级分"] == max(0, min(100, sum_scores)))

# ③ 匹配分构成（式三分解：s/δ/p）
mc = top.get("匹配分构成")
ok &= check("匹配分构成含 s/δ/p", set(mc) >= {"余弦相似度s", "间隔特征δ", "匹配分p"})

# ④ 技能覆盖（extract 口径一致）
us = recommend.extract_user_skills(user_data["l2"])
js = recommend.extract_job_skills({"技能": mock_jobs[0]["技能"], "岗位名称": mock_jobs[0]["岗位名称"]})
ok &= check("技能覆盖交集正确", bool(us & js))

# ⑤ 反馈后权重演进（经历权重饼图数据源）
tid = top["task_id"]
feedback.mark_result(tid, 1)
ev = feedback.get_profile_evolution(r["user_id"])
w = json.loads(ev[-1]["weights"])
ok &= check("权重演进快照非空且和为1", ev and abs(sum(w) - 1.0) < 1e-6)

print()
print("=== 可视化数据源回归测试", "通过" if ok else "有失败", "===")
sys.exit(0 if ok else 1)
