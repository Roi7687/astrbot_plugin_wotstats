# -*- coding: utf-8 -*-
"""坦克目录与缓存单元测试。"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cache import TTLCache  # noqa: E402
from core.config import TANK_CATALOG_FILE  # noqa: E402
from core.tanks import clear_cache, load_catalog, normalize_name, strip_quotes  # noqa: E402


class TestNormalize(unittest.TestCase):
    def test_quotes_and_spaces(self):
        self.assertEqual(normalize_name('"犀牛"'), "犀牛")
        self.assertEqual(normalize_name("Vz.58 \"熊\""), "vz58熊")
        self.assertEqual(normalize_name("E-77"), "e77")
        self.assertEqual(normalize_name("VCS 6x6 TS 90"), "vcs6x6ts90")
        self.assertEqual(normalize_name(""), "")
        self.assertEqual(normalize_name(None), "")

    def test_strip_quotes_for_display(self):
        self.assertEqual(strip_quotes('"犀牛"'), "犀牛")
        self.assertEqual(strip_quotes("E-77"), "E-77")


class TestLoadCatalog(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def test_asset_exists_and_loads(self):
        self.assertTrue(os.path.exists(TANK_CATALOG_FILE), "assets/tank_catalog.json 缺失")
        cat = load_catalog()
        self.assertGreater(len(cat), 900)
        # 真实车名（含引号/空格/连字符）都要能命中
        for name in ('"犀牛"', "E-77", "五式4型炮战车", "Pz.70-120", "WZ219"):
            self.assertIn(normalize_name(name), cat, f"{name} 未收录")

    def test_missing_file_returns_empty(self):
        self.assertEqual(load_catalog(os.path.join(tempfile.gettempdir(), "no_such_catalog.json")), {})

    def test_both_source_formats(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cat.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"1": "T-34", "2": {"name": "IS-7"}}, f, ensure_ascii=False)
            cat = load_catalog(path)
            self.assertEqual(cat.get("t34"), "1")
            self.assertEqual(cat.get("is7"), "2")


class TestTTLCache(unittest.TestCase):
    def test_disabled_when_ttl_zero(self):
        c = TTLCache(0)
        c.set("a", 1)
        self.assertIsNone(c.get("a"))

    def test_hit_and_expire(self):
        c = TTLCache(0.15)
        c.set("a", 1)
        self.assertEqual(c.get("a"), 1)
        time.sleep(0.2)
        self.assertIsNone(c.get("a"))

    def test_eviction_keeps_working(self):
        c = TTLCache(60, maxsize=2)
        for i in range(5):
            c.set(str(i), i)
        self.assertIsNotNone(c.get("4"))


if __name__ == "__main__":
    unittest.main()
