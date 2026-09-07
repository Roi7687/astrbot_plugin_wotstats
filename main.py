# -*- coding: utf-8 -*-
"""astrbot_plugin_wotstats 主入口。

指令：
- /wot <昵称>             个人战绩摘要（战斗力 / 近1500场标准局 / 场均 / 常用坦克 / 最近对局）
- /wot 总 <昵称>          总战绩摘要（入伍时间 / 全时段胜率 / 总体与场均 / 最近常用坦克）
- /wot help               用法帮助

设计约定：
- 纯 HTTP GET 抓取服务端渲染 HTML（core/fetcher.py）→ 解析（core/parser.py）→ 排版（core/formatter.py）。
- 回复格式：QQ 官方平台（qq_official / qq_official_webhook）发送原生 Markdown 消息
  （官方 Markdown 语法不含表格 → 用加粗+列表排版，见 core/formatter.py 头部说明）；
  其余平台自动回退纯文本。REPLY_STYLE 可强制 table/qq_md/plain（core/config.py）。
- 运行时零落盘：不缓存、不写任何数据文件。
"""
import logging

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.core.star.filter.command import GreedyStr

from .core.config import (
    ACT_INDEX,
    ACT_TOTAL,
    QQ_OFFICIAL_PLATFORM_NAMES,
    REPLY_STYLE,
    WotQueryError,
    ParseError,
    PlayerNotFoundError,
    is_valid_nickname,
)
from .core.fetcher import WotBoxFetcher
from .core.formatter import (
    format_index_reply,
    format_total_reply,
    player_not_found_text,
    usage_text,
)
from .core.parser import parse_page

logger = logging.getLogger("astrbot")


class WotStatsPlugin(Star):
    """坦克世界战绩查询插件。"""

    def __init__(self, context: Context):
        super().__init__(context)
        self.fetcher = WotBoxFetcher()

    # ═════════════════ 指令：/wot ═════════════════

    @filter.command("wot", alias={"战绩", "查战绩", "wot查询"})
    async def wot_command(self, event: AstrMessageEvent, query: GreedyStr):
        raw = (query or "").strip()
        if not raw or raw.lower() in ("help", "帮助", "用法", "-h"):
            yield self._build_result(event, usage_text())
            return

        action, nickname = self._parse_target(raw)
        if nickname is None:
            yield self._build_result(
                event,
                "⚠️ 无法识别的参数：%s\n\n%s" % (raw, usage_text()),
            )
            return
        if not is_valid_nickname(nickname):
            yield self._build_result(
                event,
                "⚠️ 昵称不合法：需为 2~32 个字符（字母/数字/中文/下划线/连字符/点/空格），"
                "且不能包含空格开头。示例：/wot loy1234",
            )
            return

        style = self._pick_style(event)
        try:
            html = await self.fetcher.fetch(nickname, action)
            if action == ACT_TOTAL:
                data = parse_page(html, ACT_TOTAL)
                text = format_total_reply(data, style)
            else:
                data = parse_page(html, ACT_INDEX)
                text = format_index_reply(data, style)
        except PlayerNotFoundError:
            text = player_not_found_text(nickname)
        except (WotQueryError, ParseError) as e:
            logger.warning(f"[WotStats] 查询失败 nickname={nickname!r}: {e}")
            text = (
                f"❌ 查询失败：{e}\n"
                "请稍后重试；也可到 https://wot.ouj.com/zhanji/index.html 手动确认站点可用性。"
            )
        except Exception as e:  # 兜底，避免插件崩溃
            logger.exception(f"[WotStats] 未知异常 nickname={nickname!r}")
            text = "❌ 查询过程出现未知错误，请稍后重试（详情见 AstrBot 日志）。"

        yield self._build_result(event, text)

    # ═════════════════ 内部工具 ═════════════════

    @staticmethod
    def _parse_target(raw: str) -> tuple[str, str | None]:
        """解析「/wot [总] <昵称>」。返回 (action, 昵称)；无法解析时昵称为 None。"""
        for kw in ("总战绩", "总", "total", "zong", "all"):
            if raw.lower().startswith(kw.lower() + " "):
                rest = raw[len(kw):].strip()
                return ACT_TOTAL, (rest or None)
        return ACT_INDEX, raw

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
