"""方案 B（检查 HR 回复）与 HR 回应登记的单元测试。

不联网、不开浏览器：只测纯解析/匹配/分类/落库逻辑。
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
import replies
import responses
import session

BASE_APP = Path(__file__).resolve().parents[1] / "app.py"


def task(tid, job, unit):
    return {"task_id": tid, "job_name": job, "unit_name": unit}


TASKS = [
    task(1, "Python后端开发工程师", "示例科技"),
    task(2, "Java后端开发工程师", "云创网络"),
    task(3, "算法工程师", "未来智能"),
]

APP_USER = {
    "l0": {"姓名": "测试用户", "性别": "男", "出生日期": "2001-01-01", "手机": "13800138000",
           "邮箱": "t@example.com", "政治面貌": "群众", "民族": "汉", "现居": "北京",
           "籍贯": "北京", "学历阶段": "本科", "学校": "示例大学", "学院": "计院",
           "专业": "软件工程", "入学年月": "2020-09", "毕业年月": "2024-06"},
    "l1": {"项目": 1},
    "l2": [{"类型": "项目", "名称": "Python-web", "技术工具": "Python Flask",
            "事项": "开发接口", "时间起": "2023-01", "时间止": "2023-06"}],
    "l3": {"意向城市": "北京", "意向行业": "互联网", "意向岗位": "后端开发",
           "投递策略": "海投", "到岗时间": "2024-07", "能否出差": "是"},
}
APP_JOB = {"岗位名称": "Python后端开发", "单位名称": "示例科技",
           "岗位链接": "https://example.com/1", "城市": "北京", "行业": "互联网",
           "岗位描述": "Python Flask", "技能": ["Python"], "学历": "本科",
           "投递入口类型": "API", "投递入口地址": "http://127.0.0.1:1/apply"}


class ClassifyTests(unittest.TestCase):
    def test_interview(self):
        for text in ("方便周四下午视频面试吗", "简历通过了，约面聊聊", "安排面试时间"):
            self.assertEqual(replies.classify(text), "邀面试", text)

    def test_online_chat_invite(self):
        for text in ("你好啊，可以聊一聊~", "加个微信沟通一下", "方便吗？我们电话聊"):
            self.assertEqual(replies.classify(text), "线上交流邀请", text)

    def test_reject(self):
        for text in ("抱歉，该岗位已招满", "不太合适", "已停止招聘"):
            self.assertEqual(replies.classify(text), "不合适", text)

    def test_seen_and_other(self):
        self.assertEqual(replies.classify("HR 已查看你的简历"), "已查看")
        self.assertEqual(replies.classify("你好"), "其他")
        self.assertEqual(replies.classify(""), "其他")

    def test_self_message(self):
        self.assertTrue(replies.is_self_message("你已发送招呼语"))
        self.assertTrue(replies.is_self_message("您好，我是张三…简历已发，期待回复"))
        self.assertFalse(replies.is_self_message("你好，方便面试吗"))


class ExtractTests(unittest.TestCase):
    def test_generic_extract_from_nested_payload(self):
        payload = {"zpData": {"sessions": [{
            "brandName": "示例科技", "jobName": "Python后端开发工程师",
            "bossName": "王HR", "lastMessage": "方便周四面试吗", "lastTime": "2026-11-17 10:00",
        }]}}
        records = replies.extract_conversations([payload])
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["单位名称"], "示例科技")
        self.assertEqual(rec["岗位名称"], "Python后端开发工程师")
        self.assertEqual(rec["HR"], "王HR")
        self.assertEqual(rec["最后消息"], "方便周四面试吗")

    def test_extract_ignores_non_conversation_dicts(self):
        payload = [{"code": 0, "message": "success"}, {"jobName": "x", "lastMessage": "y"}]
        records = replies.extract_conversations(payload)
        self.assertEqual([r["岗位名称"] for r in records], ["x"])

    def test_records_from_api_uses_field_map(self):
        payload = {"zpData": {"sessions": [
            {"brandName": "云创网络", "jobName": "Java后端开发工程师",
             "lastMessage": "已招满", "lastTime": "t", "unread": 1},
            {"brandName": "", "jobName": "", "lastMessage": "缺少会话主体"},
        ]}}
        fm = {"单位名称": "brandName", "岗位名称": "jobName",
              "最后消息": "lastMessage", "时间": "lastTime", "未读": "unread"}
        records = replies.records_from_api(payload, fm, "zpData.sessions")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["单位名称"], "云创网络")

    def test_dom_fallback_extracts_identity(self):
        records = replies.records_from_dom(["示例科技 Python后端开发工程师 方便面试吗"], TASKS)
        self.assertEqual(records[0]["单位名称"], "示例科技")
        self.assertEqual(records[0]["岗位名称"], "Python后端开发工程师")


class MatchTests(unittest.TestCase):
    def test_match_by_company_and_job(self):
        records = [
            {"单位名称": "示例科技", "岗位名称": "Python后端开发工程师", "最后消息": "约面试", "时间": "", "未读": ""},
            {"单位名称": "云创网络", "岗位名称": "Java后端开发工程师", "最后消息": "已招满", "时间": "", "未读": ""},
        ]
        cands = replies.match_tasks(records, TASKS)
        self.assertEqual([c["task_id"] for c in cands], [1, 2])
        self.assertEqual([c["建议类型"] for c in cands], ["邀面试", "不合适"])

    def test_unrelated_record_is_dropped(self):
        records = [{"单位名称": "完全无关的公司", "岗位名称": "厨师", "最后消息": "约吗", "时间": "", "未读": ""}]
        self.assertEqual(replies.match_tasks(records, TASKS), [])

    def test_self_message_not_a_candidate(self):
        records = [{"单位名称": "示例科技", "岗位名称": "Python后端开发工程师",
                    "最后消息": "你已发送招呼语", "时间": "", "未读": ""}]
        self.assertEqual(replies.match_tasks(records, TASKS), [])


class _DbCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jobdelivery-replies-")
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
            conn.execute("INSERT INTO delivery_tasks (job_id, user_id, job_name, unit_name, status)"
                         " VALUES (1, 1, 'Python后端开发工程师', '示例科技', '已投递')")
            conn.execute("INSERT INTO delivery_tasks (job_id, user_id, job_name, unit_name, status)"
                         " VALUES (2, 1, 'Java后端开发工程师', '云创网络', '已投递')")

    def tearDown(self):
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


class ResponseTests(_DbCase):
    def test_add_and_dedupe(self):
        ok, _, rid = responses.add_response(1, "邀面试", "周四 15:00", source="auto", platform="mock")
        self.assertTrue(ok)
        dup_ok, msg, dup_id = responses.add_response(1, "邀面试", "周四 15:00", source="auto")
        self.assertFalse(dup_ok)
        self.assertEqual(dup_id, rid)

    def test_register_from_candidates(self):
        cands = [
            {"task_id": 1, "建议类型": "邀面试", "最后消息": "约面试"},
            {"task_id": 2, "建议类型": "不合适", "最后消息": "已招满"},
        ]
        added, dup, details = replies.register(cands, platform_key="mock")
        self.assertEqual((added, dup), (2, 0))
        self.assertEqual(responses.summary(1)["分类"]["邀面试"], 1)
        self.assertEqual(responses.summary(1)["分类"]["不合适"], 1)
        added2, dup2, _ = replies.register(cands, platform_key="mock")
        self.assertEqual((added2, dup2), (0, 2))

    def test_invalid_task(self):
        ok, msg, _ = responses.add_response(999, "邀面试", "")
        self.assertFalse(ok)
        self.assertEqual(msg, "任务不存在")


class CheckTests(_DbCase):
    def test_check_with_structured_dom(self):
        """Boss 结构化 DOM（dict）应优先于接口旁听结果。"""
        dom = [{"单位名称": "示例科技", "岗位名称": "", "HR": "祝女士·HR",
                "最后消息": "方便周四面试吗", "时间": "11月12日", "未读": ""},
               {"单位名称": "示例科技", "岗位名称": "", "HR": "HR",
                "最后消息": "你已发送招呼语", "时间": "11月11日", "未读": ""}]
        with patch.object(session, "chat_capture", return_value=(True, [], dom, ["DOM 会话条目: 2"])):
            res = replies.check("boss", TASKS, timeout=1)
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["records"]), 2)
        self.assertEqual([c["task_id"] for c in res["candidates"]], [1])
        self.assertEqual(res["candidates"][0]["建议类型"], "邀面试")
        # 我方招呼语不算候选，也不进“未匹配”
        self.assertEqual(res["unmatched"], [])

    def test_check_reports_unmatched(self):
        dom = [{"单位名称": "完全无关的公司", "岗位名称": "", "HR": "HR",
                "最后消息": "你好呀", "时间": "", "未读": ""}]
        with patch.object(session, "chat_capture", return_value=(True, [], dom, [])):
            res = replies.check("boss", TASKS, timeout=1)
        self.assertEqual(res["candidates"], [])
        self.assertEqual(len(res["unmatched"]), 1)
        self.assertEqual(res["unmatched"][0]["单位"], "完全无关的公司")

    def test_check_without_api_or_browser_reports_error(self):
        # 未配置 chat_api_url 且浏览器不可用时，不应伪造结果，只返回错误
        with patch.object(session, "chat_capture",
                          return_value=(False, [], [], ["浏览器启动失败: 测试桩"])):
            res = replies.check("boss", [{"task_id": 1, "job_name": "x", "unit_name": "y"}], timeout=1)
        self.assertFalse(res["ok"])
        self.assertIn("浏览器启动失败", res["error"])
        self.assertEqual(res["candidates"], [])

    def test_check_unknown_platform(self):
        res = replies.check("nope", [])
        self.assertFalse(res["ok"])
        self.assertIn("未知平台", res["error"])


class UiTests(_DbCase):
    USER = {
        "l0": {"姓名": "测试用户", "性别": "男", "出生日期": "2001-01-01", "手机": "13800138000",
               "邮箱": "t@example.com", "政治面貌": "群众", "民族": "汉", "现居": "北京",
               "籍贯": "北京", "学历阶段": "本科", "学校": "示例大学", "学院": "计院",
               "专业": "软件工程", "入学年月": "2020-09", "毕业年月": "2024-06"},
        "l1": {"项目": 1},
        "l2": [{"类型": "项目", "名称": "Python-web", "技术工具": "Python Flask",
                "事项": "开发接口", "时间起": "2023-01", "时间止": "2023-06"}],
        "l3": {"意向城市": "北京", "意向行业": "互联网", "意向岗位": "后端开发",
               "投递策略": "海投", "到岗时间": "2024-07", "能否出差": "是"},
    }
    JOB = {"岗位名称": "Python后端开发", "单位名称": "示例科技",
           "岗位链接": "https://example.com/1", "城市": "北京", "行业": "互联网",
           "岗位描述": "Python Flask", "技能": ["Python"], "学历": "本科",
           "投递入口类型": "API", "投递入口地址": "http://127.0.0.1:1/apply"}

    def test_step_six_reply_check_click_does_not_raise(self):
        """点击「检查新回复」不能因 widget key 冲突抛异常（历史 bug：
        st.session_state['reply_check'] 与按钮 key 同名，实例化后不可写）。"""
        import pipeline
        from streamlit.testing.v1 import AppTest
        session.save_cookies("mock", [{"name": "mock_login", "value": "1"}])
        pipeline.run_full_pipeline(self.USER, jobs=[self.JOB])
        canned = {"ok": True, "error": "", "records": [], "candidates": [],
                  "unmatched": [], "debug": ["stub"], "probe": None}
        at = AppTest.from_file(str(BASE_APP))
        at.session_state["wizard_page"] = 5
        at.run(timeout=60)
        self.assertFalse(at.exception)
        with patch("replies.check", return_value=canned):
            at.button(key="reply_check").click().run(timeout=60)
        self.assertFalse(at.exception)
        self.assertIn("reply_check_result", at.session_state)
        self.assertEqual(at.session_state["reply_check_result"]["debug"], ["stub"])

    def test_step_six_renders_reply_check_and_manual_register(self):
        import pipeline
        from streamlit.testing.v1 import AppTest
        session.save_cookies("mock", [{"name": "mock_login", "value": "1"}])
        result = pipeline.run_full_pipeline(self.USER, jobs=[self.JOB])
        self.assertTrue(result["ok"])
        at = AppTest.from_file(str(BASE_APP))
        at.session_state["wizard_page"] = 5
        at.run(timeout=60)
        self.assertFalse(at.exception)
        keys = {getattr(e, "key", None) for e in at.button}
        self.assertIn("reply_check", keys)
        self.assertIn("resp_add", keys)
        self.assertEqual(at.session_state["result"]["user_id"], result["user_id"])

        at.selectbox(key="resp_kind").select("邀面试").run(timeout=60)
        at.button(key="resp_add").click().run(timeout=60)
        self.assertFalse(at.exception)
        self.assertEqual(responses.summary(result["user_id"])["分类"]["邀面试"], 1)


class AutoCheckTests(_DbCase):
    def _ok(self, candidates=None):
        return {"ok": True, "error": "", "records": [], "unmatched": [],
                "candidates": candidates or [], "debug": []}

    def test_cooldown_blocks_second_run(self):
        with patch("replies.check", return_value=self._ok()):
            first = replies.auto_check("mock", TASKS, cooldown_minutes=60)
            second = replies.auto_check("mock", TASKS, cooldown_minutes=60)
        self.assertTrue(first["ran"])
        self.assertFalse(second["ran"])
        self.assertIn("冷却", second["reason"])
        self.assertIsNotNone(replies.last_auto_check())

    def test_auto_registers_actionable_kinds_only(self):
        cands = [
            {"task_id": 1, "岗位": "Python后端开发工程师", "单位": "示例科技",
             "最后消息": "方便周四面试吗", "建议类型": "邀面试", "匹配度": 1.0},
            {"task_id": 2, "岗位": "Java后端开发工程师", "单位": "云创网络",
             "最后消息": "你好", "建议类型": "其他", "匹配度": 1.0},
        ]
        with patch("replies.check", return_value=self._ok(cands)):
            out = replies.auto_check("mock", TASKS, cooldown_minutes=0)
        self.assertTrue(out["ran"])
        self.assertEqual(out["added"], 1)
        rows = responses.list_responses(1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "邀面试")
        self.assertEqual(rows[0]["source"], "auto")

    def test_toggle_persists(self):
        self.assertTrue(replies.auto_enabled())  # 默认跟随 config
        replies.set_auto_enabled(False)
        self.assertFalse(replies.auto_enabled())
        replies.set_auto_enabled(True)
        self.assertTrue(replies.auto_enabled())

    def test_classify_new_kinds(self):
        self.assertEqual(replies.classify("可以聊一聊吗"), "线上交流邀请")
        self.assertEqual(replies.classify("方便发一份作品集吗"), "需补充资料")
        self.assertEqual(replies.classify("我们内部评估中，晚点回复"), "待定")

    def test_sidebar_renders_auto_state_with_platforms(self):
        """自动检查状态里带 platforms 列表时，侧栏渲染不能崩（历史上 platforms.get 传了两个参数）。"""
        import json
        import time
        import pipeline
        from streamlit.testing.v1 import AppTest
        session.save_cookies("mock", [{"name": "mock_login", "value": "1"}])
        pipeline.run_full_pipeline(APP_USER, jobs=[APP_JOB])
        info = {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "platforms": [
                {"platform": "boss", "ok": True, "error": "", "records": 2,
                 "candidates": 0, "added": 0, "inbox_added": 1, "unmatched": 2},
                {"platform": "unknown_pk", "ok": False, "error": "未配置", "records": 0,
                 "candidates": 0, "added": 0, "inbox_added": 0, "unmatched": 0},
            ],
            "added": 0, "records": 2, "candidates": 0, "unmatched": 2, "inbox_added": 1, "error": "",
        }
        replies._state_set("auto_reply_last", json.dumps(info, ensure_ascii=False))
        at = AppTest.from_file(str(BASE_APP)).run(timeout=60)
        self.assertFalse(at.exception)

    def test_inbox_keeps_unmatched_and_classifies(self):
        records = [
            {"单位名称": "完全无关的公司", "岗位名称": "", "HR": "王HR",
             "最后消息": "方便周四面试吗", "时间": "11月12日", "未读": ""},
            {"单位名称": "示例科技", "岗位名称": "", "HR": "李HR",
             "最后消息": "你好，简历已收到", "时间": "11月11日", "未读": ""},
        ]
        added = replies.store_inbox(records, TASKS, "mock")
        self.assertEqual(added, 2)
        rows = replies.list_inbox()
        self.assertEqual(len(rows), 2)
        by_company = {r["company"]: r for r in rows}
        self.assertEqual(by_company["完全无关的公司"]["kind"], "邀面试")
        self.assertIsNone(by_company["完全无关的公司"]["task_id"])   # 未匹配任务也保留
        self.assertEqual(by_company["示例科技"]["task_id"], 1)        # 匹配到任务
        # 同一消息重复写入幂等
        self.assertEqual(replies.store_inbox(records, TASKS, "mock"), 0)
        self.assertEqual(len(replies.list_inbox()), 2)


if __name__ == "__main__":
    unittest.main()
