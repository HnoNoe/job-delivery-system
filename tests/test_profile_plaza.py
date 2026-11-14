"""画像广场联动投影台：数据口径与联动契约回归测试。

不启动浏览器、不访问网络；空间构造与事件校验都是纯函数，
可直接用合成数据断言“三图共享有效集合、缺失不补零、PCA 一次计算、选中不串人”。
"""
import unittest

import pandas as pd

from test_support import isolate_test_environment

isolate_test_environment()

import profile_plaza as pp  # noqa: E402  (必须在隔离运行目录之后再导入)


def _df(rows):
    return pd.DataFrame(rows)


def _user(uid, name=None, gpa=0.8, rank=0.8, exps=3, skills=5, sends=2,
          interview=0.5, score=0.5):
    return {
        "user_id": uid, "姓名": name or ("用户%d" % uid), "学校": "示例大学",
        "专业": "软件工程", "GPA": gpa, "排名优秀度": rank, "经历段数": exps,
        "技能数": skills, "累计投递": sends, "进面试率": interview, "平均匹配分": score,
    }


class MetricSpaceTests(unittest.TestCase):
    def test_empty_table_returns_empty_space_with_valid_domains(self):
        df = _df([])
        space = pp.build_metric_space(df, ("GPA", "技能数", "经历段数"))
        self.assertEqual(space["total_count"], 0)
        self.assertEqual(space["visible_count"], 0)
        self.assertEqual(space["users"], [])
        self.assertEqual(len(space["axes"]), 3)
        for axis in space["axes"]:
            self.assertGreater(axis["domain"][1], axis["domain"][0])

    def test_single_user_is_visible_and_selectable(self):
        df = _df([_user(1, gpa=0.75, skills=4, exps=2)])
        space = pp.build_metric_space(df, ("GPA", "技能数", "经历段数"))
        self.assertEqual(space["visible_count"], 1)
        payload = pp.build_payload(space, "1", "linked3d")
        self.assertTrue(payload["selected_visible"])
        self.assertEqual(payload["dims"], 3)

    def test_shared_visible_set_excludes_missing_axes(self):
        df = _df([_user(1), _user(2, gpa=None), _user(3)])
        space = pp.build_metric_space(df, ("GPA", "技能数", "经历段数"))
        self.assertEqual(space["total_count"], 3)
        self.assertEqual(space["visible_count"], 2)
        self.assertEqual({u["user_id"] for u in space["users"]}, {"1", "3"})
        self.assertEqual([e["user_id"] for e in space["excluded"]], ["2"])
        self.assertIn("GPA", space["excluded"][0]["reason"])
        # 不补零：被排除用户的 GPA 原样保留 None
        self.assertIsNone(space["profiles"]["2"]["values"][0])

    def test_domains_nonzero_for_constant_axes_and_coords_normalized(self):
        df = _df([_user(1, gpa=0.8, skills=5, exps=3),
                  _user(2, gpa=0.8, skills=5, exps=3),
                  _user(3, gpa=0.8, skills=5, exps=3)])
        space = pp.build_metric_space(df, ("GPA", "技能数", "经历段数"))
        self.assertEqual(space["visible_count"], 3)
        for axis in space["axes"]:
            lo, hi = axis["domain"]
            self.assertGreater(hi, lo, "常量轴也必须给出非零显示范围")
            self.assertTrue(axis["constant"])
            self.assertTrue(axis["note"])
        for user in space["users"]:
            for value in user["coords"]:
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)

    def test_axis_metadata_and_units(self):
        df = _df([_user(1, gpa=0.5, skills=4, exps=2)])
        space = pp.build_metric_space(df, ("GPA", "技能数", "经历段数"))
        labels = [a["label"] for a in space["axes"]]
        self.assertEqual(labels, ["GPA（归一）", "技能数", "经历段数"])
        self.assertEqual(space["axes"][1]["unit"], "项")
        self.assertEqual(space["axes"][2]["unit"], "段")
        self.assertEqual(space["users"][0]["display"][1], "4 项")

    def test_out_of_range_ratio_values_are_not_clipped(self):
        # 上游异常值（GPA 归一 >1、排名优秀度 <0）应扩展显示范围，而不是裁到 [0,1]
        df = _df([_user(1, gpa=1.2, rank=-0.3, skills=4, exps=2),
                  _user(2, gpa=0.8, rank=0.9, skills=3, exps=1)])
        space = pp.build_metric_space(df, ("GPA", "排名优秀度", "技能数"))
        self.assertLessEqual(space["axes"][0]["domain"][1], 1.2 + 1e-9)
        self.assertGreaterEqual(space["axes"][0]["domain"][1], 1.2 - 1e-9)
        self.assertLessEqual(space["axes"][1]["domain"][0], -0.3 + 1e-9)
        for user in space["users"]:
            for value in user["coords"]:
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)

    def test_selected_user_missing_axis_keeps_selection_without_fake_highlight(self):
        df = _df([_user(1), _user(2, gpa=None), _user(3)])
        space = pp.build_metric_space(df, ("GPA", "技能数", "经历段数"))
        payload = pp.build_payload(space, 2, "linked3d")
        self.assertEqual(payload["selected_user_id"], "2")
        self.assertFalse(payload["selected_visible"])
        self.assertFalse(payload["selected_user"]["visible"])
        self.assertIn("无法在三张图中定位", payload["selection_note"])
        self.assertNotIn("高亮", payload["selection_note"])

    def test_deleted_selected_user_falls_back_explicitly(self):
        df = _df([_user(1), _user(3)])
        space = pp.build_metric_space(df, ("GPA", "技能数", "经历段数"))
        payload = pp.build_payload(space, 999, "linked3d")
        self.assertEqual(payload["selected_user_id"], "1")
        self.assertTrue(payload["selection_note"])
        self.assertIn("不在当前数据集", payload["selection_note"])

    def test_same_name_users_are_selected_by_stable_id(self):
        df = _df([_user(1, name="张三", gpa=0.9), _user(2, name="张三", gpa=0.5)])
        space = pp.build_metric_space(df, ("GPA", "技能数", "经历段数"))
        self.assertEqual({u["user_id"] for u in space["users"]}, {"1", "2"})
        payload = pp.build_payload(space, "2", "linked3d")
        self.assertEqual(payload["selected_user_id"], "2")
        self.assertEqual(payload["selected_user"]["user_id"], "2")
        space["revision"] = "rev-1"
        self.assertEqual(pp.parse_event(
            {"event": "select_user", "user_id": "1", "data_revision": "rev-1"}, space), "1")

    def test_event_revision_and_visible_id_validation(self):
        df = _df([_user(1), _user(2, gpa=None)])
        space = pp.build_metric_space(df, ("GPA", "技能数", "经历段数"))
        space["revision"] = "rev-1"
        ok = {"event": "select_user", "user_id": "1", "data_revision": "rev-1"}
        self.assertEqual(pp.parse_event(ok, space), "1")
        stale = {"event": "select_user", "user_id": "1", "data_revision": "rev-0"}
        self.assertIsNone(pp.parse_event(stale, space))
        invisible = {"event": "select_user", "user_id": "2", "data_revision": "rev-1"}
        self.assertIsNone(pp.parse_event(invisible, space))


