"""投递现场恢复的回归测试（分阶段翻页改造后保留的能力）。

覆盖：
1. `pipeline.latest_result()` 能从数据库重建上次投递现场（刷新/重启后第⑤⑥阶段可用）；
2. 恢复是只读的，不新增用户/任务/字段表；
3. 反馈后历史匹配分不被改写；
4. 第⑤/⑥阶段在 session 没有现场时自动恢复；
5. 刷新后自动恢复「上次确认的信息」，并且可以直接跳到第⑥阶段；
6. 「重新开始」从零开始，不会立刻被自动回填。
"""
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_support import isolate_test_environment

isolate_test_environment()

import config
import db
import feedback
import pipeline
import schema
import session

BASE = Path(__file__).resolve().parents[1]


def user():
    return {
        "l0": {"姓名": "测试用户", "性别": "男", "出生日期": "2001-01-01", "手机": "13800138000",
               "邮箱": "test@example.com", "政治面貌": "群众", "民族": "汉", "现居": "北京",
               "籍贯": "北京", "学历阶段": "本科", "学校": "示例大学", "学院": "计算机学院",
               "专业": "软件工程", "入学年月": "2020-09", "毕业年月": "2024-06"},
        "l1": {"项目": 2},
        "l2": [{"类型": "项目", "名称": "Python-web", "技术工具": "Python Flask", "事项": "开发接口",
                "时间起": "2023-01", "时间止": "2023-06"},
               {"类型": "项目", "名称": "前端", "技术工具": "Vue", "事项": "开发页面"}],
        "l3": {"意向城市": "北京", "意向行业": "互联网", "意向岗位": "后端开发", "投递策略": "海投",
               "到岗时间": "2024-07", "能否出差": "是"},
    }


def job(n=1):
    return {"岗位名称": "Python后端开发", "单位名称": "公司%d" % n,
            "岗位链接": "https://example.com/jobs/%d" % n, "城市": "北京", "行业": "互联网",
            "岗位描述": "Python Flask", "技能": ["Python", "Flask"], "学历": "本科",
            "投递入口类型": "API", "投递入口地址": "http://127.0.0.1:1/apply"}


class _Harness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jobdelivery-restore-")
        self.root = Path(self.temp.name)
        self.patches = patch.multiple(
            config, RUNTIME_DIR=self.root, DATA_DIR=self.root / "data",
            LOG_DIR=self.root / "logs", DB_PATH=str(self.root / "data/test.db"),
            SAFE_MODE=True, DELIVER_INTERVAL=0)
        self.patches.start()
        self.session_patch = patch.object(session, "SESSION_DIR", self.root / "sessions")
        self.session_patch.start()
        session.SESSION_DIR.mkdir()
        db.init_db()

    def tearDown(self):
        # 释放指向临时目录的日志文件句柄，否则 Windows 下临时目录无法删除
        for logger in list(logging.Logger.manager.loggerDict.values()):
            if isinstance(logger, logging.Logger):
                for handler in logger.handlers[:]:
                    if (isinstance(handler, logging.FileHandler)
                            and Path(handler.baseFilename).resolve().is_relative_to(self.root.resolve())):
                        logger.removeHandler(handler)
                        handler.close()
        self.session_patch.stop()
        self.patches.stop()
        self.temp.cleanup()

    def run_pipeline(self, jobs=None):
        return pipeline.run_full_pipeline(user(), jobs=jobs or [job(1), job(2)])


class RestoreTests(_Harness):
    def test_latest_result_none_when_no_tasks(self):
        self.assertIsNone(pipeline.latest_result())

    def test_latest_result_rebuilds_full_scene(self):
        result = self.run_pipeline()
        restored = pipeline.latest_result()
        self.assertIsNotNone(restored)
        self.assertTrue(restored["ok"] and restored["restored"])
        self.assertEqual(restored["user_id"], result["user_id"])
        self.assertEqual(restored["task_count"], result["task_count"])
        self.assertEqual([j["job_id"] for j in restored["target_jobs"]],
                         [j["job_id"] for j in result["target_jobs"]])
        for original, again in zip(result["target_jobs"], restored["target_jobs"]):
            self.assertAlmostEqual(original["score"], again["score"], places=6)
            self.assertTrue(again["简历内容"])
            self.assertTrue(again["匹配分构成"]["匹配分p"])
            self.assertEqual(set(schema.RESUME_ALLOWED_L2) & set(again["简历内容"]),
                             set(schema.RESUME_ALLOWED_L2) & set(original["简历内容"]))
        self.assertTrue(all(d["招呼语"] for d in restored["delivery_report"]))
        self.assertTrue(restored["画像摘要"]["技能标签"])

    def test_restore_does_not_write(self):
        self.run_pipeline()
        with db.get_conn() as conn:
            before = (conn.execute("SELECT COUNT(*) FROM user_records").fetchone()[0],
                      conn.execute("SELECT COUNT(*) FROM delivery_tasks").fetchone()[0],
                      conn.execute("SELECT COUNT(*) FROM job_field_map").fetchone()[0])
        pipeline.latest_result()
        with db.get_conn() as conn:
            after = (conn.execute("SELECT COUNT(*) FROM user_records").fetchone()[0],
                     conn.execute("SELECT COUNT(*) FROM delivery_tasks").fetchone()[0],
                     conn.execute("SELECT COUNT(*) FROM job_field_map").fetchone()[0])
        self.assertEqual(before, after)

    def test_restore_keeps_history_score_after_feedback(self):
        result = self.run_pipeline()
        tid = result["target_jobs"][0]["task_id"]
        baked = result["target_jobs"][0]["score"]
        feedback.mark_result(tid, 1)  # 式五更新权重后，历史分数仍应保持
        restored = pipeline.latest_result()
        row = next(j for j in restored["target_jobs"] if j["task_id"] == tid)
        self.assertAlmostEqual(row["score"], baked, places=6)


