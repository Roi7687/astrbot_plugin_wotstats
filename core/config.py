# -*- coding: utf-8 -*-
"""全局配置：站点 URL、抓取参数、回复样式与自定义异常。

数据口径说明（2026-09 实测，详见插件根目录 research/SITE_PROBE_REPORT.md）：
- 门户入口 wot.ouj.com/zhanji/index.html 只是"壳"页，真实查询界面在 iframe 内
  （wotbox.ouj.com/playerSearch2018.php），提交后 GET 到本文件 QUERY_ENDPOINT。
- 纯 HTTP GET 即返回服务端渲染 HTML（UTF-8），无需登录 / Cookie / 浏览器自动化。
- 查无此人也返回 HTTP 200，需按页面内 .not-find-user 块判定。
"""
import os

# 插件根目录绝对路径（core/ 的上级目录；仅用于定位，不写入任何运行期文件）
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 站点 URL ──
WOTBOX_BASE = "https://wotbox.ouj.com"
QUERY_ENDPOINT = WOTBOX_BASE + "/wotbox/index.php"   # 战绩查询后端（表单 GET 目标）
PLAYER_SEARCH_HOME = WOTBOX_BASE + "/playerSearch2018.php"  # 搜索页（真实查询入口）
PORTAL_PAGE = "https://wot.ouj.com/zhanji/index.html"       # 用户提供的门户入口

# ── r= 页面动作 ──
ACT_INDEX = "default/index"          # 个人战绩（近期 1500 场标准局）
ACT_CARPORT = "default/carport"      # 车库
ACT_BATTLELOG = "default/battlelog"  # 战斗日志（另需 &p=页码）
ACT_TOTAL = "default/battlestat"     # 总战绩（全时段）
ACT_MOBILE = "default/mobile"        # App 日志

# ── 抓取参数 ──
HTTP_TIMEOUT = 15.0        # 单次请求超时（秒）
HTTP_RETRY = 2             # 网络异常/5xx 的重试次数（幂等 GET，可安全重试）
# 偶游盒子的查询接口对本机 IP 有严格配额：短时间多次请求后会长时间返回 403
# （2026-10-16 实测；详见 research/WOTCAM_INTEGRATION_PLAN.md §2.2）。
# 浏览器 UA 在该站从未成功过一次，因此这里刻意使用"非浏览器标识串"。
USER_AGENT = "astrbot-plugin-wotstats/0.2 (+https://github.com/Roi7687/astrbot_plugin_wotstats)"
RATE_LIMIT_COOLDOWN = 40   # 撞 403 后建议的冷却秒数（仅用于提示文案）

# ── 坦克营地（tbox.wot.360.cn，官方 APP 数据源）──
# 2026-10-16 实测：全部免签接口用 httpx 直接可访问，无需 curl_cffi / 无需登录 / 无需落盘。
CAMP_API_BASE = "https://tbox.wot.360.cn"
CAMP_REFERER = "https://camp.wot.360.cn/"
CAMP_HOME = "https://camp.wot.360.cn/"          # 展示用（来源行）
CAMP_TIMEOUT = 10.0
CAMP_RETRY = 2
CAMP_PERIODS = ("all", "day_7", "day_30")       # 生涯 / 近 7 天 / 近 30 天
CAMP_PERIOD_CN = {"all": "生涯", "day_7": "近 7 天", "day_30": "近 30 天"}

CAMP_ENABLED = True        # 总开关：/wot 是否附带营地数据（速览 + 常用坦克表）
# 「三环」榜单入口（/wot3h 直接回复这个链接，方便在浏览器里查看）
THREE_RING_URL = ("https://camp.wot.360.cn/activity.html"
                  "#/AIrankDetailListThreeRing?type=mastery")
# 「常用坦克」= 营地近 CAMP_SCAN_DAYS 天内打过的全部车（以营地为准，不再受盒子 TOP5 限制）
CAMP_SCAN_DAYS = 30            # 时间窗（天）
CAMP_SCAN_MAX_BATTLES = 600    # 时间窗内最多翻多少场（安全上限，防止极端活跃玩家打爆请求数）
CAMP_BATTLE_PAGE_SIZE = 100    # 逐场单页条数（越小越快：100 条 ≈0.8s，200 条 ≈1.7s）
CAMP_BATTLE_BATCH = 3          # 一次并发翻几页（减小总体等待，营地侧不限流）
CAMP_TANKS_SCAN = 60           # 最多为多少辆车查近 30 天单车数据（超出部分丢弃）
CAMP_TANKS_TOP = 0             # 展示条数：0 = 全部（用户要求显示 30 天内全部常用坦克）
CAMP_CACHE_TTL = 0         # 进程内缓存秒数（0=不缓存，遵守"运行时零缓存"约定）
WGID_CACHE_TTL = 21600     # 昵称→wgid 的进程内缓存秒数（6 小时；只是 ID 映射，非战绩数据）

