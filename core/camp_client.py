# -*- coding: utf-8 -*-
"""坦克营地取数客户端：异步 httpx，只用免签接口，运行期零落盘。

2026-10-16 实测要点（详见 research/WOTCAM_INTEGRATION_PLAN.md）：
- 全部免签接口用普通 httpx 即可访问（**不需要 curl_cffi**），任意 UA 均返回 errno=0；
  但仍固定使用非浏览器标识串，保持行为可预期。
- 无需登录 / Cookie；单接口 0.16~0.46s，60 并发无限流。
- 参数名坑：逐场战斗接口用 **uid**（写成 accountId 会得到 errno=2003 pkey empty）。

设计：HTTP 与解析分离——本模块只负责"取 JSON + 组织请求"，字段处理全在 core/camp_parser.py。
"""
import asyncio
import logging
import time

import httpx

from .camp_model import CampPlayer, CampTank
from .camp_parser import (
    extract_user_info,
    parse_battles,
    parse_period,
    parse_tank,
    pick_tank_ids,
)
from .commands import is_wgid
from .config import (
    CAMP_API_BASE,
    CAMP_BATTLE_BATCH,
    CAMP_BATTLE_PAGE_SIZE,
    CAMP_PERIODS,
    CAMP_REFERER,
    CAMP_RETRY,
    CAMP_SCAN_DAYS,
    CAMP_SCAN_MAX_BATTLES,
    CAMP_TANKS_SCAN,
    CAMP_TANKS_TOP,
    CAMP_TIMEOUT,
    USER_AGENT,
    CampError,
    CampNotFoundError,
)

logger = logging.getLogger("astrbot")

__all__ = ["WotCampClient", "CampError", "CampNotFoundError"]

_CAMP_HEADERS = {
    "Referer": CAMP_REFERER,
    "Origin": CAMP_REFERER.rstrip("/"),
    "Accept": "application/json, text/plain, */*",
    "User-Agent": USER_AGENT,
}


