# -*- coding: utf-8 -*-
"""指令解析单元测试（纯函数，不依赖 AstrBot）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.commands import is_wgid, parse_target  # noqa: E402
from core.config import ACT_INDEX, ACT_TOTAL  # noqa: E402


class TestParseTarget(unittest.TestCase):
    def test_plain_nickname(self):
        self.assertEqual(parse_target("loy1234"), (ACT_INDEX, "loy1234"))

    def test_cjk_nickname(self):
        self.assertEqual(parse_target("庇护者一号"), (ACT_INDEX, "庇护者一号"))

    def test_total(self):
        self.assertEqual(parse_target("总 loy1234"), (ACT_TOTAL, "loy1234"))
        self.assertEqual(parse_target("总战绩 loy1234"), (ACT_TOTAL, "loy1234"))
        self.assertEqual(parse_target("total loy1234"), (ACT_TOTAL, "loy1234"))

    def test_camp_keyword_is_now_a_nickname(self):
        """已删除 /wot 营地 指令：这类输入整体当作昵称处理（不再有营地分支）。"""
        self.assertEqual(parse_target("营地 loy1234"), (ACT_INDEX, "营地 loy1234"))
        self.assertEqual(parse_target("坦克营地 loy1234"), (ACT_INDEX, "坦克营地 loy1234"))
        self.assertEqual(parse_target("camp loy1234"), (ACT_INDEX, "camp loy1234"))

    def test_extra_spaces_trimmed(self):
        self.assertEqual(parse_target("总    loy1234  "), (ACT_TOTAL, "loy1234"))

    def test_keyword_only_gives_empty_target(self):
        self.assertEqual(parse_target("总"), (ACT_TOTAL, ""))
        self.assertEqual(parse_target("总战绩 "), (ACT_TOTAL, ""))

    def test_empty(self):
        self.assertEqual(parse_target(""), (ACT_INDEX, ""))
        self.assertEqual(parse_target(None), (ACT_INDEX, ""))


class TestIsWgid(unittest.TestCase):
    def test_ok(self):
        self.assertTrue(is_wgid("7049441311"))
        self.assertTrue(is_wgid(7049441311))
        self.assertTrue(is_wgid(" 12345 "))

    def test_reject(self):
        self.assertFalse(is_wgid(""))
        self.assertFalse(is_wgid(None))
        self.assertFalse(is_wgid("123"))          # 太短
        self.assertFalse(is_wgid("loy1234"))      # 含字母
        self.assertFalse(is_wgid("７０４９４４１３１１"))   # 全角数字
        self.assertFalse(is_wgid("-12345"))


if __name__ == "__main__":
    unittest.main()
