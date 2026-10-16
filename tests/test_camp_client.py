# -*- coding: utf-8 -*-
"""坦克营地抓取层单元测试：httpx.MockTransport 注入，不发真实网络请求。"""
import asyncio
import json
import os
import sys
import unittest

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.camp_client import WotCampClient  # noqa: E402
from core.config import CAMP_BATTLE_PAGE_SIZE, CampError, CampNotFoundError  # noqa: E402
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def _run(coro):
    return asyncio.run(coro)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler),
                             base_url="https://tbox.wot.360.cn")


PROFILE = load("camp_profile_3periods.json")


def profile_handler(request):
    """按 type 参数返回对应时段；同时记录请求 URL 供断言。"""
    period = request.url.params.get("type")
    return httpx.Response(200, json=PROFILE[period])


def payload_battles(tanks):
    """构造一个只含指定车名的逐场战斗响应。"""
    return {"errno": 0, "errmsg": "success", "time": 1792147433, "data": {
        "battleList": [{"arenaId": str(i), "arenaCreateTime": 1792074412 - i, "tankName": t,
                        "mapName": "地图", "battleType": "标准模式", "winResult": 1,
                        "damageDealt": 1000, "kills": 1, "totalAssistedDamage": 100,
                        "wn8": 1500.0, "credits": 1, "duration": 300}
                       for i, t in enumerate(tanks)]}}


class TestFetchPeriod(unittest.TestCase):
    def test_ok(self):
        async def run():
            async with _client(profile_handler) as c:
                return await WotCampClient(client=c).fetch_period("7049441311", "day_30")

        period, info = _run(run())
        self.assertEqual(period.key, "day_30")
        self.assertEqual(period.fights, 297)
        self.assertEqual(info["nickname"], "loy1234")

    def test_not_found_raises(self):
        def handler(request):
            return httpx.Response(200, json={"errno": 0, "errmsg": "ok", "time": 1,
                                             "data": {"userInfo": {"nick_name": None},
                                                      "RankList": {}, "size": 0}})

        async def run():
            async with _client(handler) as c:
                await WotCampClient(client=c).fetch_period("1", "all")

        with self.assertRaises(CampNotFoundError):
            _run(run())

    def test_errno_2000_raises_camp_error(self):
        def handler(request):
            return httpx.Response(200, json={"errno": 2000, "errmsg": "用户需要登录", "data": []})

        async def run():
            async with _client(handler) as c:
                await WotCampClient(client=c).fetch_period("7049441311", "all")

        with self.assertRaises(CampError) as ctx:
            _run(run())
        self.assertIn("2000", str(ctx.exception))


class TestFetchBattles(unittest.TestCase):
    def test_param_name_is_uid(self):
        """实测坑：参数名必须是 uid，写成 accountId 会得到 errno=2003 pkey empty。"""
        seen = {}

        def handler(request):
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json=load("camp_battles_20.json"))

        async def run():
            async with _client(handler) as c:
                return await WotCampClient(client=c).fetch_battles("7049441311", 20)

        rows = _run(run())
        self.assertEqual(len(rows), 20)
        self.assertEqual(seen["params"].get("uid"), "7049441311")
        self.assertNotIn("accountId", seen["params"])
        self.assertEqual(seen["params"].get("size"), "20")

    def test_size_clamped_to_page_size(self):
        seen = {}

        def handler(request):
            seen["size"] = request.url.params.get("size")
            return httpx.Response(200, json=load("camp_battles_20.json"))

        async def run():
            async with _client(handler) as c:
                await WotCampClient(client=c).fetch_battles("7049441311", 9999)

        _run(run())
        self.assertEqual(seen["size"], str(CAMP_BATTLE_PAGE_SIZE))

    def test_errno_2003_raises(self):
        def handler(request):
            return httpx.Response(200, json={"errno": 2003, "errmsg": "pkey empty", "data": []})

        async def run():
            async with _client(handler) as c:
                await WotCampClient(client=c).fetch_battles("7049441311", 5)

        with self.assertRaises(CampError):
            _run(run())