class SemanticSpaceTests(unittest.TestCase):
    def _profiles(self, n=5):
        return {str(i): {"user_id": str(i), "name": "用户%d" % i,
                         "school": "", "major": ""} for i in range(1, n + 1)}

    def test_pca_computes_once_and_returns_three_shared_axes(self):
        vectors = {
            "1": [1.0, 0.0, 0.0], "2": [0.0, 1.0, 0.0], "3": [0.0, 0.0, 1.0],
            "4": [1.0, 1.0, 0.0], "5": [0.0, 1.0, 1.0],
        }
        space = pp.compute_pca_space(self._profiles(), vectors)
        self.assertNotIn("error", space)
        self.assertEqual(space["dims"], 3)
        self.assertEqual([a["id"] for a in space["axes"]], ["PC1", "PC2", "PC3"])
        self.assertEqual(space["visible_count"], 5)
        for user in space["users"]:
            self.assertEqual(len(user["coords"]), 3)
        self.assertTrue(any("解释方差" in note for note in space["notes"]))
        payload = pp.build_payload(space, "1", "linked3d")
        self.assertEqual(payload["dims"], 3)
        self.assertEqual(payload["view_mode"], "linked3d")

    def test_rank_two_degrades_to_two_dimensions_without_fake_pc3(self):
        vectors = {
            "1": [1.0, 0.0, 0.0], "2": [0.0, 1.0, 0.0],
            "3": [1.0, 1.0, 0.0], "4": [2.0, 1.0, 0.0],
        }
        space = pp.compute_pca_space(self._profiles(4), vectors)
        self.assertNotIn("error", space)
        self.assertEqual(space["dims"], 2)
        self.assertEqual([a["id"] for a in space["axes"]], ["PC1", "PC2"])
        self.assertTrue(any("PC3 不可用" in note for note in space["notes"]))
        payload = pp.build_payload(space, "1", "linked3d")
        self.assertEqual(payload["view_mode"], "flat2d")

    def test_rank_zero_and_small_samples_are_explicit_errors(self):
        same = {"1": [1.0, 1.0, 1.0], "2": [1.0, 1.0, 1.0]}
        space = pp.compute_pca_space(self._profiles(2), same)
        self.assertIn("有效秩", space["error"])
        one = pp.compute_pca_space(self._profiles(1), {"1": [1.0, 0.0]})
        self.assertIn("至少需要 2", one["error"])

    def test_dimension_mismatch_and_nonfinite_vectors_are_excluded(self):
        vectors = {
            "1": [1.0, 0.0, 0.0], "2": [0.0, 1.0, 0.0], "3": [1.0, 1.0, 0.0],
            "4": [0.0, 0.0, 1.0, 9.0],       # 维度不一致
            "5": [0.0, float("nan"), 1.0],   # 非有限
        }
        space = pp.compute_pca_space(self._profiles(5), vectors)
        self.assertNotIn("error", space)
        excluded = {e["user_id"]: e["reason"] for e in space["excluded"]}
        self.assertIn("维度不一致", excluded["4"])
        self.assertIn("无效数值", excluded["5"])
        self.assertEqual(space["visible_count"], 3)

    def test_semantic_space_reports_users_without_snapshot(self):
        df = _df([_user(1), _user(2), _user(3), _user(4)])
        vectors = {"1": [1.0, 0.0, 0.0], "2": [0.0, 1.0, 0.0], "3": [1.0, 1.0, 0.0]}
        space = pp.build_semantic_space(df, latest_vectors=vectors)
        self.assertNotIn("error", space)
        excluded = {e["user_id"]: e["reason"] for e in space["excluded"]}
        self.assertIn("画像快照", excluded["4"])
        self.assertEqual(space["total_count"], 4)
        self.assertEqual(space["visible_count"], 3)

    def test_payload_selected_semantic_user_not_visible_keeps_detail(self):
        df = _df([_user(1), _user(2), _user(3)])
        vectors = {"1": [1.0, 0.0, 0.0], "2": [0.0, 1.0, 0.0], "3": [0.0, 0.0, 1.0]}
        space = pp.build_semantic_space(df, latest_vectors=vectors)
        self.assertNotIn("error", space)
        payload = pp.build_payload(space, "2", "linked3d")
        self.assertTrue(payload["selected_visible"])
        self.assertEqual(payload["selected_user_id"], "2")


class PageSmokeTests(unittest.TestCase):
    def test_empty_plaza_page_renders_empty_state(self):
        """空库打开画像广场：应走空态提示，而不是抛异常。"""
        import db

        db.init_db()
        from pathlib import Path
        from streamlit.testing.v1 import AppTest

        page = Path(__file__).resolve().parents[1] / "pages" / "01_画像广场.py"
        app = AppTest.from_file(str(page), default_timeout=30).run()
        self.assertFalse(app.exception)
        texts = " ".join(x.value for x in app.caption) + " ".join(x.value for x in app.markdown)
        self.assertIn("还没有用户数据", texts)


if __name__ == "__main__":
    unittest.main()
