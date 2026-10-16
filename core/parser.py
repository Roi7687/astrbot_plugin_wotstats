# -*- coding: utf-8 -*-
"""解析层：wotbox.ouj.com 服务端渲染 HTML → 结构化数据（纯函数，可单测）。

解析依据 2026-09-07 实测的页面结构（见插件根目录 research/SITE_PROBE_REPORT.md），
所有"选择器"集中在本文件，页面改版时只需更新这里并用 research/ 新快照回归。

页面口径：
- r=default/index     个人战绩（近期战绩只算最近 1500 场标准局；查无此人含 .not-find-user）
- r=default/battlestat 总战绩（全时段；入伍时间 / 总体与场均 / 最近常用坦克）
"""
import html as _html
import re
from dataclasses import asdict, dataclass, field

from .config import ACT_INDEX, ACT_TOTAL, ParseError, PlayerNotFoundError

__all__ = [
    "RecentStats",
    "TankDetail",
    "PlayerStats",
    "TotalTankRow",
    "TotalStats",
    "parse_page",
]

# ───────────────────── 低层工具 ─────────────────────

_TAG_RE = re.compile(r"<[^>]+>")


def _strip(s: str) -> str:
    """去 HTML 标签、解实体、收拢空白。"""
    if not s:
        return ""
    return re.sub(r"\s+", " ", _html.unescape(_TAG_RE.sub("", s))).strip()


def _slice_balanced_div(html: str, open_idx: int) -> str:
    """从 '<div...>' 开标签索引取到配对 '</div>'（含）的子串；防嵌套 div。"""
    depth = 0
    for m in re.finditer(r"<div[^>]*>|</div>", html[open_idx:]):
        tok = m.group(0)
        if tok.startswith("</"):
            depth -= 1
        else:
            depth += 1
        if depth == 0:
            return html[open_idx : open_idx + m.end()]
    return html[open_idx:]  # 兜底：未配对则取到末尾


def _block(html: str, cls_token: str) -> str:
    """返回 class 属性含 <cls_token> 的元素整块源码（自动配对同名开闭标签）。

    注意不能假设目标一定在 <div> 里：userRecord-data 是 <ul>、总战绩两个数据表是 <table>，
    若按最近的 <div> 切块，会把提前闭合的兄弟 div 当作容器而切错/切空。
    """
    idx = html.find('class="' + cls_token)
    if idx < 0:
        return ""
    # class 属性一定位于其所属元素"开标签"内部：往前找最近的 "<"
    lt = html.rfind("<", 0, idx)
    if lt < 0:
        return ""
    m = re.match(r"<([a-zA-Z][a-zA-Z0-9]*)", html[lt:])
    if not m:
        return ""
    tag = m.group(1).lower()
    if tag in ("br", "img", "input", "meta", "link", "hr", "i"):
        return ""  # 无配对闭合的标签
    depth = 0
    scan = re.compile("<" + tag + r"[ >]|</" + tag + r"[ >]")
    for m2 in scan.finditer(html, lt):
        if m2.group(0).startswith("</"):
            depth -= 1
        else:
            depth += 1
        if depth == 0:
            return html[lt : m2.end()]
    return html[lt:]  # 兜底


def _td_cells(row: str) -> list:
    """一行 <tr>…</tr> 里的单元格文本列表。"""
    return [_strip(c) for c in re.findall(r"<td[^>]*>([\s\S]*?)</td>", row)]


def _rows(block: str) -> list:
    """<tr …>…</tr> 行源码列表。"""
    return re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", block)


# ───────────────────── 数据模型 ─────────────────────


@dataclass
class RecentStats:
    """近 1500 场标准局汇总（r=default/index）"""

    win_rate: str = ""      # 如 57%
    win: str = ""           # 胜场数
    lose: str = ""          # 负场数
    total: str = ""         # 总场次
    hit_rate: str = ""      # 命中率
    tier: str = ""          # 出战等级，如 10.1级
    mode: str = ""          # 统计模式（标准模式）


@dataclass
class TankDetail:
    """常用坦克（含弹层详情）"""

    key: str = ""           # 站点坦克 key（如 france-f143_fauteur）
    name: str = ""
    vehicle_type: str = ""  # 重坦/中坦/TD/SPG/LT…
    win_rate: str = ""
    battles: str = ""
    power: str = ""         # 单车战斗力
    avg: dict = field(default_factory=dict)  # 场均伤害/场均经验/场均击毁/场均银币/命中率


@dataclass
class PlayerStats:
    """个人战绩页（r=default/index）结构化结果"""

    player: str = ""
    avatar: str = ""
    wu_id: str = ""
    player_id: str = ""
    power: str = ""
    power_delta: str = ""
    updated_at: str = ""                    # 页面数据更新时间（YYYY-MM-DD HH:MM）
    recent: RecentStats = field(default_factory=RecentStats)
    avg_per_battle: dict = field(default_factory=dict)  # 杀伤/经验/击毁/占领/防守/发现
    tanks: list = field(default_factory=list)           # list[TankDetail] 常用坦克（按使用频率）
    tabs: list = field(default_factory=list)            # 页面标签 (text, href)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TotalTankRow:
    """总战绩页的最近常用坦克行"""

    name: str = ""
    battles: str = ""
    win_rate: str = ""
    power: str = ""