class TestFetchTank(unittest.TestCase):
    def test_ok(self):
        def handler(request):
            return httpx.Response(200, json=load("camp_tank_day30.json"))

        async def run():
            async with _client(handler) as c:
                return await WotCampClient(client=c).fetch_tank_30d("7049441311", "32529")

        t = _run(run())
        self.assertIsNotNone(t)
        self.assertEqual(t.tank_id, "32529")
        self.assertEqual(t.fights, 10)

    def test_zero_fights_returns_none(self):
        def handler(request):
            return httpx.Response(200, json={"errno": 0, "errmsg": "ok",
                                             "data": {"vBattles": {"list": [{"fights": 0, "WN8": 0}]}}})

        async def run():
            async with _client(handler) as c:
                return await WotCampClient(client=c).fetch_tank_30d("7049441311", "2929")

        self.assertIsNone(_run(run()))


class TestRetryAndErrors(unittest.TestCase):
    def test_retry_then_ok(self):
        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            if state["n"] <= 2:
                return httpx.Response(503, text="busy")
            return httpx.Response(200, json=PROFILE["all"])

        async def run():
            async with _client(handler) as c:
                return await WotCampClient(client=c).fetch_period("7049441311", "all")

        period, _ = _run(run())
        self.assertEqual(period.key, "all")
        self.assertEqual(state["n"], 3)

    def test_always_500_raises_camp_error(self):
        def handler(request):
            return httpx.Response(500, text="boom")

        async def run():
            async with _client(handler) as c:
                await WotCampClient(client=c).fetch_period("7049441311", "all")

        with self.assertRaises(CampError):
            _run(run())

    def test_network_error_raises_camp_error(self):
        def handler(request):
            raise httpx.ConnectError("boom")

        async def run():
            async with _client(handler) as c:
                await WotCampClient(client=c).fetch_period("7049441311", "all")

        with self.assertRaises(CampError):
            _run(run())

    def test_invalid_json_raises_camp_error(self):
        def handler(request):
            return httpx.Response(200, text="<html>not json</html>")

        async def run():
            async with _client(handler) as c:
                await WotCampClient(client=c).fetch_period("7049441311", "all")

        with self.assertRaises(CampError):
            _run(run())


