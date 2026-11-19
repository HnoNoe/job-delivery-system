"""清空本机数据（侧栏「🧹 清空本机数据」后端）的回归测试。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_support import isolate_test_environment

isolate_test_environment()

import config
import data_reset
import db
import session

BASE = Path(__file__).resolve().parents[1]


class DataResetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jobdelivery-reset-")
        self.root = Path(self.temp.name)
        self.patches = patch.multiple(
            config, RUNTIME_DIR=self.root, DATA_DIR=self.root / "data",
            LOG_DIR=self.root / "logs", DB_PATH=str(self.root / "data/test.db"))
        self.patches.start()
        self.session_patch = patch.object(session, "SESSION_DIR", self.root / "sessions")
        self.session_patch.start()
        db.init_db()
        (self.root / "data").mkdir(exist_ok=True)

        with db.get_conn() as conn:
            conn.execute("INSERT INTO user_records (l0, l1, l3) VALUES ('{}','{}','{}')")
            conn.execute("INSERT INTO delivery_tasks (job_id, user_id, job_name, unit_name, status)"
                         " VALUES (1, 1, '岗位', '公司', '已投递')")
            conn.execute("INSERT INTO hr_inbox (platform, company, message, kind, msg_hash)"
                         " VALUES ('boss','公司','聊一聊','线上交流邀请','h1')")
            conn.execute("INSERT INTO app_state (key, value) VALUES ('auto_reply_enabled','1')")

        for name in ("resumes", "packages", "outbox"):
            d = self.root / name
            d.mkdir(parents=True, exist_ok=True)
            (d / ("x_%s.txt" % name)).write_text("x", encoding="utf-8")
        data = self.root / "data"
        (data / "send_count.txt").write_text("2026-01-01,1", encoding="utf-8")
        (data / "mock_greets.jsonl").write_text("{}\n", encoding="utf-8")
        (data / "chat_probe_boss.json").write_text("{}", encoding="utf-8")
        (data / "search_debug_boss.log").write_text("log", encoding="utf-8")
        (data / "ui_prefs.json").write_text(json.dumps({"dark": False}), encoding="utf-8")

        # 伪造登录态目录
        (self.root / "sessions").mkdir(exist_ok=True)
        (self.root / "sessions" / "boss.json").write_text("[]", encoding="utf-8")

    def tearDown(self):
        self.session_patch.stop()
        self.patches.stop()
        self.temp.cleanup()

    def _counts(self):
        with db.get_conn() as conn:
            return {t: conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                    for t in ("user_records", "delivery_tasks", "hr_inbox", "app_state")}

    def test_reset_keeps_schema_files_and_login(self):
        summary = data_reset.reset_all(clear_login=False)
        self.assertEqual(self._counts(), {"user_records": 0, "delivery_tasks": 0,
                                          "hr_inbox": 0, "app_state": 0})
        # 表结构仍在（可以继续用）
        with db.get_conn() as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("user_records", tables)
        self.assertIn("hr_inbox", tables)
        # 生成文件被清掉，但目录保留
        self.assertTrue((self.root / "resumes").is_dir())
        self.assertEqual(list((self.root / "resumes").iterdir()), [])
        self.assertFalse((self.root / "data" / "send_count.txt").exists())
        self.assertFalse((self.root / "data" / "chat_probe_boss.json").exists())
        # 主题偏好保留
        self.assertTrue((self.root / "data" / "ui_prefs.json").exists())
        # 登录态默认保留
        self.assertTrue((self.root / "sessions" / "boss.json").exists())
        self.assertIn("database", summary)
        self.assertTrue(summary["files"])

    def test_reset_with_clear_login_removes_sessions(self):
        with patch.object(session, "clear_session", return_value=None), \
                patch.object(session, "dpage_quit", return_value=None):
            summary = data_reset.reset_all(clear_login=True)
        self.assertEqual(list((self.root / "sessions").iterdir()), [])
        self.assertTrue(summary["clear_login"])
        self.assertTrue(summary["login"])

    def test_reset_is_idempotent(self):
        data_reset.reset_all(clear_login=False)
        summary = data_reset.reset_all(clear_login=False)
        self.assertEqual(self._counts(), {"user_records": 0, "delivery_tasks": 0,
                                          "hr_inbox": 0, "app_state": 0})
        self.assertIsInstance(summary["database"], dict)


if __name__ == "__main__":
    unittest.main()


class UiClearTests(unittest.TestCase):
    """侧栏「🧹 清空本机数据」的二次确认交互。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jobdelivery-clear-ui-")
        self.root = Path(self.temp.name)
        self.patches = patch.multiple(
            config, RUNTIME_DIR=self.root, DATA_DIR=self.root / "data",
            LOG_DIR=self.root / "logs", DB_PATH=str(self.root / "data/test.db"))
        self.patches.start()
        self.session_patch = patch.object(session, "SESSION_DIR", self.root / "sessions")
        self.session_patch.start()
        session.SESSION_DIR.mkdir()
        db.init_db()
        with db.get_conn() as conn:
            conn.execute("INSERT INTO user_records (l0, l1, l3) VALUES ('{}','{}','{}')")

    def tearDown(self):
        import logging
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

    def _users(self):
        with db.get_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM user_records").fetchone()[0]

    def test_two_step_confirmation(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(BASE / "app.py")).run(timeout=60)
        self.assertFalse(at.exception)
        self.assertEqual(self._users(), 1)

        # 第一步：点按钮 → 弹出确认窗，但数据不动
        at.button(key="btn_clear_data").click().run(timeout=60)
        self.assertFalse(at.exception)
        self.assertTrue(at.session_state.get("_show_clear_dialog"))
        self.assertEqual(self._users(), 1)
        self.assertTrue(at.button(key="_clear_do").disabled)  # 未勾选不可确认

        # 第二步：勾选确认 → 按钮解锁 → 执行清空
        at.checkbox(key="_clear_confirmed").set_value(True).run(timeout=60)
        self.assertFalse(at.button(key="_clear_do").disabled)
        at.button(key="_clear_do").click().run(timeout=60)
        self.assertFalse(at.exception)
        self.assertEqual(self._users(), 0)
        self.assertNotIn("_show_clear_dialog", at.session_state)

    def test_cancel_keeps_data(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(BASE / "app.py")).run(timeout=60)
        at.button(key="btn_clear_data").click().run(timeout=60)
        at.button(key="_clear_cancel").click().run(timeout=60)
        self.assertFalse(at.exception)
        self.assertNotIn("_show_clear_dialog", at.session_state)
        self.assertEqual(self._users(), 1)
