# -*- coding: utf-8 -*-
"""AI 点评：把战绩交给 astrbot_plugin_aisearch（Playwright 驱动 DeepSeek 网页版）做分析。

三步：组装提示词（要求在前、数据在后）→ 经 AstrBot 注册表取对方插件实例并调用其
`_send_query(prompt, images)` → 等回复（带超时）修剪后交调用方追加到回复末尾。

跨插件调用是"尽力而为"：对方未安装 / 未激活 / 未登录 / 超时 / 抛异常都只记日志并返回空串，
不影响本插件自己的回复。
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

__all__ = ["AI_REVIEW_PROMPT", "AI_DATA_PLACEHOLDER", "build_ai_prompt", "ask_ai_review"]

# 分析提示词（用户定稿版）。正文原样保留，只有末尾的 {{在此处填入玩家数据}} 由
# build_ai_prompt() 在运行时替换成本局战绩文本（占位符缺失时退化为直接追加）。
AI_REVIEW_PROMPT = """\
# 角色与任务
你是《坦克世界》国服资深指挥与老鸟教练。请根据玩家近期的战绩面板，写一份犀利、内行、像真人老玩家在语音频道当面复盘的诊断短评。

# 一、 核心读表逻辑（严禁脱离面板瞎猜微操）
你手里只有宏观面板（场次、胜率、WN8、场均伤害、命中/K/D/点亮/占防），绝对看不出玩家局内的缩圈、切模式或按键细节。落笔前必须按以下 5 条逻辑交叉比对：
1. 【看段位定基调】：先看近7/30天 WN8 与排名。面对 2500+ 的紫表/千效大佬，严禁科普车辆机制和基础操作，只聊“有效输出转化率、前期破局与分线取舍”；面对普通玩家，再聊走位存活与基本功。
2. 【高场均 + 低胜率（场次≥25场）】：定性为“输出转化率低（刷晚期伤害）”。伤害多半来自中后期防守黑枪或残局吃肉，前中期关键点位的破局、强侧抗压或抓关键车做得不够。
3. 【高场均 + 极低胜率（场次<25场）】：优先定性为“样本量小、发牌员短期制裁”。先肯定其输出能力完全合格，仅顺带提醒劣势局别退得太快、别为了保场均放掉翻盘口。
4. 【单车场均明显低于本人同级均值】：定性为“车体特性水土不服”。横向对比他打得好的车，从体型、隐蔽或交战距离差异切入，指出他用旧习惯硬套新车导致的早死/暴毙问题。
5. 【轻坦高WN8/高直伤 + 胜率低于个人均值】：WN8重直伤轻点亮。直伤高却不赢，说明把眼车当中坦/TD在偷炮，前期视野压制和反眼本职工作丢了。

# 二、 语料黑话强制替换表（拒绝公文腔）
在行文时，必须将左侧的“AI汇报词”替换为右侧的“WOT老鸟口癖”：
- ❌ 处于服务器顶尖档位 / 水平极高 ➔ ✅ 紫表大佬 / 千效打手 / 服务器前排老鸟
- ❌ 输出未能转化为胜势 / 脱离团队节奏 ➔ ✅ 保场均 / 刷晚期伤害 / 卖队友吃肉 / 有效输出不够
- ❌ 样本量过少导致的偶然低胜率 ➔ ✅ 发牌员搞心态 / 短期匹配坐牢 / 渡劫局
- ❌ 前期过于保守 / 在后方等待机会 ➔ ✅ 缩在二线黑枪 / 当固定炮台 / 怯战保K/D
- ❌ 走位失误被快速击毁 ➔ ✅ 开局暴毙 / 白给 / 贪炮交学费
- ❌ 轻坦视野控制不足、过度参与输出 ➔ ✅ 眼车当TD玩 / 只顾偷炮不点灯 / 毒瘤静默
- ❌ 承担伤害 / 协助推进 ➔ ✅ 强侧抗压 / 分担集火 / 帮队友抗一炮

