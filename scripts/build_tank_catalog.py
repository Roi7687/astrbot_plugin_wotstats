#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成插件用的坦克目录静态资产：assets/tank_catalog.json。

来源：wotcamp/tank_catalog.json（由开发者用 /rank/more 榜单接口构建，992 条）。
产物格式：**{"tank_id": "车名"}**（与来源一致，便于直接对照），只读；
运行期由 core/tanks.py 读入内存并归一化成 {归一化车名: tank_id}。
新增车辆后重跑本脚本即可刷新（未收录的车在插件里会被跳过，不影响主流程）。

用法（插件根目录）：
    python scripts/build_tank_catalog.py            # 用默认来源
    python scripts/build_tank_catalog.py --src <path> -o assets/tank_catalog.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / "wotcamp" / "tank_catalog.json"
DEFAULT_OUT = ROOT / "assets" / "tank_catalog.json"


def load_source(path: Path) -> dict:
    """{"id": "车名"} 或 {"id": {"name": ...}} → {"id": "车名"}（去掉空名）。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for tank_id, entry in raw.items():
        name = entry if isinstance(entry, str) else (entry or {}).get("name", "")
        name = (name or "").strip()
        if name:
            out[str(tank_id)] = name
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 assets/tank_catalog.json")
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    if not args.src.exists():
        print(f"来源不存在：{args.src}", file=sys.stderr)
        return 2
    catalog = load_source(args.src)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
    size_kb = args.out.stat().st_size / 1024
    print(f"已生成 {args.out}（{len(catalog)} 辆，{size_kb:.1f} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
