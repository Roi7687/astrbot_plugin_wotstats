# -*- coding: utf-8 -*-
"""astrbot_plugin_wotstats 主入口。

指令：
- /wot <昵称>             战绩摘要（偶游盒子数据 + 官方坦克营地：三时段 WN8 + 近30天全部常用坦克）
- /wot 总 <昵称>          总战绩摘要（入伍时间 / 全时段胜率 / 总体与场均 / 最近常用坦克）
- /wot help               用法帮助

设计约定：
- 两条独立取数链：偶游盒子（core/fetcher.py + core/parser.py，HTML）与
  官方坦克营地（core/camp_client.py + core/camp_parser.py，JSON）；任一侧失败不拖垮另一侧。
- wgid 解析：官方玩家搜索（core/wgid.py，主通道）→ 盒子个人战绩页 input#p_id（回落），
  并缓存在进程内（不落盘），让盒子被限流时营地数据仍可用。
- 回复格式：QQ 官方平台（qq_official / qq_official_webhook）发送原生 Markdown 消息
  （官方 Markdown 语法不含表格 → 用加粗+列表排版，见 core/formatter.py 头部说明）；
  其余平台自动回退纯文本。REPLY_STYLE 可强制 table/qq_md/plain（core/config.py）。
- 运行时零落盘：不缓存、不写任何数据文件（仅内存 TTL 缓存，默认不缓存查询数据）。
"""
import logging

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.core.star.filter.command import GreedyStr

from .core.cache import TTLCache
from .core.camp_client import WotCampClient
from .core.commands import is_wgid, parse_target
from .core.config import (
    ACT_INDEX,
    ACT_TOTAL,
    CAMP_CACHE_TTL,
    CAMP_ENABLED,
    CAMP_TANKS_SCAN,
    CAMP_TANKS_TOP,
    QQ_OFFICIAL_PLATFORM_NAMES,
    REPLY_STYLE,
    WGID_CACHE_TTL,
    CampError,
    CampNotFoundError,
    ParseError,
    PlayerNotFoundError,
    RateLimitedError,
    WotQueryError,
    is_valid_nickname,
)
from .core.fetcher import WotBoxFetcher
from .core.formatter import (
    format_camp_block,
    format_camp_brief,
    format_index_reply,
    format_total_reply,
    player_not_found_text,
    rate_limited_brief,
    rate_limited_text,
    usage_text,
)
from .core.parser import parse_page
from .core.tanks import load_catalog
from .core.wgid import WotGameSearchClient

logger = logging.getLogger("astrbot")

def _safe_format(fn, *args, **kwargs) -> str:
    """调用排版函数；排版异常不能逃出指令处理器（否则用户一条回复都收不到）。

    排版是纯函数，正常情况下不会失败；这里兜住的是极端数据（如 JSON 里的 inf/nan
    或接口返回了意料之外的类型）导致的渲染异常。
    """
    try:
        return fn(*args, **kwargs)
    except Exception:  # noqa: BLE001
        logger.exception("[WotStats] 排版失败（数据可能异常）")
        return "❌ 数据渲染失败，请稍后重试（详情见 AstrBot 日志）。"