@dataclass
class TotalStats:
    """总战绩页（r=default/battlestat）结构化结果"""

    player: str = ""
    avatar: str = ""
    power: str = ""
    power_delta: str = ""
    join_days: str = ""                     # 已入伍 N 天
    join_date: str = ""                     # YYYY年MM月DD日加入坦克世界
    headline: dict = field(default_factory=dict)   # 胜率/伤害(场均)/助攻(场均)/经验(场均)
    total_cols: list = field(default_factory=list)  # 列名 [击毁,占领,防守,发现]
    total_row: list = field(default_factory=list)   # 总体数值
    avg_row: list = field(default_factory=list)     # 场均数值
    recent_tanks: list = field(default_factory=list)  # list[TotalTankRow]

    def to_dict(self) -> dict:
        return asdict(self)


# ───────────────────── 公共入口 ─────────────────────


def parse_page(html_text: str, action: str = ACT_INDEX):
    """按 action 选择解析器；查无此人抛 PlayerNotFoundError。"""
    if _is_not_found(html_text):
        raise PlayerNotFoundError("没有找到您搜索的玩家")
    if action == ACT_TOTAL:
        return _parse_total(html_text)
    return _parse_index(html_text)


def _is_not_found(html_text: str) -> bool:
    # 注意：页面内联 CSS 里也存在 ".not-find-user" 样式定义（两页共用），
    # 因此必须匹配"元素"形态（class="not-find-user"）或提示文案，不能只搜类名字符串。
    if 'class="not-find-user"' in html_text:
        return True
    if "没有找到您搜索的玩家" in html_text:
        return True
    return False


# ───────────────────── 个人战绩页 r=default/index ─────────────────────


