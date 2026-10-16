# -*- coding: utf-8 -*-
"""回复排版模块：把结构化战绩数据渲染为三种文本风格。

风格说明（重要，2026-09 依据 QQ 官方文档核对）：
- qq_md：QQ 官方机器人原生 Markdown（msg_type=2）。官方 Markdown 支持格式清单为
  标题 / 加粗 / 斜体 / 删除线 / 链接 / 图片 / 列表 / 引用 / 分割线 / 换行，
  **不含表格语法**，因此 QQ 风格采用"加粗 + 无序列表"排版（官方文档：
  https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/markdown.html ）
- table：通用 GFM Markdown 表格排版（仅适合支持表格的渠道/自测预览；QQ 不适用）
- plain：无任何 Markdown 标记的纯文本（其他聊天平台回退用）

所有函数为纯函数（输入数据模型，输出字符串），便于单元测试。
"""
import datetime as _dt
import logging
import math
import re
import urllib.parse

from .camp_model import CampPeriod, CampPlayer
from .config import (
    ACT_INDEX,
    ACT_TOTAL,
    CAMP_PERIOD_CN,
    QUERY_ENDPOINT,
    RATE_LIMIT_COOLDOWN,
)
from .parser import PlayerStats, TotalStats
from .tanks import strip_quotes

__all__ = [
    "format_index_reply",
    "format_total_reply",
    "format_camp_brief",
    "usage_text",
    "player_not_found_text",
    "rate_limited_text",
    "rate_limited_brief",
]

NL = chr(10)

logger = logging.getLogger("astrbot")


def _md_escape(s: str) -> str:
    """GFM 表格单元格转义（表格风格仅用于支持表格的渠道）。"""
    return str(s).replace("|", "｜").replace(chr(10), " ")


def _delta(delta: str) -> str:
    return delta or "±0"


def _source_url(player: str, total: bool = False) -> str:
    """对应查询页面的直达 URL（个人战绩页 / 总战绩页）。"""
    action = ACT_TOTAL if total else ACT_INDEX
    return QUERY_ENDPOINT + "?r=" + action + "&pn=" + urllib.parse.quote(player, safe="")


def _source_line(player: str, style: str, total: bool = False) -> str:
    """结尾来源行：plain 输出裸 URL，markdown 风格输出可点击链接。"""
    url = _source_url(player, total)
    if style == "plain":
        return "数据来源：" + url
    return "数据来源：[" + url + "](" + url + ")"


# ═══════════════ 个人战绩页（r=default/index） ═══════════════


def format_index_reply(st: PlayerStats, style: str = "qq_md", camp=None) -> str:
    """按风格渲染个人战绩摘要。style: qq_md | plain | table

    camp：可选，CampPlayer。传了且其中「近 30 天常用坦克」有数据时，
    🚗 区块会换成**营地口径 + 盒子效率**的合并表（用户要求的单车展示方式）；
    否则保持原样（纯盒子视角）。
    """
    if style == "plain":
        return _index_plain(st, camp)
    if style == "table":
        return _index_md_table(st, camp)
    return _index_qq_md(st, camp)


def _tank_brief_line(t, bold_name: bool) -> str:
    """单辆坦克一行：名称（类型）/胜率/场次/战力/场均伤害/命中率。"""
    name = "**" + t.name + "**" if bold_name else t.name
    dmg = (t.avg or {}).get("场均伤害", "-")
    hit = (t.avg or {}).get("命中率", "-")
    return "- %s（%s）：胜率 %s ｜ %s 场 ｜ 战力 **%s** ｜ 场均伤害 %s ｜ 命中率 %s" % (
        name, t.vehicle_type, t.win_rate, t.battles, t.power, dmg, hit)


# ── 常用坦克表（营地口径为主，盒子效率为可选补充） ──


def _tank_rows(camp, box_tanks):
    """取出常用坦克行；营地没有单车数据时返回空列表（调用方回退到纯盒子展示）。

    数据来源：core/tank_table.py（营地优先 + 盒子效率补充），此处只负责排版。
    """
    if camp is None:
        return []
    from .tank_table import build_tank_rows      # 局部导入，避免循环引用
    try:
        return build_tank_rows(camp, box_tanks)
    except Exception:  # noqa: BLE001  单车表失败绝不能影响主回复
        logger.exception("[WotStats] 常用坦克表构建失败")
        return []


