"""城市/行业归一化与技能兜底提取的回归测试（对应 50 → 5 的误杀问题）。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_support import isolate_test_environment

isolate_test_environment()

import config
import db
import job_filters
import pipeline
import recommend


def user():
    return {
        "l0": {"姓名": "测试用户", "性别": "男", "出生日期": "2001-01-01", "手机": "13800138000",
               "邮箱": "t@example.com", "政治面貌": "群众", "民族": "汉", "现居": "北京",
               "籍贯": "北京", "学历阶段": "本科", "学校": "示例大学", "学院": "计院",
               "专业": "软件工程", "入学年月": "2020-09", "毕业年月": "2024-06"},
        "l1": {"项目": 1},
        "l2": [{"类型": "项目", "名称": "后端服务", "技术工具": "Python, Flask",
                "事项": "开发接口", "时间起": "2023-01", "时间止": "2023-06"}],
        "l3": {"意向城市": "北京,上海", "意向行业": "互联网,人工智能", "意向岗位": "后端开发",
               "投递策略": "海投", "到岗时间": "2024-07", "能否出差": "是"},
    }


def job(city="北京 海淀", industry="计算机软件", name="Python后端开发"):
    return {"岗位名称": name, "单位名称": "示例科技", "岗位链接": "https://example.com/j",
            "城市": city, "行业": industry, "岗位描述": "Python Flask",
            "技能": ["Python", "Flask"], "学历": "本科",
            "投递入口类型": "API", "投递入口地址": "http://127.0.0.1:1/apply"}


class CityMatchTests(unittest.TestCase):
    def test_district_suffix(self):
        self.assertTrue(job_filters.city_match("北京 海淀", ["北京"]))
        self.assertTrue(job_filters.city_match("北京-朝阳区", ["北京"]))
        self.assertTrue(job_filters.city_match("北京市", ["北京"]))
        self.assertFalse(job_filters.city_match("上海 浦东", ["北京"]))

    def test_user_input_with_district(self):
        self.assertTrue(job_filters.city_match("北京", ["北京-海淀区"]))
        self.assertTrue(job_filters.city_match("北京 海淀", ["上海", "北京"]))

    def test_missing_values_do_not_filter(self):
        self.assertTrue(job_filters.city_match("", ["北京"]))
        self.assertTrue(job_filters.city_match("北京", []))

    def test_different_cities(self):
        self.assertFalse(job_filters.city_match("杭州 西湖", ["北京", "上海"]))


class IndustryMatchTests(unittest.TestCase):
    def test_aliases(self):
        for ind in ("计算机软件", "软件/IT服务", "电子商务", "信息安全", "企业服务", "游戏"):
            self.assertTrue(job_filters.industry_match(ind, ["互联网"]), ind)
        for ind in ("智能硬件", "机器人", "机器学习"):
            self.assertTrue(job_filters.industry_match(ind, ["人工智能"]), ind)

    def test_unrelated_industry(self):
        self.assertFalse(job_filters.industry_match("基金", ["互联网", "人工智能"]))
        self.assertFalse(job_filters.industry_match("人力资源服务", ["互联网"]))

    def test_missing_values_do_not_filter(self):
        self.assertTrue(job_filters.industry_match("", ["互联网"]))
        self.assertTrue(job_filters.industry_match("互联网", []))

    def test_alias_override_from_config(self):
        with patch.object(config, "INDUSTRY_ALIASES", {"互联网": ["互联网"]}):
            self.assertFalse(job_filters.industry_match("计算机软件", ["互联网"]))


class SkillFallbackTests(unittest.TestCase):
    def test_skills_from_name_and_detail_when_tech_empty(self):
        exps = [{"名称": "Python后端实习", "事项": "用 Flask 开发接口，MySQL 存储",
                 "结果": "接口响应提升30%", "技术工具": ""}]
        skills = recommend.extract_user_skills(exps)
        for kw in ("python", "flask", "mysql", "后端"):
            self.assertIn(kw, skills)

    def test_ascii_keyword_word_boundary(self):
        # 不能把 google 里的 go 当技能
        skills = recommend.extract_user_skills([{"名称": "Google 广告优化", "技术工具": ""}])
        self.assertNotIn("go", skills)

    def test_grade_gets_skill_points(self):
        data = user()
        grade, score = recommend.match_grade(data, job())
        self.assertEqual(grade, "A")
        self.assertGreaterEqual(score, 60)
        breakdown = dict((d, s) for d, s, _ in recommend.score_breakdown(data, job()))
        self.assertEqual(breakdown["技能匹配"], 40)
        self.assertEqual(breakdown["行业"], 5)
        self.assertEqual(breakdown["城市"], 5)


class PipelineFilterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jobdelivery-filters-")
        self.root = Path(self.temp.name)
        self.patches = patch.multiple(
            config, RUNTIME_DIR=self.root, DATA_DIR=self.root / "data",
            LOG_DIR=self.root / "logs", DB_PATH=str(self.root / "data/test.db"),
            SAFE_MODE=True, DELIVER_INTERVAL=0)
        self.patches.start()
        db.init_db()

    def tearDown(self):
        self.patches.stop()
        self.temp.cleanup()

    def test_district_and_software_industry_jobs_are_kept(self):
        jobs = [job(), job(city="北京 朝阳", industry="软件/IT服务", name="Java后端开发"),
                job(city="上海 浦东", industry="互联网", name="Python后端开发")]
        result = pipeline.run_full_pipeline(user(), jobs=jobs)
        self.assertTrue(result["ok"])
        self.assertEqual(result["task_count"], 3)
        names = {j["岗位名称"] for j in result["target_jobs"]}
        self.assertIn("Python后端开发", names)

    def test_unrelated_city_still_filtered(self):
        result = pipeline.run_full_pipeline(user(), jobs=[job(city="杭州 西湖", industry="互联网")])
        self.assertEqual(result["task_count"], 0)


if __name__ == "__main__":
    unittest.main()
