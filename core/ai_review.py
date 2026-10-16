# -*- coding: utf-8 -*-
"""AI 点评（路线 C：直接调用 astrbot_plugin_aisearch 插件）。

背景与边界
==========
`astrbot_plugin_aisearch` 是"Playwright 驱动 DeepSeek 网页版"的插件，它对外可用的
最小入口是实例方法 `_send_query(prompt, images) -> (created, answer)`：
不需要 event、不需要额外参数，把文本直接交给它即可（内部走
`DeepSeekSessionCore.send_message()`）。本模块负责：

1. 组装提示词：**分析要求在前、战绩数据在后**，合并成一串文本；
2. 通过 AstrBot 官方注册表拿到对方插件实例并调用（`Context.get_registered_star(name).star_cls`）；
3. 等待回复（带超时），把结果修剪后返回给调用方追加到回复末尾。

**跨插件调用是"尽力而为"**：对方未安装 / 未激活 / 未登录 / 超时 / 抛异常，都只记日志并
返回空串，绝不影响本插件自己的回复（本插件的主功能不依赖它）。
"""
import asyncio
import logging
import re

from .config import (
    AI_REVIEW_IMAGES,
    AI_REVIEW_MAX_CHARS,
    AI_REVIEW_PLUGIN,
    AI_REVIEW_TIMEOUT,
)

logger = logging.getLogger("astrbot")

__all__ = ["AI_REVIEW_PROMPT", "build_ai_prompt", "ask_ai_review"]

# 分析要求（放在战绩数据之前）。
#   材料依据（联网核实过，2026-10）：
#   - WG 官方 WTR 说明：评分只看 5 项——抵挡伤害 / 造成伤害 / 协助伤害 / 击毁数 / 生存率，
#     且**不同车型角色看重不同指标**（弹夹大单发→场均伤害；高射速→伤害+击毁；脆皮精准→远距离输出；
#     高机动好视野→协助伤害；重甲高血量→抵挡+造成伤害）。
#   - WG 官方「卓越印记（三环）」：只统计"场均伤害 + 有效协助伤害"的最大项，按最近 100 场与
#     同车玩家（近 14 天）比较，前 35% / 15% / 5% 分别对应一环 / 二环 / 三环（约需 50~100 场）。
#   用户要求（多轮迭代）：**必须写清原因**、**只点评 5 辆问题车**、
#   **先由数据推断问题再给建议**、**不要纯复述车辆参数/机制**（有效建议优先）。
AI_REVIEW_PROMPT = """\
你是《坦克世界》资深数据分析师兼教练，具备联网搜索能力。

【输入】我会给你一份玩家战绩数据：盒子战斗力、"近7天/近30天/生涯"三时段 WN8 与全服排名、
近 30 天场均（伤害/击毁/点亮/经验/命中率/出战等级），以及近 30 天打过的每一辆车
（单车 WN8 / 场次 / 胜率 / 场均伤害）。

【任务】输出一份**有依据、能落地**的点评：450~650 字，正好 **7 条编号要点**（①②③④⑤⑥⑦）。
重点不是介绍车，而是**指出这个玩家的具体问题并给出可执行建议**。用大白话，像教练当面讲。

【必须联网搜索】核实这 5 辆车的**当前版本**主流打法、推荐配件与技能、常见失误，
以及同车玩家的大众伤害/胜率量级（含三环线的场均"伤害+协助"量级，可用来说明差距）。
但搜到的内容**只用来说服建议**，不要整段介绍这辆车。

【选车规则（重要）】**不要**挑场次最多或数据最漂亮的车。挑「**胜率低 + WN8 低 + 场次够多**」的
**5 辆**问题车（按"拖后腿程度"从重到轻排）。选取门槛：
- 优先选场次 ≥10 的（样本够）；如果够 10 场的车不足 5 辆，可放宽到 ≥5 场，并在该条里点一句"样本偏少"；
- 数据明显没问题的车不要写（比如胜率、WN8 都在你搜到的常规量级以上）。

【怎么从数据下判断（每辆问题车都按这套先做诊断）】
把每辆车的四个数放一起看：场次、胜率、WN8、场均伤害，再对照你搜到的同车参考量级：
- 伤害够但胜率低 → 输出没换成胜利：多半是站位过前、残局贪伤害、不参与关键回合；
- 伤害低且胜率低 → 这辆车还没上手：车型不适配，或基础操作（俯角/卖头/切弹/机动）没过关；
- WN8 高、场次多、胜率却低 → 打法习惯固化，要改节奏而不是改技术；
- 胜率高但 WN8 低 → 多是跟着队友赢，个人贡献有限，提升空间在输出侧；
- 场均伤害明显低于同车常规量级 → 找不到输出机会：开局路线与卡点位需要重做；
- 场次越多、胜率越低的车，优先级越高（错误已被重复很多次，改起来收益最大）。

【分析框架（判断"该看哪个指标"时用，不要抄成车辆介绍）】
弹夹/大单发 → 场均伤害；高射速 → 伤害+击毁；精准脆皮 → 是否远距离输出；
高机动好视野 → 协助伤害；重甲高血量 → 抵挡+造成伤害；通用看生存率与"胜率是否跟上伤害"。

【输出格式】**正好 7 条编号要点**（①②③④⑤⑥⑦），450~650 字：
- ① 一句话定位：WN8 档位（<400 入门 / 400~900 一般 / 900~1300 中等偏上 / 1300~1600 良好 /
  1600~2000 优秀 / 2000+ 顶尖）+ 风格 + 三时段是进步还是停滞；
- ② 共性问题：最该修的 1~2 个问题，说清它为什么拉低成绩；
- ③~⑦ **5 条全部是车辆条目，一辆一条**，每条严格按这三步写：
  「车辆名：数据现象（场次/胜率/WN8/场均伤害之间哪里对不上）
   → 推断的问题（为什么会这样）
   → 具体怎么做（1~2 句可执行动作，要能今天就照着做）」。
- **③~⑦ 里不许出现任何非车辆内容**：不要"先改哪辆""短期目标""总结""总体上"之类的收尾段落；
  7 条就是 ① + ② + 5 辆车，写满为止。
- **不要纯复述车辆性能或参数**：禁止出现"单发 xxx""DPM 高低""装甲等效多少"这类科普句。
  车辆机制/参数只能作为"因此建议…"的从句出现（最多半句），不能单独成句占篇幅。
- 禁止 Markdown 表格 / 标题符号 / 加粗 / 表情；不要原样复述我已给的数字；不要客套话。

【数据】
"""