class UiRestoreTests(_Harness):
    def test_step_six_renders_restored_records(self):
        from streamlit.testing.v1 import AppTest
        result = self.run_pipeline()
        at = AppTest.from_file(str(BASE / "app.py"))
        at.session_state["wizard_page"] = 5   # 第⑥阶段，且 session 里没有 result
        at.run(timeout=40)
        self.assertFalse(at.exception)
        self.assertTrue(at.session_state["result"].get("restored"))
        self.assertEqual(at.session_state["result"]["user_id"], result["user_id"])
        # 投递记录表渲染出来
        self.assertTrue(len(at.dataframe) >= 1)

    def test_step_five_restores_without_result(self):
        from streamlit.testing.v1 import AppTest
        result = self.run_pipeline()
        at = AppTest.from_file(str(BASE / "app.py"))
        at.session_state["wizard_page"] = 4
        at.run(timeout=40)
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["result"]["user_id"], result["user_id"])
        keys = {getattr(e, "key", None) for e in at.button}
        self.assertTrue(any(str(k or "").startswith("del_") for k in keys), keys)

    def test_refresh_restores_confirmed_info_and_allows_jump_to_records(self):
        from streamlit.testing.v1 import AppTest
        result = self.run_pipeline()
        at = AppTest.from_file(str(BASE / "app.py")).run(timeout=40)
        self.assertFalse(at.exception)
        self.assertIn("info_confirmed", at.session_state)
        self.assertTrue(at.session_state["info_confirmed"])
        self.assertEqual(at.session_state["confirmed_user_data"]["l0"]["姓名"],
                         user()["l0"]["姓名"])
        self.assertFalse(at.button(key="jump_5").disabled)
        at.button(key="jump_5").click().run(timeout=40)
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["wizard_page"], 5)
        self.assertEqual(at.session_state["result"]["user_id"], result["user_id"])

    def test_refresh_lands_on_step_five_when_scene_is_restored(self):
        """恢复投递现场后默认停在第⑤阶段（逐条投递与反馈），而不是直接跳到⑥。"""
        from streamlit.testing.v1 import AppTest
        self.run_pipeline()
        at = AppTest.from_file(str(BASE / "app.py")).run(timeout=40)
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["wizard_page"], 4)
        # 第⑤阶段的工作台确实渲染了
        keys = {getattr(e, "key", None) for e in at.button}
        self.assertTrue(any(str(k or "").startswith("del_") for k in keys), keys)
        # 仍然可以手动跳到第⑥阶段看记录
        self.assertFalse(at.button(key="jump_5").disabled)

    def test_restart_button_starts_fresh_and_blocks_auto_restore(self):
        from streamlit.testing.v1 import AppTest
        self.run_pipeline()
        at = AppTest.from_file(str(BASE / "app.py")).run(timeout=40)
        self.assertTrue(at.session_state["info_confirmed"])
        next(b for b in at.button if b.label == "🔄 重新开始").click().run(timeout=40)
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["wizard_page"], 0)
        self.assertNotIn("info_confirmed", at.session_state)
        self.assertTrue(at.session_state.get("_no_auto_restore"))
        self.assertTrue(at.button(key="jump_5").disabled)
        next(b for b in at.button if b.label == "✅ 确认信息，进入下一步").click().run(timeout=40)
        self.assertFalse(at.exception)
        self.assertNotIn("_no_auto_restore", at.session_state)
        self.assertEqual(at.session_state["wizard_page"], 1)

    def test_normalized_legacy_user_keeps_confirmation(self):
        from streamlit.testing.v1 import AppTest
        with db.get_conn() as conn:
            conn.execute("INSERT INTO user_records (l0, l1, l3) VALUES (?,?,?)",
                         (json.dumps({"姓名": "老用户"}), json.dumps({}),
                          json.dumps({"意向城市": "北京"})))
        at = AppTest.from_file(str(BASE / "app.py")).run(timeout=40)
        self.assertFalse(at.exception)
        self.assertTrue(at.session_state["info_confirmed"])
        at.run(timeout=40)
        self.assertTrue(at.session_state["info_confirmed"])


if __name__ == "__main__":
    unittest.main()