class WotStatsPlugin(Star):
    """坦克世界战绩查询插件。"""

    def __init__(self, context: Context):
        super().__init__(context)
        self.fetcher = WotBoxFetcher()
        self.camp_client = WotCampClient()
        self.wg_client = WotGameSearchClient()      # 官方玩家搜索（昵称 → wgid 主通道）
        self.catalog = load_catalog()
        # 进程内缓存（不落盘）：wgid 映射长期保留，查询数据默认不缓存（CAMP_CACHE_TTL=0）
        self._wgid_cache = TTLCache(WGID_CACHE_TTL)
        self._camp_cache = TTLCache(CAMP_CACHE_TTL)

    # ═════════════════ 指令：/wot ═════════════════

    @filter.command("wot", alias={"战绩", "查战绩", "wot查询"})
    async def wot_command(self, event: AstrMessageEvent, query: GreedyStr):
        raw = (query or "").strip()
        if not raw or raw.lower() in ("help", "帮助", "用法", "-h"):
            yield self._build_result(event, usage_text())
            return

        action, target = self._parse_target(raw)
        if not target:
            yield self._build_result(event, "⚠️ 无法识别的参数：%s\n\n%s" % (raw, usage_text()))
            return

        style = self._pick_style(event)
        if not is_valid_nickname(target):
            yield self._build_result(
                event,
                "⚠️ 昵称不合法：需为 2~32 个字符（字母/数字/中文/下划线/连字符/点/空格），"
                "且不能包含空格开头。示例：/wot loy1234",
            )
            return

        data, wgid, box_status, err_text = await self._handle_box(action, target)

        # 个人战绩页才带 wgid；总战绩页没有 → 只对 /wot <昵称> 追加营地数据
        # 注意：盒子"查无此人"时不补营地数据（否则会出现"没找到玩家"却又贴出营地数据的矛盾回复）；
        #       盒子被限流/失败时改为走官方搜索拿 wgid，让营地数据仍可用。
        camp = None
        if CAMP_ENABLED and action == ACT_INDEX and box_status != "notfound":
            if not wgid:
                wgid = (await self._resolve_wgid(target))[0]
            cached = self._wgid_cache.get(target)
            if isinstance(cached, tuple):        # 缓存里存的是 (wgid, 规范昵称)
                cached = cached[0]
            wgid = wgid or cached or ""
            if wgid:
                # 把盒子「常用坦克」的车名交给营地：它们通常也是营地 30 天里的主力车，
                # 传过去既能保证被查到，也能让单车表的「盒子效率」列对上号
                box_names = [t.name for t in (getattr(data, "tanks", None) or [])]
                camp = await self._fetch_camp(wgid, tanks_top=CAMP_TANKS_TOP,
                                              extra_names=box_names)
            else:
                logger.info(f"[WotStats] 未取得 wgid，跳过营地数据 nickname={target!r}")

        if data is not None:
            text = _safe_format(format_index_reply, data, style, camp) if action == ACT_INDEX \
                else _safe_format(format_total_reply, data, style)
            if camp is not None:
                # 盒子成功：常用坦克表已含在正文里，这里只追加三时段速览
                brief = _safe_format(format_camp_brief, camp, style)
                if brief:
                    text = (text + "\n\n" + brief) if text else brief
        else:
            # 盒子不可用（限流/失败）：营地数据成为主体 → 常用坦克表 + 三时段速览照常输出
            head = rate_limited_brief() if (camp is not None and box_status == "ratelimited") \
                else err_text
            body = _safe_format(format_camp_block, camp, style) if camp is not None else ""
            text = (head + "\n\n" + body) if body else head

        yield self._build_result(event, text)

    # ═════════════════ 偶游盒子取数 ═════════════════

    async def _handle_box(self, action: str, nickname: str):
        """抓取并解析盒子页面。

        返回 (解析结果 or None, wgid 或 "", 状态, 错误文本)；
        状态取 ok / notfound / ratelimited / error。任何异常都收敛为友好文本。
        排版交给调用方（因为营地数据要参与个人战绩页的单车展示）。
        """
        wgid, status, err_text = "", "ok", ""
        try:
            html = await self.fetcher.fetch(nickname, action)
            data = parse_page(html, action)
            if action == ACT_INDEX:
                wgid = str(getattr(data, "player_id", "") or "")
                if is_wgid(wgid):
                    self._wgid_cache.set(nickname, wgid)   # 进程内映射，供营地复用
                else:
                    wgid = ""
            return data, wgid, status, err_text
        except PlayerNotFoundError:
            status = "notfound"
            err_text = player_not_found_text(nickname)
        except RateLimitedError as e:
            status = "ratelimited"
            logger.warning(f"[WotStats] 站点限流 nickname={nickname!r}: {e}")
            err_text = rate_limited_text(nickname)
        except (WotQueryError, ParseError) as e:
            status = "error"
            logger.warning(f"[WotStats] 查询失败 nickname={nickname!r}: {e}")
            err_text = (
                f"❌ 查询失败：{e}\n"
                "请稍后重试；也可到 https://wot.ouj.com/zhanji/index.html 手动确认站点可用性。"
            )
        except Exception:  # 兜底，避免插件崩溃
            status = "error"
            logger.exception(f"[WotStats] 未知异常 nickname={nickname!r}")
            err_text = "❌ 查询过程出现未知错误，请稍后重试（详情见 AstrBot 日志）。"
        return None, wgid, status, err_text

    # ═════════════════ wgid 解析（营地数据的必需参数） ═════════════════

    async def _resolve_wgid(self, nickname: str) -> tuple[str, str, str]:
        """昵称 → (wgid, 规范昵称, 来源)。来源：cache / official / box / ""。

        依次尝试：进程内缓存 → 官方搜索(wotgame.cn) → 盒子页面 p_id。
        官方搜索是主通道：免登录、无限流迹象、大小写不敏感，1 次请求即可；
        昵称不足 4 字符或官方搜索失败时，回落到盒子个人战绩页里的 input#p_id。
        全部失败返回 ("", "", "")，不抛异常。
        """
        cached = self._wgid_cache.get(nickname)
        if cached:
            wgid, canonical = cached if isinstance(cached, tuple) else (cached, nickname)
            return wgid, canonical, "cache"

        # ① 官方搜索
        try:
            account, state = await self.wg_client.resolve(nickname)
        except Exception:  # noqa: BLE001  兜底：任何意外都不影响回落
            logger.exception(f"[WotStats] 官方搜索未知异常 nickname={nickname!r}")
            account, state = None, "error"
        if account is not None:
            self._wgid_cache.set(nickname, (account.account_id, account.name))
            logger.info(f"[WotStats] wgid 解析成功（官方搜索）{nickname!r} → {account.account_id}")
            return account.account_id, account.name, "official"
        if state in ("ambiguous", "notfound"):
            logger.info(f"[WotStats] 官方搜索未唯一命中 nickname={nickname!r} state={state}")
            return "", "", ""

        # ② 回落：盒子个人战绩页
        try:
            html = await self.fetcher.fetch(nickname, ACT_INDEX)
            page = parse_page(html, ACT_INDEX)
            wgid = str(getattr(page, "player_id", "") or "")
            if is_wgid(wgid):
                canonical = page.player or nickname
                self._wgid_cache.set(nickname, (wgid, canonical))
                logger.info(f"[WotStats] wgid 解析成功（盒子页面）{nickname!r} → {wgid}")
                return wgid, canonical, "box"
        except PlayerNotFoundError:
            logger.info(f"[WotStats] 盒子查无此人 nickname={nickname!r}")
        except RateLimitedError:
            logger.warning(f"[WotStats] 盒子限流，wgid 回落失败 nickname={nickname!r}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[WotStats] 盒子取 wgid 失败 nickname={nickname!r}: {e}")
        return "", "", ""

    # ═════════════════ 坦克营地取数 ═════════════════

    async def _fetch_camp(self, wgid: str, tanks_top: int = CAMP_TANKS_TOP, extra_names=None):
        """取营地数据；失败返回 None（调用方降级），不抛异常。

        extra_names：盒子「常用坦克」的车名，保证两边能按车名对齐（单车表的「盒子效率」列）。
        缓存键包含取数形状 + 车名，避免不同查询互相污染（CAMP_CACHE_TTL=0 时缓存整体不生效）。
        """
        key = (wgid, tanks_top > 0, tuple(extra_names or ())[:10])
        cached = self._camp_cache.get(key)
        if cached is not None:
            return cached
        try:
            camp = await self.camp_client.fetch_player(
                wgid,
                tanks_top=tanks_top,
                tanks_scan=CAMP_TANKS_SCAN,
                catalog=self.catalog,
                extra_tank_names=extra_names,
                want_tanks=True,
            )
        except CampNotFoundError as e:
            logger.info(f"[WotStats] 营地查无此人 wgid={wgid}: {e}")
            return None
        except CampError as e:
            logger.warning(f"[WotStats] 营地取数失败 wgid={wgid}: {e}")
            return None
        except Exception:
            logger.exception(f"[WotStats] 营地取数未知异常 wgid={wgid}")
            return None
        self._camp_cache.set(key, camp)
        return camp

    # ═════════════════ 内部工具 ═════════════════

    @staticmethod
    def _parse_target(raw: str) -> tuple[str, str]:
        """解析「/wot [营地|总] <昵称>」。实现见 core/commands.parse_target（纯函数，有单测）。"""
        return parse_target(raw)

    @staticmethod
    def _pick_style(event: AstrMessageEvent) -> str:
        """决定回复排版风格：auto 时 QQ 官方平台 → qq_md，其他平台 → plain。"""
        if REPLY_STYLE != "auto":
            return REPLY_STYLE
        platform = str(event.get_platform_name() or "").lower()
        if any(name in platform for name in QQ_OFFICIAL_PLATFORM_NAMES):
            return "qq_md"
        return "plain"

    def _build_result(self, event: AstrMessageEvent, text: str):
        """QQ 官方平台强制 Markdown 消息（msg_type=2，发送失败由适配器自动降级纯文本）。"""
        style = self._pick_style(event)
        if style == "qq_md":
            return event.make_result().message(text).use_markdown(True)
        return event.plain_result(text)
