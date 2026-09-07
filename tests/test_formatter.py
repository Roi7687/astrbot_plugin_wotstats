# -*- coding: utf-8 -*-
"""排版器单元测试：三种风格（qq_md / plain / table）的关键特征断言。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.formatter import (format_index_reply, format_total_reply,
                            player_not_found_text, usage_text)
from core.parser import (BattleBrief, PlayerStats, RecentStats, TankDetail,
                         TotalStats, TotalTankRow)


def make_index_stats():
    st = PlayerStats(
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
                          avg={"场均伤害": "4196"})],
        evaluation=["团队中坚力量，不可或缺", "使用频率最高的坦克是：庇护者"],
        recent_battles=[BattleBrief(result="胜利", exp="691", mode="标准", time="09-07 22:00"),
                        BattleBrief(result="失败", exp="400", mode="标准", time="09-07 21:48")],
    )
    return st


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


class TestIndexStyles(unittest.TestCase):
    def setUp(self):
        self.st = make_index_stats()

    def test_qq_md_uses_official_syntax(self):
        text = format_index_reply(self.st, "qq_md")
        self.assertIn("**loy1234**", text)
        self.assertIn("**57%**", text)
        self.assertIn("- 胜率：", text)
        self.assertNotIn("| --- |", text)  # QQ 官方 markdown 不支持表格

    def test_plain_has_no_markdown_markers(self):
        text = format_index_reply(self.st, "plain")
        self.assertNotIn("**", text)
        self.assertNotIn("| --- |", text)
        self.assertIn("胜率 57%", text)
        self.assertIn("常用坦克：庇护者", text)

    def test_table_style(self):
        text = format_index_reply(self.st, "table")
        self.assertIn("| --- |", text)
        self.assertIn("| 胜率 |", text)
        self.assertIn("| 庇护者 | 重坦 | 58% | 111 | 1767 |", text)

    def test_source_note_present(self):
        for style in ("qq_md", "plain", "table"):
            self.assertIn("偶游盒子", format_index_reply(self.st, style))


class TestTotalStyles(unittest.TestCase):
    def setUp(self):
        self.ts = make_total_stats()

    def test_qq_md(self):
        text = format_total_reply(self.ts, "qq_md")
        self.assertIn("总战绩", text)
        self.assertIn("**53%**", text)
        self.assertIn("已入伍4984天", text)
        self.assertNotIn("| --- |", text)

    def test_plain(self):
        text = format_total_reply(self.ts, "plain")
        self.assertNotIn("**", text)
        self.assertIn("总胜率 53%", text)

    def test_table(self):
        text = format_total_reply(self.ts, "table")
        self.assertIn("| 总胜率 | 53% |", text)
        self.assertIn("| 总体击毁 | 15708 |", text)
        self.assertIn("| 场均击毁 | 0.92 |", text)


class TestCommonText(unittest.TestCase):
    def test_usage(self):
        self.assertIn("/wot", usage_text())
        self.assertIn("总战绩", usage_text())

    def test_not_found(self):
        t = player_not_found_text("Nope_123")
        self.assertIn("Nope_123", t)
        self.assertIn("没有找到玩家", t)


if __name__ == "__main__":
    unittest.main()
