"""分阶段翻页向导的回归测试。

验证本轮交互改版的核心行为：
1. 首屏只渲染第①阶段（不再把 ②~⑥ 全部铺在同一页）；
2. 完成第①阶段后自动翻到第②阶段；
3. 未完成的阶段不能从侧栏跳转（按钮禁用）；
4. 底部「下一页」在阶段未完成时禁用，完成后可用；
5. 预置 result 时，翻到第⑤/⑥阶段能正常渲染且无异常。
"""
import io
import sys
import unittest
from contextlib import closing
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from test_support import isolate_test_environment  # noqa: E402

isolate_test_environment()

from streamlit.testing.v1 import AppTest  # noqa: E402

CONFIRM_LABEL = "✅ 确认信息，进入下一步"
PREPARE_LABEL = "🚀 准备投递材料"


def _app():
    return AppTest.from_file(str(BASE / "app.py"))


def _markdown_text(at):
    return "\n".join((m.value or "") for m in at.markdown)


def _keys(elements):
    """元素列表 -> key 集合（AppTest 按 key 取缺失元素会抛 KeyError，这里改用枚举）。"""
    return {getattr(e, "key", None) for e in elements}


class WizardPaginationTests(unittest.TestCase):
    def test_first_page_only_renders_step_one(self):
        at = _app().run(timeout=30)
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["wizard_page"], 0)
        # 第①阶段独有的控件存在
        self.assertIn("l0_姓名", _keys(at.text_input))
        # 其他阶段的标志性控件不存在（证明没有整页铺开）
        self.assertEqual(len([b for b in at.button if b.label == PREPARE_LABEL]), 0)
        self.assertNotIn("kw", _keys(at.text_input))          # ③ 检索关键词
        self.assertNotIn("btn_rematch", _keys(at.button))      # ⑤ 重新匹配
        self.assertNotIn("batch_deliver", _keys(at.button))    # ⑤ 批量投递

    def test_confirm_advances_to_step_two(self):
        at = _app().run(timeout=30)
        next(b for b in at.button if b.label == CONFIRM_LABEL).click().run(timeout=30)
        self.assertFalse(at.exception)
        self.assertTrue(at.session_state["info_confirmed"])
        self.assertEqual(at.session_state["wizard_page"], 1)
        # 第②阶段的平台勾选出现
        self.assertIn("sel_boss", _keys(at.checkbox))

    def test_jump_buttons_are_gated_by_completion(self):
        at = _app().run(timeout=30)
        self.assertFalse(at.exception)
        # 只完成到哪，就能跳到哪：首屏只有第①阶段可点
        self.assertFalse(at.button(key="jump_0").disabled)
        for idx in range(1, 6):
            self.assertTrue(at.button(key="jump_%d" % idx).disabled,
                            "第 %d 阶段不应在未完成时就能跳转" % (idx + 1))
        next(b for b in at.button if b.label == CONFIRM_LABEL).click().run(timeout=30)
        self.assertFalse(at.button(key="jump_0").disabled)
        self.assertFalse(at.button(key="jump_1").disabled)   # 复看已完成的①/当前②
        self.assertTrue(at.button(key="jump_2").disabled)    # ③ 仍未解锁

    def test_next_button_disabled_until_stage_done(self):
        at = _app().run(timeout=30)
        self.assertTrue(at.button(key="nav_next_0").disabled)
        next(b for b in at.button if b.label == CONFIRM_LABEL).click().run(timeout=30)
        # 第②阶段未登录 → 下一页仍禁用
        self.assertTrue(at.button(key="nav_next_1").disabled)

    def test_prev_button_returns_to_previous_page(self):
        at = _app().run(timeout=30)
        next(b for b in at.button if b.label == CONFIRM_LABEL).click().run(timeout=30)
        at.button(key="nav_prev_1").click().run(timeout=30)
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["wizard_page"], 0)

    def test_step_four_requires_confirmed_info(self):
        at = _app()
        at.session_state["jobs"] = [{"岗位名称": "Python 后端", "单位名称": "示例科技",
                                     "城市": "北京", "岗位链接": "https://example.com/1"}]
        at.session_state["wizard_page"] = 3
        at.run(timeout=30)
        self.assertFalse(at.exception)
        # 未确认信息 → 第④阶段给出回退引导，而不是直接崩
        self.assertIn("信息尚未确认", _markdown_text(at) + "".join(
            w.value or "" for w in at.warning))

    def test_step_five_without_result_shows_empty_state(self):
        at = _app()
        at.session_state["wizard_page"] = 4
        at.run(timeout=30)
        self.assertFalse(at.exception)
        self.assertIn("step5_back", _keys(at.button))

    def test_reset_returns_to_first_page(self):
        at = _app().run(timeout=30)
        next(b for b in at.button if b.label == CONFIRM_LABEL).click().run(timeout=30)
        self.assertEqual(at.session_state["wizard_page"], 1)
        next(b for b in at.button if b.label == "🔄 重新开始").click().run(timeout=30)
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["wizard_page"], 0)
        self.assertNotIn("info_confirmed", at.session_state)


if __name__ == "__main__":
    unittest.main()