def _tank_heading(rows, style: str) -> str:
    """表头：营地为主；只有当确实存在盒子效率补充时才提"盒子效率"。"""
    boxed = any(r.has_box for r in rows)
    tail = " ｜ 盒子效率为补充" if boxed else ""
    if style == "plain":
        return "常用坦克（营地近 30 天%s）：" % (" | 附盒子效率" if boxed else "")
    if style == "table":
        return "常用坦克（营地近 30 天口径%s）" % tail
    return "**常用坦克**（营地近 30 天口径%s）" % tail


def _box_segment(row, style: str, as_column: bool = False) -> str:
    """盒子效率补充片段；没有补充数据时返回空串（不显示 "-"，避免噪音）。"""
    if not row.has_box:
        return ""
    power = row.box_power
    if style != "plain" and not as_column:
        power = "**%s**" % power
    return power


def _tank_line(row, style: str) -> str:
    """一行单车数据（营地字段在前，盒子效率在最后按需追加）。"""
    name = _md_text(strip_quotes(row.name), limit=32) or "未知坦克"
    wn8 = _fmt_wn8(row.wn8)
    if style != "plain":
        name = "**%s**" % name
        wn8 = "**%s**" % wn8
    tier = ("%s 级" % row.tier) if row.tier else "等级未知"
    line = "%s%s（%s）：营地WN8 %s ｜ 近30天 %s 场 ｜ 胜率 %s ｜ 场均伤害 %s" % (
        _bullet(style), name, tier, wn8, _fmt_int(row.fights),
        _fmt_pct(row.win_rate, 1, zero_is_dash=row.fights <= 0),
        _fmt_int(row.avgdmg) if row.fights > 0 else "-")
    segment = _box_segment(row, style)
    if segment:
        line += " ｜ 盒子效率 %s" % segment
    return line


def _tank_table_block(rows, style: str) -> list:
    """table 风格：真正的 GFM 表格；"盒子效率"列仅在确有补充时出现。"""
    boxed = any(r.has_box for r in rows)
    header = ["坦克", "等级", "营地WN8", "近30天场次", "30天胜率", "场均伤害"]
    if boxed:
        header.append("盒子效率")
    out = ["", "### " + _tank_heading(rows, "table"), "",
           "| " + " | ".join(header) + " |",
           "| " + " | ".join("---" for _ in header) + " |"]
    for row in rows:
        cells = [_md_escape(_md_text(strip_quotes(row.name), limit=32)),
                 str(row.tier) if row.tier else "未知",
                 _fmt_wn8(row.wn8), _fmt_int(row.fights),
                 _fmt_pct(row.win_rate, 1, zero_is_dash=row.fights <= 0),
                 _fmt_int(row.avgdmg) if row.fights > 0 else "-"]
        if boxed:
            cells.append(_md_escape(_box_segment(row, "table", as_column=True)) or "-")
        out.append("| " + " | ".join(cells) + " |")
    return out


def _tank_block(rows, style: str) -> list:
    """常用坦克区块：qq_md / plain 用列表，table 用表格。"""
    if style == "table":
        return _tank_table_block(rows, style)
    return ["", _tank_heading(rows, style)] + [_tank_line(r, style) for r in rows]


def _index_qq_md(st: PlayerStats, camp=None) -> str:
    r = st.recent
    rows = _tank_rows(camp, st.tanks)
    lines = [
        "🎖 **%s** ｜ 战斗力 **%s**（%s）" % (st.player, st.power, _delta(st.power_delta)),
        "",
    ]
    head = "📋 **近期战绩**（近 1500 场标准局"
    if st.updated_at:
        head += " ｜ 更新于 %s" % st.updated_at
    head += "）"
    lines.append(head)
    lines += [
        "- 胜率：**%s**（胜 %s / 负 %s / 共 %s）" % (r.win_rate, r.win, r.lose, r.total),
        "- 命中率：%s ｜ 出战等级：%s" % (r.hit_rate, r.tier),
    ]
    av = st.avg_per_battle
    if av.get("杀伤"):
        lines.append("- 场均：**杀伤 %s** ｜ 经验 %s ｜ 击毁 %s" % (av["杀伤"], av.get("经验", "-"), av.get("击毁", "-")))
        lines.append("- 场均：占领 %s ｜ 防守 %s ｜ 发现 %s" % (av.get("占领", "-"), av.get("防守", "-"), av.get("发现", "-")))
    if rows:
        lines += _tank_block(rows, "qq_md")
    elif st.tanks:
        lines += ["", "🚗 **常用坦克**（战力 / 胜率 / 场均伤害 / 命中率）"]
        for t in st.tanks[:5]:
            lines.append(_tank_brief_line(t, bold_name=True))
    lines += ["", _source_line(st.player, "qq_md")]
    return NL.join(lines)


