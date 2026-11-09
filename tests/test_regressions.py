"""Reproductions for portability and data-integrity bugs; no external sends."""
import copy
from contextlib import closing
import importlib
import io
import json
import logging
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from test_support import isolate_test_environment
isolate_test_environment()

import config
import crawler
import db
import delivery
import feedback
import generation
import matching
import mock_site
import pipeline
import platforms
import session
import start
import user_profile
import verification
from runtime_paths import resolve_resume, safe_filename
import numpy as np
from formulas import formula_4_experience_allocation, formula_5_weight_update, logistic

BASE = Path(__file__).resolve().parents[1]


def user():
    return {
        "l0": {"姓名": "测试用户", "性别": "男", "出生日期": "2001-01-01", "手机": "13800138000",
               "邮箱": "test@example.com", "政治面貌": "群众", "民族": "汉", "现居": "北京", "籍贯": "北京",
               "学历阶段": "本科", "学校": "示例大学", "学院": "计算机学院", "专业": "软件工程",
               "入学年月": "2020-09", "毕业年月": "2024-06"},
        "l1": {"项目": 2},
        "l2": [{"类型": "项目", "名称": "Python-web", "技术工具": "Python Flask", "事项": "开发接口",
                "时间起": "2023-01", "时间止": "2023-06"},
               {"类型": "项目", "名称": "前端", "技术工具": "Vue", "事项": "开发页面"}],
        "l3": {"意向城市": "北京", "意向行业": "互联网", "意向岗位": "后端开发", "投递策略": "海投",
               "到岗时间": "2024-07", "能否出差": "是"}}


