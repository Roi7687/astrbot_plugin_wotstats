# -*- coding: utf-8 -*-
"""排版器单元测试：三种风格（qq_md / plain / table）的关键特征断言。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.camp_model import CampPeriod, CampPlayer, CampTank
from core.config import THREE_RING_URL
from core.formatter import (format_camp_block, format_camp_brief,
                            format_index_reply, format_total_reply,
                            player_not_found_text, rate_limited_brief,
                            rate_limited_text, three_ring_text, usage_text)
from core.parser import (PlayerStats, RecentStats, TankDetail, TotalStats,
                         TotalTankRow)

INDEX_URL = "https://wotbox.ouj.com/wotbox/index.php?r=default/index&pn=loy1234"
TOTAL_URL = "https://wotbox.ouj.com/wotbox/index.php?r=default/battlestat&pn=loy1234"


def make_index_stats():
    return PlayerStats(
        player="loy1234",
        power="1480",
        power_delta="+0",
        updated_at="2026-09-07 06:51",
        recent=RecentStats(win_rate="57%", win="867", lose="633", total="1500",
                           hit_rate="74%", tier="10.1级", mode="标准模式"),
        avg_per_battle={"杀伤": "3332", "经验": "713", "击毁": "1.31",
                        "占领": "0.11", "防守": "0.09", "发现": "1.29"},
        tanks=[TankDetail(key="k1", name="庇护者", vehicle_type="重坦",
                          win_rate="58%", battles="111", power="1767",
                          avg={"场均伤害": "4196", "场均经验": "789",
                               "场均击毁": "1.32", "场均银币": "39271", "命中率": "81%"})],
    )


def make_total_stats():
    return TotalStats(
        player="loy1234", power="1480", power_delta="+0",
        join_days="已入伍4984天", join_date="2013年01月14日加入坦克世界",
        headline={"胜率": "53%", "伤害": "1367", "助攻": "649", "经验": "762"},
        total_cols=["击毁", "占领", "防守", "发现"],
        total_row=["15708", "9778", "6563", "24074"],
        avg_row=["0.92", "0.57", "0.38", "1.41"],
        recent_tanks=[TotalTankRow(name="庇护者", battles="189", win_rate="58%", power="1767")],
    )


def make_camp():
    """营地数据（口径取自 2026-10-16 实测）。"""
    return CampPlayer(
        wgid="7049441311", nickname="loy1234", last_battle_time=1792082671,
        periods={
            "day_7": CampPeriod(key="day_7", fights=164, win=101, lose=61, draw=2,
                                wn8=3077.59, win_rate=61.59, kd=1.88, avgdmg=3201.96,
                                rank=1021, population=129540),
            "day_30": CampPeriod(key="day_30", fights=297, win=173, lose=118, draw=6,
                                 wn8=2903.45, win_rate=58.25, kd=1.77, avgdmg=3209.14,
                                 avgfrag=1.34, avgspot=1.64, avgexp=1100.47, hit_rate=76.82,
                                 avglevel=10.09, rank=1941, population=187731),
            "all": CampPeriod(key="all", fights=30536, win=17126, lose=12911, draw=499,
                              wn8=2226.36, win_rate=56.08, kd=1.43, rank=10099, population=384874),
        },
        tanks_30d=[  # 均取自 2026-10-16 实测，按近 30 天场次降序
            CampTank(tank_id="36673", name="WZ132-1", tier=10, type="lightTank", fights=56,
                     wn8=2702.0, win_rate=53.6, avgdmg=2050.0, avgdmgasst=900.0, kd=1.0),
            CampTank(tank_id="37649", name="UDES 15/16", tier=10, type="MT", fights=38,
                     wn8=3202.8, win_rate=52.6, avgdmg=3704.0, avgdmgasst=1006.0, kd=1.0),
            # 4 场 < 门槛（CAMP_TANKS_MIN_FIGHTS=10）→ 不应出现在常用坦克表里（v0.3.5 过滤规则）
            CampTank(tank_id="2977", name='"犀牛"', tier=10, type="heavyTank", fights=4,
                     wn8=3670.6, win_rate=25.0, avgdmg=3831.25, avgdmgasst=120.0, kd=1.0)],
    )


class TestIndexStyles(unittest.TestCase):
    """未提供营地数据时的纯盒子视图（降级路径，必须与改造前一致）。"""

    def setUp(self):
        self.st = make_index_stats()

    def test_qq_md_tank_line_has_extra_fields(self):
        text = format_index_reply(self.st, "qq_md")
        self.assertIn("**庇护者**（重坦）", text)
        self.assertIn("场均伤害 4196", text)
        self.assertIn("命中率 81%", text)

    def test_source_line_removed(self):
        """v0.3.5：用户要求删除结尾的「数据来源：<盒子查询页链接>」（回复已足够详细）。"""
        for style in ("qq_md", "plain", "table"):
            text = format_index_reply(self.st, style)
            self.assertNotIn("数据来源", text, style)
            self.assertNotIn(INDEX_URL, text, style)
            self.assertNotIn("wotbox.ouj.com", text, style)
        ts = make_total_stats()
        for style in ("qq_md", "plain", "table"):
            text = format_total_reply(ts, style)
            self.assertNotIn("数据来源", text, style)
            self.assertNotIn(TOTAL_URL, text, style)

    def test_deleted_sections_not_rendered(self):
        """用户要求删除的三段（各车型战斗力 / 最近对局 / 盒子评价）不得再出现。"""
        for style in ("qq_md", "plain", "table"):
            text = format_index_reply(self.st, style)
            for gone in ("各车型", "最近对局", "盒子评价", "战斗力**TD", "SPG"):
                self.assertNotIn(gone, text, style)

    def test_plain_has_no_markdown_markers(self):
        text = format_index_reply(self.st, "plain")
        self.assertNotIn("**", text)
        self.assertNotIn("| --- |", text)
        self.assertIn("胜率 57%", text)
        self.assertIn("· 庇护者（重坦）", text)
        self.assertNotIn("数据来源", text)          # v0.3.5 已删除来源行

    def test_table_style(self):
        text = format_index_reply(self.st, "table")
        self.assertIn("| --- |", text)
        self.assertIn("| 胜率 |", text)
        self.assertIn("| 庇护者 | 重坦 | 58% | 111 | 1767 | 4196 | 81% |", text)


class TestIndexWithCamp(unittest.TestCase):
    """提供营地数据时：常用坦克区块 = 营地近 30 天口径（盒子效率按需补充）。"""

    def setUp(self):
        self.st = make_index_stats()
        self.camp = make_camp()

    def test_camp_only_when_no_box_data(self):
        """拿不到盒子数据时，整段仍是完整的营地内容，且不出现"盒子效率"字样。"""
        text = format_index_reply(self.st, "qq_md", self.camp)
        self.assertIn("常用坦克", text)
        self.assertIn("营地WN8 **3,203**", text)
        self.assertIn("**UDES 15/16**", text)
        self.assertIn("营地 近 30 天 >10 场", text)     # v0.3.5：表头写明"常玩"门槛
        self.assertNotIn("盒子效率", text)             # 无补充数据 → 不显示该字段
        self.assertNotIn("盒子效率 -", text)

    def test_tanks_below_fight_threshold_are_filtered(self):
        """v0.3.5：30 天只打了几场的车不算"常用"，不进表（犀牛只有 4 场）。"""
        text = format_index_reply(self.st, "qq_md", self.camp)
        self.assertNotIn("犀牛", text)
        self.assertNotIn('"犀牛"', text)              # 引号去掉了，但整辆车的行都不该在

    def test_box_power_appended_only_for_matched_rows(self):
        """有盒子数据时：**只给匹配上的行**追加"盒子效率"，其余行不显示。"""
        st = make_index_stats()
        st.tanks = [TankDetail(name="UDES 15/16", vehicle_type="中坦", win_rate="54%",
                               battles="42", power="1516", avg={"场均伤害": "3700"}),
                    TankDetail(name="别的车", power="999")]
        text = format_index_reply(st, "qq_md", self.camp)
        self.assertIn("盒子效率为补充", text)          # 表头点明是补充
        self.assertIn("盒子效率 **1516**", text)
        self.assertEqual(text.count("盒子效率"), 2)    # 表头 1 次 + 命中行 1 次

    def test_only_shows_tanks_with_camp_battles(self):
        self.camp.tanks_30d.append(CampTank(name="没打过的车", tier=10, fights=0, wn8=0))
        text = format_index_reply(self.st, "qq_md", self.camp)
        self.assertNotIn("没打过的车", text)

    def test_plain_and_table(self):
        plain = format_index_reply(self.st, "plain", self.camp)
        self.assertNotIn("**", plain)
        self.assertIn("常用坦克（营地 近 30 天 >10 场）：", plain)
        table = format_index_reply(self.st, "table", self.camp)
        self.assertIn("| 坦克 | 等级 | 营地WN8 | 近30天场次 | 30天胜率 | 场均伤害 |", table)
        self.assertIn("| WZ132-1 | 10 | 2,702 | 56 | 53.6% | 2,050 |", table)
        self.assertIn("| UDES 15/16 | 10 | 3,203 | 38 | 52.6% | 3,704 |", table)
        self.assertNotIn("犀牛", table)                 # 4 场 < 门槛 → 被过滤
        self.assertNotIn("盒子效率", table)              # 无补充 → 不加列

    def test_table_adds_box_column_only_when_available(self):
        st = make_index_stats()
        st.tanks = [TankDetail(name="UDES 15/16", power="1516")]
        table = format_index_reply(st, "table", self.camp)
        self.assertIn("| 坦克 | 等级 | 营地WN8 | 近30天场次 | 30天胜率 | 场均伤害 | 盒子效率 |", table)
        self.assertIn("| UDES 15/16 | 10 | 3,203 | 38 | 52.6% | 3,704 | 1516 |", table)
        self.assertIn("| WZ132-1 | 10 | 2,702 | 56 | 53.6% | 2,050 | - |", table)

    def test_camp_without_tanks_falls_back_to_box_view(self):
        """营地只有时段数据、没有单车数据时，仍展示盒子的常用坦克（不出现空表）。"""
        camp = CampPlayer(nickname="loy1234",
                          periods={"day_30": CampPeriod(key="day_30", fights=10, wn8=1000)})
        text = format_index_reply(self.st, "qq_md", camp)
        self.assertIn("**庇护者**（重坦）", text)
        self.assertNotIn("营地WN8", text)

    def test_infinity_and_nan_do_not_raise(self):
        """JSON 的 1e999 会变成 inf；排版层必须兜住，不能抛 OverflowError。"""
        camp = CampPlayer(
            nickname="x",
            periods={"day_30": CampPeriod(key="day_30", fights=5, wn8=float("inf"),
                                          win_rate=float("nan"), kd=float("inf"),
                                          avgdmg=float("inf"), avglevel=float("inf"),
                                          rank=10 ** 12, population=float("inf"))},
            tanks_30d=[CampTank(name="T", tier=10, fights=2, wn8=float("inf"),
                                win_rate=float("nan"), avgdmg=float("inf"))],
        )
        for style in ("qq_md", "plain", "table"):
            text = format_index_reply(self.st, style, camp)
            self.assertNotIn("inf", text)
            self.assertNotIn("nan", text)

    def test_remote_strings_are_sanitized(self):
        """昵称/车名来自外部接口，换行与 Markdown 控制字符必须清理。"""
        camp = CampPlayer(
            nickname="坏\n名字**加粗**[链接](http://evil)",
            periods={"all": CampPeriod(key="all", fights=1, wn8=1000)},
            tanks_30d=[CampTank(name='T\n**注入**', tier=10, fights=1, wn8=900)],
        )
        for style in ("qq_md", "plain", "table"):
            text = format_index_reply(self.st, style, camp)
            self.assertNotIn("**加粗**", text)
            self.assertNotIn("[链接]", text)
            self.assertNotIn("**注入**", text)
            self.assertFalse(any(ln.startswith("## ") for ln in text.split("\n")))

    def test_truncation_limits_echo_length(self):
        """超长车名不能把回复撑爆。"""
        camp = CampPlayer(nickname="x" * 5000,
                          periods={"all": CampPeriod(key="all", fights=1, wn8=1000)},
                          tanks_30d=[CampTank(name="y" * 5000, tier=10, fights=1, wn8=900)])
        text = format_index_reply(self.st, "qq_md", camp)
        self.assertLess(len(text), 1500)

    def test_unknown_tier_wording(self):
        camp = CampPlayer(nickname="x", periods={"day_30": CampPeriod(key="day_30", fights=12, wn8=100)},
                          tanks_30d=[CampTank(name="T", tier=0, fights=12, wn8=100)])
        text = format_index_reply(self.st, "qq_md", camp)
        self.assertIn("等级未知", text)
        self.assertNotIn("（- 级）", text)


class TestTotalStyles(unittest.TestCase):
    def setUp(self):
        self.ts = make_total_stats()

    def test_qq_md(self):
        text = format_total_reply(self.ts, "qq_md")
        self.assertIn("总战绩", text)
        self.assertIn("**53%**", text)
        self.assertIn("已入伍4984天", text)
        self.assertNotIn("| --- |", text)
        self.assertNotIn("数据来源", text)          # v0.3.5 已删除来源行
        self.assertNotIn("仅供参考", text)

    def test_plain(self):
        text = format_total_reply(self.ts, "plain")
        self.assertNotIn("**", text)
        self.assertIn("总胜率 53%", text)
        self.assertNotIn("数据来源", text)

    def test_table(self):
        text = format_total_reply(self.ts, "table")
        self.assertIn("| 总胜率 | 53% |", text)
        self.assertIn("| 总体击毁 | 15708 |", text)
        self.assertIn("| 场均击毁 | 0.92 |", text)


class TestCommonText(unittest.TestCase):
    def test_usage(self):
        text = usage_text()
        self.assertIn("/wot", text)
        self.assertIn("总战绩", text)
        self.assertIn("常用坦克", text)
        self.assertNotIn("/wot 营地", text)          # 该指令已删除

    def test_not_found(self):
        t = player_not_found_text("Nope_123")
        self.assertIn("Nope_123", t)
        self.assertIn("没有找到玩家", t)

    def test_rate_limited(self):
        t = rate_limited_text("loy1234")
        self.assertIn("限流", t)
        self.assertIn("loy1234", t)
        self.assertIn("坦克营地", t)
        self.assertNotIn("/wot 营地", t)

    def test_rate_limited_brief(self):
        t = rate_limited_brief()
        self.assertIn("限流", t)
        self.assertIn("坦克营地", t)
        self.assertIn("战斗力", t)      # 说清缺的是盒子那部分


class TestThreeRing(unittest.TestCase):
    """`/wot3h`：只回一个可在浏览器打开的「三环」榜单链接。"""

    def test_qq_md_link(self):
        text = three_ring_text("qq_md")
        self.assertIn(THREE_RING_URL, text)
        self.assertIn("[%s](%s)" % (THREE_RING_URL, THREE_RING_URL), text)   # QQ 官方 Markdown 可点击
        self.assertEqual(text.count("\n"), 1)                                # 两行：标题 + 链接

    def test_plain_bare_url(self):
        text = three_ring_text("plain")
        self.assertIn(THREE_RING_URL, text)
        self.assertNotIn("**", text)
        self.assertNotIn("](", text)                     # 纯文本给裸 URL，可直接复制

    def test_url_is_official_three_ring_page(self):
        self.assertTrue(THREE_RING_URL.startswith("https://camp.wot.360.cn/"))
        self.assertIn("AIrankDetailListThreeRing", THREE_RING_URL)
        self.assertIn("type=mastery", THREE_RING_URL)

    def test_usage_mentions_command(self):
        self.assertIn("/wot3h", usage_text())


class TestCampBlock(unittest.TestCase):
    """盒子不可用时的营地正文（常用坦克表 + 近 7 天/近 30 天速览）。"""

    def test_includes_tank_table_even_without_box(self):
        text = format_camp_block(make_camp(), "qq_md")
        self.assertIn("常用坦克", text)                 # 表必须在（v0.3.2 修的真实缺陷）
        self.assertIn("营地WN8 **3,203**", text)
        self.assertIn("🏕 **loy1234** ｜ **坦克营地**数据", text)
        self.assertNotIn("近 30 天场均", text)           # v0.3.5 删除（与开头场均重复）
        self.assertNotIn("生涯", text)                  # v0.3.5 删除（代表意义不大）
        self.assertNotIn("盒子效率", text)              # 无盒子数据 → 不出现该字段
        self.assertNotIn("| --- |", text)
        self.assertFalse(text.startswith("\n"))         # 正文不以空行开头

    def test_table_style(self):
        text = format_camp_block(make_camp(), "table")
        self.assertIn("| 坦克 | 等级 | 营地WN8 | 近30天场次 | 30天胜率 | 场均伤害 |", text)
        self.assertIn("| UDES 15/16 | 10 | 3,203 | 38 | 52.6% | 3,704 |", text)

    def test_plain_style(self):
        text = format_camp_block(make_camp(), "plain")
        self.assertNotIn("**", text)
        self.assertIn("常用坦克（营地 近 30 天 >10 场）：", text)

    def test_empty_when_no_camp(self):
        self.assertEqual(format_camp_block(None), "")

    def test_only_brief_when_no_tanks(self):
        camp = CampPlayer(nickname="x", periods={"day_30": CampPeriod(key="day_30", fights=5, wn8=1000)})
        text = format_camp_block(camp, "qq_md")
        self.assertIn("🏕 **x**", text)
        self.assertNotIn("常用坦克", text)


class TestCampBrief(unittest.TestCase):
    """营地速览（挂在 /wot 回复末尾）：只保留近 7 天 / 近 30 天两行。"""

    def test_qq_md(self):
        text = format_camp_brief(make_camp(), "qq_md")
        self.assertIn("坦克营地", text)
        self.assertIn("近 7 天", text)
        self.assertIn("**3,078**", text)
        self.assertIn("全服第 1,021 名（129,540 人）", text)
        self.assertIn("近 30 天", text)
        self.assertNotIn("近 30 天场均", text)          # v0.3.5 删除（与开头重复）
        self.assertNotIn("生涯", text)                  # v0.3.5 删除
        self.assertNotIn("逐场", text)
        self.assertEqual(text.count("\n"), 2)           # 标题 + 近7天 + 近30天 = 3 行

    def test_plain(self):
        text = format_camp_brief(make_camp(), "plain")
        self.assertNotIn("**", text)
        self.assertIn("【坦克营地】loy1234", text)
        self.assertIn("61.6%", text)

    def test_empty_when_no_period(self):
        self.assertEqual(format_camp_brief(CampPlayer(nickname="x"), "qq_md"), "")

    def test_zero_win_rate_is_shown_not_dashed(self):
        """有场次时 0% 是真实数据，不能渲染成 '-'。"""
        camp = CampPlayer(nickname="x", periods={"day_30": CampPeriod(
            key="day_30", fights=3, wn8=500, win_rate=0.0, kd=0.0, hit_rate=0.0)})
        text = format_camp_brief(camp, "qq_md")
        self.assertIn("胜率 0.0%", text)
        self.assertIn("K/D 0.00", text)
        self.assertNotIn("近 30 天场均", text)      # v0.3.5 该行已删除

    def test_no_data_period_is_skipped(self):
        """fights=0 的时段不算数据（CampPlayer.period 会过滤）→ 速览整体为空。"""
        camp = CampPlayer(nickname="x", periods={"day_30": CampPeriod(key="day_30", fights=0)})
        self.assertEqual(format_camp_brief(camp, "qq_md"), "")

    def test_table_zero_values_not_dashed(self):
        """有场次时 0 胜率要显示 0.0%，不能渲染成 '-'（复核 A3）。"""
        camp = CampPlayer(
            nickname="x",
            periods={"day_7": CampPeriod(key="day_7", fights=3, wn8=500.0, win_rate=0.0, kd=0.0,
                                         rank=100, population=1000)},
            tanks_30d=[CampTank(name="T", tier=10, fights=12, wn8=0.0, win_rate=0.0, avgdmg=0.0)],
        )
        brief = format_camp_brief(camp, "qq_md")
        self.assertIn("胜率 0.0%", brief)
        self.assertNotIn("-%", brief)
        table = format_index_reply(make_index_stats(), "table", camp)
        self.assertIn("| T | 10 | - | 12 | 0.0% | - |", table)   # 无盒子补充 → 没有盒子列


if __name__ == "__main__":
    unittest.main()
