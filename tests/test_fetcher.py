# -*- coding: utf-8 -*-
"""抓取层单元测试：httpx.MockTransport 注入，不发真实网络请求。"""
import asyncio
import os
import sys
import unittest

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import RateLimitedError, WotQueryError
from core.fetcher import WotBoxFetcher, build_query_url

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def _run(coro):
    return asyncio.run(coro)


def _client(handler):
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://wotbox.ouj.com",
        follow_redirects=True,
    )


class TestBuildUrl(unittest.TestCase):
    def test_index(self):
        self.assertEqual(
            build_query_url("loy1234"),
            "https://wotbox.ouj.com/wotbox/index.php?r=default%2Findex&pn=loy1234",
        )

    def test_cjk_encoded(self):
        url = build_query_url("庇护者")
        self.assertIn("pn=%E5%BA%87%E6%8A%A4%E8%80%85", url)

    def test_battlelog_page(self):
        url = build_query_url("loy1234", "default/battlelog", page=3)
        self.assertIn("r=default%2Fbattlelog", url)
        self.assertIn("p=3", url)


class TestFetch(unittest.TestCase):
    def test_fetch_ok(self):
        called = {}

        def handler(request):
            called["url"] = str(request.url)
            return httpx.Response(
                200, content=load("zhanji_index_raw.html"),
                headers={"content-type": "text/html; charset=utf-8"},
            )

        async def run():
            async with _client(handler) as client:
                fetcher = WotBoxFetcher(client=client)
                return await fetcher.fetch("loy1234")

        html = _run(run())
        self.assertIn("loy1234", html)
        self.assertIn("战斗力", html)
        self.assertIn("pn=loy1234", called["url"])

    def test_retry_then_ok(self):
        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            if state["n"] <= 2:
                return httpx.Response(503, text="busy")
            return httpx.Response(200, content=load("zhanji_index_raw.html"))

        async def run():
            async with _client(handler) as client:
                fetcher = WotBoxFetcher(client=client)
                return await fetcher.fetch("loy1234")

        html = _run(run())
        self.assertIn("战斗力", html)
        self.assertEqual(state["n"], 3)

    def test_always_503_raises(self):
        def handler(request):
            return httpx.Response(503, text="busy")

        async def run():
            async with _client(handler) as client:
                fetcher = WotBoxFetcher(client=client)
                await fetcher.fetch("loy1234")

        with self.assertRaises(WotQueryError):
            _run(run())

    def test_network_error_raises(self):
        def handler(request):
            raise httpx.ConnectError("boom")

        async def run():
            async with _client(handler) as client:
                fetcher = WotBoxFetcher(client=client)
                await fetcher.fetch("loy1234")

        with self.assertRaises(WotQueryError):
            _run(run())

    def test_403_is_rate_limited_and_not_retried(self):
        """403 是该站的限流信号：归类为 RateLimitedError，且不重试（重试只会加深惩罚）。"""
        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            return httpx.Response(403, text="Forbidden")

        async def run():
            async with _client(handler) as client:
                fetcher = WotBoxFetcher(client=client)
                await fetcher.fetch("loy1234")

        with self.assertRaises(RateLimitedError):
            _run(run())
        self.assertEqual(state["n"], 1)
        # RateLimitedError 是 WotQueryError 的子类，上层可用一个 except 兜住
        self.assertTrue(issubclass(RateLimitedError, WotQueryError))

    def test_user_agent_is_not_browser_like(self):
        """实测：该站会 403 掉浏览器 UA，因此刻意使用非浏览器标识串。"""
        from core.config import USER_AGENT
        self.assertNotIn("Mozilla", USER_AGENT)


if __name__ == "__main__":
    unittest.main()
