# -*- coding: utf-8 -*-
"""解析器单元测试：使用 research/ 落盘的真实页面快照做 fixture。

预期值来源：2026-09-07 浏览器实测 + research/loy1234_zhanji_2026-09-07.json。
站点若改版：重新抓取新快照替换 tests/fixtures/*.html，再按失败信息修 core/parser.py。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import ParseError, PlayerNotFoundError
from core.parser import parse_page

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


class TestIndexParser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = parse_page(load("zhanji_index_raw.html"))

    def test_player_identity(self):
        self.assertEqual(self.st.player, "loy1234")
        self.assertEqual(self.st.power, "1480")
        self.assertEqual(self.st.power_delta, "+0")
        self.assertEqual(self.st.wu_id, "30450122")
        self.assertEqual(self.st.player_id, "7049441311")

    def test_updated_at(self):
        self.assertEqual(self.st.updated_at, "2026-09-07 06:51")

    def test_recent_stats(self):
        r = self.st.recent
        self.assertEqual(r.win_rate, "57%")
        self.assertEqual(r.win, "867")
        self.assertEqual(r.lose, "633")
        self.assertEqual(r.total, "1500")
        self.assertEqual(r.hit_rate, "74%")
        self.assertEqual(r.tier, "10.1级")
        self.assertEqual(r.mode, "标准模式")

    def test_avg_per_battle(self):
        expect = {"杀伤": "3332", "经验": "713", "击毁": "1.31",
                  "占领": "0.11", "防守": "0.09", "发现": "1.29"}
        self.assertEqual(self.st.avg_per_battle, expect)

    def test_tanks(self):
        self.assertEqual(len(self.st.tanks), 5)
        first = self.st.tanks[0]
        self.assertEqual(first.name, "庇护者")
        self.assertEqual(first.vehicle_type, "重坦")
        self.assertEqual(first.win_rate, "58%")
        self.assertEqual(first.battles, "111")
        self.assertEqual(first.power, "1767")

        self.assertIn("场均伤害", first.avg)
        self.assertEqual(first.avg["场均伤害"], "4196")
        self.assertIn("命中率", first.avg)
        self.assertEqual(first.avg["命中率"], "81%")

    def test_tabs(self):
        labels = [t for t, _ in self.st.tabs]
        for expected in ("个人战绩", "车库", "战斗日志", "总战绩", "App日志"):
            self.assertIn(expected, labels)

    def test_deleted_sections_not_parsed(self):
        """用户要求删除的区块（各车型战斗力/最近对局/盒子评价）不再进模型。"""
        for attr in ("class_power", "recent_battles", "evaluation"):
            self.assertFalse(hasattr(self.st, attr), attr)

    def test_to_dict_roundtrip(self):
        d = self.st.to_dict()
        self.assertEqual(d["player"], "loy1234")
        self.assertEqual(d["recent"]["win_rate"], "57%")


class TestNotFound(unittest.TestCase):
    def test_not_found_raises(self):
        with self.assertRaises(PlayerNotFoundError):
            parse_page(load("player_notfound_sample_raw.html"))


class TestGarbageInput(unittest.TestCase):
    def test_garbage_raises_parse_error(self):
        with self.assertRaises(ParseError):
            parse_page("<html><body>什么数据都没有</body></html>")

    def test_css_only_not_found_word_ok(self):
        html = ("<style>.not-find-user { color: red }</style>"
                "<div class=\"userRecord-data clearfix\">x</div>")
        with self.assertRaises(ParseError):
            parse_page(html)


class TestTotalParser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ts = parse_page(load("zongzhanji_battlestat_raw.html"), "default/battlestat")

    def test_identity(self):
        self.assertEqual(self.ts.player, "loy1234")
        self.assertEqual(self.ts.power, "1480")
        self.assertEqual(self.ts.power_delta, "+0")

    def test_join_info(self):
        self.assertEqual(self.ts.join_days, "已入伍4984天")
        self.assertEqual(self.ts.join_date, "2013年01月14日加入坦克世界")

    def test_headline(self):
        self.assertEqual(self.ts.headline["胜率"], "53%")
        self.assertEqual(self.ts.headline["伤害"], "1367")
        self.assertEqual(self.ts.headline["经验"], "762")

    def test_total_avg_rows(self):
        self.assertEqual(self.ts.total_cols, ["击毁", "占领", "防守", "发现"])
        self.assertEqual(self.ts.total_row, ["15708", "9778", "6563", "24074"])
        self.assertEqual(self.ts.avg_row, ["0.92", "0.57", "0.38", "1.41"])

    def test_recent_tanks(self):
        self.assertGreaterEqual(len(self.ts.recent_tanks), 5)
        first = self.ts.recent_tanks[0]
        self.assertEqual(first.name, "庇护者")
        self.assertEqual(first.battles, "189")
        self.assertEqual(first.win_rate, "58%")
        self.assertEqual(first.power, "1767")


if __name__ == "__main__":
    unittest.main()
