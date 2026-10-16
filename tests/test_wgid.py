# -*- coding: utf-8 -*-
"""官方玩家搜索（wotgame.cn）单元测试：纯函数 + MockTransport，不发真实网络。

接口实测见 research/WOTCAM_INTEGRATION_PLAN.md §9；
真实响应样例：{"response": [{"account_id": "7049441311", "account_name": "loy1234", ...}]}
"""
import asyncio
import os
import sys
import unittest

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import WgSearchError, WgTooShortError  # noqa: E402
from core.wgid import (  # noqa: E402
    WotGameAccount,
    WotGameSearchClient,
    WG_SEARCH_MIN_LEN,
    parse_search_payload,
    pick_account,
)

REAL = {"response": [
    {"account_id": "7049441311", "account_name": "loy1234",
     "account_profile": "/zh-cn/community/accounts/7049441311-loy1234/",
     "account_battles": 30568, "account_wins": 56.07170897670767,
     "account_exp": 26919639, "clan_tag": "TEST", "clan_url": "https://example.invalid/"},
    {"account_id": "7050000001", "account_name": "loy12345",
     "account_battles": 100, "account_wins": 50.0, "account_exp": 1000},
]}


def _run(coro):
    return asyncio.run(coro)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler),
                             base_url="https://wotgame.cn")


class TestParse(unittest.TestCase):
    def test_real_shape(self):
        rows = parse_search_payload(REAL)
        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertIsInstance(first, WotGameAccount)
        self.assertEqual(first.account_id, "7049441311")
        self.assertEqual(first.name, "loy1234")
        self.assertEqual(first.battles, 30568)
        self.assertAlmostEqual(first.wins_rate, 56.07, places=1)
        self.assertEqual(first.exp, 26919639)
        self.assertEqual(first.clan_tag, "TEST")

    def test_empty_and_hostile(self):
        self.assertEqual(parse_search_payload({"response": []}), [])
        self.assertEqual(parse_search_payload({"response": None}), [])
        self.assertEqual(parse_search_payload({}), [])
        self.assertEqual(parse_search_payload(["not", "dict"]), [])
        # 缺 account_id 的行直接丢弃；数值字段异常时回落默认值
        rows = parse_search_payload({"response": [
            {"account_name": "no-id"},
            "junk",
            {"account_id": 1234567890, "account_name": None, "account_battles": "abc",
             "account_wins": None},
        ]})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].account_id, "1234567890")
        self.assertEqual(rows[0].name, "")
        self.assertEqual(rows[0].battles, 0)
        self.assertEqual(rows[0].wins_rate, 0.0)


class TestPick(unittest.TestCase):
    def setUp(self):
        self.rows = parse_search_payload(REAL)

    def test_exact_case_insensitive(self):
        acc, unique = pick_account(self.rows, "loy1234")
        self.assertTrue(unique)
        self.assertEqual(acc.account_id, "7049441311")
        acc, _ = pick_account(self.rows, "LOY1234")
        self.assertEqual(acc.account_id, "7049441311")

    def test_ambiguous_when_no_exact_match(self):
        acc, unique = pick_account(self.rows, "loy")
        self.assertIsNone(acc)
        self.assertFalse(unique)

    def test_single_result_used_even_if_not_exact(self):
        rows = parse_search_payload({"response": [{"account_id": "1", "account_name": "someone"}]})
        acc, unique = pick_account(rows, "someon")
        self.assertTrue(unique)
        self.assertEqual(acc.account_id, "1")

    def test_empty(self):
        self.assertEqual(pick_account([], "x"), (None, False))


class TestSearchClient(unittest.TestCase):
    def test_search_ok_and_param_name(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json=REAL)

        async def run():
            async with _client(handler) as c:
                return await WotGameSearchClient(client=c).resolve("loy1234")

        acc, state = _run(run())
        self.assertEqual(state, "ok")
        self.assertEqual(acc.account_id, "7049441311")
        self.assertEqual(seen["params"].get("name"), "loy1234")
        self.assertIn("/zh-cn/community/accounts/search/", seen["url"])

    def test_too_short_is_rejected_locally(self):
        def handler(request):
            raise AssertionError("昵称过短时不应发请求")

        async def run():
            async with _client(handler) as c:
                return await WotGameSearchClient(client=c).resolve("loy")

        acc, state = _run(run())
        self.assertIsNone(acc)
        self.assertEqual(state, "too_short")
        self.assertEqual(WG_SEARCH_MIN_LEN, 4)

    def test_http_409_maps_to_too_short(self):
        def handler(request):
            return httpx.Response(409, json={"name": ["确保该变量至少包含 4 字符(目前字符数 3)。"]})

        async def run():
            async with _client(handler) as c:
                await WotGameSearchClient(client=c).search("abcd")

        with self.assertRaises(WgTooShortError):
            _run(run())

    def test_notfound(self):
        def handler(request):
            return httpx.Response(200, json={"response": []})

        async def run():
            async with _client(handler) as c:
                return await WotGameSearchClient(client=c).resolve("nobody123")

        self.assertEqual(_run(run()), (None, "notfound"))

    def test_ambiguous(self):
        def handler(request):
            return httpx.Response(200, json=REAL)

        async def run():
            async with _client(handler) as c:
                return await WotGameSearchClient(client=c).resolve("loy123")

        acc, state = _run(run())
        self.assertIsNone(acc)
        self.assertEqual(state, "ambiguous")

    def test_http_error(self):
        def handler(request):
            return httpx.Response(503, text="busy")

        async def run():
            async with _client(handler) as c:
                return await WotGameSearchClient(client=c).resolve("loy1234")

        self.assertEqual(_run(run()), (None, "error"))

    def test_network_error(self):
        def handler(request):
            raise httpx.ConnectError("boom")

        async def run():
            async with _client(handler) as c:
                await WotGameSearchClient(client=c).search("loy1234")

        with self.assertRaises(WgSearchError):
            _run(run())

    def test_invalid_json(self):
        def handler(request):
            return httpx.Response(200, text="<html>nope</html>")

        async def run():
            async with _client(handler) as c:
                await WotGameSearchClient(client=c).search("loy1234")

        with self.assertRaises(WgSearchError):
            _run(run())

    def test_headers_not_browser_ua(self):
        seen = {}

        def handler(request):
            seen.update(dict(request.headers))
            return httpx.Response(200, json=REAL)

        async def run():
            async with _client(handler) as c:
                await WotGameSearchClient(client=c).search("loy1234")

        _run(run())
        self.assertNotIn("Mozilla", seen.get("user-agent", ""))
        self.assertIn("wotgame.cn", seen.get("referer", ""))


if __name__ == "__main__":
    unittest.main()