class WotCampClient:
    """tbox.wot.360.cn 免签接口客户端。

    client 参数仅用于测试注入（httpx.AsyncClient + MockTransport）；
    正常运行时不传，每次请求使用独立 AsyncClient。
    """

    def __init__(self, client: httpx.AsyncClient | None = None, timeout: float = CAMP_TIMEOUT):
        self._client = client
        self._timeout = timeout

    # ── 底层 ──

    async def _get_json(self, path: str, params: dict, client: httpx.AsyncClient | None = None) -> dict:
        url = CAMP_API_BASE + path
        last: Exception | None = None
        for attempt in range(CAMP_RETRY + 1):
            try:
                if client is not None:
                    resp = await client.get(url, params=params, headers=_CAMP_HEADERS)
                elif self._client is not None:
                    resp = await self._client.get(url, params=params, headers=_CAMP_HEADERS)
                else:
                    async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as c:
                        resp = await c.get(url, params=params, headers=_CAMP_HEADERS)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                last = e
                # 5xx 与 429（限流）可重试；其余 4xx 直接失败
                if (500 <= e.response.status_code < 600 or e.response.status_code == 429) \
                        and attempt < CAMP_RETRY:
                    await asyncio.sleep(0.3 * (attempt + 1))
                    continue
                raise CampError(f"坦克营地接口 {path} 返回 HTTP {e.response.status_code}") from e
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last = e
                if attempt < CAMP_RETRY:
                    await asyncio.sleep(0.3 * (attempt + 1))
                    continue
                raise CampError(f"坦克营地接口 {path} 网络失败（已重试 {CAMP_RETRY} 次）: {e}") from e
            except ValueError as e:      # resp.json() 解析失败
                raise CampError(f"坦克营地接口 {path} 返回非法 JSON: {e}") from e
        raise CampError(f"坦克营地接口 {path} 请求失败: {last}")

    # ── 业务 ──

    async def fetch_period(self, wgid: str, period: str, client: httpx.AsyncClient | None = None):
        """返回 (CampPeriod, user_info)。user_info 取任一时段的结果即可（三时段一致）。"""
        payload = await self._get_json("/tank/appuserrank",
                                       {"type": period, "accountId": wgid}, client)
        info = extract_user_info(payload)          # nick_name 为空 → CampNotFoundError
        return parse_period(payload, period), info

    async def fetch_battles(self, wgid: str, want: int = 20, page: int = 1,
                            client: httpx.AsyncClient | None = None) -> list:
        """最近逐场战斗（单页上限 200）。page 从 1 开始。"""
        size = max(1, min(CAMP_BATTLE_PAGE_SIZE, want))
        payload = await self._get_json("/WotArena/getUserBattles", {
            "uid": wgid, "guiType": "", "tankType": "", "range": "", "ret": "",
            "page": max(1, page), "size": size,
        }, client)
        return parse_battles(payload, want)

    async def scan_window_battles(self, wgid: str, days: int = CAMP_SCAN_DAYS,
                                  max_battles: int = CAMP_SCAN_MAX_BATTLES,
                                  client: httpx.AsyncClient | None = None) -> list:
        """翻页取到时间窗边界为止，返回窗内的逐场战斗（最新在前）。

        营地接口**没有**按时间过滤的参数（实测 range 传 day_30/30/… 都无效），
        因此只能按 arenaCreateTime 客户端过滤：一直翻页直到最旧一场早于窗口起点。
        用途：枚举「近 N 天打过哪些车」——官方没有"玩家单车列表"接口，
        全目录扫描（998 辆）在聊天场景不可用，这条路实测 2~3 页即可覆盖活跃玩家的 30 天。

        性能：单页 100 条 ≈0.8s，因此**一次并发取 CAMP_BATTLE_BATCH 页**再判定边界
        （顺序翻页会让 30 天的活跃玩家多花 2s 以上）。多取的页面只是多几个请求，营地侧不限流。
        """
        cutoff = time.time() - days * 86400
        out: list = []
        page = 1
        max_page = max(1, (max_battles + CAMP_BATTLE_PAGE_SIZE - 1) // CAMP_BATTLE_PAGE_SIZE)
        while page <= max_page and len(out) < max_battles:
            pages = list(range(page, min(page + CAMP_BATTLE_BATCH, max_page + 1)))
            batch = await asyncio.gather(
                *(self.fetch_battles(wgid, CAMP_BATTLE_PAGE_SIZE, p, client) for p in pages),
                return_exceptions=True)
            reached_end = False
            for rows in batch:
                if isinstance(rows, Exception) or not rows:
                    reached_end = True
                    break
                out.extend(b for b in rows if b.ts >= cutoff)
                if len(rows) < CAMP_BATTLE_PAGE_SIZE or rows[-1].ts < cutoff:
                    reached_end = True        # 已翻过窗口边界 / 没有更多数据
                    break
            if reached_end:
                break
            page += len(pages)
        out.sort(key=lambda b: b.ts, reverse=True)
        return out[:max_battles]

    async def fetch_tank_30d(self, wgid: str, tank_id: str,
                             client: httpx.AsyncClient | None = None):
        """单车近 30 天数据；没打过/未拥有 → None。"""
        payload = await self._get_json("/tank/uservehiclestat",
                                       {"tankid": tank_id, "accountId": wgid, "type": "day_30"},
                                       client)
        return parse_tank(payload, tank_id)

    async def fetch_player(self, wgid: str, *, tanks_top: int = CAMP_TANKS_TOP,
                           tanks_scan: int = CAMP_TANKS_SCAN, catalog: dict | None = None,
                           extra_tank_names=None, scan_days: int = CAMP_SCAN_DAYS,
                           battles: int = 0, want_battles: bool | None = None,
                           want_tanks: bool = True,
                           ) -> CampPlayer:
        """一次完整取数：三时段总览（并发） + 近 N 天常用坦克（并发）。

        「常用坦克」的口径（用户要求）：
          1. 时间窗内（默认 30 天）打过的车 —— 由逐场战斗翻页枚举车名；
          2. 加上 extra_tank_names（盒子「常用坦克」的车名），保证两边能按车名对齐；
          3. 逐辆查 day_30 单车数据，只保留 fights>0（确实打过）的车，按场次降序；
          4. tanks_top=0 → 全部展示。

        battles：在 player.battles 里保留多少条逐场记录（0=不留）；None 的 want_battles 表示
        "battles>0 时才留"。
        实测耗时 ≈1.5~3s（2~3 页战斗 + 20~40 次单车请求，营地侧无限流）。
        部分失败不算失败：某个时段/某辆车拿不到就跳过，三时段全失败才抛错。
        """
        if not is_wgid(wgid):
            raise CampError(f"wgid 非法: {wgid!r}")
        if want_battles is None:
            want_battles = battles > 0

        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as shared:
            client = self._client or shared      # 复用连接，避免每次请求重新握手

            async def _periods():
                res = await asyncio.gather(
                    *(self.fetch_period(wgid, p, client) for p in CAMP_PERIODS),
                    return_exceptions=True)
                return res

            async def _window():
                if not (want_tanks or want_battles):
                    return []
                try:
                    return await self.scan_window_battles(wgid, scan_days, client=client)
                except CampError as e:
                    logger.warning(f"[WotStats] 营地逐场扫描失败 wgid={wgid}: {e}")
                    return []

            # 三时段与"时间窗内的车"互相独立 → 并发；否则 30 天的活跃玩家要多等 2s 以上
            results, window = await asyncio.gather(_periods(), _window())

            periods, info, errors = {}, None, []
            for period, res in zip(CAMP_PERIODS, results):
                if isinstance(res, Exception):
                    errors.append(res)
                    continue
                per, user_info = res
                periods[per.key] = per
                if info is None:
                    info = user_info
            if not periods:
                # 全部失败：优先暴露"查无此人"，否则暴露接口错误
                not_found = next((e for e in errors if isinstance(e, CampNotFoundError)), None)
                raise not_found or (errors[0] if errors else CampError("三个时段均无数据"))
            if info is None:                       # 理论不可达（periods 非空则 info 必有）
                info = {"nickname": "", "face_url": "", "last_battle_time": 0, "server_time": 0}

            player = CampPlayer(
                wgid=str(wgid),
                nickname=info["nickname"],
                face_url=info["face_url"],
                last_battle_time=info["last_battle_time"],
                server_time=info["server_time"],
                periods=periods,
            )
            if errors:
                logger.warning(f"[WotStats] 营地部分时段取数失败 wgid={wgid}: "
                               f"{[type(e).__name__ + ': ' + str(e) for e in errors]}")

            window = window or []
            if want_battles and battles > 0:
                player.battles = window[:battles]

            if want_tanks and tanks_scan > 0 and catalog and (window or extra_tank_names):
                ids = pick_tank_ids(window, catalog, limit=tanks_scan,
                                    extra_names=extra_tank_names)
                if ids:
                    rows = await asyncio.gather(
                        *(self.fetch_tank_30d(wgid, t, client) for t in ids),
                        return_exceptions=True)
                    tanks = [r for r in rows if isinstance(r, CampTank)]
                    # 「常用坦克」= 近 30 天打得最多的车（与截图里的排序一致）；同场次按 WN8 降序
                    tanks.sort(key=lambda t: (-t.fights, -t.wn8))
                    player.tanks_30d = tanks[:tanks_top] if tanks_top > 0 else tanks

        return player
