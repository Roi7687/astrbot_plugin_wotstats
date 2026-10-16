# -*- coding: utf-8 -*-
"""坦克营地解析层单元测试（纯函数，不发网络请求）。

fixtures 来源：research/camp_probe/snapshots/（2026-10-16 实测原始响应）。
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.camp_parser import (  # noqa: E402
    check_payload,
    extract_user_info,
    parse_battles,
    parse_period,
    parse_tank,
    pick_tank_ids,
)
from core.camp_model import CampBattle  # noqa: E402
from core.config import CampError, CampNotFoundError  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def payload(data, errno=0, errmsg="ok", time=1792147433):
    return {"errno": errno, "errmsg": errmsg, "time": time, "data": data}


class TestCheckPayload(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(check_payload(payload({"a": 1})), {"a": 1})

    def test_errno_2000(self):
        with self.assertRaises(CampError) as ctx:
            check_payload(payload([], errno=2000, errmsg="用户需要登录"), "/tank/appuserrank")
        self.assertIn("2000", str(ctx.exception))

    def test_errno_2003(self):
        with self.assertRaises(CampError) as ctx:
            check_payload(payload([], errno=2003, errmsg="pkey empty"), "/WotArena/getUserBattles")
        self.assertIn("pkey empty", str(ctx.exception))

    def test_non_dict(self):
        with self.assertRaises(CampError):
            check_payload(["not", "a", "dict"])


class TestUserInfo(unittest.TestCase):
    def test_real_fixture(self):
        raw = load("camp_profile_3periods.json")["day_30"]
        info = extract_user_info(raw)
        self.assertEqual(info["nickname"], "loy1234")
        self.assertTrue(info["face_url"].startswith("https://"))
        self.assertEqual(info["last_battle_time"], 1792082671)
        self.assertEqual(info["server_time"], raw["time"])   # 取接口返回的服务器时间

    def test_missing_nickname_is_not_found(self):
        # 实测：wgid 不存在时 errno 仍为 0，但 nick_name 为空
        with self.assertRaises(CampNotFoundError):
            extract_user_info(payload({"userInfo": {"nick_name": None}, "RankList": {}, "size": 0}))


class TestParsePeriod(unittest.TestCase):
    def setUp(self):
        self.raw = load("camp_profile_3periods.json")

    def test_day_7_values(self):
        p = parse_period(self.raw["day_7"], "day_7")
        self.assertEqual(p.key, "day_7")
        self.assertEqual(p.fights, 164)
        self.assertAlmostEqual(p.wn8, 3077.59, places=2)
        self.assertAlmostEqual(p.win_rate, 61.59, places=2)
        self.assertAlmostEqual(p.kd, 1.88, places=2)
        self.assertEqual(p.rank, 1021)
        self.assertEqual(p.population, 129540)
        self.assertEqual(p.win, 101)
        self.assertEqual(p.lose, 61)
        self.assertEqual(p.draw, 2)

    def test_all_periods_parsed(self):
        for key in ("all", "day_7", "day_30"):
            p = parse_period(self.raw[key], key)
            self.assertGreater(p.fights, 0)
            self.assertGreater(p.wn8, 0)

    def test_less_maps_to_lose(self):
        # 接口用 "less" 表示负场数
        p = parse_period(self.raw["all"], "all")
        self.assertEqual(p.lose, self.raw["all"]["data"]["RankList"]["less"])

    def test_unknown_period(self):
        with self.assertRaises(CampError):
            parse_period(self.raw["all"], "day_1")

    def test_missing_fields_default_zero(self):
        p = parse_period(payload({"userInfo": {"nick_name": "x"}, "RankList": {}}), "all")
        self.assertEqual(p.fights, 0)
        self.assertEqual(p.wn8, 0.0)
        self.assertEqual(p.rank, 0)

    def test_bad_types_do_not_raise(self):
        p = parse_period(payload({"RankList": {"fights": "abc", "WN8": None, "K/D": "1.5"}}), "all")
        self.assertEqual(p.fights, 0)
        self.assertEqual(p.wn8, 0.0)
        self.assertAlmostEqual(p.kd, 1.5)


class TestParseBattles(unittest.TestCase):
    def setUp(self):
        self.raw = load("camp_battles_20.json")

    def test_count_and_order(self):
        rows = parse_battles(self.raw, 20)
        self.assertEqual(len(rows), 20)
        self.assertGreater(rows[0].ts, rows[1].ts)      # 最新在前

    def test_first_row_fields(self):
        b = parse_battles(self.raw, 1)[0]
        self.assertIsInstance(b, CampBattle)
        self.assertEqual(b.tank, '"犀牛"')
        self.assertEqual(b.map, "寂静海岸")
        self.assertEqual(b.mode, "标准模式")
        self.assertEqual(b.result, -1)
        self.assertEqual(b.damage, 3677)
        self.assertEqual(b.kills, 1)
        self.assertGreater(b.wn8, 0)
        self.assertGreater(b.assisted, 0)

    def test_want_limits(self):
        self.assertEqual(len(parse_battles(self.raw, 5)), 5)
        self.assertEqual(len(parse_battles(self.raw, 0)), 0)

    def test_empty_list(self):
        self.assertEqual(parse_battles(payload({"battleList": []}), 20), [])


class TestParseTank(unittest.TestCase):
    def test_real_fixture(self):
        t = parse_tank(load("camp_tank_day30.json"), "32529")
        self.assertIsNotNone(t)
        self.assertEqual(t.name, "Pz.70-120")
        self.assertEqual(t.tier, 11)
        self.assertEqual(t.fights, 10)
        self.assertAlmostEqual(t.wn8, 2762.66, places=2)
        self.assertGreater(t.avgdmgasst, 0)

    def test_zero_fights_is_none(self):
        # 实测：有车但该时段没打 → 返回 fights=0 的占位行，必须过滤掉
        raw = payload({"vBattles": {"list": [{"fights": 0, "WN8": 0, "rank": -1}]}})
        self.assertIsNone(parse_tank(raw, "2929"))

    def test_empty_list_is_none(self):
        self.assertIsNone(parse_tank(payload({"vBattles": {"list": []}}), "6513"))

    def test_missing_container_is_none(self):
        self.assertIsNone(parse_tank(payload({}), "6513"))


class TestPickTankIds(unittest.TestCase):
    CATALOG = {"犀牛": "2977", "e77": "37649", "wz219": "11313"}

    def test_picks_in_battle_order_without_dupes(self):
        battles = [
            CampBattle(tank='"犀牛"'),
            CampBattle(tank='"犀牛"'),
            CampBattle(tank="E-77"),
            CampBattle(tank="未收录的新车"),
            CampBattle(tank="WZ219"),
        ]
        self.assertEqual(pick_tank_ids(battles, self.CATALOG, limit=12), ["2977", "37649", "11313"])

    def test_limit(self):
        battles = [CampBattle(tank='"犀牛"'), CampBattle(tank="E-77"), CampBattle(tank="WZ219")]
        self.assertEqual(pick_tank_ids(battles, self.CATALOG, limit=2), ["2977", "37649"])

    def test_empty_catalog(self):
        self.assertEqual(pick_tank_ids([CampBattle(tank="犀牛")], {}, limit=5), [])


class TestHostileValues(unittest.TestCase):
    """接口返回异常值时的容错（复核发现的 B2/B3/B6）。"""

    def test_infinity_from_json_is_not_kept(self):
        # json.loads("1e999") → inf；若原样透传，排版层 int(round(inf)) 会抛 OverflowError
        raw = json.loads('{"errno":0,"errmsg":"ok","time":1,"data":{"RankList":{"WN8":1e999,'
                         '"fights":3,"avgdmg":"Infinity"},"size":10}}')
        p = parse_period(raw, "all")
        self.assertEqual(p.wn8, 0.0)
        self.assertEqual(p.avgdmg, 0.0)
        self.assertEqual(p.fights, 3)

    def test_nan_is_not_kept(self):
        p = parse_period(payload({"RankList": {"WN8": float("nan"), "fights": 2}}), "all")
        self.assertEqual(p.wn8, 0.0)
        self.assertEqual(p.fights, 2)

    def test_numeric_nickname(self):
        # 纯数字昵称真实存在（如 8848133），接口可能按数字返回
        info = extract_user_info(payload({"userInfo": {"nick_name": 8848133, "last_time": 1}}))
        self.assertEqual(info["nickname"], "8848133")

    def test_userinfo_wrong_container(self):
        with self.assertRaises(CampNotFoundError):
            extract_user_info(payload({"userInfo": ["oops"]}))

    def test_ranklist_wrong_container(self):
        p = parse_period(payload({"RankList": [1, 2, 3]}), "all")
        self.assertEqual(p.fights, 0)

    def test_battles_with_numeric_and_wrong_types(self):
        raw = payload({"battleList": [
            {"tankName": 12345, "mapName": 678, "battleType": None, "winResult": None,
             "damageDealt": "abc", "wn8": 1e999},
            "not-a-dict",
            {"tankName": "E-77", "winResult": 0},
        ]})
        rows = parse_battles(raw, 10)
        self.assertEqual(len(rows), 2)               # 非 dict 行被跳过
        self.assertEqual(rows[0].tank, "12345")
        self.assertEqual(rows[0].map, "678")
        self.assertEqual(rows[0].mode, "")
        self.assertEqual(rows[0].damage, 0)
        self.assertEqual(rows[0].wn8, 0.0)
        self.assertEqual(rows[1].result, 0)          # 0 = 平局

    def test_battlelist_wrong_container(self):
        self.assertEqual(parse_battles(payload({"battleList": {"a": 1}}), 5), [])

    def test_errno_as_string_zero(self):
        self.assertEqual(check_payload(payload({"a": 1}, errno="0")), {"a": 1})
        with self.assertRaises(CampError):
            check_payload(payload({}, errno="2000"))

    def test_tank_wrong_container(self):
        self.assertIsNone(parse_tank(payload({"vBattles": {"list": "oops"}}), "1"))


if __name__ == "__main__":
    unittest.main()