def _index_plain(st: PlayerStats, camp=None) -> str:
    r = st.recent
    rows = _tank_rows(camp, st.tanks)
    lines = ["🎖 %s | 战斗力 %s（%s）" % (st.player, st.power, _delta(st.power_delta))]
    head = "近期战绩（近 1500 场标准局"
    if st.updated_at:
        head += " | 更新于 %s" % st.updated_at
    head += "）"
    lines.append(head)
    lines.append("胜率 %s（胜 %s / 负 %s / 共 %s） | 命中率 %s | 出战等级 %s" % (r.win_rate, r.win, r.lose, r.total, r.hit_rate, r.tier))
    av = st.avg_per_battle
    if av:
        lines.append("场均：杀伤 %s | 经验 %s | 击毁 %s | 占领 %s | 防守 %s | 发现 %s" % (
            av.get("杀伤", "-"), av.get("经验", "-"), av.get("击毁", "-"),
            av.get("占领", "-"), av.get("防守", "-"), av.get("发现", "-")))
    if rows:
        lines += _tank_block(rows, "plain")
    elif st.tanks:
        lines.append("常用坦克：")
        for t in st.tanks[:5]:
            dmg = (t.avg or {}).get("场均伤害", "-")
            hit = (t.avg or {}).get("命中率", "-")
            lines.append("· %s（%s）%s | %s场 | 战力 %s | 场均伤害 %s | 命中率 %s" % (
                t.name, t.vehicle_type, t.win_rate, t.battles, t.power, dmg, hit))
    lines.append(_source_line(st.player, "plain"))
    return NL.join(lines)


def _index_md_table(st: PlayerStats, camp=None) -> str:
    r = st.recent
    av = st.avg_per_battle
    merged = _tank_rows(camp, st.tanks)
    lines = [
        "🎖 **%s** ｜ 战斗力 **%s**（%s）" % (st.player, st.power, _delta(st.power_delta)),
        "",
        "### 近期战绩（近 1500 场标准局%s）" % ("，更新于 " + st.updated_at if st.updated_at else ""),
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        "| 胜率 | **%s**（胜 %s / 负 %s / 共 %s） |" % (r.win_rate, r.win, r.lose, r.total),
        "| 命中率 | %s |" % r.hit_rate,
        "| 出战等级 | %s |" % r.tier,
    ]
    for key in ("杀伤", "经验", "击毁", "占领", "防守", "发现"):
        if key in av:
            lines.append("| 场均%s | %s |" % (_md_escape(key), _md_escape(av[key])))
    if merged:
        lines += _tank_block(merged, "table")
    elif st.tanks:
        lines += ["", "### 常用坦克", "",
                  "| 坦克 | 类型 | 胜率 | 场次 | 战力 | 场均伤害 | 命中率 |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for t in st.tanks[:5]:
            dmg = (t.avg or {}).get("场均伤害", "-")
            hit = (t.avg or {}).get("命中率", "-")
            lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                _md_escape(t.name), t.vehicle_type, t.win_rate, t.battles, t.power, _md_escape(dmg), _md_escape(hit)))
    lines += ["", _source_line(st.player, "table")]
    return NL.join(lines)


# ═══════════════ 总战绩页（r=default/battlestat） ═══════════════


def format_total_reply(ts: TotalStats, style: str = "qq_md") -> str:
    """按风格渲染总战绩摘要。style: qq_md | plain | table"""
    if style == "plain":
        return _total_plain(ts)
    if style == "table":
        return _total_md_table(ts)
    return _total_qq_md(ts)


