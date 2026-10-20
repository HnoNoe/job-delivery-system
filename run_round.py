"""跑一轮完整流程：真实检索 → 画像 → 匹配 → 生成简历 → 准备投递材料。

说明：
- 岗位来自真实 Boss直聘检索（用登录态），绝不虚构。
- 用户画像是演示占位数据（真实信息明天在界面填写）。
- SAFE_MODE 默认开启，本轮只生成材料，不会自动投递/发消息给 HR。
"""
import json
import sys
import config
import db
import loop
import pipeline

config.SAFE_MODE = True

# 演示用户画像（占位，明天在界面填真实信息）
SAMPLE = {
    "l0": {"姓名": "演示用户", "学校": "示例大学", "专业": "软件工程", "手机": "13800138000",
           "邮箱": "demo@example.com", "性别": "男", "出生日期": "2001-01-01", "政治面貌": "群众",
           "民族": "汉", "现居": "北京", "籍贯": "北京", "学历阶段": "本科在读",
           "学院": "计算机学院", "入学年月": "2020-09", "毕业年月": "2024-06", "GPA": "3.7", "专业排名": "1"},
    "l1": {"实习/工作": 1, "项目": 1, "竞赛": 0, "论文": 0, "专利": 0, "学生工作": 0, "证书": 0, "作品链接": 0},
    "l2": [
        {"类型": "实习/工作", "名称": "后端开发实习生", "角色": "实习生", "时间起": "2023-06", "时间止": "2023-09",
         "事项": "负责用户服务接口开发", "结果": "接口响应提升30%", "技术工具": "Python", "挂靠": "独立", "证据": "无"},
        {"类型": "项目", "名称": "校园二手交易平台", "角色": "负责人", "时间起": "2023-03", "时间止": "2023-08",
         "事项": "搭建后端服务与数据库", "结果": "上线并服务200+用户", "技术工具": "Flask", "挂靠": "独立", "证据": "无"},
    ],
    "l3": {"意向城市": "北京", "意向行业": "互联网", "意向岗位": "后端开发", "到岗时间": "2024-07",
           "期望薪资": "15k", "投递策略": "海投", "能否出差": "是", "禁忌公司": ""},
}

print("=" * 60)
print("步骤① 真实检索（Boss直聘，关键词「Python 后端」，城市 北京）")
print("=" * 60)
db.init_db()
jobs, logs = loop.search_logged_in_platforms(["boss"], "Python 后端", city="北京")
for k, msg in logs:
    print(f"  [{k}] {msg}")
print(f"共检索到 {len(jobs)} 个真实岗位")
for j in jobs[:5]:
    print(f"   · {j.get('岗位名称')} | {j.get('单位名称')} | 薪资{j.get('薪资')} | 行业{j.get('行业')} | 学历{j.get('学历')}")

if not jobs:
    print("!! 未检索到岗位，终止")
    sys.exit(1)

print()
print("=" * 60)
print("步骤② 画像 → 匹配 → 建任务 → 生成简历 → 准备材料")
print("=" * 60)
r = pipeline.run_full_pipeline(SAMPLE, jobs=jobs)
if not r["ok"]:
    print("核检未通过:", r["errors"])
    sys.exit(1)
print(f"匹配到 {r['task_count']} 个目标岗位（已按匹配分排序）")
print("-" * 60)
for j in r["target_jobs"]:
    print(f"  ★ [{j.get('等级','')}级/{j.get('等级分','')}分] {j['岗位名称']} @ {j['单位名称']}  薪资{j['薪资']}  匹配分{j['score']}")
    reasons = j.get("推荐理由", [])
    if reasons:
        print(f"    🔎 {'；'.join(reasons)}")
    mc = j.get("匹配分构成", {})
    if mc:
        print(f"    📐 p=σ({mc['w_s']}×{mc['余弦相似度s']} + {mc['w_δ']}×{mc['间隔特征δ']}) = {mc['匹配分p']}")
print("-" * 60)
summ = r.get("画像摘要", {})
if summ:
    print("画像摘要: 技能[%s] 意向岗位[%s] 行业[%s] 城市[%s]"
          % ("、".join(summ.get("技能标签", [])), "、".join(summ.get("意向岗位", [])),
             "、".join(summ.get("意向行业", [])), "、".join(summ.get("意向城市", []))))
print("投递材料（招呼语，安全模式下供手动复制，不会自动发送）：")
for d in r["delivery_report"][:3]:
    print(f"  · {d['岗位']}：{d['招呼语']}")

# 展示生成的简历文件
import os
resumes = [f for f in os.listdir("resumes") if f.endswith(".pdf")]
print(f"生成的简历 PDF：{resumes}")
print()
print("=" * 60)
print("完成。本轮为安全模式：只生成了材料，未向任何 HR 发送消息。")
print("=" * 60)

# 命令行一次性跑完，清理浏览器（Web UI 场景由 Streamlit 长驻保持登录态）
try:
    import session as _s
    _s.dpage_quit("boss")
except Exception:
    pass