# ── AI 点评（跨插件调用 astrbot_plugin_aisearch，实现见 core/ai_review.py）──
AI_REVIEW_ENABLED = True    # /wot <昵称> 末尾是否追加「AI评价：……」
AI_REVIEW_PLUGIN = "astrbot_plugin_aisearch"   # 提供对话能力的插件名（换了插件改这里）
AI_REVIEW_TIMEOUT = 120.0   # 等对方回复的上限（秒；对方是浏览器自动化，通常 10~60s）
AI_REVIEW_IMAGES = ()       # 随附图片（本条链路不需要，保持空元组）
AI_REVIEW_MAX_CHARS = 1400  # AI 点评正文最大长度（超出截断；提示词要求 400~600 字 / 6~8 条）

# 坦克目录静态资产（车名 → tank_id）。由 wotcamp/tank_catalog.json 生成，只读、运行期不写。
TANK_CATALOG_FILE = os.path.join(PLUGIN_DIR, "assets", "tank_catalog.json")

# ── 官方玩家搜索（wotgame.cn，用于「昵称 → wgid」，2026-10-16 实测）──
# GET https://wotgame.cn/zh-cn/community/accounts/search/?name=<昵称>
# → {"response": [{"account_id": "<wgid>", "account_name": ..., "clan_tag": ...}]}
# 免登录、免签名；实测 15 次连发全 200（1.4s）；大小写不敏感；返回 ≤25 条模糊匹配，需自行挑精确项。
# 注意：服务端要求昵称 **至少 4 个字符**（不足返回 HTTP 409），短昵称需回落到盒子页面取 p_id。
WG_SEARCH_URL = "https://wotgame.cn/zh-cn/community/accounts/search/"
WG_PORTAL_REFERER = "https://wotgame.cn/zh-cn/community/accounts/"
WG_SEARCH_MIN_LEN = 4
WG_SEARCH_TIMEOUT = 10.0

# ── 昵称约束（服务端要求长度 > 1，大小写敏感；中文昵称常见）──
NAME_MIN_LEN = 2
NAME_MAX_LEN = 32


def is_valid_nickname(name: str) -> bool:
    """昵称合法性：2~32 字符，仅字母数字/下划线/连字符/点/空格（含中文等 Unicode 字母）。
    服务端要求长度大于 1；昵称大小写敏感（不做大小写折叠）。
    """
    if not isinstance(name, str):
        return False
    n = len(name)
    if n < NAME_MIN_LEN or n > NAME_MAX_LEN:
        return False
    for ch in name:
        if ch.isalnum() or ch in "_- .":
            continue
        return False
    return True

# ── 数据口径 ──
STATS_WINDOW_NOTE = "只算最近 1500 场标准局"   # 站方近期战绩口径（页面注明）

# ── 回复样式 ──
# auto: QQ 官方平台用 qq_md（官方 Markdown 语法排版），其他平台纯文本
# table: 强制通用 Markdown 表格排版（适合支持 GFM 表格的渠道/自测预览）
# qq_md / plain: 强制指定某一种排版
REPLY_STYLE = "auto"

# 原生 Markdown 消息（msg_type=2）可用的 QQ 官方平台名（AstrBot 内置适配器）
QQ_OFFICIAL_PLATFORM_NAMES = ("qq_official", "qq_official_webhook")

class WotQueryError(Exception):
    """网络层异常：超时 / 非 200 / 站点不可达"""


class PlayerNotFoundError(Exception):
    """查无此人（站点返回 .not-find-user 提示块）"""


class RateLimitedError(WotQueryError):
    """站点限流（HTTP 403）：偶游盒子对单 IP 有严格配额，需等待后重试。"""


class ParseError(Exception):
    """HTML 解析失败（页面结构可能改版，需更新 core/parser.py 并刷新 research 快照）"""


class CampError(Exception):
    """坦克营地接口异常：网络 / errno!=0 / 响应结构异常"""


class CampNotFoundError(CampError):
    """坦克营地查无此人（errno=0 但 userInfo.nick_name 为空）"""


class WgSearchError(Exception):
    """官方玩家搜索（wotgame.cn）失败：网络 / 非 200 / 响应结构异常"""


class WgTooShortError(WgSearchError):
    """官方搜索要求昵称至少 4 个字符（服务端 HTTP 409）"""