def _total_qq_md(ts: TotalStats) -> str:
    lines = [
        "🎖 **%s** ｜ 总战绩 ｜ 战斗力 **%s**（%s）" % (ts.player, ts.power, _delta(ts.power_delta)),
        "⏳ %s（%s）" % (ts.join_days, ts.join_date) if ts.join_days else "⏳ 入伍时间未知",
    ]
    hd = ts.headline
    if hd.get("胜率"):
        lines += [
            "- **总胜率**：**%s**" % hd["胜率"],
            "- 场均伤害：%s ｜ 场均助攻：%s ｜ 场均经验：%s" % (hd.get("伤害", "-"), hd.get("助攻", "-"), hd.get("经验", "-")),
        ]
    if ts.total_cols and ts.total_row and ts.avg_row:
        n = min(len(ts.total_cols), len(ts.total_row), len(ts.avg_row))
        for i in range(n):
            lines.append("- %s：总体 %s ｜ 场均 %s" % (ts.total_cols[i], ts.total_row[i], ts.avg_row[i]))
    if ts.recent_tanks:
        lines += ["", "🚗 **最近常用坦克**"]
        for t in ts.recent_tanks[:5]:
            lines.append("- %s：%s 场 ｜ %s ｜ 战力 **%s**" % (t.name, t.battles, t.win_rate, t.power))
    lines += ["", _source_line(ts.player, "qq_md", total=True)]
    return NL.join(lines)


def _total_plain(ts: TotalStats) -> str:
    lines = ["🎖 %s | 总战绩 | 战斗力 %s（%s）" % (ts.player, ts.power, _delta(ts.power_delta))]
    lines.append("%s（%s）" % (ts.join_days, ts.join_date) if ts.join_days else "入伍时间未知")
    hd = ts.headline
    if hd.get("胜率"):
        lines.append("总胜率 %s | 场均伤害 %s | 场均助攻 %s | 场均经验 %s" % (
            hd["胜率"], hd.get("伤害", "-"), hd.get("助攻", "-"), hd.get("经验", "-")))
    if ts.total_cols and ts.total_row and ts.avg_row:
        n = min(len(ts.total_cols), len(ts.total_row), len(ts.avg_row))
        pair = []
        for i in range(n):
            pair.append("%s %s（场均 %s）" % (ts.total_cols[i], ts.total_row[i], ts.avg_row[i]))
        lines.append("总体（场均）：" + " ｜ ".join(pair))
    if ts.recent_tanks:
        parts = []
        for t in ts.recent_tanks[:5]:
            parts.append("%s（%s场·%s·战力%s）" % (t.name, t.battles, t.win_rate, t.power))
        lines.append("最近常用坦克：" + " ".join(parts))
    lines.append(_source_line(ts.player, "plain", total=True))
    return NL.join(lines)


def _total_md_table(ts: TotalStats) -> str:
    lines = [
        "🎖 **%s** ｜ 总战绩 ｜ 战斗力 **%s**（%s）" % (ts.player, ts.power, _delta(ts.power_delta)),
        "",
    ]
    if ts.join_days:
        lines.append("⏳ %s（%s）" % (ts.join_days, ts.join_date))
    lines += ["", "| 指标 | 数值 |", "| --- | --- |"]
    hd = ts.headline
    if hd.get("胜率"):
        lines += [
            "| 总胜率 | %s |" % hd["胜率"],
            "| 场均伤害 | %s |" % hd.get("伤害", "-"),
            "| 场均助攻 | %s |" % hd.get("助攻", "-"),
            "| 场均经验 | %s |" % hd.get("经验", "-"),
        ]
    if ts.total_cols and ts.total_row and ts.avg_row:
        n = min(len(ts.total_cols), len(ts.total_row), len(ts.avg_row))
        for i in range(n):
            lines.append("| 总体%s | %s |" % (_md_escape(ts.total_cols[i]), ts.total_row[i]))
            lines.append("| 场均%s | %s |" % (_md_escape(ts.total_cols[i]), ts.avg_row[i]))
    if ts.recent_tanks:
        lines += ["", "### 最近常用坦克", "", "| 坦克 | 场次 | 胜率 | 战力 |", "| --- | --- | --- | --- |"]
        for t in ts.recent_tanks[:5]:
            lines.append("| %s | %s | %s | %s |" % (_md_escape(t.name), t.battles, t.win_rate, t.power))
    lines += ["", _source_line(ts.player, "table", total=True)]
    return NL.join(lines)


# ═══════════════ 通用文案 ═══════════════


