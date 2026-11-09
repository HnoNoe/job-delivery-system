"""可视化数据源回归测试：六维分数明细 / 匹配分构成 / 权重演进结构正确性。

不启动浏览器、不联网，验证 app.py 可视化图表依赖的数据结构。
"""
import sys
import io
import json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from test_support import isolate_test_environment
isolate_test_environment()

import config, db, pipeline, recommend, feedback, persona, viz, theme, workbench

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

# ⑥ 人物画像（⑤ 新卡片的数据源）：身份/技能/方向/一句话齐全
p = persona.build_persona(user_data, targets=targets, weights=w)
ok &= check("人物画像含姓名与身份", p["姓名"] == "张三" and "本科" in p["身份"])
ok &= check("人物画像技能标签非空", bool(p["技能标签"]))
ok &= check("人物画像一句话含经历数", ("%d 段经历" % len(user_data["l2"])) in p["一句话"])
ok &= check("人物画像优势/短板来自能力维度", set(p["优势"]) | set(p["短板"]) <= set(persona.ABILITY_DIMS))
ok &= check("人物画像能力匹配为百分比",
            p["能力匹配"] and all(0 <= v <= 100 for v in p["能力匹配"].values()))
ok &= check("人物画像权重状态随反馈变化", "已修正" in p["画像规模"])

# ⑦ 三维匹配空间：坐标、聚合、选中与主题（分析工作台数据契约）
ok &= check("三维坐标落在 0~100",
            all(0 <= c <= 100 for j in targets for c in viz._fit_point(j)))
expected = [max(0, min(100, 100 * next(s for n, s, *_ in j["分数明细"] if n == "技能匹配") / 40))
            for j in targets]
ok &= check("三维技能轴 == 技能得分/40", all(
    abs(viz._fit_point(j)[0] - e) < 1e-9 for j, e in zip(targets, expected)))

space = viz.build_match_space_data(targets)
ok &= check("空输入返回空结构", viz.build_match_space_data([])["job_count"] == 0
            and viz.build_match_space_data([])["groups"] == [])
ok &= check("每组岗位数与任务ID数一致",
            all(g["count"] == len(g["task_ids"]) == len(g["jobs"]) for g in space["groups"]))
ok &= check("聚合前后岗位总数与ID集合一致",
            space["job_count"] == len(targets)
            and {t for g in space["groups"] for t in g["task_ids"]}
            <= set(space["jobs_by_id"].keys()))
ok &= check("默认选中第一个岗位", space["default_task_id"] == str(targets[0]["task_id"]))

# 同坐标聚合：三轴相同的岗位进同一组，组内保持原顺序
same = [
    {"task_id": 101, "岗位名称": "后端", "单位名称": "A", "score": 0.7, "等级": "A",
     "分数明细": [("技能匹配", 40, ""), ("岗位方向", 25, ""), ("学历", 15, ""),
                ("薪资", 10, ""), ("行业", 5, ""), ("城市", 5, "")]},
    {"task_id": 102, "岗位名称": "后端", "单位名称": "B", "score": 0.6, "等级": "B",
     "分数明细": [("技能匹配", 40, ""), ("岗位方向", 25, ""), ("学历", 15, ""),
                ("薪资", 10, ""), ("行业", 5, ""), ("城市", 5, "")]},
    {"task_id": 103, "岗位名称": "前端", "单位名称": "C", "score": 0.5, "等级": "C",
     "分数明细": [("技能匹配", 0, ""), ("岗位方向", 0, ""), ("学历", 15, ""),
                ("薪资", 10, ""), ("行业", 5, ""), ("城市", 5, "")]},
]
sdata = viz.build_match_space_data(same)
ok &= check("同坐标岗位聚合为一个组点",
            sdata["group_count"] == 2
            and sdata["groups"][0]["count"] == 2
            and sdata["groups"][0]["task_ids"] == ["101", "102"])
ok &= check("同名不同单位可独立选择",
            "101" in sdata["jobs_by_id"] and "102" in sdata["jobs_by_id"])
ok &= check("选中ID失效时回退到第一个岗位",
            viz.resolve_selected_task(sdata, "不存在") == "101"
            and viz.resolve_selected_task(sdata, "102") == "102")

# 近似但不相等的坐标不应被合并（6 位小数容差）
near = [
    {"task_id": 201, "岗位名称": "x", "等级": "A", "score": 0.5,
     "分数明细": [("技能匹配", 13.333333, ""), ("岗位方向", 0, ""), ("学历", 0, ""),
                ("薪资", 0, ""), ("行业", 0, ""), ("城市", 0, "")]},
    {"task_id": 202, "岗位名称": "y", "等级": "A", "score": 0.5,
     "分数明细": [("技能匹配", 13.333334, ""), ("岗位方向", 0, ""), ("学历", 0, ""),
                ("薪资", 0, ""), ("行业", 0, ""), ("城市", 0, "")]},
]
ok &= check("接近但不相等的坐标不合并", viz.build_match_space_data(near)["group_count"] == 2)

# 缺六维分数：不能当成 0 分，明细显示“未知”
nodim = [{"task_id": 301, "岗位名称": "z", "单位名称": "D", "等级": "B", "score": 0.4}]
ndata = viz.build_match_space_data(nodim)
ok &= check("缺分数岗位不进入三维图且标记未知",
            ndata["group_count"] == 0 and ndata["unknown_task_ids"] == ["301"]
            and viz.match_space_rows(nodim)[0]["技能适配"] == "未知")

ok &= check("选中ID对应的组与坐标一致",
            sdata["jobs_by_id"]["102"]["coords"]
            == tuple(sdata["group_by_id"][sdata["jobs_by_id"]["102"]["group_id"]]["coords"]))
ok &= check("组内顺序沿用岗位原顺序", sdata["groups"][0]["task_ids"] == ["101", "102"])

payload = workbench._jobs_payload(ndata)
ok &= check("组件参数保留未知坐标与原始匹配分",
            payload[0]["x"] is None and payload[0]["score"] == 0.4
            and payload[0]["task_id"] == "301")
ok &= check("匹配空间组件文件存在",
            (workbench._COMPONENT_DIR / "index.html").is_file())

colors_light = theme.match_space_colors()
ok &= check("亮色工作台配色来自局部令牌",
            colors_light["bg"] == theme.MATCH_SPACE["light"]["bg"]
            and colors_light["accent"] == theme.MATCH_SPACE["light"]["accent"])
_orig_dark = theme.is_dark
theme.is_dark = lambda: True
try:
    colors_dark = theme.match_space_colors()
finally:
    theme.is_dark = _orig_dark
ok &= check("暗色主题切换工作台配色",
            colors_dark["bg"] == theme.MATCH_SPACE["dark"]["bg"]
            and colors_dark["accent"] == theme.MATCH_SPACE["dark"]["accent"])

print()
print("=== 可视化数据源回归测试", "通过" if ok else "有失败", "===")
sys.exit(0 if ok else 1)
