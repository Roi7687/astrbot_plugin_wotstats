# -*- coding: utf-8 -*-
"""AI 点评（跨插件调用）单元测试：只覆盖编排逻辑，不发网络、不起浏览器。

真实 DeepSeek 调用由 research/verify_ai_review.py 负责（端到端）。
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ai_review import (AI_DATA_PLACEHOLDER, AI_REVIEW_PROMPT,  # noqa: E402
                            ask_ai_review, build_ai_prompt)
from core.config import AI_REVIEW_MAX_CHARS, AI_REVIEW_PLUGIN  # noqa: E402
from core.formatter import ai_panel_text  # noqa: E402

STATS = "🎖 **loy1234** ｜ 近 7 天：WN8 **3,078**（164 场）\n- 常用坦克：UDES 15/16 38 场"


def _run(coro):
    return asyncio.run(coro)


class FakeStar:
    """模拟 astrbot_plugin_aisearch 的实例（只需要 _send_query）。"""

    def __init__(self, *, answer="AI 点评内容", created=False, exc=None, delay=0.0):
        self.answer, self.created, self.exc, self.delay = answer, created, exc, delay
        self.seen = None

    async def _send_query(self, prompt, images):
        self.seen = (prompt, images)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.created, self.answer


class FakeMeta:
    def __init__(self, inst, activated=True):
        self.star_cls, self.activated, self.name = inst, activated, AI_REVIEW_PLUGIN


class FakeContext:
    def __init__(self, meta=None, exc=None):
        self.meta, self.exc = meta, exc

    def get_registered_star(self, name):
        if self.exc:
            raise self.exc
        return self.meta if name == AI_REVIEW_PLUGIN else None


class TestPrompt(unittest.TestCase):
    """提示词 = 用户定稿版：角色 / 5 条读表逻辑 / 黑话替换表 / 正反例 / 写作铁律与格式。"""

    def test_data_placeholder_is_filled(self):
        """提示词末尾的 {{在此处填入玩家数据}} 由 build_ai_prompt 填入本局数据。"""
        self.assertIn(AI_DATA_PLACEHOLDER, AI_REVIEW_PROMPT)
        merged = build_ai_prompt(STATS)
        self.assertNotIn(AI_DATA_PLACEHOLDER, merged)
        self.assertTrue(merged.rstrip().endswith(STATS.strip()))
        self.assertIn("待分析玩家数据", merged)

    def test_role_is_wot_veteran_coach(self):
        self.assertIn("国服资深指挥与老鸟教练", AI_REVIEW_PROMPT)
        self.assertIn("严禁脱离面板瞎猜微操", AI_REVIEW_PROMPT)

    def test_five_read_table_rules(self):
        """5 条交叉比对逻辑（段位 / 高场均低胜率 / 小样本 / 单车低于均值 / 轻坦）。"""
        for key in ("【看段位定基调】", "【高场均 + 低胜率（场次≥25场）】",
                    "【高场均 + 极低胜率（场次<25场）】",
                    "【单车场均明显低于本人同级均值】",
                    "【轻坦高WN8/高直伤 + 胜率低于个人均值】"):
            self.assertIn(key, AI_REVIEW_PROMPT)
        self.assertIn("发牌员短期制裁", AI_REVIEW_PROMPT)      # 小样本定性
        self.assertIn("车体特性水土不服", AI_REVIEW_PROMPT)    # 单车低于均值定性

    def test_slang_replacement_table(self):
        """黑话替换表：7 条，且必须同时给出禁用词与替代表达。"""
        self.assertEqual(AI_REVIEW_PROMPT.count("➔ ✅"), 7)
        for term in ("紫表大佬", "刷晚期伤害", "发牌员搞心态", "缩在二线黑枪",
                     "开局暴毙", "眼车当TD玩", "强侧抗压"):
            self.assertIn(term, AI_REVIEW_PROMPT)

    def test_few_shot_examples_present(self):
        """3 组正反例（严格模仿正例的推理与语气）。"""
        self.assertEqual(AI_REVIEW_PROMPT.count("❌ 错误示范"), 3)
        self.assertEqual(AI_REVIEW_PROMPT.count("✅ 正确示范"), 3)
        for key in ("晚期伤害", "发牌员", "横向对比"):
            self.assertIn(key, AI_REVIEW_PROMPT)

    def test_writing_rules_and_format(self):
        """禁流水账但用概数打反差；禁脑补微观动作；7 条 500 字内、每车 60 字以内。"""
        self.assertIn("禁报流水账，但要用概数打反差", AI_REVIEW_PROMPT)
        self.assertIn("严禁脑补微观动作与局内改配", AI_REVIEW_PROMPT)
        self.assertIn("严格输出 7 条，总字数 500 字以内", AI_REVIEW_PROMPT)
        self.assertIn("每辆 60 字以内", AI_REVIEW_PROMPT)
        for key in ("① 【定段位与底色】", "② 【核心痛点】", "③~⑦ 【单车复盘】"):
            self.assertIn(key, AI_REVIEW_PROMPT)

    def test_empty_stats(self):
        merged = build_ai_prompt("")
        self.assertNotIn(AI_DATA_PLACEHOLDER, merged)


class TestAiPanel(unittest.TestCase):
    """补充面板：玩家可见文本里没有、但读表需要的字段（命中/点亮/防守/单车 K/D）。"""

    @staticmethod
    def _camp(with_tanks=True):
        from core.camp_model import CampPeriod, CampPlayer, CampTank
        tanks = [
            CampTank(tank_id="37649", name="UDES 15/16", tier=10, fights=38, wn8=3202.8,
                     win_rate=52.6, avgdmg=3704.0, avgdmgasst=1006.0, kd=1.31, hit_rate=74.2),
            CampTank(tank_id="2977", name='"犀牛"', tier=10, fights=4, wn8=3670.6,
                     win_rate=25.0, avgdmg=3831.25, kd=1.0, hit_rate=70.0),
        ] if with_tanks else []
        return CampPlayer(
            nickname="loy1234",
            periods={"day_7": CampPeriod(key="day_7", fights=164, wn8=3077.6, win_rate=61.6,
                                         kd=1.88, avgdmg=3201.96, avgfrag=1.5, avgspot=1.8,
                                         hit_rate=76.0),
                     "day_30": CampPeriod(key="day_30", fights=297, wn8=2903.45, win_rate=58.25,
                                          kd=1.77, avgdmg=3209.14, avgfrag=1.34, avgspot=1.64,
                                          avgdef=0.71, avgexp=1100.47, hit_rate=76.82,
                                          avglevel=10.09, rank=1941, population=187731)},
            tanks_30d=tanks,
        )

    def test_panel_has_average_and_per_tank_detail(self):
        panel = ai_panel_text(self._camp())
        self.assertIn("【补充面板", panel)
        self.assertIn("近 30 天场均", panel)
        for key in ("伤害", "击毁", "点亮", "防守", "命中率", "出战等级"):
            self.assertIn(key, panel)
        self.assertIn("K/D", panel)
        self.assertIn("UDES 15/16", panel)          # >10 场的车
        self.assertNotIn("犀牛", panel)              # 4 场 < 门槛 → 不进面板

    def test_panel_empty_without_camp(self):
        from core.camp_model import CampPlayer
        self.assertEqual(ai_panel_text(None), "")
        self.assertEqual(ai_panel_text(CampPlayer(nickname="x")), "")
        # 只有时段数据时，面板仍有近 30 天场均（含命中/点亮/防守），只是没有单车明细
        panel = ai_panel_text(self._camp(with_tanks=False))
        self.assertIn("近 30 天场均", panel)
        self.assertNotIn("单车", panel)

    def test_panel_marks_itself_ai_only(self):
        self.assertIn("仅你可见", ai_panel_text(self._camp()))


class TestAskAiReview(unittest.TestCase):
    def test_success_and_append_ready(self):
        inst = FakeStar(answer="  \r\n打得不错。\r\n\r\n\r\n继续加油。  ")
        text = _run(ask_ai_review(FakeContext(FakeMeta(inst)), STATS))
        self.assertEqual(text, "打得不错。\n\n继续加油。")          # 归一化 + 去多余空行
        prompt, images = inst.seen
        self.assertIn(STATS, prompt)                                # 战绩确实传过去了
        self.assertEqual(images, [])                                # 不带图片

    def test_star_receives_merged_prompt(self):
        inst = FakeStar()
        _run(ask_ai_review(FakeContext(FakeMeta(inst)), STATS))
        prompt, _ = inst.seen
        self.assertLess(prompt.index("老鸟教练"), prompt.index("loy1234"))   # 提示词在前、数据在后

    def test_length_is_capped(self):
        inst = FakeStar(answer="很" * (AI_REVIEW_MAX_CHARS + 500))
        text = _run(ask_ai_review(FakeContext(FakeMeta(inst)), STATS))
        self.assertEqual(len(text), AI_REVIEW_MAX_CHARS + 1)        # 截断后带省略号

    def test_created_conversation_flag_is_fine(self):
        inst = FakeStar(answer="新会话里的点评", created=True)
        self.assertEqual(_run(ask_ai_review(FakeContext(FakeMeta(inst)), STATS)),
                         "新会话里的点评")

    def test_resets_peer_idle_timer(self):
        """调完对方会话后要替它重置空闲计时器（否则无头浏览器可能常驻）。"""
        class Conv:
            local_id = 7

        class Session:
            current_conversation = Conv()

        class Inst(FakeStar):
            def __init__(self):
                super().__init__()
                self.session = Session()
                self.armed = []

            def _arm_idle_timer(self, local_id):
                self.armed.append(local_id)

        inst = Inst()
        _run(ask_ai_review(FakeContext(FakeMeta(inst)), STATS))
        self.assertEqual(inst.armed, [7])

    def test_idle_timer_absence_is_ignored(self):
        inst = FakeStar()          # 没有 session/_arm_idle_timer → 不应报错
        self.assertEqual(_run(ask_ai_review(FakeContext(FakeMeta(inst)), STATS)), "AI 点评内容")

    # ── 降级：任何异常都不能抛给调用方 ──

    def test_empty_stats_skips(self):
        inst = FakeStar()
        self.assertEqual(_run(ask_ai_review(FakeContext(FakeMeta(inst)), "   ")), "")

    def test_no_context(self):
        self.assertEqual(_run(ask_ai_review(None, STATS)), "")

    def test_plugin_not_installed(self):
        self.assertEqual(_run(ask_ai_review(FakeContext(None), STATS)), "")

    def test_plugin_inactive(self):
        inst = FakeStar()
        self.assertEqual(
            _run(ask_ai_review(FakeContext(FakeMeta(inst, activated=False)), STATS)), "")

    def test_star_cls_none(self):
        self.assertEqual(_run(ask_ai_review(FakeContext(FakeMeta(None)), STATS)), "")

    def test_instance_without_send_query(self):
        class Bad:
            pass
        self.assertEqual(_run(ask_ai_review(FakeContext(FakeMeta(Bad())), STATS)), "")

    def test_registry_raises(self):
        self.assertEqual(_run(ask_ai_review(FakeContext(exc=RuntimeError("boom")), STATS)), "")

    def test_对方抛异常时静默降级(self):
        inst = FakeStar(exc=RuntimeError("AuthError: 未登录"))
        self.assertEqual(_run(ask_ai_review(FakeContext(FakeMeta(inst)), STATS)), "")

    def test_timeout_returns_empty(self):
        inst = FakeStar(answer="来不及了", delay=0.3)
        self.assertEqual(
            _run(ask_ai_review(FakeContext(FakeMeta(inst)), STATS, timeout=0.05)), "")

    def test_empty_answer(self):
        for answer in ("", "   ", None):
            inst = FakeStar(answer=answer)
            self.assertEqual(_run(ask_ai_review(FakeContext(FakeMeta(inst)), STATS)), "")


if __name__ == "__main__":
    unittest.main()
