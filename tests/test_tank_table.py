# -*- coding: utf-8 -*-
"""常用坦克表单元测试（纯函数）：**营地优先，盒子效率仅作可选补充**。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.camp_model import CampPlayer, CampTank  # noqa: E402
from core.parser import TankDetail  # noqa: E402
from core.tank_table import (build_tank_rows, enrich_with_box,  # noqa: E402
                             rows_from_camp)


def camp_with(*tanks):
    return CampPlayer(nickname="n", tanks_30d=list(tanks))


class TestRowsFromCamp(unittest.TestCase):
    """第一阶段：完全由营地数据构成（不依赖盒子，盒子挂了也要有完整内容）。"""

    def test_camp_fields_mapped(self):
        camp = camp_with(CampTank(tank_id="2977", name="犀牛", tier=10, fights=4, wn8=3671.0,
                                  win_rate=25.0, avgdmg=3831.0, avgdmgasst=1006.0, kd=1.0,
                                  hit_rate=70.0))
        rows = rows_from_camp(camp)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.name, "犀牛")
        self.assertEqual(row.tier, 10)
        self.assertEqual(row.wn8, 3671.0)
        self.assertEqual(row.fights, 4)
        self.assertEqual(row.win_rate, 25.0)
        self.assertEqual(row.avgdmg, 3831.0)
        self.assertEqual(row.avgdmgasst, 1006.0)
        # 营地口径自带、盒子不必参与
        self.assertFalse(row.has_box)
        self.assertEqual(row.box_power, "")

    def test_skips_tanks_without_battles(self):
        """近 30 天没打过的车不出现（用户要求：只显示营地抓到的有战力数据的车）。"""
        camp = camp_with(
            CampTank(name="有战绩", tier=10, fights=3, wn8=1500.0),
            CampTank(name="零场次", tier=10, fights=0, wn8=0.0),
            CampTank(name="", tier=10, fights=5, wn8=100.0),
        )
        self.assertEqual([r.name for r in rows_from_camp(camp)], ["有战绩"])

    def test_keeps_camp_order(self):
        """顺序由取数层决定（近 30 天场次降序 = 常用优先），本模块不改动。"""
        camp = camp_with(CampTank(name="A", fights=30, wn8=1000.0),
                         CampTank(name="B", fights=5, wn8=2000.0))
        self.assertEqual([r.name for r in rows_from_camp(camp)], ["A", "B"])

    def test_none_camp(self):
        self.assertEqual(rows_from_camp(None), [])
        self.assertEqual(rows_from_camp(CampPlayer(nickname="x")), [])


class TestEnrichWithBox(unittest.TestCase):
    """第二阶段：只有"盒子效率"这一项来自盒子，且完全可选。"""

    def rows(self):
        return [build_tank_rows(camp_with(
            CampTank(name='"犀牛"', tier=10, fights=4, wn8=3671.0),
            CampTank(name="E-77", tier=9, fights=5, wn8=3335.0)))[0],
            build_tank_rows(camp_with(
                CampTank(name="E-77", tier=9, fights=5, wn8=3335.0)))[0]]

    def test_fills_power_by_normalized_name(self):
        """车名差异（引号/大小写/空格）要被抹平。"""
        rows = self.rows()
        box = [TankDetail(name='犀牛', power="1767", battles="189")]
        hits = enrich_with_box(rows, box)
        self.assertEqual(hits, 1)
        self.assertEqual(rows[0].box_power, "1767")
        self.assertEqual(rows[0].box_battles, "189")
        self.assertTrue(rows[0].has_box)
        self.assertFalse(rows[1].has_box)          # 没匹配上 → 保持营地口径

    def test_no_box_data_is_noop(self):
        for box in (None, [], [TankDetail(name="别的车", power="999")]):
            rows = build_tank_rows(camp_with(CampTank(name="E-77", fights=5, wn8=1.0)), box)
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0].has_box)
            self.assertEqual(rows[0].fights, 5)    # 营地数据不受影响

    def test_box_dash_power_treated_as_missing(self):
        """盒子自己有这辆车但战力是 '-' → 视为无补充（不显示"盒子效率 -"）。"""
        rows = build_tank_rows(camp_with(CampTank(name="E-77", fights=5, wn8=1.0)),
                               [TankDetail(name="E-77", power="-")])
        self.assertFalse(rows[0].has_box)

    def test_box_dict_payload_supported(self):
        rows = build_tank_rows(camp_with(CampTank(name="A", fights=2, wn8=1000.0)),
                               [{"name": "A", "power": "123", "battles": "10"}])
        self.assertEqual(rows[0].box_power, "123")
        self.assertEqual(rows[0].box_battles, "10")

    def test_enrich_only_touches_box_fields(self):
        """补充不得覆盖营地字段（营地是主数据源）。"""
        rows = build_tank_rows(camp_with(
            CampTank(name="A", tier=10, fights=7, wn8=2500.0, win_rate=60.0, avgdmg=3000.0)),
            [TankDetail(name="A", power="1500", battles="999")])
        row = rows[0]
        self.assertEqual((row.tier, row.fights, row.wn8, row.win_rate, row.avgdmg),
                         (10, 7, 2500.0, 60.0, 3000.0))


if __name__ == "__main__":
    unittest.main()
