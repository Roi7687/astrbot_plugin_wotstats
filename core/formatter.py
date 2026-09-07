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
from .config import SOURCE_NOTE
from .parser import PlayerStats, TotalStats

__all__ = [
    "format_index_reply",
    "format_total_reply",
    "usage_text",
    "player_not_found_text",
]

NL = chr(10)


def _md_escape(s: str) -> str:
    """GFM 表格单元格转义（表格风格仅用于支持表格的渠道）。"""
    return str(s).replace("|", "｜").replace(chr(10), " ")


def _delta(delta: str) -> str:
    return delta or "±0"


# ═══════════════ 个人战绩页（r=default/index） ═══════════════


def format_index_reply(st: PlayerStats, style: str = "qq_md") -> str:
    """按风格渲染个人战绩摘要。style: qq_md | plain | table"""
    if style == "plain":
        return _index_plain(st)
    if style == "table":
        return _index_md_table(st)
    return _index_qq_md(st)


def _index_qq_md(st: PlayerStats) -> str:
    r = st.recent
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
    if st.tanks:
        lines += ["", "🚗 **常用坦克**"]
        for t in st.tanks[:5]:
            lines.append("- %s（%s） 胜率 %s ｜ %s 场 ｜ 战力 **%s**" % (t.name, t.vehicle_type, t.win_rate, t.battles, t.power))
    if st.recent_battles:
        lines += ["", "🕘 **最近对局**（最新在前）"]
        for b in st.recent_battles[:5]:
            mark = "✅" if b.result == "胜利" else "❌"
            lines.append("- %s %s %s（%s ｜ %s）" % (mark, b.result, b.exp, b.mode, b.time))
    if st.evaluation:
        lines += ["", "> 盒子评价：%s" % st.evaluation[0]]
    lines += ["", SOURCE_NOTE]
    return NL.join(lines)


def _index_plain(st: PlayerStats) -> str:
    r = st.recent
    lines = ["🎖 %s | 战斗力 %s（%s）" % (st.player, st.power, _delta(st.power_delta))]
    head = "近期战绩（近 1500 场标准局"
    if st.updated_at:
        head += " | 更新于 %s" % st.updated_at
    head += "）"
    lines.append(head)
    lines.append("胜率 %s（胜 %s / 负 %s / 共 %s） ｜ 命中率 %s ｜ 出战等级 %s" % (r.win_rate, r.win, r.lose, r.total, r.hit_rate, r.tier))
    av = st.avg_per_battle
    if av:
        lines.append("场均：杀伤 %s ｜ 经验 %s ｜ 击毁 %s ｜ 占领 %s ｜ 防守 %s ｜ 发现 %s" % (
            av.get("杀伤", "-"), av.get("经验", "-"), av.get("击毁", "-"),
            av.get("占领", "-"), av.get("防守", "-"), av.get("发现", "-")))
    if st.tanks:
        parts = []
        for t in st.tanks[:5]:
            parts.append("%s（%s，%s·%s场·战力%s）" % (t.name, t.vehicle_type, t.win_rate, t.battles, t.power))
        lines.append("常用坦克：" + " ".join(parts))
    if st.recent_battles:
        parts = []
        for b in st.recent_battles[:5]:
            parts.append("%s%s" % (b.result, b.exp))
        lines.append("最近对局：" + " / ".join(parts) + "（%s）" % st.recent_battles[0].mode)
    if st.evaluation:
        lines.append("盒子评价：" + st.evaluation[0])
    lines.append(SOURCE_NOTE)
    return NL.join(lines)


def _index_md_table(st: PlayerStats) -> str:
    r = st.recent
    av = st.avg_per_battle
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
    if st.tanks:
        lines += ["", "### 常用坦克", "", "| 坦克 | 类型 | 胜率 | 场次 | 战力 |", "| --- | --- | --- | --- | --- |"]
        for t in st.tanks[:5]:
            lines.append("| %s | %s | %s | %s | %s |" % (_md_escape(t.name), t.vehicle_type, t.win_rate, t.battles, t.power))
    if st.evaluation:
        lines += ["", "> 盒子评价：" + st.evaluation[0]]
    lines += ["", SOURCE_NOTE]
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
    lines += ["", SOURCE_NOTE]
    return NL.join(lines)


def _total_plain(ts: TotalStats) -> str:
    lines = ["🎖 %s | 总战绩 | 战斗力 %s（%s）" % (ts.player, ts.power, _delta(ts.power_delta))]
    lines.append("%s（%s）" % (ts.join_days, ts.join_date) if ts.join_days else "入伍时间未知")
    hd = ts.headline
    if hd.get("胜率"):
        lines.append("总胜率 %s ｜ 场均伤害 %s ｜ 场均助攻 %s ｜ 场均经验 %s" % (
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
    lines.append(SOURCE_NOTE)
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
    lines += ["", SOURCE_NOTE]
    return NL.join(lines)


# ═══════════════ 通用文案 ═══════════════


def usage_text() -> str:
    return NL.join([
        "🎮 坦克世界战绩查询（数据来自偶游盒子 wot.ouj.com）",
        "",
        "用法：",
        "· /wot <昵称> —— 近期战绩（战斗力 / 胜率 / 场均 / 常用坦克）",
        "· /wot 总 <昵称>（或 /wot 总战绩 <昵称>）—— 总战绩",
        "· /wot help —— 本帮助",
        "",
        "示例：/wot loy1234　/wot 总 庇护者一号",
        "",
        "💡 昵称区分大小写；中文昵称可直接输入；战绩非实时，更新有一定延迟。",
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
