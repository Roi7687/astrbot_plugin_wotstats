# -*- coding: utf-8 -*-
"""指令解析（纯函数，可单测；不依赖 AstrBot 运行时）。

支持形态：
    /wot <昵称>               → ("default/index", "<昵称>")
    /wot 总 <昵称>            → ("default/battlestat", "<昵称>")
"""
from .config import ACT_INDEX, ACT_TOTAL

__all__ = ["TOTAL_KEYWORDS", "parse_target", "is_wgid"]

TOTAL_KEYWORDS = ("总战绩", "总", "total", "zong", "all")

_WGID_MIN_LEN = 5     # 真实 wgid 为 8~10 位数字；给个下限以避开"1"这类误输入


def is_wgid(value) -> bool:
    """是否是合法的 wgid（半角数字、长度 ≥5）。

    注意用 isascii()：str.isdigit() 对全角数字/上标也返回 True，会把"７０４"误判成 wgid。
    用于校验盒子页面里的 input#p_id（营地 accountId 与它相同）。
    """
    s = str(value or "").strip()
    return s.isascii() and s.isdigit() and len(s) >= _WGID_MIN_LEN


def _strip_prefix(raw: str, keywords) -> str | None:
    """若 raw 以「关键词+空格」开头，返回去掉关键词后的剩余部分（可能为空串）。"""
    low = raw.lower()
    for kw in keywords:
        if low.startswith(kw.lower() + " "):
            return raw[len(kw):].strip()
    return None


def parse_target(raw: str) -> tuple[str, str]:
    """解析「/wot [总] <目标>」。返回 (action, 目标)；无法识别时目标为原串。

    单独输入关键词（如 `/wot 总`，后面没跟目标）→ 返回空目标，由上层提示用法。
    """
    text = (raw or "").strip()
    if text.lower() in [k.lower() for k in TOTAL_KEYWORDS]:
        return ACT_TOTAL, ""
    rest = _strip_prefix(text, TOTAL_KEYWORDS)
    if rest is not None:
        return ACT_TOTAL, rest
    return ACT_INDEX, text
