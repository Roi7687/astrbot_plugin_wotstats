# -*- coding: utf-8 -*-
"""官方玩家搜索（wotgame.cn）：「昵称 → wgid」的**主解析通道**。

为什么需要它：偶游盒子（wotbox.ouj.com）对单 IP 有严格请求配额，密集查询会长时间 403，
而 wgid 恰恰是查询官方《坦克营地》数据的必需参数。2026-10-16 实测发现官方门户提供免登录搜索：

    GET https://wotgame.cn/zh-cn/community/accounts/search/?name=<昵称>
    → {"response": [
         {"account_id": "7049441311", "account_name": "loy1234",
          "account_battles": 30568, "account_wins": 56.07, "account_exp": 26919639,
          "account_profile": "/zh-cn/community/accounts/7049441311-loy1234/",
          "clan_tag": ..., "clan_url": ...}, ...]}

实测结论：
- `account_id` **就是**坦克营地接口的 `accountId`（wgid）——已用 loy1234 双向交叉验证；
- 免登录/免签名；15 次连发全部 200（1.4s），本机未观察到限流；
- **大小写不敏感**（LOY1234 → loy1234），比重名后缀敏感的盒子页面更友好；
- 返回**模糊匹配**（最多 25 条），必须自行挑精确项；
- 服务端要求昵称 **至少 4 个字符**（不足 → HTTP 409），短昵称由调用方回落到盒子页面。

本模块只做"搜索 + 结构化"，HTTP 与解析分离以便单测（parse/pick 为纯函数）。
"""
import logging
from dataclasses import dataclass

import httpx

from .config import (
    USER_AGENT,
    WG_PORTAL_REFERER,
    WG_SEARCH_MIN_LEN,
    WG_SEARCH_TIMEOUT,
    WG_SEARCH_URL,
    WgSearchError,
    WgTooShortError,
)

logger = logging.getLogger("astrbot")

__all__ = [
    "WotGameAccount",
    "parse_search_payload",
    "pick_account",
    "WotGameSearchClient",
    "WG_SEARCH_MIN_LEN",
]


@dataclass
class WotGameAccount:
    """官方搜索返回的一条账号信息。"""

    account_id: str = ""
    name: str = ""
    battles: int = 0
    wins_rate: float = 0.0
    exp: int = 0
    clan_tag: str = ""
    profile: str = ""

    def to_dict(self) -> dict:
        return {"account_id": self.account_id, "name": self.name, "battles": self.battles,
                "wins_rate": self.wins_rate, "exp": self.exp, "clan_tag": self.clan_tag,
                "profile": self.profile}


def _int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(value) -> str:
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value).strip()


def parse_search_payload(payload) -> list:
    """官方搜索响应 → list[WotGameAccount]（纯函数，容忍字段缺失/类型异常）。"""
    if not isinstance(payload, dict):
        return []
    rows = payload.get("response")
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        account_id = _text(row.get("account_id"))
        if not account_id:
            continue
        out.append(WotGameAccount(
            account_id=account_id,
            name=_text(row.get("account_name")),
            battles=_int(row.get("account_battles")),
            wins_rate=_float(row.get("account_wins")),
            exp=_int(row.get("account_exp")),
            clan_tag=_text(row.get("clan_tag")),
            profile=_text(row.get("account_profile")),
        ))
    return out


def pick_account(accounts: list, nickname: str):
    """从模糊匹配里挑出目标账号：优先大小写不敏感的**完全同名**；否则仅在唯一结果时采用。

    返回 (账号 or None, 是否唯一命中)。无法确定时返回 (None, False)，由上层提示"多个相似玩家"。
    """
    if not accounts:
        return None, False
    target = (nickname or "").strip().casefold()
    for acc in accounts:
        if acc.name.casefold() == target:
            return acc, True
    if len(accounts) == 1:
        return accounts[0], True
    return None, False


class WotGameSearchClient:
    """官方玩家搜索客户端（async httpx；client 可注入用于单测）。"""

    def __init__(self, client: httpx.AsyncClient | None = None, timeout: float = WG_SEARCH_TIMEOUT):
        self._client = client
        self._timeout = timeout

    async def search(self, nickname: str) -> list:
        """按昵称搜索，返回账号列表（可能为空）。

        - 昵称不足 WG_SEARCH_MIN_LEN 个字符 → WgTooShortError（调用方走回落通道）
        - 网络/非 200/非法 JSON → WgSearchError
        """
        name = (nickname or "").strip()
        if len(name) < WG_SEARCH_MIN_LEN:
            raise WgTooShortError(f"官方搜索要求昵称至少 {WG_SEARCH_MIN_LEN} 个字符：{name!r}")
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": WG_PORTAL_REFERER,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
        params = {"name": name}
        try:
            if self._client is not None:
                resp = await self._client.get(WG_SEARCH_URL, params=params, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as c:
                    resp = await c.get(WG_SEARCH_URL, params=params, headers=headers)
        except (httpx.TransportError, httpx.TimeoutException) as e:
            raise WgSearchError(f"官方搜索网络失败: {e}") from e

        if resp.status_code == 409:
            # 服务端校验失败（实测为"至少 4 字符"）
            raise WgTooShortError(f"官方搜索拒绝该昵称（HTTP 409）: {name!r}")
        if resp.status_code != 200:
            raise WgSearchError(f"官方搜索返回 HTTP {resp.status_code}")
        try:
            return parse_search_payload(resp.json())
        except ValueError as e:
            raise WgSearchError(f"官方搜索返回非法 JSON: {e}") from e

    async def resolve(self, nickname: str):
        """昵称 → (WotGameAccount | None, 状态)。

        状态：ok（命中唯一精确项）/ ambiguous（多个相似）/ notfound（无结果）/ error（失败）
        """
        try:
            accounts = await self.search(nickname)
        except WgTooShortError:
            return None, "too_short"
        except WgSearchError as e:
            logger.warning(f"[WotStats] 官方搜索失败 nickname={nickname!r}: {e}")
            return None, "error"
        acc, unique = pick_account(accounts, nickname)
        if acc is not None:
            return acc, "ok"
        return (None, "ambiguous" if accounts else "notfound")
