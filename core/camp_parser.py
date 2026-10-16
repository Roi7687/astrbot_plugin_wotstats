# -*- coding: utf-8 -*-
"""解析层：坦克营地接口 JSON → 数据模型（纯函数，可单测）。

所有字段名与容错策略集中在本文件；接口改字段时只需改这里 + 更新
tests/fixtures/camp_*.json（素材来自 research/camp_probe/snapshots/）。

errno 语义（2026-10-16 实测）：
    0    成功（**wgid 不存在时 errno 仍为 0**，但 userInfo.nick_name 为空 → 判为查无此人）
    2000 用户需要登录（缺 accountId / 调了需登录接口）
    2003 pkey empty（参数名写错，如 getUserBattles 用 accountId 而非 uid）
    400  sign check wrong（需签名接口，本插件不碰）
"""
import math

from .camp_model import CampBattle, CampPeriod, CampTank
from .config import CAMP_PERIODS, CampError, CampNotFoundError

__all__ = [
    "check_payload",
    "parse_period",
    "parse_battles",
    "parse_tank",
    "pick_tank_ids",
    "extract_user_info",
]

_MAX_INT = 2 ** 31  # 防止接口给出异常大值把排版撑坏


def _num(value, default: float = 0.0) -> float:
    """转 float；非法值（含 inf / nan）一律回退默认值。

    注意 inf：JSON 里的 1e999 会被 python 解析成 inf，若原样透传，
    排版层的 int(round(inf)) 会抛 OverflowError 把整条回复弄没（已踩坑）。
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _int(value, default: int = 0) -> int:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    v = int(v)
    return v if -_MAX_INT < v < _MAX_INT else default


def _text(value) -> str:
    """字符串字段容错：None/数字/其它标量都能安全转成 str 并去空白。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _as_dict(value) -> dict:
    """接口偶尔会把对象字段返回成 list/null → 统一成 dict，避免 .get 抛异常。"""
    return value if isinstance(value, dict) else {}


def check_payload(payload: dict, path: str = "") -> dict:
    """校验 errno 并返回 data 段；异常统一抛 CampError。"""
    if not isinstance(payload, dict):
        raise CampError(f"{path} 返回非 JSON 对象")
    errno = payload.get("errno")
    # 兼容 errno 被写成字符串 "0" 的情况
    if errno not in (0, None) and str(errno) != "0":
        raise CampError(f"{path} 返回 errno={errno} {payload.get('errmsg')}")
    return _as_dict(payload.get("data"))


def extract_user_info(payload: dict) -> dict:
    """从总览响应里取玩家信息；nick_name 为空 → CampNotFoundError。"""
    data = check_payload(payload, "/tank/appuserrank")
    ui = _as_dict(data.get("userInfo"))
    nick = _text(ui.get("nick_name"))
    if not nick:
        raise CampNotFoundError("坦克营地查无此人（userInfo.nick_name 为空）")
    return {
        "nickname": nick,
        "face_url": _text(ui.get("face_url")),
        "last_battle_time": _int(ui.get("last_time")),
        "server_time": _int(payload.get("time")),
    }


def parse_period(payload: dict, period: str) -> CampPeriod:
    """总览响应 → CampPeriod（不校验昵称，见 extract_user_info）。"""
    if period not in CAMP_PERIODS:
        raise CampError(f"未知时段 {period!r}")
    data = check_payload(payload, f"/tank/appuserrank?type={period}")
    rl = _as_dict(data.get("RankList"))
    return CampPeriod(
        key=period,
        fights=_int(rl.get("fights")),
        win=_int(rl.get("win")),
        lose=_int(rl.get("less")),          # 接口用 less 表示负场
        draw=_int(rl.get("draw")),
        wn8=_num(rl.get("WN8")),
        win_rate=_num(rl.get("win_rate")),
        kd=_num(rl.get("K/D")),
        avgdmg=_num(rl.get("avgdmg")),
        avgfrag=_num(rl.get("avgfrag")),
        avgspot=_num(rl.get("avgspot")),
        avgexp=_num(rl.get("avgexp")),
        avgdef=_num(rl.get("avgdef")),
        hit_rate=_num(rl.get("hit_rate")),
        avglevel=_num(rl.get("avglevel")),
        rank=_int(rl.get("rank")),
        population=_int(data.get("size")),
    )


def parse_battles(payload: dict, want: int = 20) -> list:
    """逐场战斗响应 → list[CampBattle]（保持接口顺序：最新在前）。

    注：winResult 由接口定义为 1 胜 / -1 负 / 0 平；字段缺失时按 0 处理（渲染为平局），
    实测 2026-10-16 的 20 场样本均带该字段。
    """
    data = check_payload(payload, "/WotArena/getUserBattles")
    rows = data.get("battleList") or []
    if not isinstance(rows, list):
        return []
    out = []
    for b in rows[: max(0, want)]:
        if not isinstance(b, dict):
            continue
        out.append(CampBattle(
            arena_id=_text(b.get("arenaId")),
            ts=_int(b.get("arenaCreateTime")),
            tank=_text(b.get("tankName")),
            map=_text(b.get("mapName")),
            mode=_text(b.get("battleType")),
            result=_int(b.get("winResult")),
            damage=_int(b.get("damageDealt")),
            kills=_int(b.get("kills")),
            assisted=_int(b.get("totalAssistedDamage")),
            wn8=_num(b.get("wn8")),
            credits=_int(b.get("credits")),
            duration=_int(b.get("duration")),
        ))
    return out


def parse_tank(payload: dict, tank_id: str) -> CampTank | None:
    """单车响应 → CampTank；该时段没打过（fights=0）或没有该车（list 空）→ None。"""
    data = check_payload(payload, f"/tank/uservehiclestat?tankid={tank_id}")
    rows = _as_dict(data.get("vBattles")).get("list") or []
    if not isinstance(rows, list):
        return None
    row = next((r for r in rows if isinstance(r, dict) and _int(r.get("fights")) > 0), None)
    if row is None:
        return None
    return CampTank(
        tank_id=_text(tank_id),
        name=_text(row.get("vehicle_name")) or _text(row.get("name")),
        tier=_int(row.get("vlevel")),
        type=_text(row.get("vtype")),
        fights=_int(row.get("fights")),
        wn8=_num(row.get("WN8")),
        win_rate=_num(row.get("win_rate")),
        avgdmg=_num(row.get("avgdmg")),
        avgdmgasst=_num(row.get("avgdmgasst")),
        kd=_num(row.get("K/D")),
        hit_rate=_num(row.get("hit_rate")),
        mastery=_int(row.get("vehicle_mastery")),
    )


def pick_tank_ids(battles: list, catalog: dict, limit: int = 12, extra_names=None) -> list:
    """挑出要查近 30 天数据的 tank_id（去重、保持顺序、最多 limit 辆）。

    官方没有"玩家的单车列表"接口，因此候选来自两处：
      1. extra_names（推荐）：盒子「常用坦克」的车名——这些才是玩家真正的主力车；
      2. battles：最近战斗里出现过的车（兜底，盒子不可用时仍能取到数据）。
    catalog 为 {归一化车名: tank_id}，见 core/tanks.py。
    """
    from .tanks import normalize_name  # 局部导入，避免循环依赖

    seen, ids = set(), []

    def add(name):
        tid = catalog.get(normalize_name(name)) if name else None
        if tid and str(tid) not in seen and len(ids) < limit:
            seen.add(str(tid))
            ids.append(str(tid))

    for name in (extra_names or []):
        add(name)
    for b in battles:
        if len(ids) >= limit:
            break
        add(b.tank)
    return ids