def usage_text() -> str:
    return NL.join([
        "🎮 坦克世界战绩查询（偶游盒子 + 官方坦克营地）",
        "",
        "用法：",
        "· /wot <昵称> —— 战绩摘要：盒子数据 + 营地近 30 天常用坦克（含盒子效率对照）",
        "· /wot 总 <昵称>（或 /wot 总战绩 <昵称>）—— 总战绩",
        "· /wot help —— 本帮助",
        "",
        "示例：/wot loy1234　/wot 总 庇护者一号",
        "",
        "💡 昵称区分大小写；中文昵称可直接输入；战绩非实时，更新有一定延迟。",
        "💡 「常用坦克」以官方营地近 30 天数据为准；「战斗力」（盒子）与「WN8」（营地）是两套口径，不可换算。",
    ])


def player_not_found_text(nickname: str) -> str:
    return NL.join([
        "😕 没有找到玩家「%s」" % nickname,
        "",
        "可能原因：",
        "· 昵称输入有误或大小写不匹配（本站昵称区分大小写）",
        "· 玩家刚改名：盒子约 3 小时内自动同步新名字",
        "· 长时间查询不到，可在盒子客户端「意见反馈」联系盒子管理同步",
    ])


def rate_limited_text(nickname: str = "") -> str:
    """偶游盒子 403 限流时的友好提示（该站对单 IP 有严格请求配额）。"""
    head = "⏳ 偶游盒子暂时拒绝了查询请求（站点限流 HTTP 403）"
    if nickname:
        head = "⏳ 查询「%s」时，偶游盒子拒绝了请求（站点限流 HTTP 403）" % nickname
    return NL.join([
        head,
        "",
        "该站对同一 IP 有较严格的请求频率限制，稍等 %d 秒以上再试（实测密集请求后可能需数分钟~更久）。"
        % RATE_LIMIT_COOLDOWN,
        "· 稍等片刻后重试即可；官方《坦克营地》数据（WN8/常用坦克）不受影响，会照常显示。",
    ])


def rate_limited_brief() -> str:
    """限流但营地数据可用时的一行提示：说清"缺的是什么"，后面紧跟营地数据。"""
    return ("⚠️ 偶游盒子限流（HTTP 403）：**战斗力 / 近 1500 场 / 总战绩** 暂不可用，"
            "以下为官方《坦克营地》数据（含近 30 天全部常用坦克）")


# ═══════════════ 坦克营地（官方 APP 数据） ═══════════════
#
# 与盒子数据的关系（务必在文案里保持区分，两套评分不可换算）：
#   · 盒子「战斗力」          ← 偶游盒子口径（近 1500 场标准局）
#   · 营地「WN8」             ← 官方口径，分 生涯 / 近 7 天 / 近 30 天 三个窗口


def _safe_float(value):
    """转 float；非法值（含 inf/nan，JSON 的 1e999 会变成 inf）返回 None。"""
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return v if math.isfinite(v) else None


def _fmt_int(value, dash: str = "-") -> str:
    """整数千分位；0 视为无数据（场均伤害/助攻/经验等也用这个，读起来更清楚）。"""
    v = _safe_float(value)
    if v is None:
        return dash
    n = int(round(v))
    return format(n, ",") if n else dash


def _fmt_num(value, nd: int = 1, dash: str = "-", zero_is_dash: bool = True) -> str:
    """数值保留 nd 位小数；zero_is_dash=True 时 0 视为无数据。

    zero_is_dash 用于区分"真 0"（如胜率 0%、K/D 0）与"接口没给"：
    有场次（fights>0）时传 False，就能显示 0.0% 而不是 '-'。
    """
    v = _safe_float(value)
    if v is None:
        return dash
    if zero_is_dash and not v:
        return dash
    return ("%%.%df" % nd) % v


def _fmt_pct(value, nd: int = 1, dash: str = "-", zero_is_dash: bool = False) -> str:
    """百分比；无数据时只输出 '-'（不带 % 号）。"""
    s = _fmt_num(value, nd, dash, zero_is_dash)
    return dash if s == dash else s + "%"


def _fmt_wn8(value) -> str:
    """WN8 显示：>=1000 取整，否则保留 1 位小数。"""
    v = _safe_float(value)
    if v is None or not v:
        return "-"
    return format(int(round(v)), ",") if v >= 1000 else "%.1f" % v


