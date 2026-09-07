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
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

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


class ParseError(Exception):
    """HTML 解析失败（页面结构可能改版，需更新 core/parser.py 并刷新 research 快照）"""

