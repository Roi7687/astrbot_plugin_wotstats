# -*- coding: utf-8 -*-
"""坦克目录：车名 → tank_id 的只读静态映射。

为什么需要它：官方没有"玩家的单车列表"接口，而"近 30 天常用坦克"必须按 tank_id 逐辆查
（/tank/uservehiclestat?tankid=...&accountId=...）。全目录扫描 998 辆 ≈40 秒，聊天场景不可用，
所以用"最近战斗里出现过的车名"作为清单，再用本目录把车名翻译成 tank_id。

数据来源：wotcamp/tank_catalog.json（由 /rank/more 榜单接口构建，992 条）。
assets/tank_catalog.json 由 scripts/build_tank_catalog.py 生成，**只读**，运行期不写任何文件。
未收录的车（新车）会被直接跳过，不影响其它车与主流程。
"""
import json
import re
from functools import lru_cache

from .config import TANK_CATALOG_FILE

__all__ = ["normalize_name", "load_catalog", "clear_cache"]

# 归一化时去掉的字符：引号/空格/连字符/点/下划线等（战斗记录里车名可能写作 "犀牛"、Vz.58 "熊"）
_STRIP_RE = re.compile(r"[\s\"'“”‘’·．.\-—_]+")
_QUOTE_RE = re.compile(r'^[\s"\'“”‘’]+|[\s"\'“”‘’]+$')


def normalize_name(name: str) -> str:
    """车名归一化：去引号/空格/连字符/点/下划线，转小写。"""
    return _STRIP_RE.sub("", str(name or "")).lower()


def strip_quotes(name: str) -> str:
    """显示用车名：去掉接口原样返回的首尾引号（如 '"犀牛"' → '犀牛'）。"""
    return _QUOTE_RE.sub("", str(name or "")).strip()


@lru_cache(maxsize=1)
def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    for tank_id, entry in raw.items():
        # 兼容两种缓存格式：{"id": "名字"} 与 {"id": {"name": ...}}
        name = entry if isinstance(entry, str) else (entry or {}).get("name", "")
        key = normalize_name(name)
        if key and key not in out:
            out[key] = str(tank_id)
    return out


def load_catalog(path: str | None = None) -> dict:
    """加载 {归一化车名: tank_id}；文件缺失时返回空字典（功能降级，不抛错）。"""
    try:
        return _load(path or TANK_CATALOG_FILE)
    except (OSError, ValueError):
        return {}


def clear_cache() -> None:
    """测试用：清掉 lru_cache。"""
    _load.cache_clear()