def job(n=1):
    return {"岗位名称": "Python后端开发", "单位名称": "公司%d" % n, "岗位链接": "https://example.com/jobs/%d" % n,
            "城市": "北京", "行业": "互联网", "岗位描述": "Python Flask", "技能": ["Python", "Flask"],
            "学历": "本科", "投递入口类型": "API", "投递入口地址": "http://127.0.0.1:1/apply"}


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jobdelivery-case-")
        self.root = Path(self.temp.name)
        self.patches = patch.multiple(config, RUNTIME_DIR=self.root, DATA_DIR=self.root / "data",
                                      LOG_DIR=self.root / "logs", DB_PATH=str(self.root / "data/test.db"),
                                      SAFE_MODE=True, DELIVER_INTERVAL=0)
        self.patches.start()
        self.session_patch = patch.object(session, "SESSION_DIR", self.root / "sessions")
        self.session_patch.start()
        session.SESSION_DIR.mkdir()
        db.init_db()

    def tearDown(self):
        for logger in list(logging.Logger.manager.loggerDict.values()):
            if isinstance(logger, logging.Logger):
                for handler in logger.handlers[:]:
                    if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename).resolve().is_relative_to(self.root.resolve()):
                        logger.removeHandler(handler)
                        handler.close()
        self.session_patch.stop()
        self.patches.stop()
        self.temp.cleanup()

    def run_pipeline(self, jobs=None, data=None):
        result = pipeline.run_full_pipeline(data or user(), jobs=[job()] if jobs is None else jobs)
        self.assertTrue(result["ok"], result)
        return result

    def task(self, tid):
        with db.get_conn() as conn:
            return dict(conn.execute("SELECT * FROM delivery_tasks WHERE task_id=?", (tid,)).fetchone())

    def test_stdlib_profile_import(self):
        self.assertTrue(callable(importlib.import_module("cProfile").run))

    def test_html_collection_without_lxml_and_relative_links(self):
        page = self.root / "岗位 页面.html"
        page.write_text('<ul><li><h3>Python后端</h3><b>公司</b><a href="../jobs/1">详情</a></li></ul>', encoding="utf-8")
        cfg = {"url": page.as_uri(), "delay": 0, "item_selector": "li", "base_url": "https://example.com/search/page/",
               "fields": {"岗位名称": "h3", "单位名称": "b", "岗位链接": "a"}}
        jobs = crawler.collect_from_sources([cfg])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["岗位链接"], "https://example.com/search/jobs/1")
        self.assertEqual(crawler._abs_url("//cdn.example.com/1", "https://example.com"), "https://cdn.example.com/1")

    def test_url_encoding_and_city(self):
        url = platforms.search_url("boss", "C++ & Python", "上海", api=True)
        self.assertIn("C%2B%2B%20%26%20Python", url)
        self.assertIn("city=101020100", url)
        self.assertEqual(platforms.city_code("boss", "101020100"), "101020100")
        with self.assertRaises(ValueError):
            platforms.city_code("boss", "不存在的城市")
        self.assertIn("job_detail/abc.html", platforms.job_url("boss", "abc"))

    def test_history_survives_new_search(self):
        first = self.run_pipeline()
        tid = first["target_jobs"][0]["task_id"]
        self.run_pipeline(jobs=[job(2)])
        self.assertTrue(feedback.mark_result(tid, 1)[0])
        self.assertEqual(self.task(tid)["result"], "进面试")
        self.assertEqual(len(generation.regenerate_one(first["user_id"], user_profile.build_profile(first["user_id"]), tid, [0])), 1)

    def test_repeated_search_is_idempotent_and_user_scoped(self):
        first = self.run_pipeline()
        self.run_pipeline(jobs=[job(2)])
        targets = pipeline.re_match(first["user_id"], user())
        self.assertEqual([x["job"]["单位名称"] for x in targets], ["公司1"])
        matching.store_jobs([job()], user_id=first["user_id"])
        with db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 2)

    def test_empty_search_stays_empty_after_other_user_search(self):
        empty = self.run_pipeline(jobs=[])
        self.run_pipeline()
        self.assertEqual(pipeline.re_match(empty["user_id"], user()), [])

    def test_feedback_retry_and_correction(self):
        result = self.run_pipeline()
        tid = result["target_jobs"][0]["task_id"]
        with db.get_conn() as conn:
            conn.execute("UPDATE task_indicators SET indicator='[1,0]' WHERE task_id=?", (tid,))
        ok, once = feedback.mark_result(tid, 1)
        self.assertTrue(ok)
        self.assertGreater(once[0], 0.5)
        self.assertEqual(feedback.mark_result(tid, 1), (True, once))
        with db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM history_samples").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM profile_pool").fetchone()[0], 1)
        ok, corrected = feedback.mark_result(tid, 0)
        self.assertTrue(ok)
        np.testing.assert_allclose(corrected, [0.5, 0.5])
        with db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM history_samples").fetchone()[0], 1)

    def test_invalid_feedback_is_atomic(self):
        result = self.run_pipeline()
        tid = result["target_jobs"][0]["task_id"]
        old = self.task(tid)["result"]
        self.assertFalse(feedback.mark_result(tid, 2)[0])
        with db.get_conn() as conn:
            conn.execute("DELETE FROM task_indicators WHERE task_id=?", (tid,))
        self.assertFalse(feedback.mark_result(tid, 1)[0])
        self.assertEqual(self.task(tid)["result"], old)

    def test_materials_are_not_feedback_or_sends(self):
        result = self.run_pipeline()
        tid = result["target_jobs"][0]["task_id"]
        self.assertEqual(feedback.get_quality(result["user_id"])["已标注"], 0)
        self.assertTrue(delivery.deliver_one(tid)[0])
        self.assertEqual(self.task(tid)["status"], "待投递")
        self.assertEqual(delivery._daily_sends(), 0)
        self.assertTrue(delivery.record_manual_delivery(tid)[0])
        self.assertFalse(delivery.record_manual_delivery(tid)[0])
        feedback.mark_result(tid, 1)
        quality = feedback.get_quality(result["user_id"])
        self.assertEqual(quality["进面试"], 1)
        self.assertEqual(quality["反馈率%"], 100)

    def test_failed_http_is_not_sent(self):
        result = self.run_pipeline()
        tid = result["target_jobs"][0]["task_id"]
        with patch.object(config, "SAFE_MODE", False), patch.object(config, "MAX_RETRY", 1), \
             patch("requests.post", return_value=Mock(status_code=503)):
            self.assertFalse(delivery.deliver_one(tid)[0])
        self.assertEqual(self.task(tid)["status"], "待投递")
        self.assertEqual(delivery._daily_sends(), 0)

    def test_http_business_error_is_not_sent(self):
        result = self.run_pipeline()
        tid = result["target_jobs"][0]["task_id"]
        response = Mock(status_code=200, content=b'{}')
        response.json.return_value = {"code": 37, "message": "风控"}
        with patch.object(config, "SAFE_MODE", False), patch("requests.post", return_value=response):
            ok, message = delivery.deliver_one(tid)
        self.assertFalse(ok)
        self.assertIn("风控", message)
        self.assertEqual(self.task(tid)["status"], "待投递")

    def test_successful_api_sends_once(self):
        result = self.run_pipeline()
        tid = result["target_jobs"][0]["task_id"]
        response = Mock(status_code=201, content=b'{}')
        response.json.return_value = {"code": 0}
        with patch.object(config, "SAFE_MODE", False), patch("requests.post", return_value=response) as post:
            self.assertTrue(delivery.deliver_one(tid)[0])
            self.assertFalse(delivery.deliver_one(tid)[0])
            self.assertEqual(post.call_count, 1)
        self.assertEqual(delivery._daily_sends(), 1)

    def test_timeout_requires_manual_check_without_retry(self):
        import requests
        result = self.run_pipeline()
        tid = result["target_jobs"][0]["task_id"]
        with patch.object(config, "SAFE_MODE", False), patch("requests.post", side_effect=requests.Timeout("timeout")) as post:
            self.assertFalse(delivery.deliver_one(tid)[0])
            self.assertEqual(post.call_count, 1)
        self.assertEqual(self.task(tid)["status"], "待核实")

    def test_uncertain_task_is_not_downgraded_and_cannot_be_resent(self):
        """待核实 = 可能已经发到平台，不能回到「待投递」被二次投递。"""
        import requests
        result = self.run_pipeline()
        tid = result["target_jobs"][0]["task_id"]
        with patch.object(config, "SAFE_MODE", False), patch("requests.post", side_effect=requests.Timeout("t")):
            self.assertFalse(delivery.deliver_one(tid)[0])
        self.assertEqual(self.task(tid)["status"], "待核实")
        profile = user_profile.build_profile(result["user_id"])
        self.assertEqual(generation.regenerate_one(result["user_id"], profile, tid, [0]), [])
        self.assertEqual(delivery.prepare_batch(result["user_id"], [tid]), [])
        self.assertEqual(self.task(tid)["status"], "待核实")
        self.assertFalse(delivery.deliver_one(tid)[0])
        self.assertEqual(self.task(tid)["status"], "待核实")

    def test_search_launches_hidden_browser(self):
        """检索默认静默：需要新开浏览器时以 hidden=True 启动（窗口移到屏幕外）。"""
        session._DPAGES.clear()
        screen = {"mock": object()}
        with patch.object(session, "_attach_existing", return_value=None), \
             patch.object(session, "_launch_dpage", side_effect=lambda key, hidden=False: screen[key]) as launch:
            page = session._get_page("mock", hidden=True)
        self.assertIs(page, screen["mock"])
        launch.assert_called_once_with("mock", hidden=True)
        session._DPAGES.clear()

    def test_login_status_detection(self):
        import time as _time
        import login_status
        self.assertEqual(login_status.check_platform("boss", online=False)["state"], "absent")
        session.save_cookies("boss", [{"name": "bst", "value": "x", "expires": _time.time() + 3600}])
        self.assertEqual(login_status.check_platform("boss", online=False)["state"], "saved")
        session.save_cookies("boss", [{"name": "bst", "value": "x", "expires": 1}])
        self.assertEqual(login_status.check_platform("boss", online=False)["state"], "expired")

    def test_login_status_online_probe(self):
        import time as _time
        import login_status
        session.save_cookies("boss", [{"name": "bst", "value": "x", "expires": _time.time() + 3600}])
        expired = Mock(status_code=200, url="https://www.zhipin.com/web/user/?ka=header-login", text="login")
        with patch("requests.get", return_value=expired):
            self.assertEqual(login_status.check_platform("boss", online=True)["state"], "expired")
        blocked = Mock(status_code=200, url="https://www.zhipin.com/web/chat/index",
                       text="Security Verification")
        with patch("requests.get", return_value=blocked):
            self.assertEqual(login_status.check_platform("boss", online=True)["state"], "blocked")
        alive = Mock(status_code=200, url="https://www.zhipin.com/web/chat/index", text="消息列表")
        with patch("requests.get", return_value=alive):
            self.assertEqual(login_status.check_platform("boss", online=True)["state"], "logged_in")

    def test_missing_drissionpage_gives_friendly_error(self):
        """CI 只装 requirements.txt（无 DrissionPage）时，登录入口要给安装提示而不是 ImportError。"""
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "DrissionPage":
                raise ImportError("blocked for test")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            ok, msg = session.dpage_open("boss")
        self.assertFalse(ok)
        self.assertIn("浏览器功能依赖缺失", msg)

    def test_entry_url_validation(self):
        for bad in ("file:///etc/passwd", "ftp://example.com/x", "http://10.0.0.5/apply",
                    "http://user:pass@example.com/x", "not-a-url"):
            with self.subTest(url=bad), self.assertRaises(delivery.DeliveryError):
                delivery.checked_entry_url(bad)
        self.assertTrue(delivery.checked_entry_url("http://127.0.0.1:8000/apply").startswith("http://127.0.0.1"))

    def test_mock_search_accepts_multi_token_keyword(self):
        import requests
        server = mock_site.start_in_background(port=0)
        try:
            port = server.server_address[1]
            data = requests.get(
                "http://127.0.0.1:%d/wapi/zpgeek/search/joblist.json?query=Python%%20后端&city=北京&page=1" % port,
                timeout=10).json()
            names = [j["jobName"] for j in data["zpData"]["jobList"]]
            self.assertTrue(names, "multi-token keyword returned nothing")
            self.assertIn("Python后端开发工程师", names)
        finally:
            mock_site.stop_server()

    def test_concurrent_task_claim_and_daily_budget(self):
        result = self.run_pipeline(jobs=[job(1), job(2)])
        first, second = [t["task_id"] for t in result["target_jobs"]]
        with patch.object(config, "DAILY_SEND_LIMIT", 1):
            delivery._reserve_send(first)
            with self.assertRaises(delivery.DeliveryError):
                delivery._reserve_send(first)
            with self.assertRaises(delivery.DeliveryError):
                delivery._reserve_send(second)
            delivery._finish_send(first, False, "失败")
            delivery._reserve_send(second)

    def test_legacy_cookie_data_and_json_roundtrip(self):
        import pickle
        cookies = [{"name": "mock_login", "value": "1"}]
        (session.SESSION_DIR / "mock.pkl").write_bytes(pickle.dumps(cookies))
        self.assertEqual(session.load_session("mock"), cookies)
        session.save_cookies("mock", cookies)
        self.assertEqual(session.load_session("mock"), cookies)
        session.clear_session("mock")
        self.assertFalse(session.has_session("mock"))

    def test_smtp_failure_creates_draft_and_keeps_pending(self):
        mail = job()
        mail.update({"投递入口类型": "邮件", "投递入口地址": "test@example.com", "岗位链接": ""})
        result = self.run_pipeline(jobs=[mail])
        tid = result["target_jobs"][0]["task_id"]
        with patch.object(config, "SAFE_MODE", False), patch.object(config, "SMTP_USER", "me@example.com"), \
             patch.object(config, "SMTP_PASSWORD", "test-password"), patch("smtplib.SMTP_SSL", side_effect=OSError("offline")):
            self.assertFalse(delivery.deliver_one(tid)[0])
        self.assertEqual(self.task(tid)["status"], "待投递")
        self.assertEqual(len(list((self.root / "outbox").glob("*.txt"))), 1)

    def test_missing_smtp_is_not_sent(self):
        mail = job()
        mail.update({"投递入口类型": "邮件", "投递入口地址": "test@example.com"})
        result = self.run_pipeline(jobs=[mail])
        with patch.object(config, "SAFE_MODE", False), patch.object(config, "SMTP_USER", ""), patch.object(config, "SMTP_PASSWORD", ""):
            self.assertFalse(delivery.deliver_one(result["target_jobs"][0]["task_id"])[0])
        self.assertEqual(delivery._daily_sends(), 0)

    def test_batch_empty_selection_and_cap(self):
        result = self.run_pipeline(jobs=[job(n) for n in range(7)])
        with patch.object(config, "SAFE_MODE", False), patch("delivery.deliver_one", return_value=(True, "ok")) as send:
            self.assertEqual(delivery.deliver_batch(task_ids=[])["投递数"], 0)
            self.assertFalse(send.called)
            self.assertEqual(delivery.deliver_batch(limit=999)["投递数"], config.BATCH_SEND_LIMIT)

    def test_pdf_portable_escaped_and_dates_preserved(self):
        data = user()
        data["l0"]["姓名"] = "测试<用户>&"
        data["l2"][0]["事项"] = "使用 C++ <vector> & Python"
        result = self.run_pipeline(data=data)
        t = self.task(result["target_jobs"][0]["task_id"])
        self.assertFalse(Path(t["resume_path"]).is_absolute())
        path = resolve_resume(t["resume_path"])
        self.assertEqual(path.suffix, ".pdf")
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        self.assertIn("测试<用户>&", text)
        self.assertIn("2023-01", text)
        self.assertIn("Python-web", text)
        old = "Z:/old/project/resumes/" + path.name
        self.assertEqual(resolve_resume(old), path)

    def test_illegal_company_name_and_distinct_duplicate_experiences(self):
        data = user()
        data["l2"][1] = dict(data["l2"][0], 事项="另一条经历")
        source = job()
        source["单位名称"] = '研发/平台: A?B*<C>|'
        result = self.run_pipeline(jobs=[source], data=data)
        tid = result["target_jobs"][0]["task_id"]
        generation.regenerate_one(result["user_id"], user_profile.build_profile(result["user_id"]), tid, [0, 1])
        with db.get_conn() as conn:
            fields = json.loads(conn.execute("SELECT fields FROM job_field_map WHERE task_id=?", (tid,)).fetchone()[0])
        self.assertEqual(len([key for key in fields if key.endswith("-事项")]), 2)
        self.assertEqual(len(list((self.root / "packages").glob("*.zip"))), 1)
        for value in ("../CON", 'a/b:c?d*', "NUL"):
            self.assertNotIn("/", safe_filename(value))

    def test_regenerate_updates_archive(self):
        result = self.run_pipeline()
        tid = result["target_jobs"][0]["task_id"]
        generation.regenerate_one(result["user_id"], user_profile.build_profile(result["user_id"]), tid, [1])
        delivery.prepare_batch(result["user_id"], [tid])
        path = resolve_resume(self.task(tid)["resume_path"])
        with zipfile.ZipFile(next((self.root / "packages").glob("*.zip"))) as archive:
            self.assertEqual(archive.read(path.name), path.read_bytes())
        delivery.record_manual_delivery(tid)
        self.assertEqual(generation.regenerate_one(result["user_id"], user_profile.build_profile(result["user_id"]), tid, []), [])

    def test_missing_browser_and_corrupt_session_are_handled(self):
        with patch("session._launch_dpage", side_effect=RuntimeError("缺浏览器")):
            self.assertEqual(session.dpage_open("boss"), (False, "缺浏览器"))
        self.assertFalse(session.dpage_open("unknown")[0])
        (session.SESSION_DIR / "boss.pkl").write_bytes(b"bad cookie")
        self.assertFalse(session.has_session("boss"))
        session._DPAGES["boss"] = Mock()
        try:
            self.assertFalse(session.is_active("boss"))
        finally:
            session._DPAGES.pop("boss")

    @unittest.skipUnless(importlib.util.find_spec("selenium"), "optional Selenium is not installed")
    def test_form_missing_submit_is_failure(self):
        import form_filler
        driver = Mock()
        driver.find_elements.return_value = []
        with patch("form_filler.collect_controls", return_value=[]), patch("form_filler._submit", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "提交"):
                form_filler.fill_form(driver, {})

    def test_invalid_user_values_report_errors(self):
        for bad in (None, {"l0": None}, dict(user(), l1={"项目": "abc"}), dict(user(), l1={"项目": -2})):
            self.assertFalse(verification.verify(bad)[0])
        data = user()
        data["l0"]["出生日期"] = "2025-02-31"
        self.assertFalse(verification.verify(data)[0])
        data["l0"]["出生日期"] = None
        self.assertFalse(verification.verify(data)[0])

    def test_zero_experiences_and_large_exponents(self):
        np.testing.assert_equal(formula_4_experience_allocation([], [], 1), [])
        weights = formula_4_experience_allocation([0.5, 0.5], [1, -1], 10000)
        self.assertTrue(np.isfinite(weights).all())
        self.assertAlmostEqual(float(weights.sum()), 1)
        self.assertLess(float(logistic(10000)), 1)
        self.assertTrue(np.isfinite(formula_5_weight_update([0.5, 0.5], 1, [1, 0], 10000)).all())
        data = user()
        data["l1"] = {}
        data["l2"] = []
        self.assertTrue(pipeline.run_full_pipeline(data, jobs=[job()])["ok"])

    def test_legacy_database_migration(self):
        legacy = self.root / "legacy.db"
        with closing(sqlite3.connect(legacy)) as conn:
            conn.execute("CREATE TABLE jobs (job_id INTEGER PRIMARY KEY AUTOINCREMENT, fields TEXT NOT NULL, embedding TEXT)")
            conn.execute("INSERT INTO jobs(fields) VALUES ('{}')")
            conn.commit()
        with patch.object(config, "DB_PATH", str(legacy)):
            db.init_db()
            db.init_db()
            with db.get_conn() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)
                self.assertIn("match_score", {r[1] for r in conn.execute("PRAGMA table_info(delivery_tasks)")})

    def test_occupied_port_chooses_another(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            sock.listen()
            self.assertNotEqual(start.available_port(port), port)
            self.assertFalse(start.health_ready(port))

    def test_failed_generation_rolls_back_and_releases_db(self):
        result = self.run_pipeline()
        tid = result["target_jobs"][0]["task_id"]
        llm = Mock()
        llm.generate.side_effect = RuntimeError("LLM offline")
        with self.assertRaises(RuntimeError):
            generation.regenerate_one(result["user_id"], user_profile.build_profile(result["user_id"]), tid, [0], llm=llm)
        with db.get_conn() as conn:
            conn.execute("UPDATE delivery_tasks SET result='rollback checked' WHERE task_id=?", (tid,))

    def test_ui_material_manual_delivery_and_feedback(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(BASE / "app.py"))
        at.session_state["jobs"] = [job()]
        at.run(timeout=30)
        self.assertFalse(at.exception)
        next(b for b in at.button if b.label == "✅ 确认信息，进入下一步").click().run(timeout=30)
        next(b for b in at.button if b.label == "🚀 准备投递材料").click().run(timeout=30)
        self.assertFalse(at.exception)
        result = at.session_state["result"]
        self.assertGreater(result["task_count"], 0)
        tid = result["target_jobs"][0]["task_id"]
        self.assertTrue(at.button(key="fb1_%d" % tid).disabled)
        at.button(key="manual_%d" % tid).click().run(timeout=30)
        self.assertFalse(at.exception)
        self.assertFalse(at.button(key="fb1_%d" % tid).disabled)
        at.button(key="fb1_%d" % tid).click().run(timeout=30)
        self.assertFalse(at.exception)
        self.assertEqual(feedback.get_quality(result["user_id"])["进面试"], 1)

    def test_ui_edit_invalidates_confirmation(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(BASE / "app.py")).run(timeout=30)
        next(b for b in at.button if b.label == "✅ 确认信息，进入下一步").click().run(timeout=30)
        self.assertTrue(at.session_state["info_confirmed"])
        at.text_input(key="l0_姓名").set_value("新姓名").run(timeout=30)
        self.assertFalse(at.session_state["info_confirmed"])

    def test_ui_duplicate_experiences_and_reset(self):
        from streamlit.testing.v1 import AppTest
        data = user()
        data["l2"][1] = dict(data["l2"][0])
        result = self.run_pipeline(data=data)
        at = AppTest.from_file(str(BASE / "app.py"))
        at.session_state["jobs"] = [job()]
        at.session_state["result"] = result
        at.session_state["prepared_user_data"] = data
        at.session_state["rematch"] = []
        at.run(timeout=30)
        self.assertFalse(at.exception)
        at.button(key="btn_rematch").click().run(timeout=30)
        self.assertFalse(at.exception)
        self.assertIn(result["target_jobs"][0]["job_id"], at.session_state["rematch_old"])
        next(b for b in at.button if b.label == "🔄 重新开始").click().run(timeout=30)
        self.assertFalse(at.exception)
        self.assertNotIn("result", at.session_state)
        self.assertNotIn("rematch", at.session_state)

    def test_pdf_upload_parses_once_and_keeps_edits(self):
        from streamlit.testing.v1 import AppTest
        pdf_path = resolve_resume(generation._write_resume(1, 1, {"姓名": "原始姓名"}, job()))
        uploaded = io.BytesIO(pdf_path.read_bytes())
        with patch("streamlit.file_uploader", return_value=uploaded), patch("recommend.resume_parse", return_value={"姓名": "解析姓名"}) as parse:
            at = AppTest.from_file(str(BASE / "app.py")).run(timeout=30)
            self.assertFalse(at.exception)
            self.assertEqual(parse.call_count, 1)
            at.text_input(key="l0_姓名").set_value("手改姓名").run(timeout=30)
            self.assertFalse(at.exception)
            self.assertEqual(parse.call_count, 1)
            self.assertEqual(at.text_input(key="l0_姓名").value, "手改姓名")


    def test_new_platform_city_codes(self):
        self.assertEqual(platforms.city_code("zhilian", "北京"), "530")
        self.assertEqual(platforms.city_code("zhilian", "杭州"), "653")
        self.assertEqual(platforms.city_code("liepin", "上海"), "020")
        self.assertEqual(platforms.city_code("liepin", "郑州"), "150020")
        self.assertEqual(platforms.city_code("job51", "广州"), "030200")
        self.assertEqual(platforms.city_code("job51", "长沙"), "190200")
        with self.assertRaises(ValueError):
            platforms.city_code("zhilian", "不存在的城市")

    def test_zhilian_state_jobs_include_links(self):
        state = {"positionList": [{
            "name": "后端工程师",
            "companyName": "示例科技",
            "workCity": "北京",
            "cityDistrict": "朝阳",
            "salary60": "1-2万",
            "education": "本科",
            "workingExp": "3-5年",
            "industryName": "互联网",
            "positionUrl": "https://www.zhaopin.com/jobdetail/CCL1.htm",
        }]}
        jobs = crawler.jobs_from_zhilian_state(state)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["城市"], "北京 朝阳")
        self.assertEqual(jobs[0]["薪资"], "1-2万")
        self.assertIn("jobdetail/CCL1.htm", jobs[0]["岗位链接"])

    def test_rendered_cards_for_job51_and_liepin(self):
        job51_html = """
        <div class="joblist-item">
          <div class="joblist-item-jobname">后端工程师</div>
          <div class="joblist-item-right"><a class="comp"><span class="cname">示例科技</span></a></div>
          <div class="joblist-item-jobinfo">1.5-2万 北京·海淀区 5分钟前回复</div>
          <div sensorsdata='{"jobId":"174153967"}'></div>
        </div>
        """
        jobs = crawler.parse_job_cards(job51_html, "job51", "https://we.51job.com")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["城市"], "北京·海淀区")
        self.assertEqual(jobs[0]["薪资"], "1.5-2万")
        self.assertEqual(jobs[0]["岗位链接"], "https://jobs.51job.com/all/174153967.html")

        liepin_html = """
        <div class="jobCardPcContainer">
          <div class="jobTitleBox">
            <div class="ellipsis-1" title="后端工程师">后端工程师</div>
            <span class="ellipsis-1">北京-海淀区</span>
          </div>
          <span class="companyName">示例科技</span>
          <a data-nick="job-detail-job-info" href="https://www.liepin.com/job/1.shtml?trace=1">x</a>
        </div>
        """
        jobs = crawler.parse_job_cards(liepin_html, "liepin", "https://www.liepin.com")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["城市"], "北京-海淀区")
        self.assertEqual(jobs[0]["岗位链接"], "https://www.liepin.com/job/1.shtml")


if __name__ == "__main__":
    unittest.main()
