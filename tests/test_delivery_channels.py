"""多平台批量投递渠道的回归测试（不联网、不开浏览器）。

覆盖：
1. 平台投递配置齐全（Boss 选择器 / 文案兜底 / 前程无忧无站内聊天）；
2. dpage_deliver 按平台配置构造 JS，并正确映射 成功/风控/已投递/未找到；
3. dpage_greet 对「直接投递」平台跳过，对不确定送达保持「待核实」语义；
4. deliver_one 按岗位链接域名路由到对应平台；
5. deliver_batch 返回按渠道统计，且单条失败不中断其余投递。
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_support import isolate_test_environment

isolate_test_environment()

import config
import db
import delivery
import platforms
import session

BASE = Path(__file__).resolve().parents[1]


class FakePage:
    """最小 DrissionPage 替身：记录 JS 并返回预设值。"""

    def __init__(self, result="ok:a.btn-startchat", url="https://www.zhipin.com/job_detail/x.html",
                 results=None):
        self.result = result
        self.results = list(results) if results is not None else None
        self.url = url
        self.last_script = ""

    def get(self, url):
        # 真实浏览器会导航并可能被重定向；替身只记录请求，url 由测试预设（模拟重定向后的地址）
        self.requested = url

    def wait(self, seconds=1):
        return None

    def run_js(self, script, *args, **kwargs):
        self.last_script = script
        if self.results is not None:
            return self.results.pop(0) if self.results else "unconfirmed"
        return self.result


class ChannelConfigTests(unittest.TestCase):
    def test_all_platforms_have_delivery_config(self):
        for pk in ("mock", "boss", "zhilian", "lagou", "liepin", "job51"):
            cfg = platforms.get(pk)
            self.assertIsNotNone(cfg, pk)
            self.assertTrue(cfg.get("deliver_click_texts"), "%s 缺少投递按钮文案" % pk)
            self.assertIsInstance(cfg.get("greet_supported"), bool, pk)
        self.assertIn("a.btn-startchat", platforms.get("boss")["deliver_click_selectors"])
        self.assertFalse(platforms.get("job51")["greet_supported"])
        zhilian = platforms.get("zhilian")
        self.assertIn("立即投递", zhilian["deliver_click_texts"])
        self.assertTrue(zhilian.get("auto_greeting"))
        self.assertTrue(zhilian.get("deliver_success_texts"))

    def test_unknown_platform_has_no_delivery_config(self):
        self.assertIsNone(platforms.get("nope"))


class DpageDeliverTests(unittest.TestCase):
    def tearDown(self):
        session._DPAGES.clear()

    def test_job51_clicks_by_configured_text(self):
        page = FakePage(result="ok:立即申请")
        session._DPAGES["job51"] = page
        ok, msg = session.dpage_deliver("job51", "https://jobs.51job.com/x.html")
        self.assertTrue(ok)
        self.assertIn("立即申请", msg)
        self.assertIn("立即申请", page.last_script)
        self.assertIn("申请职位", page.last_script)

    def test_risk_detected(self):
        session._DPAGES["boss"] = FakePage(result="risk")
        ok, msg = session.dpage_deliver("boss", "https://www.zhipin.com/job_detail/1.html")
        self.assertFalse(ok)
        self.assertIn("风控", msg)

    def test_already_applied(self):
        session._DPAGES["zhilian"] = FakePage(result="done")
        ok, msg = session.dpage_deliver("zhilian", "https://www.zhaopin.com/x.htm")
        self.assertFalse(ok)
        self.assertIn("已投递", msg)

    def test_button_not_found(self):
        session._DPAGES["liepin"] = FakePage(result="notfound")
        ok, msg = session.dpage_deliver("liepin", "https://www.liepin.com/job/1.shtml")
        self.assertFalse(ok)
        self.assertIn("未找到投递按钮", msg)

    def test_zhilian_confirms_immediate_apply(self):
        page = FakePage(results=["ok:立即投递", "confirmed:已向对方发送简历"])
        session._DPAGES["zhilian"] = page
        ok, msg = session.dpage_deliver(
            "zhilian", "https://www.zhaopin.com/jobdetail/CC1.htm")
        self.assertTrue(ok)
        self.assertIn("平台确认", msg)
        self.assertIn("已向对方发送简历", msg)

    def test_zhilian_unconfirmed_apply(self):
        page = FakePage(results=["ok:立即投递"] + ["none"] * 3)
        session._DPAGES["zhilian"] = page
        ok, msg = session.dpage_deliver(
            "zhilian", "https://www.zhaopin.com/jobdetail/CC1.htm")
        self.assertFalse(ok)
        self.assertIn("未检测到平台确认", msg)

    def test_login_redirect(self):
        page = FakePage(result="ok:x")
        page.url = "https://www.zhipin.com/web/user/?ka=header-login"
        session._DPAGES["boss"] = page
        ok, msg = session.dpage_deliver("boss", "https://www.zhipin.com/job_detail/1.html")
        self.assertFalse(ok)
        self.assertIn("登录态失效", msg)

    def test_no_browser(self):
        ok, msg = session.dpage_deliver("boss", "https://www.zhipin.com/job_detail/1.html")
        self.assertFalse(ok)
        self.assertIn("浏览器未打开", msg)


class DpageGreetTests(unittest.TestCase):
    def tearDown(self):
        session._DPAGES.clear()

    def test_direct_apply_platform_skips_greeting(self):
        ok, msg = session.dpage_greet("job51", "您好")
        self.assertTrue(ok)
        self.assertIn("无站内招呼语", msg)

    def test_confirmed_when_message_appears(self):
        page = FakePage(results=["已点击发送按钮", "unconfirmed", "confirmed"])
        session._DPAGES["boss"] = page
        ok, msg = session.dpage_greet("boss", "您好，我想应聘这个岗位")
        self.assertTrue(ok)
        self.assertIn("确认出现在聊天记录", msg)
        # 确认脚本必须排除输入框区域，避免把未发送的输入误判为已发送
        self.assertIn("chat-input", page.last_script)
        self.assertIn("contenteditable", page.last_script)

    def test_unconfirmed_when_message_missing(self):
        page = FakePage(results=["已尝试按 Enter 发送"] + ["unconfirmed"] * 4)
        session._DPAGES["boss"] = page
        ok, msg = session.dpage_greet("boss", "您好，我想应聘这个岗位")
        self.assertFalse(ok)
        self.assertIn("未检测到", msg)
        self.assertIn("请人工核对", msg)

    def test_missing_input(self):
        session._DPAGES["boss"] = FakePage(result="未找到聊天输入框")
        ok, msg = session.dpage_greet("boss", "您好")
        self.assertFalse(ok)
        self.assertIn("未找到聊天输入框", msg)

    def test_sent_is_reported_as_uncertain(self):
        session._DPAGES["boss"] = FakePage(result="已点击发送按钮")
        ok, msg = session.dpage_greet("boss", "您好")
        self.assertFalse(ok)          # 不能确认送达 → 记为待核实
        self.assertIn("请人工核对", msg)
        self.assertIn("已点击发送按钮", msg)


class _DbCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jobdelivery-channel-")
        self.root = Path(self.temp.name)
        self.patches = patch.multiple(
            config, RUNTIME_DIR=self.root, DATA_DIR=self.root / "data",
            LOG_DIR=self.root / "logs", DB_PATH=str(self.root / "data/test.db"),
            SAFE_MODE=False, DELIVER_INTERVAL=0, DAILY_SEND_LIMIT=20, BATCH_SEND_LIMIT=5)
        self.patches.start()
        self.session_patch = patch.object(session, "SESSION_DIR", self.root / "sessions")
        self.session_patch.start()
        session.SESSION_DIR.mkdir()
        (self.root / "data").mkdir(exist_ok=True)
        db.init_db()
        self.resume = self.root / "resume.pdf"
        self.resume.write_bytes(b"%PDF-1.4 test")
        with db.get_conn() as conn:
            conn.execute("INSERT INTO user_records (l0, l1, l3) VALUES (?,?,?)",
                         (json.dumps({"姓名": "测试", "手机": "13800138000",
                                      "邮箱": "t@example.com", "学校": "示例大学",
                                      "专业": "软件工程", "学历阶段": "本科"}),
                          "{}", json.dumps({"意向城市": "北京"})))
            conn.execute("INSERT INTO jobs (fields, embedding) VALUES (?,?)",
                         (json.dumps({"岗位名称": "后端工程师", "单位名称": "示例科技"}),
                          json.dumps([1.0, 0.0])))

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

    def add_task(self, link, entry_type=None, entry_addr=None, status="待投递"):
        with db.get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO delivery_tasks (job_id, user_id, job_name, unit_name, job_link,"
                " entry_type, entry_addr, resume_path, status)"
                " VALUES (1, 1, '后端工程师', '示例科技', ?, ?, ?, ?, ?)",
                (link, entry_type, entry_addr, str(self.resume), status))
            return cur.lastrowid


class DeliverOneRoutingTests(_DbCase):
    def test_routes_to_platform_by_domain(self):
        tid = self.add_task("https://www.zhipin.com/job_detail/x.html")
        calls = {}

        def fake_deliver(pk, link):
            calls["deliver"] = (pk, link)
            return True, "已点击投递按钮"

        def fake_greet(pk, greeting):
            calls["greet"] = (pk, greeting)
            return True, "已发送"

        with patch.object(session, "ensure_page", return_value=(True, "ok")), \
                patch.object(session, "dpage_deliver", side_effect=fake_deliver), \
                patch.object(session, "dpage_greet", side_effect=fake_greet), \
                patch.object(delivery, "_resume_path", return_value=str(self.resume)):
            ok, msg = delivery.deliver_one(tid)
        self.assertTrue(ok, msg)
        self.assertEqual(calls["deliver"][0], "boss")
        self.assertEqual(calls["greet"][0], "boss")
        with db.get_conn() as conn:
            self.assertEqual(conn.execute(
                "SELECT status FROM delivery_tasks WHERE task_id=?", (tid,)).fetchone()[0], "已投递")

    def test_unknown_domain_is_rejected(self):
        tid = self.add_task("https://example.com/job/1")
        with patch.object(session, "ensure_page", return_value=(True, "ok")), \
                patch.object(delivery, "_resume_path", return_value=str(self.resume)):
            ok, msg = delivery.deliver_one(tid)
        self.assertFalse(ok)
        self.assertIn("不在已支持自动投递的平台内", msg)
        with db.get_conn() as conn:
            self.assertEqual(conn.execute(
                "SELECT status FROM delivery_tasks WHERE task_id=?", (tid,)).fetchone()[0], "待投递")

    def test_zhilian_auto_greeting_skips_custom_greet(self):
        tid = self.add_task("https://www.zhaopin.com/jobdetail/CC1.htm")
        greeted = []
        with patch.object(session, "ensure_page", return_value=(True, "ok")), \
                patch.object(session, "dpage_deliver",
                             return_value=(True, "已点击投递按钮（立即投递）；平台确认：已向对方发送简历")), \
                patch.object(session, "dpage_greet",
                             side_effect=lambda pk, g: greeted.append(pk) or (True, "ok")), \
                patch.object(delivery, "_resume_path", return_value=str(self.resume)):
            ok, msg = delivery.deliver_one(tid)
        self.assertTrue(ok, msg)
        self.assertIn("自动发送", msg)
        self.assertEqual(greeted, [])
        with db.get_conn() as conn:
            self.assertEqual(conn.execute(
                "SELECT status FROM delivery_tasks WHERE task_id=?", (tid,)).fetchone()[0], "已投递")

    def test_job51_success_without_greeting(self):
        tid = self.add_task("https://jobs.51job.com/x.html")
        greeted = []
        with patch.object(session, "ensure_page", return_value=(True, "ok")), \
                patch.object(session, "dpage_deliver", return_value=(True, "已点击投递按钮")), \
                patch.object(session, "dpage_greet",
                             side_effect=lambda pk, g: greeted.append(pk) or (True, "无站内招呼语")), \
                patch.object(delivery, "_resume_path", return_value=str(self.resume)):
            ok, msg = delivery.deliver_one(tid)
        self.assertTrue(ok, msg)
        self.assertIn("无站内招呼语", msg)
        self.assertEqual(greeted, [])   # deliver_one 不应再调用打招呼（平台已声明不支持）


class BatchChannelTests(_DbCase):
    def test_batch_summary_by_channel_and_continues_on_failure(self):
        self.add_task("https://www.zhipin.com/job_detail/1.html")          # 半自动
        self.add_task("https://example.com/apply", "API", "https://example.com/api/apply")  # API
        self.add_task("hr@example.com", "邮件", "mailto:hr@example.com")  # 邮件
        results = [(False, "未找到投递按钮"), (True, "API 已接受"), (True, "邮件已发送")]
        with patch.object(session, "ensure_page", return_value=(True, "ok")), \
                patch.object(delivery, "deliver_one", side_effect=results):
            batch = delivery.deliver_batch()
        self.assertEqual(batch["投递数"], 3)
        self.assertEqual(batch["成功数"], 2)
        self.assertEqual(batch["失败数"], 1)
        self.assertEqual(batch["按渠道"], {"半自动": 1, "API": 1, "邮件": 1})
        self.assertEqual(batch["停止原因"], "")  # 普通失败不会中断整批

    def test_uncertain_greeting_does_not_stop_batch(self):
        """「请人工核对」是待核实，不是风控；不能因此停掉整批。"""
        for i in range(3):
            self.add_task("https://www.zhipin.com/job_detail/%d.html" % i)
        results = [(False, "已点击沟通，但招呼语未确认发送：已尝试发送招呼语，请人工核对平台是否实际送达"),
                   (True, "ok"), (True, "ok")]
        with patch.object(session, "ensure_page", return_value=(True, "ok")), \
                patch.object(delivery, "deliver_one", side_effect=results):
            batch = delivery.deliver_batch()
        self.assertEqual(batch["投递数"], 3)
        self.assertEqual(batch["成功数"], 2)
        self.assertEqual(batch["失败数"], 1)
        self.assertEqual(batch["停止原因"], "")

    def test_batch_aborts_when_browser_cannot_open(self):
        self.add_task("https://www.zhipin.com/job_detail/1.html")
        with patch.object(session, "ensure_page", return_value=(False, "profile 被占用")), \
                patch.object(delivery, "deliver_one") as fake:
            batch = delivery.deliver_batch()
        self.assertEqual(batch["投递数"], 0)
        self.assertIn("无法打开浏览器", batch["停止原因"])
        fake.assert_not_called()

    def test_batch_stops_on_risk_signal(self):
        for i in range(3):
            self.add_task("https://www.zhipin.com/job_detail/%d.html" % i)
        results = [(True, "ok"), (False, "触发风控验证，请人工处理"), (True, "ok")]
        with patch.object(session, "ensure_page", return_value=(True, "ok")), \
                patch.object(delivery, "deliver_one", side_effect=results):
            batch = delivery.deliver_batch()
        self.assertEqual(batch["投递数"], 2)
        self.assertIn("风控", batch["停止原因"])


if __name__ == "__main__":
    unittest.main()


class BatchLimitTests(_DbCase):
    def _seed(self, n):
        for i in range(n):
            self.add_task("https://www.zhipin.com/job_detail/%d.html" % i)

    def test_default_still_caps_at_batch_limit(self):
        self._seed(7)
        with patch.object(session, "ensure_page", return_value=(True, "ok")), \
                patch.object(delivery, "deliver_one", return_value=(True, "ok")) as fake:
            batch = delivery.deliver_batch()
        self.assertEqual(batch["投递数"], config.BATCH_SEND_LIMIT)  # 5
        self.assertEqual(fake.call_count, 5)

    def test_all_pending_can_deliver_everything(self):
        self._seed(7)
        with patch.object(session, "ensure_page", return_value=(True, "ok")), \
                patch.object(delivery, "deliver_one", return_value=(True, "ok")) as fake:
            batch = delivery.deliver_batch(limit=7, interval=0, all_pending=True)
        self.assertEqual(batch["投递数"], 7)
        self.assertEqual(fake.call_count, 7)

    def test_explicit_limit_still_capped_by_default(self):
        self._seed(7)
        with patch.object(session, "ensure_page", return_value=(True, "ok")), \
                patch.object(delivery, "deliver_one", return_value=(True, "ok")):
            batch = delivery.deliver_batch(limit=7, interval=0)
        self.assertEqual(batch["投递数"], config.BATCH_SEND_LIMIT)

    def test_all_mode_uses_longer_interval(self):
        self._seed(3)
        with patch.object(session, "ensure_page", return_value=(True, "ok")), \
                patch.object(delivery, "deliver_one", return_value=(True, "ok")), \
                patch.object(delivery.time, "sleep") as sleeper:
            delivery.deliver_batch(limit=3, interval=20, all_pending=True)
        self.assertEqual([c.args[0] for c in sleeper.call_args_list], [20, 20])

    def test_daily_limit_still_applies_to_all_mode(self):
        self._seed(7)
        with patch.object(config, "DAILY_SEND_LIMIT", 6), \
                patch.object(session, "ensure_page", return_value=(True, "ok")), \
                patch.object(delivery, "deliver_one", return_value=(True, "ok")):
            batch = delivery.deliver_batch(limit=7, interval=0, all_pending=True)
        self.assertEqual(batch["投递数"], 6)
