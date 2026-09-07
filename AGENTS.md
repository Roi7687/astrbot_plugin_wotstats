# astrbot_plugin_wotstats 开发文档

> **插件名称**：坦克世界战绩查询（WoT Stats Query）
> **版本**：v0.1.1（首版编码 + 回复排版迭代完成；待 AstrBot 实机联调）
> **作者**：Roi
> **许可证**：（待定，建议参考同类插件使用 AGPL-3.0）
> **仓库地址**：https://github.com/Roi7687/astrbot_plugin_wotstats

---

## 一、项目概述

[AstrBot](https://github.com/AstrBotDevs/AstrBot) 插件：用户发送 `/wot <昵称>`（或 `/wot 总 <昵称>`），
机器人抓取**偶游盒子战绩查询站**（入口 https://wot.ouj.com/zhanji/index.html ，真实数据后端 wotbox.ouj.com）的
服务端渲染 HTML 并解析，回复玩家近期/总战绩摘要。

核心思路：**纯 HTTP GET 抓取服务端渲染 HTML + 正则解析**——2026-09-07 已用真实浏览器与纯 HTTP 双重验证：
无需登录、无需 Cookie、无需浏览器自动化（调研落盘见 research/）。cloakbrowser 浏览器自动化
（参考 astrbot_plugin_aisearch）仅为站点加反爬后的兜底选项，不进入主链路。

**架构分层**（单向依赖）：`main.py`（指令层）→ `core/fetcher.py`（抓取）→ `core/parser.py`（HTML→数据模型，纯函数）→ `core/formatter.py`（数据→回复文本，纯函数）。

**重要设计约定**：
- **运行时零落盘**：插件不缓存查询数据、不写任何状态/临时文件，只做"抓取 → 提取 → 回复"（用户明确要求）。
- 解析失败时**绝不让插件崩溃**：所有异常在 main.py 收敛为友好回复，并用 `logger.exception` 留日志。
- **无测试不可合并**：parser/formatter 是纯函数，页面结构改动必须先用 research/ 新快照更新
  tests/fixtures 再改代码（回归测试兜底）。

---

## 二、项目结构

```
astrbot_plugin_wotstats/
├── core/
│   ├── __init__.py
│   ├── config.py       # URL/超时/UA/昵称校验/样式常量/自定义异常
│   ├── fetcher.py      # WotBoxFetcher：纯 HTTP GET + 重试（可注入 httpx client 便于测试）
│   ├── parser.py       # HTML → PlayerStats / TotalStats（纯函数，选择器集中于此）
│   └── formatter.py    # 数据 → qq_md / plain / table 三种风格文本（纯函数）
├── tests/              # unittest（python -m unittest discover -s tests -t .）
│   ├── fixtures/       # research/ 真实页面快照副本（正常页/总战绩页/查无此人页）
│   ├── test_parser.py
│   ├── test_formatter.py
│   └── test_fetcher.py # httpx.MockTransport，不发真实网络
├── __init__.py
├── main.py             # Star 插件：/wot 指令、风格选择、异常兜底
├── metadata.yaml
├── requirements.txt    # 无额外依赖（httpx 由 AstrBot 核心提供）
├── README.md
├── AGENTS.md           # 本文档
└── research/           # 站点调研落盘——本地开发目录，不入库（回归快照已内置于 tests/fixtures）
```

---

## 三、指令与行为

| 命令 | 行为 |
|------|------|
| `/wot <昵称>` | 个人战绩摘要：战斗力、近 1500 场标准局（胜率/胜负/命中/出战等级）、场均 6 项、常用坦克 TOP5、最近 5 局、盒子评价、数据更新时间 |
| `/wot 总 <昵称>`（或 `/wot 总战绩 <昵称>`） | 总战绩：入伍天数/日期、总胜率、场均伤害/助攻/经验、击毁/占领/防守/发现（总体+场均）、最近常用坦克 TOP5 |
| `/wot help` | 用法帮助 |
| 查无此人 | 回复可能原因（昵称大小写敏感/刚改名 3h 内同步等） |

- 昵称校验：2~32 字符，字母/数字/中文/下划线/连字符/点/空格（`core/config.is_valid_nickname`），大小写敏感不折叠。
- 中文昵称 URL 编码由 `core/fetcher.build_query_url` 处理。

## 四、回复排版（QQ 官方 Markdown 调研结论，2026-09）

### 4.1 QQ 官方群消息 API（POST /v2/groups/{group_openid}/messages）

官方文档：https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html

| 字段 | 说明 |
|------|------|
| `msg_type` | 0=纯文本(content)；2=Markdown(markdown)；7=富媒体(media)。**content 与 markdown 互斥** |
| `markdown` | `{content: "..."}`；旧模板字段 template_id / custom_template_id 已废弃（无需申请模板） |
| `keyboard` | 可选内嵌键盘（本插件暂不使用） |
| 频控 | 被动回复 msg_id 5 分钟内有效、每条最多回 5 次；机器人维度 60/qpm（认证）等 |

### 4.2 QQ 原生 Markdown **不支持表格**

官方 Markdown 支持格式清单（https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/markdown.html ）：
**标题 / 加粗 / 斜体 / 删除线 / 链接 / 图片 / 有序与无序列表 / 列表嵌套 / 块引用 / 水平分割线 / 多行**——**表格不在清单中**。
因此"表格排版"需求在 QQ 官方机器人上无法原生实现。

### 4.3 本插件的排版策略（formatter.py）

| 风格 | 适用 | 形态 |
|------|------|------|
| `qq_md`（默认，QQ 官方平台自动选用） | qq_official / qq_official_webhook | 加粗 + 无序列表 + 分割线（官方语法内最工整的排版），经 MessageChain.use_markdown(True) 以 msg_type=2 发送；被拒时 AstrBot qqofficial 适配器自动降级纯文本 |
| `table` | 支持 GFM 表格的渠道/本地预览 | 标准 Markdown 表格（含转义 `|`→`｜`） |
| `plain`（默认，其他平台） | 其他聊天平台 | 无 Markdown 标记的纯文本 |

回复内容（v0.1.1）：常用坦克行含 **场均伤害/命中率**；盒子评价**完整多条**逐行展示；新增**各车型近 1000 场单车战斗力**（0 值显示"暂无"）；结尾"数据来源："为**可点击直达查询页**的链接（qq_md/table 为 `[url](url)`，plain 输出裸 URL）。

- 平台选择：`REPLY_STYLE=auto`（config）→ 平台名含 `qq_official` 用 qq_md，否则 plain；`REPLY_STYLE` 可强制 table/qq_md/plain。
- AstrBot 侧机制：`event.make_result().message(text).use_markdown(True)`；qqofficial 适配器将
  use_markdown_ 非 False 的消息链按 msg_type=2 + markdown.content 发送，出错自动回退 content 模式。

---

## 五、数据模型（core/parser.py，2026-09 实测选择器）

### 5.1 个人战绩页 r=default/index → PlayerStats

| 字段 | 来源 |
|------|------|
| player / avatar | `.user-info .name` / 头像 img |
| power / power_delta | `.power .num` / `.power .float-num` |
| wu_id / player_id | `input#wu_id` / `input#p_id`（value） |
| updated_at | `.userRecord-history__title` 内「更新时间：」 |
| recent{win_rate,win,lose,total,hit_rate,tier,mode} | `.userRecord-charts__winRate--frame/-data`、killRate、fightingRate 等块 |
| avg_per_battle | `.userRecord-data`（ul）的 li：杀伤/经验/击毁/占领/防守/发现 |
| tanks[] | `.use-tank-list` li[tank] 顺序 + `.user-tank__pop[tank]` 弹层（名称/类型/胜率/场次/战力/场均 5 项） |
| evaluation[] | `.comment-list__text p` |
| recent_battles[] | `.userRecord-recent__box` ul>li（胜负/经验/模式/时间/坦克图） |
| class_power | 页面底部脚本 `App.init([Math.min(2000,v),...])` 五值，与 userRecord.js 蜘蛛图顺序 TD/HT/MT/SPG/LT 一一对应 |
| tabs | `.mod-tabs-trigger` a |

### 5.2 总战绩页 r=default/battlestat → TotalStats

- 头部：`.user-info .name`、`.power`；入伍：`.totalRecord-otherInfo__length/__time`
- headline：`.totalRecord-data1` li（胜率/伤害/助攻/经验）
- 四列总体/场均：`.totalRecord-data2__tableHead`（列名）+ `.totalRecord-data2__tableBody`（两行）
- 最近常用坦克：`<h3>最近常用坦克</h3>` 后表格 tbody（名称/场次/胜率/战力）

### 5.3 判空 / 改版防御

- 查无此人：页面含 `class="not-find-user"` 元素或文案「没有找到您搜索的玩家」→ PlayerNotFoundError
  （**注意**：页面内联 CSS 也含 `.not-find-user` 定义，不可只搜类名字符串——已踩坑修复）
- 核心字段全空 → ParseError（提示"页面结构可能已改版"，要求用新快照更新本文件）

---

## 六、调研记录（2026-09-07 实测）

完整报告：`research/SITE_PROBE_REPORT.md`（含全部原始 HTML 快照与选择器清单、坑位说明）。
要点：

1. wot.ouj.com/zhanji/index.html 是门户壳页，真实查询界面在 iframe：wotbox.ouj.com/playerSearch2018.php
   （表单 GET `r=default/index&pn=<昵称>`；原区服下拉已注释，仅国服）。
2. 纯 HTTP GET 即得完整服务端 HTML（UTF-8），HTTPS 200 正常；无需登录/Cookie/浏览器。
3. 模块 r 值：default/index、carport、battlelog(&p=)、battlestat、mobile。
4. 查无此人 HTTP 200（判据见 5.3）；昵称大小写敏感；近期战绩口径"只算最近 1500 场标准局"，更新非实时。
5. 战斗力刷新（#refresh）需盒子客户端登录 + 月卡 POST wotapp.ouj.com——插件不做。
6. **数据随玩家新战斗变化**：2026-09-08 实测同一玩家近 5 局已翻新（含新败局），证实为动态实时数据，不应做本地缓存（本项目即不缓存）。

---

## 七、技术栈

| 技术 | 用途 |
|------|------|
| Python 3.12+ | 主语言（async/await） |
| AstrBot API | Star / Context / filter.command / GreedyStr / make_result().use_markdown() |
| httpx（AstrBot 核心自带） | 抓取（requirements 仅声明注释，不钉版本） |
| re / html / dataclasses（stdlib） | HTML 解析与数据模型 |
| unittest（stdlib） | 单元测试（无需 pytest） |
| research/ 快照 | fixture 库 + 页面改版对照物 |

---

## 八、进度

### ✅ v0.1.1 已完成（2026-09-08）

| 项 | 说明 |
|----|------|
| 常用坦克补场均伤害/命中率 | ✅ 三风格同步更新 |
| 盒子评价完整展示 | ✅ 逐条输出全部评价 |
| 各车型近1000场单车战斗力 | ✅ 解析 App.init 五值并排版（TD/HT/MT/SPG/LT），0→暂无 |
| 来源行改为可点击直达链接 | ✅ 删除旧免责文案；QQ markdown 用 [url](url)，纯文本输出裸 URL |
| 单测 | ✅ 35/35 通过 |

### ✅ v0.1.0 已完成

| 项 | 说明 |
|----|------|
| 站点调研（入口/iframe/表单/模块/选择器） | ✅ 真实浏览器 + 纯 GET 双重验证 |
| 玩家 loy1234 数据采集与落盘 | ✅ research/（JSON 结构化 + 原始 HTML ×4 + 截图 + 报告） |
| core/config.py | ✅ URL/异常/昵称校验/样式常量 |
| core/fetcher.py | ✅ 纯 HTTP GET、重试、UTF-8 解码、URL 编码（单测 6 项） |
| core/parser.py | ✅ 个人战绩页/总战绩页/查无此人/改版防御（单测 12 项） |
| core/formatter.py | ✅ qq_md / plain / table 三风格（单测 11 项） |
| main.py | ✅ /wot 与 /wot 总 指令、平台风格选择、异常兜底（AstrBot 环境导入冒烟通过） |
| 单测 | ✅ 32/32 通过（venv python -m unittest discover -s tests -t .） |
| 真实链路验证 | ✅ 2026-09-08 实网抓取 loy1234 个人/总战绩并输出三种风格文本 |
| 运行时零缓存 | ✅ 插件运行不写任何文件 |

### ⬜ 待办

- AstrBot 实机联调：把插件目录放入 plugins（本仓库已在 data/plugins 下），重启 AstrBot，
  群聊里 @机器人 或私聊执行 `/wot loy1234` 验证 QQ 官方 Markdown 渲染效果；
  若 QQ 侧对某些字符报错，按错误码调整 formatter（错误码参考 QQ 文档：40034008/40034009/40034011 等）。
- README/metadata 的作者与仓库地址补全；可选：发布到插件市场。

### ⚠️ 已知风险

- 站点页面改版 → parser 失效：按「用 research/ 新快照更新 fixtures → 跑单测 → 修 parser」流程处理。
- QQ 官方 Markdown 语法范围以官方文档为准（无表格/无代码块）；若未来 QQ 支持表格，把 formatter 的 qq_md
  换成 table 输出即可（两种排版均已实现并测试）。
- 站点反爬/封禁 → 降频 + 备选 cloakbrowser 抓取通道（fetcher 接口不变，仅替换实现）。

---

*文档更新日期：2026-09-08（v0.1.0）*
