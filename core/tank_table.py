# -*- coding: utf-8 -*-
"""常用坦克表（独立模块）：**营地优先，盒子仅作可选补充**。

为什么单独拆出来
================
「常用坦克」这一块里，**除了「盒子效率」以外，所有字段都来自官方坦克营地**
（单车 WN8、近 30 天场次、胜率、场均伤害、助攻、K/D、命中率、等级）。
盒子只可能补一项：单车战斗力（它的口径是"近 1500 场"，且只有首页「常用坦克」TOP5 才有）。

因此本模块按两阶段构建，职责互不耦合：

1. `rows_from_camp(camp)`   —— **主逻辑**：纯营地数据 → 行列表（不依赖盒子，盒子挂了也有完整内容）；
2. `enrich_with_box(rows, box_tanks)` —— **可选补充**：按归一化车名匹配，把"盒子效率"填进对应行；
   匹配不上就留空，**绝不猜**（避免 T-34 与 T-34-85 张冠李戴）。

渲染层据此决定：没有盒子数据时整段不显示"盒子效率"，有则逐行追加。
"""
from dataclasses import dataclass

from .camp_model import CampPlayer
from .tanks import normalize_name

__all__ = ["TankRow", "rows_from_camp", "enrich_with_box", "build_tank_rows"]


@dataclass
class TankRow:
    """一行单车数据。

    camp_* 为**主数据**（官方营地近 30 天）；box_power 为**可选补充**（偶游盒子单车战斗力）。
    """

    # ── 营地（近 30 天）──
    name: str = ""
    tier: int = 0
    tank_id: str = ""
    wn8: float = 0.0
    fights: int = 0
    win_rate: float = 0.0
    avgdmg: float = 0.0
    avgdmgasst: float = 0.0
    kd: float = 0.0
    hit_rate: float = 0.0
    mastery: int = 0          # 实测恒为 0，暂不展示（见 AGENTS.md §5.4 坑位 7）

    # ── 盒子（可选补充：只有"盒子效率"这一项）──
    box_power: str = ""
    box_battles: str = ""

    @property
    def has_box(self) -> bool:
        """是否有可用的盒子效率补充。"""
        return bool(self.box_power)


def rows_from_camp(camp: CampPlayer) -> list:
    """**营地口径**生成行列表：只保留近 30 天确实打过（fights>0）的车。

    `CampPlayer.tanks_30d` 已由取数层按"近 30 天场次降序"排好（常用优先），此处保持顺序。
    """
    rows = []
    for t in (camp.tanks_30d if camp else []) or []:
        if not t.name or t.fights <= 0:
            continue
        rows.append(TankRow(
            name=t.name, tier=t.tier, tank_id=str(t.tank_id or ""),
            wn8=t.wn8, fights=t.fights, win_rate=t.win_rate,
            avgdmg=t.avgdmg, avgdmgasst=t.avgdmgasst, kd=t.kd,
            hit_rate=t.hit_rate, mastery=t.mastery,
        ))
    return rows


def _box_index(box_tanks) -> dict:
    """盒子常用坦克 → {归一化车名: TankDetail}（同名只保留第一个）。"""
    out = {}
    for t in box_tanks or []:
        name = t.get("name") if isinstance(t, dict) else getattr(t, "name", "")
        if name:
            out.setdefault(normalize_name(name), t)
    return out


def _field(t, key: str) -> str:
    value = t.get(key) if isinstance(t, dict) else getattr(t, key, None)
    return str(value) if value not in (None, "") else ""


def enrich_with_box(rows: list, box_tanks) -> int:
    """**可选补充**：把盒子效率填进同名行，返回成功补充的行数。

    box_tanks 可以为 None/空（盒子被限流、查无此人等）——此时不做任何事，行数据保持纯营地口径。
    """
    if not rows or not box_tanks:
        return 0
    index = _box_index(box_tanks)
    hits = 0
    for row in rows:
        box = index.get(normalize_name(row.name))
        if box is None:
            continue
        power = _field(box, "power")
        if not power or power == "-":
            continue                     # 盒子自己也没有这辆车的战力 → 视为无补充
        row.box_power = power
        row.box_battles = _field(box, "battles")
        hits += 1
    return hits


def build_tank_rows(camp: CampPlayer, box_tanks=None) -> list:
    """对外入口：先取营地数据，能拿到盒子数据时再补充效率。"""
    rows = rows_from_camp(camp)
    enrich_with_box(rows, box_tanks)
    return rows
