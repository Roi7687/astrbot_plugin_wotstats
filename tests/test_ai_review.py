# -*- coding: utf-8 -*-
"""AI 点评（跨插件调用）单元测试：只覆盖编排逻辑，不发网络、不起浏览器。

真实 DeepSeek 调用由 research/verify_ai_review.py 负责（端到端）。
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ai_review import (AI_REVIEW_PROMPT, ask_ai_review,  # noqa: E402
                            build_ai_prompt)
from core.config import AI_REVIEW_MAX_CHARS, AI_REVIEW_PLUGIN  # noqa: E402

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
    def test_requirements_come_before_stats(self):
        prompt = build_ai_prompt(STATS)
        self.assertTrue(prompt.startswith(AI_REVIEW_PROMPT[:20]))   # 分析要求在前
        self.assertTrue(prompt.rstrip().endswith(STATS.strip()))     # 战绩数据在后
        self.assertIn("【数据】", AI_REVIEW_PROMPT)                  # 数据段标记

    def test_requires_web_search(self):
        """用户要求：显式强调联网搜索车辆资料（对方支持联网搜索）。"""
        for key in ("必须联网搜索", "当前版本", "配件", "参考量级"):
            self.assertIn(key, AI_REVIEW_PROMPT)

    def test_demands_reasons_not_just_actions(self):
        """要点必须讲原因：先由数据推断问题，再给建议。"""
        for key in ("怎么从数据下判断", "推断的问题", "数据现象", "具体怎么做"):
            self.assertIn(key, AI_REVIEW_PROMPT)

    def test_demands_seven_points_and_five_tanks(self):
        for key in ("正好 7 条编号要点", "450~650 字", "5 条全部是车辆条目，一辆一条"):
            self.assertIn(key, AI_REVIEW_PROMPT)
        self.assertIn("禁止 Markdown 表格", AI_REVIEW_PROMPT)

    def test_forbids_non_tank_filler_in_3_to_7(self):
        """③~⑦ 必须是 5 辆车，不许塞"先改哪辆/短期目标/总结"。"""
        self.assertIn("不许出现任何非车辆内容", AI_REVIEW_PROMPT)
        for key in ("先改哪辆", "短期目标", "总结"):
            self.assertIn(key, AI_REVIEW_PROMPT)      # 出现在"禁止"清单里

    def test_forbids_spec_recital(self):
        """用户要求：不要纯复述车辆性能/参数，有效建议更重要。"""
        for key in ("不要纯复述车辆性能或参数", "单发 xxx", "DPM 高低"):
            self.assertIn(key, AI_REVIEW_PROMPT)

    def test_prefers_weak_tanks(self):
        """优先选胜率低、WN8 低、场次够多的车（而不是场次最多的）。"""
        self.assertIn("胜率低 + WN8 低 + 场次够多", AI_REVIEW_PROMPT)
        self.assertIn("不要**挑场次最多", AI_REVIEW_PROMPT)
        self.assertIn("优先选场次 ≥10 的", AI_REVIEW_PROMPT)
        self.assertIn("放宽到 ≥5 场", AI_REVIEW_PROMPT)

    def test_embeds_researched_frameworks(self):
        """联网调研后补充的权威口径：WTR 五指标（按角色）+ 数据诊断对照表 + 三环量级。"""
        for key in ("弹夹", "高机动", "重甲", "生存率",
                    "伤害够但胜率低", "伤害低且胜率低", "胜率高但 WN8 低", "三环线"):
            self.assertIn(key, AI_REVIEW_PROMPT)

    def test_prioritises_by_repeated_mistakes(self):
        """场次越多、胜率越低的车优先点评（错误重复次数多，改起来收益最大）。"""
        self.assertIn("场次越多、胜率越低的车，优先级越高", AI_REVIEW_PROMPT)

    def test_structure_has_seven_slots(self):
        for key in ("WN8 档位", "共性问题", "5 条全部是车辆条目"):
            self.assertIn(key, AI_REVIEW_PROMPT)

    def test_empty_stats(self):
        self.assertEqual(build_ai_prompt("").strip(), AI_REVIEW_PROMPT.strip())


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
        self.assertLess(prompt.index("资深数据分析师"), prompt.index("loy1234"))

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
