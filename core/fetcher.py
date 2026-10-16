# -*- coding: utf-8 -*-
"""抓取层：对 wotbox.ouj.com 战绩查询后端发起纯 HTTP GET。

设计要点：
- 不登录、不带 Cookie、不需要浏览器——直接拿服务端渲染 HTML（2026-09 实测可行）。
- 幂等 GET，网络异常/5xx 自动重试 HTTP_RETRY 次。
- **403 视为"站点限流"**：该站对单 IP 有严格请求配额（2026-10-16 实测，详见
  research/WOTCAM_INTEGRATION_PLAN.md §2.2），抛 RateLimitedError 以便上层给出
  "稍后重试"而不是"未知错误"的提示；不重试（撞限额后立刻重试只会加深惩罚）。
- 本模块不落盘任何文件（无缓存）；解析交给 core/parser.py。
"""
import logging
import urllib.parse

import httpx

from .config import (
    ACT_BATTLELOG,
    HTTP_RETRY,
    HTTP_TIMEOUT,
    QUERY_ENDPOINT,
    USER_AGENT,
    RateLimitedError,
    WotQueryError,
)

logger = logging.getLogger("astrbot")


def build_query_url(nickname: str, action: str = "default/index", page: int | None = None) -> str:
    """构造查询 URL：r=<action>&pn=<昵称>（昵称 URL 编码，大小写敏感）。

    2026-09 实测：表单提交即 GET /wotbox/index.php?r=default/index&pn=<昵称>，
    原区服下拉 #zone 已被站点注释（仅国服），无需 zone 参数。
    """
    params = {"r": action, "pn": nickname}
    if action == ACT_BATTLELOG:
        params["p"] = str(page if page and page > 0 else 1)
    return QUERY_ENDPOINT + "?" + urllib.parse.urlencode(params)


class WotBoxFetcher:
    """wotbox.ouj.com 抓取器。

    client 参数仅用于测试注入（httpx.AsyncClient + MockTransport）；
    正常运行时不传，每次请求使用独立 AsyncClient。
    """

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client

    async def fetch(self, nickname: str, action: str = "default/index", page: int | None = None) -> str:
        """抓取指定页面的 HTML 文本。失败抛 WotQueryError。"""
        url = build_query_url(nickname, action, page)
        last_error: Exception | None = None
        for attempt in range(HTTP_RETRY + 1):
            try:
                if self._client is not None:
                    return await self._do_get(self._client, url)
                async with httpx.AsyncClient(
                    timeout=HTTP_TIMEOUT,
                    follow_redirects=True,
                    headers={"User-Agent": USER_AGENT},
                ) as client:
                    return await self._do_get(client, url)
            except httpx.HTTPStatusError as e:
                # 服务端对查询一律返回 200；403 是该站的"限流/风控"信号（实测会持续数十秒~数分钟）
                if e.response.status_code == 403:
                    raise RateLimitedError(
                        f"站点限流（HTTP 403，{len(e.response.content)} 字节响应）"
                    ) from e
                if 500 <= e.response.status_code < 600 and attempt < HTTP_RETRY:
                    last_error = e
                    continue
                raise WotQueryError(f"站点返回异常状态码 {e.response.status_code}") from e
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last_error = e
                if attempt < HTTP_RETRY:
                    continue
                raise WotQueryError(f"网络请求失败（已重试 {HTTP_RETRY} 次）: {e}") from e
        raise WotQueryError(f"网络请求失败: {last_error}")

    @staticmethod
    async def _do_get(client: httpx.AsyncClient, url: str) -> str:
        resp = await client.get(url)
        resp.raise_for_status()
        # 页面 meta 声明 charset=UTF-8；若响应头未带 charset，httpx 默认按 utf-8 解码
        text = resp.content.decode("utf-8", errors="replace")
        if "\ufffd" in text:
            logger.warning(f"[WotStats] 页面疑似非 UTF-8 编码: {url}")
        return text
