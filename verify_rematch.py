"""画像闭环「再匹配」回归测试：式三间隔特征 δ 从冷启动 0 → 反馈后生效。"""
import sys
import io
import json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import config, db, pipeline, feedback

config.SAFE_MODE = True
db.init_db()

user_data = {
    "l0": {"姓名": "张三", "学校": "示例大学", "专业": "软件工程", "手机": "13800138000",
           "邮箱": "a@b.com", "性别": "男", "出生日期": "2001-01-01", "政治面貌": "群众",
           "民族": "汉", "现居": "北京", "籍贯": "北京", "学历阶段": "本科在读",
           "学院": "计算机学院", "入学年月": "2020-09", "毕业年月": "2024-06", "GPA": "3.7", "专业排名": "1"},
    "l1": {"实习/工作": 2, "项目": 0},
    "l2": [
        {"类型": "实习/工作", "名称": "后端实习生", "角色": "实习生", "时间起": "2023-06", "时间止": "2023-09",
         "事项": "后端接口开发", "结果": "提升30%", "技术工具": "Python, Flask", "挂靠": "独立", "证据": "无"},
        {"类型": "实习/工作", "名称": "前端实习生", "角色": "实习生", "时间起": "2022-06", "时间止": "2022-09",
         "事项": "前端页面开发", "结果": "上线", "技术工具": "Vue, JavaScript", "挂靠": "独立", "证据": "无"},
    ],
    "l3": {"意向城市": "北京", "意向行业": "互联网", "意向岗位": "后端开发",
           "到岗时间": "2024-07", "期望薪资": "15k/月", "投递策略": "海投", "能否出差": "是", "禁忌公司": ""},
}
mock_jobs = [
    {"岗位名称": "Python后端工程师", "单位名称": "公司A", "岗位链接": "http://a", "城市": "北京",
     "行业": "互联网", "公司": "公司A", "薪资": "15k/月", "学历": "本科", "经验": "不限",
     "技能": "python,flask,后端", "已沟通": False, "岗位描述": "后端"},
    {"岗位名称": "前端工程师", "单位名称": "公司B", "岗位链接": "http://b", "城市": "北京",
     "行业": "互联网", "公司": "公司B", "薪资": "14k/月", "学历": "本科", "经验": "不限",
     "技能": "vue,javascript,前端", "已沟通": False, "岗位描述": "前端"},
    {"岗位名称": "后端工程师", "单位名称": "公司C", "岗位链接": "http://c", "城市": "北京",
     "行业": "互联网", "公司": "公司C", "薪资": "16k/月", "学历": "本科", "经验": "不限",
     "技能": "python,后端,redis", "已沟通": False, "岗位描述": "后端"},
]

def check(name, cond):
    print(("  PASS  " if cond else "  FAIL  ") + name)
    return bool(cond)

ok = True

# ① 冷启动：无中心，δ=0
r = pipeline.run_full_pipeline(user_data, jobs=mock_jobs)
ok &= check("冷启动所有 δ=0",
            all(j["匹配分构成"]["间隔特征δ"] == 0 for j in r["target_jobs"]))

# ② 反馈：后端进面试、前端未进面试 → 形成正负中心
for tj in r["target_jobs"]:
    feedback.mark_result(tj["task_id"], 1 if "后端" in tj["岗位名称"] else 0)

# ③ 重新匹配：δ 生效
rm = pipeline.re_match(r["user_id"], user_data, jobs=mock_jobs)
ok &= check("反馈后形成正负中心", all(x["has_center"] for x in rm))
ok &= check("反馈后 δ 非 0（间隔特征生效）", any(abs(float(x["delta"])) > 1e-9 for x in rm))
by_name = {x["job"]["岗位名称"]: x for x in rm}
ok &= check("后端岗位 δ>0（更靠近正中心）", float(by_name["Python后端工程师"]["delta"]) > 0)
ok &= check("前端岗位 δ<0（更靠近负中心）", float(by_name["前端工程师"]["delta"]) < 0)
ok &= check("后端匹配分 > 前端匹配分（反馈后分化）",
            float(by_name["Python后端工程师"]["score"]) > float(by_name["前端工程师"]["score"]))

print()
print("=== 画像闭环「再匹配」回归测试", "通过" if ok else "有失败", "===")
sys.exit(0 if ok else 1)