def _parse_index(html_text: str) -> PlayerStats:
    st = PlayerStats()

    # 玩家名 / 头像 / 战斗力
    m = re.search(r'<p class="name">([^<]*)</p>', html_text)
    if m:
        st.player = _strip(m.group(1))
    ui = _block(html_text, "user-info fl")
    if ui:
        m = re.search(r'<img src="([^"]+)"', ui)
        if m:
            st.avatar = m.group(1)
    pw = _block(html_text, "power fl")
    if pw:
        m = re.search(r'<span class="num">([^<]*)</span>', pw)
        if m:
            st.power = _strip(m.group(1))
        m = re.search(r'<span class="float-num">([\s\S]*?)</span>', pw)
        if m:
            st.power_delta = _strip(m.group(1))

    # 盒子/玩家内部 id（input 的 value）
    m = re.search(r'id="wu_id"\s+value="([^"]*)"', html_text)
    if m:
        st.wu_id = m.group(1)
    m = re.search(r'id="p_id"\s+value="([^"]*)"', html_text)
    if m:
        st.player_id = m.group(1)

    # 更新时间
    title_blk = _block(html_text, "userRecord-history__title")
    if title_blk:
        m = re.search(r"更新时间：(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", _strip(title_blk))
        if m:
            st.updated_at = m.group(1)

    # 近期战绩汇总（胜率环 + 数据）
    wr_frame = _strip(_block(html_text, "userRecord-charts__winRate--frame"))
    if wr_frame:
        m = re.findall(r"([\d.]+%)", wr_frame)
        if m:
            st.recent.win_rate = m[-1]
    wr_data = _strip(_block(html_text, "userRecord-charts__winRate--data"))
    if wr_data:
        m = re.search(r"胜\s*(\d+)\s*负\s*(\d+)\s*总\s*(\d+)", wr_data)
        if m:
            st.recent.win, st.recent.lose, st.recent.total = m.group(1), m.group(2), m.group(3)
        if "标准模式" in wr_data or "标准" in wr_data:
            st.recent.mode = "标准模式"  # 近 1500 场只统计标准局（站方口径）
    kr = _strip(_block(html_text, "userRecord-charts__killRate--frame"))
    if kr:
        m = re.findall(r"([\d.]+%)", kr)
        if m:
            st.recent.hit_rate = m[-1]
    fr = _strip(_block(html_text, "userRecord-charts__fightingRate--frame"))
    if fr:
        m = re.findall(r"([\d.]+级)", fr)
        if m:
            st.recent.tier = m[-1]

    # 场均数据 6 项
    data_blk = _block(html_text, "userRecord-data clearfix")
    for m in re.finditer(r"<li>([\s\S]*?)</li>", data_blk):
        t = re.search(r'<p class="title">([^<]+)</p>', m.group(1))
        n = re.search(r'<p class="num">([^<]*)</p>', m.group(1))
        if t and n:
            st.avg_per_battle[_strip(t.group(1))] = _strip(n.group(1))

    # 常用坦克图标顺序
    tank_keys = []
    use_blk = _block(html_text, "use-tank-list fr")
    if use_blk:
        tank_keys = re.findall(r'<li tank="([^"]+)"', use_blk)

    # 常用坦克弹层详情（user-tank__pop 与上面的 li 同 key 对应）
    pops = list(re.finditer(r'<div class="user-tank__pop" tank="([^"]+)"', html_text))
    by_key = {}
    for pm in pops:
        blk = _slice_balanced_div(html_text, pm.start())
        td = TankDetail(key=pm.group(1))
        m = re.search(r"<h3>([^<]*)</h3>", blk)
        if m:
            td.name = _strip(m.group(1))
        m = re.search(r'<em class="tank-pop__name">([^<]*)</em>', blk)
        if m:
            td.vehicle_type = _strip(m.group(1))
        info = _strip(_block(blk, "tank-pop__info"))
        m = re.search(r"([\d.]+%)\s*胜\s*(\d+)\s*场\s*战力：\s*([\d.]+)", info)
        if m:
            td.win_rate, td.battles, td.power = m.group(1), m.group(2), m.group(3)
        for am in re.finditer(r"<p>([^<]*?)<span class=\"data\">([^<]*)</span></p>", blk):
            label = _strip(am.group(1)).rstrip("：:")
            td.avg[label] = _strip(am.group(2))
        by_key[td.key] = td
    st.tanks = [by_key[k] for k in tank_keys if k in by_key] or list(by_key.values())

    # 标签页
    m = re.search(r'<ul class="mod-tabs-trigger[^"]*"[^>]*>([\s\S]*?)</ul>', html_text)
    if m:
        for am in re.finditer(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', m.group(1)):
            st.tabs.append((_strip(am.group(2)), _strip(am.group(1))))

    # 防御：核心数据一个都没解析到 → 大概率页面已改版/结构异常
    if not st.power and not st.tanks and not st.avg_per_battle:
        snippet = _strip(html_text)[:120]
        raise ParseError(f"未能从页面解析出战绩数据（页面结构可能已改版）。页面片段: {snippet}")
    return st


# ───────────────────── 总战绩页 r=default/battlestat ─────────────────────


def _parse_total(html_text: str) -> TotalStats:
    ts = TotalStats()
    m = re.search(r'<p class="name">([^<]*)</p>', html_text)
    if m:
        ts.player = _strip(m.group(1))
    ui = _block(html_text, "user-info fl")
    if ui:
        m = re.search(r'<img src="([^"]+)"', ui)
        if m:
            ts.avatar = m.group(1)
    pw = _block(html_text, "power fl")
    if pw:
        m = re.search(r'<span class="num">([^<]*)</span>', pw)
        if m:
            ts.power = _strip(m.group(1))
        m = re.search(r'<span class="float-num">([\s\S]*?)</span>', pw)
        if m:
            ts.power_delta = _strip(m.group(1))

    m = re.search(r'<p class="totalRecord-otherInfo__length">([^<]+)</p>', html_text)
    if m:
        ts.join_days = _strip(m.group(1))
    m = re.search(r'<p class="totalRecord-otherInfo__time">([^<]+)</p>', html_text)
    if m:
        ts.join_date = _strip(m.group(1))

    # 头部 4 项：胜率 / 伤害 / 助攻 / 经验（场均口径见页内标注，直接按页面展示保存）
    for li in re.findall(r"<li>([\s\S]*?)</li>", _block(html_text, "totalRecord-data1 clearfix")):
        t = re.search(r'<p class="title">([^<]+)</p>', li)
        n = re.search(r'<p class="num">([^<]*)</p>', li)
        if t and n:
            ts.headline[_strip(t.group(1))] = _strip(n.group(1))

    # 总体/场均 4 列（击毁 占领 防守 发现）
    head_blk = _block(html_text, "totalRecord-data2__tableHead")
    body_blk = _block(html_text, "totalRecord-data2__tableBody")
    if head_blk:
        for row in _rows(head_blk)[:1]:
            ts.total_cols = _td_cells(row)
    if body_blk:
        rows = _rows(body_blk)
        if rows:
            ts.total_row = _td_cells(rows[0])
        if len(rows) > 1:
            ts.avg_row = _td_cells(rows[1])

    # 最近常用坦克表（tbody）
    idx = html_text.find("<h3>最近常用坦克</h3>")
    if idx >= 0:
        seg = html_text[idx : html_text.find("</table>", idx)]
        for row in _rows(seg):
            cells = _td_cells(row)
            if not cells or "坦克名称" in cells[0]:
                continue
            tr = TotalTankRow()
            m = re.search(r"<span>([^<]+)</span>", row)
            if m:
                tr.name = _strip(m.group(1))
            elif cells:
                tr.name = cells[0]
            if len(cells) > 1:
                tr.battles = cells[1]
            if len(cells) > 2:
                tr.win_rate = cells[2]
            if len(cells) > 3:
                tr.power = cells[3]
            ts.recent_tanks.append(tr)

    if not ts.power and not ts.headline and not ts.recent_tanks:
        snippet = _strip(html_text)[:120]
        raise ParseError(f"未能从总战绩页面解析出数据（页面结构可能已改版）。页面片段: {snippet}")
    return ts