class TestFetchPlayer(unittest.TestCase):
    def test_composes_periods_battles_and_tanks(self):
        seen = {"periods": [], "tanks": []}

        def handler(request):
            path = request.url.path
            if path == "/tank/appuserrank":
                period = request.url.params.get("type")
                seen["periods"].append(period)
                return httpx.Response(200, json=PROFILE[period])
            if path == "/WotArena/getUserBattles":
                return httpx.Response(200, json=load("camp_battles_20.json"))
            if path == "/tank/uservehiclestat":
                tid = request.url.params.get("tankid")
                seen["tanks"].append(tid)
                if tid == "32529":
                    return httpx.Response(200, json=load("camp_tank_day30.json"))
                # 其余车按"近30天没打过"处理
                return httpx.Response(200, json={"errno": 0, "errmsg": "ok",
                                                 "data": {"vBattles": {"list": [{"fights": 0, "WN8": 0}]}}})
            raise AssertionError(f"未预期的请求：{request.url}")

        catalog = {"犀牛": "2977", "e77": "37649", "pz70120": "32529", "vcs6x6ts90": "66625"}

        async def run():
            async with _client(handler) as c:
                return await WotCampClient(client=c).fetch_player(
                    "7049441311", battles=20, tanks_top=5, tanks_scan=12, catalog=catalog)

        player = _run(run())
        self.assertEqual(player.nickname, "loy1234")
        self.assertEqual(set(player.periods), {"all", "day_7", "day_30"})
        self.assertEqual(len(player.battles), 20)
        self.assertEqual(set(seen["periods"]), {"all", "day_7", "day_30"})
        # 只保留有场次的车（本例只有 32529 有数据）
        self.assertEqual([t.tank_id for t in player.tanks_30d], ["32529"])
        self.assertIn("32529", seen["tanks"])

    def test_invalid_wgid_raises(self):
        async def run():
            return await WotCampClient().fetch_player("loy1234")

        with self.assertRaises(CampError):
            _run(run())

    def test_box_names_are_queried_and_sorted_by_battles(self):
        """盒子车名（即使不在最近战斗里）也要被查；结果按近 30 天场次降序。"""
        names = {"1": "Alpha", "2": "boxcar", "3": "Bravo"}
        fights = {"1": 1, "2": 9, "3": 5}

        def handler(request):
            path = request.url.path
            if path == "/tank/appuserrank":
                return httpx.Response(200, json=PROFILE[request.url.params.get("type")])
            if path == "/WotArena/getUserBattles":
                return httpx.Response(200, json=payload_battles(["Alpha", "Bravo"]))
            if path == "/tank/uservehiclestat":
                tid = request.url.params.get("tankid")
                return httpx.Response(200, json={"errno": 0, "errmsg": "ok", "data": {"vBattles": {
                    "list": [{"fights": fights[tid], "WN8": {"1": 900.0, "2": 100.0, "3": 800.0}[tid],
                              "vehicle_name": names[tid], "vlevel": 8, "win_rate": 50.0,
                              "avgdmg": 900}]}}})

        catalog = {"alpha": "1", "boxcar": "2", "bravo": "3"}

        async def run():
            async with _client(handler) as c:
                return await WotCampClient(client=c).fetch_player(
                    "7049441311", tanks_top=3, tanks_scan=3, catalog=catalog,
                    extra_tank_names=["boxcar"])

        player = _run(run())
        # boxcar 不在最近战斗里（只有 Alpha 在），但作为盒子车名被查到了 → 三条都在，按场次降序
        self.assertEqual([t.name for t in player.tanks_30d], ["boxcar", "Bravo", "Alpha"])

    def test_battles_only_mode(self):
        """want_battles/want_tanks=False 时不得发出对应请求（参数给足才测得到标志位）。"""
        def handler(request):
            path = request.url.path
            if path == "/tank/appuserrank":
                return httpx.Response(200, json=PROFILE[request.url.params.get("type")])
            raise AssertionError(f"want_battles=False/want_tanks=False 时不应请求 {request.url}")

        async def run():
            async with _client(handler) as c:
                return await WotCampClient(client=c).fetch_player(
                    "7049441311", battles=20, tanks_top=5, catalog={"犀牛": "2977"},
                    want_battles=False, want_tanks=False)

        player = _run(run())
        self.assertEqual(player.battles, [])
        self.assertEqual(player.tanks_30d, [])
        self.assertEqual(len(player.periods), 3)

    # ── 部分失败容错（复核 B1） ──

    def test_partial_period_failure_keeps_other_periods(self):
        def handler(request):
            path = request.url.path
            if path == "/tank/appuserrank":
                if request.url.params.get("type") == "day_7":
                    return httpx.Response(500, text="boom")
                return httpx.Response(200, json=PROFILE[request.url.params.get("type")])
            if path == "/WotArena/getUserBattles":
                return httpx.Response(200, json=load("camp_battles_20.json"))
            raise AssertionError(f"未预期请求 {request.url}")

        async def run():
            async with _client(handler) as c:
                return await WotCampClient(client=c).fetch_player(
                    "7049441311", battles=20, tanks_top=0)

        player = _run(run())
        self.assertEqual(set(player.periods), {"all", "day_30"})   # day_7 失败被跳过
        self.assertEqual(player.nickname, "loy1234")
        self.assertEqual(len(player.battles), 20)                 # 总览部分失败不影响逐场

    def test_all_periods_failed_raises(self):
        def handler(request):
            if request.url.path == "/tank/appuserrank":
                return httpx.Response(500, text="boom")
            raise AssertionError("三时段全失败时不应继续请求其它接口")

        async def run():
            async with _client(handler) as c:
                await WotCampClient(client=c).fetch_player("7049441311", battles=20)

        with self.assertRaises(CampError):
            _run(run())

    def test_all_periods_not_found_raises_not_found(self):
        def handler(request):
            return httpx.Response(200, json={"errno": 0, "errmsg": "ok", "time": 1,
                                             "data": {"userInfo": {"nick_name": None}}})

        async def run():
            async with _client(handler) as c:
                await WotCampClient(client=c).fetch_player("9999999999", battles=0)

        with self.assertRaises(CampNotFoundError):
            _run(run())

    def test_battles_failure_does_not_kill_periods(self):
        def handler(request):
            path = request.url.path
            if path == "/tank/appuserrank":
                return httpx.Response(200, json=PROFILE[request.url.params.get("type")])
            if path == "/WotArena/getUserBattles":
                return httpx.Response(500, text="boom")
            raise AssertionError(f"未预期请求 {request.url}")

        async def run():
            async with _client(handler) as c:
                return await WotCampClient(client=c).fetch_player(
                    "7049441311", battles=20, tanks_top=5, catalog={"犀牛": "2977"})

        player = _run(run())
        self.assertEqual(len(player.periods), 3)
        self.assertEqual(player.battles, [])
        self.assertEqual(player.tanks_30d, [])

    def test_tanks_sorted_by_battles_and_truncated(self):
        """近 30 天常用坦克：按场次降序（同场次看 WN8）+ 只保留前 tanks_top 辆。"""
        def handler(request):
            path = request.url.path
            if path == "/tank/appuserrank":
                return httpx.Response(200, json=PROFILE[request.url.params.get("type")])
            if path == "/WotArena/getUserBattles":
                return httpx.Response(200, json=payload_battles(["A", "B", "C", "D"]))
            if path == "/tank/uservehiclestat":
                tid = request.url.params.get("tankid")
                wn8 = {"1": 100.0, "2": 900.0, "3": 500.0, "4": 0.0}[tid]
                fights = {"1": 5, "2": 1, "3": 5, "4": 0}[tid]
                return httpx.Response(200, json={"errno": 0, "errmsg": "ok", "data": {"vBattles": {
                    "list": [{"fights": fights, "WN8": wn8, "vehicle_name": f"T{tid}",
                              "vlevel": 10, "win_rate": 50.0, "avgdmg": 1000}]}}})

        catalog = {"a": "1", "b": "2", "c": "3", "d": "4"}

        async def run():
            async with _client(handler) as c:
                return await WotCampClient(client=c).fetch_player(
                    "7049441311", tanks_top=2, tanks_scan=4, catalog=catalog)

        player = _run(run())
        # 场次：T1=5, T3=5, T2=1 → 先按场次降序，5 场的两辆按 WN8 降序（T3 500 > T1 100）；T4 零场次被过滤
        self.assertEqual([t.tank_id for t in player.tanks_30d], ["3", "1"])

    def test_all_tanks_shown_when_top_is_zero(self):
        """tanks_top=0 → 展示近 30 天全部有战绩的车（用户要求）。"""
        def handler(request):
            path = request.url.path
            if path == "/tank/appuserrank":
                return httpx.Response(200, json=PROFILE[request.url.params.get("type")])
            if path == "/WotArena/getUserBattles":
                return httpx.Response(200, json=payload_battles(["A", "B", "C", "D"]))
            if path == "/tank/uservehiclestat":
                tid = request.url.params.get("tankid")
                return httpx.Response(200, json={"errno": 0, "errmsg": "ok", "data": {"vBattles": {
                    "list": [{"fights": int(tid), "WN8": 1000.0, "vehicle_name": f"T{tid}",
                              "vlevel": 10, "win_rate": 50.0, "avgdmg": 1000}]}}})

        async def run():
            async with _client(handler) as c:
                return await WotCampClient(client=c).fetch_player(
                    "7049441311", tanks_top=0, tanks_scan=4,
                    catalog={"a": "1", "b": "2", "c": "3", "d": "4"})

        player = _run(run())
        self.assertEqual([t.tank_id for t in player.tanks_30d], ["4", "3", "2", "1"])

    def test_tanks_scan_limit(self):
        """tanks_scan 限制实际查询的车辆数。"""
        asked = []

        def handler(request):
            path = request.url.path
            if path == "/tank/appuserrank":
                return httpx.Response(200, json=PROFILE[request.url.params.get("type")])
            if path == "/WotArena/getUserBattles":
                return httpx.Response(200, json=payload_battles(["A", "B", "C", "D"]))
            if path == "/tank/uservehiclestat":
                asked.append(request.url.params.get("tankid"))
                return httpx.Response(200, json={"errno": 0, "errmsg": "ok",
                                                 "data": {"vBattles": {"list": []}}})
            raise AssertionError(f"未预期请求 {request.url}")

        async def run():
            async with _client(handler) as c:
                return await WotCampClient(client=c).fetch_player(
                    "7049441311", battles=10, tanks_top=5, tanks_scan=2,
                    catalog={"a": "1", "b": "2", "c": "3", "d": "4"})

        player = _run(run())
        self.assertEqual(len(asked), 2)
        self.assertEqual(player.tanks_30d, [])


class TestHeaders(unittest.TestCase):
    def test_headers_sent(self):
        seen = {}

        def handler(request):
            seen.update(dict(request.headers))
            return httpx.Response(200, json=PROFILE["all"])

        async def run():
            async with _client(handler) as c:
                await WotCampClient(client=c).fetch_period("7049441311", "all")

        _run(run())
        self.assertIn("camp.wot.360.cn", seen.get("referer", ""))
        self.assertNotIn("Mozilla", seen.get("user-agent", ""))   # 刻意不使用浏览器 UA


if __name__ == "__main__":
    unittest.main()
