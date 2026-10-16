# -*- coding: utf-8 -*-
"""坦克营地数据模型（纯数据类，无 IO、无解析逻辑）。

数据来源：官方《坦克营地》APP 的免签 HTTP 接口（https://tbox.wot.360.cn），
2026-10-16 实测字段见 research/WOTCAM_INTEGRATION_PLAN.md §2.4 与 research/camp_probe/snapshots/。

口径提示（与偶游盒子数据**不同体系，不可换算**）：
- 这里的 WN8 是营地口径的综合评分；盒子的「战斗力」是另一套体系。
- 时段只有 all / day_7 / day_30 三种；盒子是「最近 1500 场标准局」。
"""
from dataclasses import asdict, dataclass, field

__all__ = ["CampPeriod", "CampBattle", "CampTank", "CampPlayer"]


@dataclass
class CampPeriod:
    """某个时段的汇总（/tank/appuserrank?type=<all|day_7|day_30>）。

    注意：该接口的 RankList 里**没有** avgdmgasst（场均助攻），
    wotcamp/docs/api-notes.md 的字段表有误，因此这里不建模该字段。
    """

    key: str = ""            # all / day_7 / day_30
    fights: int = 0
    win: int = 0
    lose: int = 0            # 接口字段名是 less
    draw: int = 0
    wn8: float = 0.0
    win_rate: float = 0.0
    kd: float = 0.0          # 接口字段名是 "K/D"
    avgdmg: float = 0.0
    avgfrag: float = 0.0
    avgspot: float = 0.0
    avgexp: float = 0.0
    avgdef: float = 0.0
    hit_rate: float = 0.0
    avglevel: float = 0.0
    rank: int = 0            # 该时段全服排名
    population: int = 0      # 该时段有数据的玩家数


@dataclass
class CampBattle:
    """逐场战斗（/WotArena/getUserBattles，明文免签，单页上限 200）。"""

    arena_id: str = ""
    ts: int = 0              # arenaCreateTime（Unix 秒）
    tank: str = ""           # tankName（可能带引号，如 "犀牛"）
    map: str = ""
    mode: str = ""           # battleType，如 标准模式
    result: int = 0          # winResult: 1 胜 / -1 负 / 0 平
    damage: int = 0
    kills: int = 0
    assisted: int = 0        # totalAssistedDamage
    wn8: float = 0.0
    credits: int = 0
    duration: int = 0        # 秒


@dataclass
class CampTank:
    """单辆坦克的近 30 天数据（/tank/uservehiclestat）。"""

    tank_id: str = ""
    name: str = ""
    tier: int = 0            # vlevel
    type: str = ""           # vtype（heavyTank / mediumTank / …）
    fights: int = 0
    wn8: float = 0.0
    win_rate: float = 0.0
    avgdmg: float = 0.0
    avgdmgasst: float = 0.0
    kd: float = 0.0
    hit_rate: float = 0.0
    mastery: int = 0         # vehicle_mastery（三环标记）


@dataclass
class CampPlayer:
    """一次坦克营地查询的全部结果。"""

    wgid: str = ""
    nickname: str = ""
    face_url: str = ""
    last_battle_time: int = 0     # userInfo.last_time（最后一场战斗时间）
    server_time: int = 0          # 接口返回的服务器时间
    battles: list = field(default_factory=list)      # list[CampBattle]（最新在前）
    tanks_30d: list = field(default_factory=list)    # list[CampTank]（按近 30 天 WN8 降序）
    periods: dict = field(default_factory=dict)      # {"all"/"day_7"/"day_30": CampPeriod}

    # ── 便捷访问 ──

    def period(self, key: str) -> CampPeriod | None:
        p = self.periods.get(key)
        return p if p and p.fights else None

    @property
    def day_7(self) -> CampPeriod | None:
        return self.period("day_7")

    @property
    def day_30(self) -> CampPeriod | None:
        return self.period("day_30")

    @property
    def all_time(self) -> CampPeriod | None:
        return self.period("all")

    @property
    def recent_win(self) -> int:
        return sum(1 for b in self.battles if b.result == 1)

    @property
    def recent_wn8_avg(self) -> float:
        return sum(b.wn8 for b in self.battles) / len(self.battles) if self.battles else 0.0

    def to_dict(self) -> dict:
        return asdict(self)
