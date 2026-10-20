"""简历解析回归测试：验证 L0/L2 自动填充（粘贴/上传简历）的正确性。"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import recommend


def check(name, cond):
    print(("  PASS  " if cond else "  FAIL  ") + name)
    return bool(cond)


ok = True
text = """姓名：张三
性别：男
民族：汉族
政治面貌：共青团员
现居：北京
出生：2001年5月6日
GPA：3.8
专业排名：前5%
学院：计算机学院
2020年9月入学 2024年6月毕业
手机：13912345678 邮箱：zhangsan@example.com
北京理工大学 计算机科学与技术专业 本科在读
技能：Python、Flask、MySQL、Redis

实习经历：
2023.06 - 2023.09 字节跳动 Python后端实习生
负责订单系统接口开发，使用 Flask + MySQL，接口响应提升 30%

项目经历：
2023.01 - 2023.05 电商秒杀系统项目
基于 Spring Boot + MySQL + Redis 实现秒杀，QPS 1000+
"""
p = recommend.resume_parse(text)

ok &= check("姓名提取", p.get("姓名") == "张三")
ok &= check("性别提取", p.get("性别") == "男")
ok &= check("民族提取", p.get("民族") == "汉族")
ok &= check("政治面貌提取", p.get("政治面貌") == "共青团员")
ok &= check("现居提取", p.get("现居") == "北京")
ok &= check("手机提取", p.get("手机") == "13912345678")
ok &= check("邮箱提取", p.get("邮箱") == "zhangsan@example.com")
ok &= check("学校提取", p.get("学校") == "北京理工大学")
ok &= check("专业提取", p.get("专业") == "计算机科学与技术")
ok &= check("学历提取", p.get("学历阶段") == "本科在读")
ok &= check("出生日期提取", p.get("出生日期") == "2001-05-06")
ok &= check("GPA提取", p.get("GPA") == "3.8")
ok &= check("专业排名提取", p.get("专业排名") == "前5%")
ok &= check("学院提取", p.get("学院") == "计算机学院")
ok &= check("入学年月提取", p.get("入学年月") == "2020-09")
ok &= check("毕业年月提取", p.get("毕业年月") == "2024-06")

exps = p.get("经历", [])
ok &= check("经历数量=2", len(exps) == 2)
ok &= check("实习类型识别", exps[0]["类型"] == "实习/工作")
ok &= check("项目类型识别", exps[1]["类型"] == "项目")
ok &= check("量化成果提取", exps[0]["结果"] == "提升 30%" and exps[1]["结果"] == "QPS 1000")
ok &= check("技术工具提取", "flask" in exps[0]["技术工具"] and "spring" in exps[1]["技术工具"])

print()
print("=== 简历解析回归测试", "通过" if ok else "有失败", "===")
sys.exit(0 if ok else 1)