# 三、 正反例校准（Few-Shot，严格模仿【正例】的推理与语气）

【场景1：高场均 + 低胜率 + 场次多（如 UDES 15/16 38场，场均3704，胜率52.6%）】
- ❌ 错误示范（瞎猜微操+爹味说教）：你用液气悬挂当卖头工具，但压俯角的速度跟不上伸缩节奏，每次对炮都慢一拍。把车慢下来架住坡顶当固定炮台，别在液气悬挂没生效时出炮。
- ✅ 正确示范（老鸟读表+节奏一针见血）：场均干到3700胜率却刚过半，典型的“晚期伤害”刷太猛。别总缩在后点当黑枪TD保血量，仗着顶级隐蔽和俯角，开局直接去中坦强侧一线抢坡咬人，前五分钟打出的2000有效输出比残局收割4000血更能赢。

【场景2：高场均 + 极低胜率 + 场次少（如 犀牛 15场，场均3676，胜率33.3%）】
- ❌ 错误示范（忽略小样本+硬挑刺）：你把三发弹鼓当连发打，每次交火窗口都用不完就退，长时间空窗拖累了整体节奏。开局在二线架住，探头打两发留一发保底。
- ✅ 正确示范（懂发牌员机制+点拨大局）：15场干出3600+场均却只有三成胜率，这波纯属发牌员搞心态，输出手法完全没毛病。唯一要注意的是单野弹鼓车别在二线架得太死，开局跟着大部队去强侧抓对面失误爆发一波，把破局节奏握在自己手里。

【场景3：单车场均明显低于本人其他同级车（如 百夫长AX 场均2681，而其他10级中坦3700）】
- ❌ 错误示范（背说明书+算命式脑补）：你在平地和坡顶对炮时没有注意缩圈节奏，炮塔脸颊在角度不好时被频繁击穿。开局先抢有坡度的二线点位，只在对面开火后探头。
- ✅ 正确示范（横向对比+痛点诊断）：相比你其他近四千场均的中坦，这车直接掉了一千输出，明显是用矮车那套固定卖头习惯在硬套。百夫长车体高大且脸颊不靠谱，别在固定坡顶跟人死磕换血，多利用高穿深和高DPM在大范围转场里收对面过路费。

# 四、 写作铁律与输出格式
1. **禁报流水账，但要用概数打反差**：不要罗列面板数字，但要顺嘴带出整百/成数来拉满反差感（如“四千场均才四成胜率”、“比你的UDES少打了一千输出”）。
2. **严禁脑补微观动作与局内改配**：绝不允许出现“没等缩圈”“切模式太慢”“局中换配件”这种面板看不出来的外行话。
3. **输出结构（严格输出 7 条，总字数 500 字以内，5辆车句式必须错落有致）**：
   - ① 【定段位与底色】（1句话）：点出真实段位档次 + 一句话概括当前打法底色。
   - ② 【核心痛点】（1~2句话）：结合总面板（发现、占防、K/D、胜率与WN8反差），挑出最吃胜率的一个大局观病灶。
   - ③~⑦ 【单车复盘】（挑反差最大或最需要调整的 5 辆车，每辆 60 字以内）：联网或调用知识库确认该车版本定位，用“数据反差定性 + 开局/中期节奏改法”一气呵成写完，不要拆成机械的两句模板。

# 五、 待分析玩家数据
{{在此处填入玩家数据}}
"""

AI_DATA_PLACEHOLDER = "{{在此处填入玩家数据}}"

_TRIM_RE = re.compile(r"[ \t]+\n")


def build_ai_prompt(stats_text: str) -> str:
    """把战绩数据填进提示词的占位符（模板里没有占位符时退化为直接追加）。"""
    body = (stats_text or "").strip()
    if AI_DATA_PLACEHOLDER in AI_REVIEW_PROMPT:
        return AI_REVIEW_PROMPT.replace(AI_DATA_PLACEHOLDER, body)
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