_TRIM_RE = re.compile(r"[ \t]+\n")


def build_ai_prompt(stats_text: str) -> str:
    """把分析要求与战绩数据合并成一串文本（要求在前、数据在后）。"""
    body = (stats_text or "").strip()
    return AI_REVIEW_PROMPT + body


def _clean_answer(text: str) -> str:
    """修剪 AI 回答：去掉多余空行/首尾空白，并限制长度（避免撑爆消息）。"""
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    s = _TRIM_RE.sub("\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    if AI_REVIEW_MAX_CHARS and len(s) > AI_REVIEW_MAX_CHARS:
        s = s[: AI_REVIEW_MAX_CHARS].rstrip() + "…"
    return s


def _resolve_instance(context, plugin_name: str):
    """从 AstrBot 注册表取出对方插件实例；不可用时返回 None（并说明原因）。"""
    if context is None:
        return None, "context 为空"
    get_star = getattr(context, "get_registered_star", None)
    if get_star is None:
        return None, "当前 AstrBot 版本没有 get_registered_star"
    try:
        md = get_star(plugin_name)
    except Exception as e:  # noqa: BLE001
        return None, f"查询注册表异常: {type(e).__name__}: {e}"
    if md is None:
        return None, f"未安装/未加载插件 {plugin_name}"
    if not getattr(md, "activated", True):
        return None, f"插件 {plugin_name} 处于未激活状态"
    inst = getattr(md, "star_cls", None)
    if inst is None:
        return None, f"插件 {plugin_name} 实例不可用（star_cls 为空）"
    return inst, ""


async def ask_ai_review(context, stats_text: str, *, timeout: float | None = None,
                        plugin_name: str | None = None) -> str:
    """把「分析要求 + 战绩数据」交给 aisearch 插件，返回 AI 点评正文。

    失败（未安装/未激活/未登录/超时/异常）一律返回空串，只记日志——调用方照常发出自己的回复。
    """
    text = (stats_text or "").strip()
    if not text:
        return ""
    name = plugin_name or AI_REVIEW_PLUGIN
    inst, why = _resolve_instance(context, name)
    if inst is None:
        logger.warning(f"[WotStats] AI 点评跳过：{why}")
        return ""

    sender = getattr(inst, "_send_query", None)
    if not callable(sender):
        logger.warning(f"[WotStats] AI 点评跳过：{name} 没有可用的 _send_query 方法"
                       f"（版本可能不兼容）")
        return ""

    prompt = build_ai_prompt(text)
    limit = timeout if timeout is not None else AI_REVIEW_TIMEOUT
    try:
        created, answer = await asyncio.wait_for(sender(prompt, list(AI_REVIEW_IMAGES)), limit)
    except asyncio.TimeoutError:
        logger.warning(f"[WotStats] AI 点评超时（>{limit:.0f}s，{name} 未返回）")
        return ""
    except Exception as e:  # noqa: BLE001  对方的 AuthError/ConversationError 等一律兜住
        logger.warning(f"[WotStats] AI 点评失败：{type(e).__name__}: {e}")
        return ""

    cleaned = _clean_answer(answer if isinstance(answer, str) else str(answer or ""))
    if not cleaned:
        logger.warning(f"[WotStats] AI 点评返回空内容（{name} 的返回：created={created}）")
        return ""
    _arm_idle_timer(inst)
    logger.info(f"[WotStats] AI 点评成功：{len(cleaned)} 字符（{name}，新建会话={created}）")
    return cleaned


def _arm_idle_timer(inst) -> None:
    """替对方插件重置空闲计时器（它自己的 _respond() 会做这件事，我们绕过了它）。

    不这么做的话，我们新建的会话不会被计入空闲销毁，无头浏览器可能一直挂着。
    属于对私有 API 的"最小善意调用"，失败就忽略。
    """
    try:
        conv = getattr(getattr(inst, "session", None), "current_conversation", None)
        arm = getattr(inst, "_arm_idle_timer", None)
        local_id = getattr(conv, "local_id", None)
        if local_id is not None and callable(arm):
            arm(local_id)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[WotStats] 重置对方空闲计时器失败（忽略）: {type(e).__name__}: {e}")