def _fmt_time(ts) -> str:
    v = _safe_float(ts)
    if v is None or v <= 0:
        return "-"
    try:
        return _dt.datetime.fromtimestamp(int(v)).strftime("%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return "-"


def _md_text(value, limit: int = 48) -> str:
    """远程字符串进 Markdown 前的清理：去掉换行与 Markdown 控制字符，并限长。

    昵称/车名/地图名都来自外部接口，直接拼进回复可能撑破排版甚至注入链接或标题。
    """
    s = "" if value is None else str(value)
    s = re.sub(r"[\r\n\t]+", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    for ch in ("*", "_", "`", "[", "]", "<", ">"):
        s = s.replace(ch, "")
    if limit and len(s) > limit:
        s = s[:limit] + "…"
    return s


def _bullet(style: str) -> str:
    """列表符号：markdown 风格用 '- '，纯文本用 '· '（与既有风格保持一致）。"""
    return "· " if style == "plain" else "- "


def _camp_period_line(per: CampPeriod, style: str) -> str:
    """一行时段汇总：WN8 / 场次 / 胜率 / K/D / 全服排名。"""
    bold = (lambda s: "**%s**" % s) if style != "plain" else (lambda s: s)
    rank = ""
    if per.rank:
        rank = " ｜ 全服第 %s 名" % _fmt_int(per.rank)
        if per.population:
            rank += "（%s 人）" % _fmt_int(per.population)
    has_data = per.fights > 0
    return "%s%s：WN8 %s ｜ %s 场 ｜ 胜率 %s ｜ K/D %s%s" % (
        _bullet(style), CAMP_PERIOD_CN.get(per.key, per.key), bold(_fmt_wn8(per.wn8)),
        _fmt_int(per.fights),
        _fmt_pct(per.win_rate, 1, zero_is_dash=not has_data),
        _fmt_num(per.kd, 2, zero_is_dash=not has_data), rank)


def _camp_avg_line(per: CampPeriod, style: str) -> str:
    has_data = per.fights > 0
    return "%s近 30 天场均：伤害 %s ｜ 击毁 %s ｜ 点亮 %s ｜ 经验 %s ｜ 命中率 %s ｜ 出战等级 %s" % (
        _bullet(style),
        _fmt_int(per.avgdmg) if has_data else "-",
        _fmt_num(per.avgfrag, 2, zero_is_dash=not has_data),
        _fmt_num(per.avgspot, 2, zero_is_dash=not has_data),
        _fmt_int(per.avgexp) if has_data else "-",
        _fmt_pct(per.hit_rate, 1, zero_is_dash=not has_data),
        _fmt_num(per.avglevel, 1, zero_is_dash=not has_data))


def format_camp_brief(camp: CampPlayer, style: str = "qq_md") -> str:
    """营地速览（挂在 /wot 回复末尾）：三时段 WN8/场次/胜率/排名 + 近 30 天场均。"""
    bold = (lambda s: "**%s**" % s) if style != "plain" else (lambda s: s)
    if style == "plain":
        lines = ["【坦克营地】%s（官方 APP 数据）" % _md_text(camp.nickname)]
    else:
        lines = ["🏕 %s ｜ %s数据" % (bold(_md_text(camp.nickname)), bold("坦克营地"))]
    shown = False
    for key in ("day_7", "day_30", "all"):
        per = camp.period(key)
        if per:
            lines.append(_camp_period_line(per, style))
            shown = True
    if not shown:
        return ""
    d30 = camp.day_30
    if d30:
        lines.append(_camp_avg_line(d30, style))
    return NL.join(lines)


def format_camp_block(camp: CampPlayer, style: str = "qq_md", box_tanks=None) -> str:
    """**盒子不可用时**的营地正文：常用坦克表 + 三时段速览。

    盒子被限流/查无此人时，`/wot` 拿不到个人战绩页，此时营地数据就是主体——
    常用坦克表本来也只依赖营地（见 core/tank_table.py），因此必须照常输出，
    不能只在"盒子成功"的渲染路径里出现（这是 v0.3.0/0.3.1 的真实缺陷）。
    """
    if camp is None:
        return ""
    lines = []
    rows = _tank_rows(camp, box_tanks)
    if rows:
        lines += _tank_block(rows, style)
    brief = format_camp_brief(camp, style)
    if brief:
        lines += (["", brief] if lines else [brief])
    return NL.join(lines).strip()
