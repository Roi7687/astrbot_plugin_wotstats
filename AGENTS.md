# astrbot_plugin_wotstats 开发文档

> **插件名称**：坦克世界战绩查询（WoT Stats Query）
> **版本**：v0.3.4（偶游盒子 + 官方坦克营地 + AI 点评；单测 186 项 + 实网/桩驱动脚本验证完成，待 QQ 实机复验）
> **作者**：Roi
> **许可证**：（待定，建议参考同类插件使用 AGPL-3.0）
> **仓库地址**：https://github.com/Roi7687/astrbot_plugin_wotstats

---

## 一、项目概述

[AstrBot](https://github.com/AstrBotDevs/AstrBot) 插件：用户发送 `/wot <昵称>`（或 `/wot 总 <昵称>`），
机器人抓取**两个数据源**并合并回复：

| 数据源 | 入口 | 抓取方式 | 提供内容 |
|---|---|---|---|
| 偶游盒子（第三方） | https://wot.ouj.com/zhanji/index.html（后端 wotbox.ouj.com） | 服务端渲染 HTML + 正则解析 | 战斗力、近 1500 场标准局、场均 6 项、**常用坦克的盒子效率**、总战绩 |
| 官方《坦克营地》 | https://camp.wot.360.cn/（接口 tbox.wot.360.cn） | 免签 JSON 接口 | WN8（生涯/近7天/近30天）、全服排名、近 30 天场均、**近 30 天打过的全部车（单车 WN8/场次/胜率/场均伤害）** |
| 官方玩家搜索（辅助） | https://wotgame.cn/zh-cn/community/accounts/ | 免签 JSON 接口（`?name=<昵称>`） | **昵称 → wgid**（+ 总场次/胜率/经验/军团），wgid 解析的主通道；盒子限流时营地功能仍可用 |

核心思路：**纯 HTTP GET + 纯函数解析**——两个源都无需登录、无需 Cookie、无需浏览器自动化、
**无需任何额外第三方依赖**（只用 AstrBot 自带的 httpx）。核查报告与全部实测证据见
`research/WOTCAM_INTEGRATION_PLAN.md`（含可复现脚本 `research/camp_probe/probe_camp.py`）。

**架构分层**（单向依赖）：`main.py`（指令层）→ `core/fetcher.py` / `core/camp_client.py`（抓取层，网络 IO）
→ `core/parser.py` / `core/camp_parser.py`（HTML/JSON→数据模型，纯函数）→ `core/formatter.py`（数据→回复文本，纯函数）。

**重要设计约定**：
- **运行时零落盘**：插件不写任何数据/状态/临时文件，只做"抓取 → 提取 → 回复"（用户明确要求）。
  仅有两处**进程内**缓存（不落盘）：昵称→wgid 映射（默认 6h）与营地查询数据（默认关闭）。
- 解析失败时**绝不让插件崩溃**：所有异常在 main.py 收敛为友好回复，并用 `logger.exception` 留日志。
- **两个数据源互不拖累**：盒子失败不影响营地段，反之亦然（见 §五 降级矩阵）。
- **无测试不可合并**：parser/formatter 是纯函数，页面/接口结构改动必须先用 research/ 新快照更新
  tests/fixtures 再改代码（回归测试兜底）。

---

## 二、项目结构

```
astrbot_plugin_wotstats/
├── core/
│   ├── __init__.py
│   ├── config.py       # URL/超时/UA/营地常量/昵称校验/样式常量/自定义异常
│   ├── fetcher.py      # WotBoxFetcher：盒子 HTML 抓取 + 重试；403 → RateLimitedError
│   ├── parser.py       # 盒子 HTML → PlayerStats / TotalStats（纯函数，选择器集中于此）
│   ├── camp_model.py   # 营地数据模型：CampPlayer / CampPeriod / CampBattle / CampTank
│   ├── camp_client.py  # WotCampClient：营地免签 JSON 接口（async httpx，可注入 client）
│   ├── camp_parser.py  # 营地 JSON → 数据模型（纯函数，字段容错集中于此）
│   ├── tanks.py        # 车名归一化 + 坦克目录（assets/tank_catalog.json）加载
│   ├── cache.py        # 进程内 TTL 缓存（不落盘；默认不缓存查询数据）
│   ├── commands.py     # 指令解析纯函数（parse_target / is_wgid）
│   ├── wgid.py         # 官方玩家搜索（wotgame.cn）：昵称 → wgid 主通道
│   ├── tank_table.py   # 常用坦克表：营地数据为主（rows_from_camp）+ 盒子效率可选补充（enrich_with_box）
│   ├── ai_review.py    # AI 点评：跨插件调用 astrbot_plugin_aisearch（提示词 + 注册表解析 + 降级）
│   └── formatter.py    # 数据 → qq_md / plain / table 三种风格文本（纯函数）
├── assets/
│   └── tank_catalog.json  # 车名→tank_id 只读静态资产（scripts/build_tank_catalog.py 生成）
├── scripts/
│   └── build_tank_catalog.py  # 由 wotcamp/tank_catalog.json 生成上面的资产
├── tests/              # unittest（python -m unittest discover -s tests -t .）
│   ├── fixtures/       # 真实快照：盒子 HTML ×3 + 营地 JSON ×3（正常/总战绩/查无此人/三时段/逐场/单车）
│   ├── test_parser.py / test_formatter.py / test_fetcher.py
│   └── test_camp_parser.py / test_camp_client.py / test_tanks.py / test_commands.py / test_tank_table.py / test_wgid.py / test_ai_review.py
├── __init__.py
├── main.py             # Star 插件：/wot 指令族、风格选择、双源降级、异常兜底
├── metadata.yaml
├── requirements.txt    # 无额外依赖（httpx 由 AstrBot 核心提供）
├── README.md
├── AGENTS.md           # 本文档
├── wotcamp/            # 坦克营地取数调研工程（独立子项目，未入库；接口/字段速查见其 docs/api-notes.md）
└── research/           # 本地调研落盘——不入库（核查脚本/快照/接入方案/端到端验证脚本）
```

---

## 三、指令与行为

| 命令 | 行为 |
|------|------|
| `/wot <昵称>` | **盒子摘要 + 营地数据 + AI 点评**：战斗力、近 1500 场标准局（胜率/胜负/命中/出战等级）、场均 6 项、**常用坦克表（以营地近 30 天为准，显示全部车；「盒子效率」能取到时才作为补充追加）**、盒子数据来源链接；末尾追加营地三时段 WN8/场次/胜率/K/D/全服排名与近 30 天场均；最后追加「**AI评价：**…」（调用 astrbot_plugin_aisearch，见 §5.5） |
| `/wot 总 <昵称>`（或 `/wot 总战绩 <昵称>`） | 总战绩：入伍天数/日期、总胜率、场均伤害/助攻/经验、击毁/占领/防守/发现（总体+场均）、最近常用坦克 TOP5 |
| `/wot3h` | 只回一条《坦克营地》「三环」榜单链接（`THREE_RING_URL`），供用户直接在浏览器打开；不抓任何数据 |
| `/wot help` | 用法帮助 |
| 查无此人 | 回复可能原因（昵称大小写敏感/刚改名 3h 内同步等） |
| 盒子 403 | 一行限流提示 + 营地数据（不再报"未知错误"） |

> v0.3.0 起**已删除** `/wot 营地` 指令与 `/wot 营地 #<wgid>`（用户要求只保留 `/wot <昵称>`），
> 同时删除回复中的「各车型近 1000 场单车战斗力」「最近对局」「盒子评价」三段及其解析代码。

- **`/wot3h` 与 `/wot` 不冲突**：AstrBot 的指令过滤规则是「消息等于指令名 或 以『指令名+空格』开头」
  （`astrbot/core/star/filter/command.py`），因此 `wot3h` 不会被 `wot` 的前缀匹配吃掉；已用
  `research/verify_wot3h.py` 固化验证。
- 昵称校验：2~32 字符，字母/数字/中文/下划线/连字符/点/空格（`core/config.is_valid_nickname`），大小写敏感不折叠。
- 中文昵称 URL 编码由 `core/fetcher.build_query_url` 处理。
- **wgid 解析顺序**（`main._resolve_wgid`）：进程内缓存 → **官方玩家搜索**（wotgame.cn，1 次请求、大小写不敏感、
  免登录，要求昵称 ≥4 字符）→ 盒子个人战绩页 `input#p_id`（短昵称/官方搜索失败时回落）。
  因此**盒子被限流时营地数据依然可用**。
- `/wot 总` 不附营地数据（总战绩页没有 `input#p_id`，也拿不到单车口径）。

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

回复内容（v0.3.0）：**常用坦克 = 营地近 30 天口径**（车名/等级/营地WN8/近30天场次/30天胜率/场均伤害），**「盒子效率」为可选补充**（有则追加，无则不显示）；结尾"数据来源："为**可点击直达查询页**的链接（qq_md/table 为 `[url](url)`，plain 输出裸 URL）。
v0.3.0 已删除：「各车型近 1000 场单车战斗力」「最近对局」「盒子评价」三段（含解析代码）。

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
| tabs | `.mod-tabs-trigger` a |

> v0.3.0 起 `.comment-list__text`（盒子评价）、`.userRecord-recent__box`（最近对局）、
> `App.init(...)`（各车型近 1000 场战斗力）**不再解析**——这三段展示已按用户要求删除，
> 需要恢复时从 git 历史取回解析代码即可（页面结构未变）。

### 5.2 总战绩页 r=default/battlestat → TotalStats

- 头部：`.user-info .name`、`.power`；入伍：`.totalRecord-otherInfo__length/__time`
- headline：`.totalRecord-data1` li（胜率/伤害/助攻/经验）
- 四列总体/场均：`.totalRecord-data2__tableHead`（列名）+ `.totalRecord-data2__tableBody`（两行）
- 最近常用坦克：`<h3>最近常用坦克</h3>` 后表格 tbody（名称/场次/胜率/战力）

### 5.3 判空 / 改版防御

- 查无此人：页面含 `class="not-find-user"` 元素或文案「没有找到您搜索的玩家」→ PlayerNotFoundError
  （**注意**：页面内联 CSS 也含 `.not-find-user` 定义，不可只搜类名字符串——已踩坑修复）
- 核心字段全空 → ParseError（提示"页面结构可能已改版"，要求用新快照更新本文件）

### 5.4 官方坦克营地（core/camp_model.py + core/camp_parser.py，2026-10-16 实测）

三个免签接口（`https://tbox.wot.360.cn`，无需登录/签名/指纹）：**详细核查见 `research/WOTCAM_INTEGRATION_PLAN.md`**

| 用途 | 接口 | 关键字段 |
|------|------|----------|
| 三时段总览 | `GET /tank/appuserrank?type=<all\|day_7\|day_30>&accountId=<wgid>` | `data.userInfo{nick_name,qid,face_url,last_time}`、`data.RankList{WN8,fights,win,less,draw,win_rate,K/D,avgdmg,avgfrag,avgspot,avgexp,avgdef,avglevel,hit_rate,rank}`、`data.size` |
| 逐场战斗 | `GET /WotArena/getUserBattles?uid=<wgid>&page=1&size=≤200` | `battleList[]{arenaId,arenaCreateTime,tankName,mapName,battleType,winResult(1/-1/0),damageDealt,kills,totalAssistedDamage,wn8,credits,duration}` |
| 单车分时段 | `GET /tank/uservehiclestat?tankid=<id>&accountId=<wgid>&type=day_30` | `vBattles.list[0]{vehicle_name,fights,WN8,win_rate,avgdmg,avgdmgasst,K/D,hit_rate,vlevel,vtype,country,vehicle_mastery}` |

坑位（均已固化为单测）：

1. **参数名是 `uid`**，写成 `accountId` → `errno=2003 pkey empty`（这就是 wotcamp 文档里"指纹风控"的真实成因）。
2. **总览 `RankList` 没有 `avgdmgasst`**（场均助攻只在单车接口里有），模型里刻意不建该字段。
3. **wgid 不存在时 `errno` 仍为 0**，但 `userInfo.nick_name` 为空 → 判为查无此人（`CampNotFoundError`）。
4. **未打的时段**：单车接口返回 `fights=0 / WN8=0 / rank=-1` 的占位行，必须按 `fights>0` 过滤；
   未拥有的车 `list` 为空。
5. **无"玩家的单车列表"接口** → "近 30 天常用坦克"靠**逐场战斗翻页枚举车名**：
   逐场接口没有按时间过滤的参数（实测 `range=day_30/30/month` 全部无效），因此按
   `arenaCreateTime` **客户端过滤**，一次并发取 `CAMP_BATTLE_BATCH=3` 页（每页
   `CAMP_BATTLE_PAGE_SIZE=100` 条），翻到窗口边界为止（上限 600 场）。
   实测活跃玩家 `loy1234`：3 页覆盖 296 场 → **18 辆**（30 天全部打过的车）。
   全目录扫描（998 辆）≈40s，聊天场景不可用，因此不采用。
6. 错误码语义：`0` 成功 / `2000` 用户需要登录 / `2003` pkey empty / `400` sign check wrong（需签名接口，不碰）。
7. **`vehicle_mastery`（环）实测恒为 0**：抽查了单车榜前 5 名玩家（Vz.55/Ares 90 C/庇护者 三辆车共 15 人）
   全是 0 → 该字段当前不可用，**因此单车表不展示"环"列**（截屏里那种三环图标无法复现）。
8. 盒子车库页 `r=default/carport` 有全车表（坦克名称/级别/参战次数/胜场/胜率/单车战力），
   但**单车战力列几乎都是 `-`**（实测 T-100 LT 等 6 辆车全为 `-`），且该页比首页更早触发 403 限流
   （实测 5 个分型一次连发即全 403）→ 因此**不采用车库页**，盒子效率只来自首页「常用坦克」弹层。
9. 性能（实测，18 辆车）：三时段并发 1.1s + 战斗翻页 1.2s + 单车并发 0.9s ≈ **2.8s**；
   早期"顺序翻页 + 逐辆串行"版本为 5.7s，故采用**时段与翻页并发 + 翻页批量并发 + 100 条/页**。

**常用坦克表（core/tank_table.py，营地优先 + 盒子可选补充）**

用户明确要求：这一块里**除了「盒子效率」以外，所有字段都来自官方坦克营地**
（单车 WN8、近 30 天场次、胜率、场均伤害、助攻、K/D、命中率、等级），
因此模块拆成**两个互不耦合的阶段**，盒子只是可选加料：

| 阶段 | 函数 | 依赖 | 说明 |
|---|---|---|---|
| ① 主逻辑 | `rows_from_camp(camp)` | **只依赖营地** | 营地近 30 天有战绩的车 → `TankRow` 列表（按 30 天场次降序，常用优先） |
| ② 可选补充 | `enrich_with_box(rows, box_tanks)` | 盒子（可缺省） | 按归一化车名匹配，只填 `box_power/box_battles`，**不动任何营地字段**；返回补充成功的行数 |
| 便捷入口 | `build_tank_rows(camp, box_tanks=None)` | — | ① + ② |

渲染层（`formatter._tank_block`）据此决定：

```
🚗 **常用坦克**（营地近 30 天口径 ｜ 盒子效率为补充）      ← 仅当确有盒子数据时才有后半句
- **WZ132-1**（10 级）：营地WN8 **2,702** ｜ 近30天 56 场 ｜ 胜率 53.6% ｜ 场均伤害 2,050
- **Ares 90 C**（11 级）：营地WN8 **2,641** ｜ 近30天 4 场 ｜ 胜率 100.0% ｜ 场均伤害 3,728 ｜ 盒子效率 **1612**
```

- 一行里"盒子效率"**只在真拿到数据时才追加**；拿不到就不显示（不再打印 `盒子效率 -` 这种噪音）；
- `table` 风格同理：只有存在补充数据时才追加"盒子效率"列，否则表格仍是 6 列；
- 盒子数据整体缺失（限流/查无此人）时，常用坦克表**内容完全不变**——只是少了那截补充；
- 匹配规则保守：**只认归一化后完全相同的车名**（抹平引号/空格/连字符/大小写），匹配不上就留空，绝不模糊猜；
- 盒子自己把战力标成 `-` 的车（如车库页常见）也按"无补充"处理；
- **显示全部**（`CAMP_TANKS_TOP=0`），只剔除 `fights=0` 的车；候选车清单 = 时间窗内出现过的车名 ∪ 盒子「常用坦克」车名，受 `CAMP_TANKS_SCAN=60` 限制。

**降级矩阵（main.py）**

| 情况 | 表现 |
|------|------|
| 盒子 403 限流 | 一行限流提示（说明缺的是战斗力/近1500场/总战绩）+ **完整的营地主体**（常用坦克表 + 三时段速览，实测 1.6k 字符）；营地也拿不到时回退完整限流说明 |
| 盒子查无此人 | 只回"没有找到玩家"，**不附营地数据**（避免自相矛盾） |
| 营地接口超时/异常 | 只回盒子数据，日志 warning，不打扰用户 |
| 营地查无此人或拿不到 wgid | 跳过营地段（回复只剩盒子部分），日志留痕 |
| 单车数据缺失 | 少一辆车，不影响其它部分 |
| 排版函数抛异常 | `_safe_format` 兜住 → 回"数据渲染失败"，绝不让用户收不到回复 |

### 5.5 AI 点评（跨插件调用，2026-10-16 实测）

`/wot <昵称>` 的正文末尾会追加一段 AI 点评（`AI评价：…`）。实现见 `core/ai_review.py`，
**路线 = 直接调用另一个插件**（`astrbot_plugin_aisearch`，Playwright 驱动 DeepSeek 网页版）。

**AstrBot 允许插件互相调用**（有官方"默认许可"痕迹）：

| 证据 | 位置 |
|---|---|
| `StarMetadata.star_cls: Star \| None` —— 插件实例本体 | `astrbot/core/star/star.py:42` |
| 加载时赋值 `metadata.star_cls = metadata.star_cls_type(...)`（热重载 `:1362`，未激活置 `None` `:1245`） | `astrbot/core/star/star_manager.py:1227/1232/1236` |
| 公开取值入口 `Context.get_registered_star(name)` / `get_all_stars()` | `astrbot/core/star/context.py:346/:352` |
| 官方注释提醒"未激活时 star_cls 可能为 None，**请不要在插件未激活时调用 star_cls 的方法**" | `astrbot/core/star/star.py:21` |

**调用流程（三步）**：

1. **组装提示词**：`AI_REVIEW_PROMPT`（分析要求）在前、战绩正文在后，合并成一串文本
   → `build_ai_prompt(stats)`。提示词要点（v0.3.4，按用户要求迭代过四轮）：
   - **输出格式固定 7 条**：① 定位（WN8 档位 + 风格 + 三时段趋势）② 共性问题（1~2 个）
     ③~⑦ **5 辆问题车，一辆一条**——每条按「**数据现象**（场次/胜率/WN8/场均伤害哪里对不上）
     → **推断的问题**（为什么会这样）→ **具体怎么做**（1~2 句可执行动作）」三步写；
   - **③~⑦ 不许塞非车辆内容**（"先改哪辆""短期目标""总结"等一律禁止，7 条就是 ①+②+5 辆车）；
   - **不许纯复述车辆参数/机制科普**（"单发 xxx""DPM 高低""装甲等效多少"）；参数只能作为
     "因此建议…"的从句出现，有效建议优先；
   - **选车规则**：挑「**胜率低 + WN8 低 + 场次够多**」的 5 辆短板车，不要挑场次最多的；
     优先场次 ≥10，不足 5 辆时放宽到 ≥5 场（该条注明样本偏少）；
   - **数据诊断对照表**（先由数据推断问题）：伤害够但胜率低 → 输出没换成胜利；
     伤害低且胜率低 → 这辆车没上手；WN8 高场次多胜率低 → 打法固化；
     胜率高但 WN8 低 → 跟队友赢、个人贡献有限；场均伤害低于同车常规 → 找不到输出机会；
     场次越多胜率越低 → 优先级越高；
   - **必须联网搜索**：核实这 5 辆车的当前版本主流打法、配件技能、常见失误，
     以及同车玩家的大众伤害/胜率量级（含三环线的"伤害+协助"量级），但只用来说服建议；
   - 分析框架（按车型角色看指标，来自 WG 官方 WTR）：弹夹/大单发→场均伤害；高射速→伤害+击毁；
     精准脆皮→远距离输出；高机动好视野→协助伤害；重甲→抵挡+造成伤害；通用看生存率。

2. **提交给对方插件**：`ctx.get_registered_star("astrbot_plugin_aisearch").star_cls._send_query(prompt, [])`
   —— 对方这个入口**不需要 event、不需要额外参数**，内部走 `DeepSeekSessionCore.send_message()`；
3. **等待并追加**：`asyncio.wait_for(..., AI_REVIEW_TIMEOUT)` 拿回文本 → 修剪（去多余空行、
   截断到 `AI_REVIEW_MAX_CHARS`）→ 追加为 `\n\n**AI评价：**<正文>`（plain 风格无加粗）。

**提示词三轮迭代与实测（2026-10-16）**：

| 版本 | 要求 | 实测输出 | 耗时 | 总消息 |
|---|---|---|---|---|
| v1 | 6 段结构、300~500 字 | 678 字符 | 52.2s | 2373 |
| v2 | 4 行、200~300 字、禁止罗列 | 217 字符 | 39.5s | 1912 |
| v3 | 6~8 条、400~600 字、每条讲原因、优先弱车、联网核实机制 | 844 字符 | 51.6s | 2539 |
| **v4（当前）** | **7 条：① 定位 ② 共性问题 ③~⑦ 五辆问题车；先数据诊断再给建议；禁止参数复述** | **666 字符** | 51.5s | **2382** |

v4 实测质量：正好 7 条、③~⑦ 恰好 5 辆短板车（BV-111 / 犀牛 / 百夫长 AX / WZ132-1 / UDES 15/16），
每条都先给数据现象与推断、再给动作，例如
*"BV-111：场次不少但胜率是最大短板，伤害打得出来却赢不了，推断是切模式后站位过前、在切换僵直里被反打。
开局别急着切高伤模式，先用普通模式抢到卖头位…"*；
参数复述已基本消失（不再整段介绍单发/装甲），⑧ 那类"短期目标/先改哪辆"的收尾段落也已按要求去掉。

**资料来源（联网核实，写进提示词的权威口径）**：
- WG 官方 WTR 五指标与"按车型角色看指标"：
  [Tactics and Strategy Basics: A Way to Better Statistics](https://worldoftanks.asia/en/news/general-news/educational-video-3/)
- WG 官方卓越印记（三环）规则：只算"场均伤害 + 有效协助（取点亮/断带/震荡最大项）"，
  最近 100 场与同车玩家近 14 天比较，前 35% / 15% / 5% = 一环 / 二环 / 三环：
  [如何獲得卓越印記？](https://wargaming.net/support/zh_tw/products/wot/article/15060/)

**降级与边界（全部固化为单测，共 23 项）**：

| 情况 | 行为 |
|---|---|
| 对方未安装 / 未激活 / `star_cls` 为空 / 无 `_send_query` / 注册表异常 | 记 WARNING，**不追加**，本插件回复照常发出 |
| 对方抛异常（未登录 `AuthError`、会话错误等） | 同上（跨插件异常一律兜住，绝不逃逸） |
| 超过 `AI_REVIEW_TIMEOUT`（默认 120s） | 放弃并记 WARNING（对方是浏览器自动化，正常 20~60s） |
| 返回空内容 | 不追加，记 WARNING |
| 排障 | 插件加载 + `on_astrbot_loaded` 各做一次自检，日志打印 `AI 点评可用：astrbot_plugin_aisearch → CloakSearchPlugin` 或不可用原因 |

**注意事项（踩过/需知道的点）**：
- 对方是**浏览器自动化 + 串行锁**：多人同时 `/wot` 会排队，第二个可能撞上超时（降级为无点评）。
- 调用后要替对方 `_arm_idle_timer(local_id)` —— 它自己的 `_respond()` 才会做这件事，
  我们绕过了 `_respond`（那会带键盘按钮并直接发消息），不补这一步无头浏览器可能常驻。
- **不要缓存对方实例**：插件热重载后实例会被替换；每次调用现取。
- 属于**跨插件私有接口**：对方版本升级（`_send_query` 改名等）会断，届时日志会明确报出原因。
- 开关：`AI_REVIEW_ENABLED=False` 可整体关闭；`AI_REVIEW_PLUGIN` 可换成别的对话插件。

---

## 六、调研记录

### 6.1 偶游盒子（2026-09-07 实测）

完整报告：`research/SITE_PROBE_REPORT.md`（含全部原始 HTML 快照与选择器清单、坑位说明）。
要点：

1. wot.ouj.com/zhanji/index.html 是门户壳页，真实查询界面在 iframe：wotbox.ouj.com/playerSearch2018.php
   （表单 GET `r=default/index&pn=<昵称>`；原区服下拉已注释，仅国服）。
2. 纯 HTTP GET 即得完整服务端 HTML（UTF-8），HTTPS 200 正常；无需登录/Cookie/浏览器。
3. 模块 r 值：default/index、carport、battlelog(&p=)、battlestat、mobile。
4. 查无此人 HTTP 200（判据见 5.3）；昵称大小写敏感；近期战绩口径"只算最近 1500 场标准局"，更新非实时。
5. 战斗力刷新（#refresh）需盒子客户端登录 + 月卡 POST wotapp.ouj.com——插件不做。
6. **数据随玩家新战斗变化**：2026-09-08 实测同一玩家近 5 局已翻新（含新败局），证实为动态实时数据，不应做本地缓存（本项目即不缓存）。

### 6.2 官方坦克营地 + 盒子限流（2026-10-16 实测）

完整报告与可复现脚本：`research/WOTCAM_INTEGRATION_PLAN.md`、`research/camp_probe/`。

1. **不需要 curl_cffi**：`tbox.wot.360.cn` 全部免签接口用普通 httpx / stdlib urllib / 任意 UA 都返回 `errno=0`。
   wotcamp 文档里"必须伪装浏览器指纹"的结论不成立——`pkey empty` 的真因见 §5.4 坑位 1。
2. **偶游盒子对单 IP 有严格请求配额**：密集请求后长时间返回 `403 Forbidden`（9 字节）。
   2026-10-16 18:40 AstrBot 生产日志实测到该 403；A/B 实验（Chrome UA vs 库 UA 各 4 次、冷却 5 分钟后）
   **全部 403** → 限流按 IP 生效，**换 UA 不能解决**（浏览器 UA 另有一条更严格的拒绝规则，故 UA 仍保持非浏览器标识串）。
3. **wgid 复用**：盒子个人战绩页 `input#p_id` == 营地 `accountId`（实测 `7049441311` 两侧一致）。
4. **营地侧限流宽松**：单接口 0.16~0.46s，60 次 8 并发全部成功（1.6s）；一次完整取数 ≈1.2~2.0s / 4~16 请求。
5. 营地接口的真实字段与 wotcamp 文档的三处偏差已记录在 §5.4（`avgdmgasst` 不存在、单车只回一条、
   `keyword` 搜索无效）。
6. **找到官方的 wgid 来源（重要）**：wotgame.cn 玩家搜索页内联 JS 给出真实接口
   `GET /zh-cn/community/accounts/search/?name=<昵称>`（页面里的 `accounts/#wot&at_search=` 只是前端路由），
   返回 `account_id` **就是营地 wgid**（`loy1234` → `7049441311`，已双向交叉验证）；
   免登录、免签名、15 次连发全 200、**大小写不敏感**、支持 `*1` 重名后缀；服务端要求昵称 ≥4 字符。
   已接入为 wgid 主通道（`core/wgid.py`），因此**盒子 403 期间营地功能完整可用**：
   `/wot loy1234` 从"只有限流提示"变为"限流提示 + 完整营地数据（含 18 辆车的单车表）"。
   复现脚本：`research/camp_probe/wotgame_search_probe.py` / `wotgame_characterize.py` / `wotgame_edge_probe.py`。
7. **逐场战斗接口可翻页**：`page=1/2/3` 分别覆盖 2026-10-15→10-01 / 09-28→09-07 / 09-07→08-28
   （单页上限 200，插件用 100 条/页以降低单次耗时）；`range` 参数无过滤语义。

---

## 七、技术栈

| 技术 | 用途 |
|------|------|
| Python 3.12+ | 主语言（async/await） |
| AstrBot API | Star / Context / filter.command / GreedyStr / make_result().use_markdown() |
| httpx（AstrBot 核心自带） | 两个数据源的抓取（requirements 仅声明注释，不钉版本） |
| re / json / html / dataclasses（stdlib） | HTML / JSON 解析与数据模型 |
| unittest（stdlib） | 单元测试（无需 pytest） |
| research/ 快照 | fixture 库 + 站点/接口改版对照物 |

---

## 八、进度

### ✅ v0.3.4 已完成（2026-10-16）

| 项 | 说明 |
|----|------|
| AI 点评（路线 C） | ✅ 新增 `core/ai_review.py`：分析提示词 + 战绩文本合并 → 调用 `astrbot_plugin_aisearch` 的 `_send_query` → 追加「**AI评价：**…」 |
| 提示词调优（四轮） | ✅ v1 六段式 → v2 强制联网+精简 4 行（用户反馈太短）→ v3 6~8 条+讲原因+优先弱车 → **v4：固定 7 条（① 定位 ② 共性问题 ③~⑦ **恰好 5 辆问题车**），每条先由数据诊断问题再给建议，禁止复述车辆参数**；实测 v4 输出 666 字符 / 51.5s，格式与车辆数完全符合要求 |
| 跨插件调用验证 | ✅ 真实运行时日志确认注册表解析成功（`AI 点评可用：astrbot_plugin_aisearch → CloakSearchPlugin`）；独立脚本 `research/verify_ai_review.py` 跑通完整链路 |
| 降级与善后 | ✅ 未安装/未激活/异常/超时/空回复一律静默降级（23 项单测覆盖）；调用后替对方重置空闲计时器，避免无头浏览器常驻 |
| 单测 | ✅ **186/186 通过** |

### ✅ v0.3.3 已完成（2026-10-16）

| 项 | 说明 |
|----|------|
| 新增 `/wot3h` | ✅ 直接回复《坦克营地》「三环」榜单链接（`core/config.THREE_RING_URL` + `formatter.three_ring_text`）：QQ 官方 Markdown 输出 `[url](url)`（可点击且可复制），其他平台输出裸 URL；不发起任何网络请求 |
| 指令冲突验证 | ✅ `research/verify_wot3h.py`：驱动真实 handler + 校验 AstrBot 过滤规则（`wot3h` / `wot loy1234` / `wot` 三种输入互不误命中） |
| 单测 | ✅ **159/159 通过**（新增 4 项：两风格输出、URL 断言、help 文案含新指令） |

### ✅ v0.3.2 已完成（2026-10-16）

| 项 | 说明 |
|----|------|
| **修复：限流时丢失常用坦克表** | ✅ 原实现把常用坦克表只挂在"盒子成功"的渲染路径（`format_index_reply`）；盒子 403 时 `data=None`，营地数据只剩三时段速览，**18 辆车的表被吞掉**（用户实测发现的真缺陷）。新增 `format_camp_block()`：盒子不可用时输出「常用坦克表 + 三时段速览」，实测 1664 字符 / 18 辆车 |
| 限流提示改写 | ✅ 明确说清缺的是「战斗力 / 近 1500 场 / 总战绩」三块，不再像一条错误 |
| 耗时复核 | ✅ 单条 `/wot` 营地取数实测 2.8s（loy1234）/ 3.4s（战争之神潘多拉，19 辆车），无卡顿 |
| 单测 | ✅ **155/155 通过**（新增 5 项覆盖"盒子不可用"路径） |

### ✅ v0.3.1 已完成（2026-10-16）

| 项 | 说明 |
|----|------|
| 常用坦克表拆成独立模块 | ✅ 新建 `core/tank_table.py`（`TankRow` / `rows_from_camp` / `enrich_with_box` / `build_tank_rows`）；删除 `merge.py` 与 `test_merge.py`，新增 `test_tank_table.py`（9 项） |
| 营地优先、盒子可选 | ✅ 盒子效率**只在真取到时**逐行追加；无补充时不显示「盒子效率 -」，table 风格也不加该列（保持 6 列） |
| 单测 | ✅ **150/150 通过** |

### ✅ v0.3.0 已完成（2026-10-16）

| 项 | 说明 |
|----|------|
| 删除 `/wot 营地` 指令 | ✅ 只保留 `/wot <昵称>` 与 `/wot 总 <昵称>`；用户参数输入"营地 xxx"整体当昵称处理 |
| 删除三段展示 | ✅ 「各车型近 1000 场单车战斗力」「最近对局」「盒子评价」的渲染 + 解析代码全部删除（`PlayerStats` 同步瘦身） |
| 常用坦克改为 30 天全量 | ✅ 以营地 `day_30` 为准，**显示近 30 天打过的全部车**（实测 18 辆），按 30 天场次降序 |
| 枚举方式 | ✅ 逐场战斗翻页 + 时间窗过滤（`scan_window_battles`）；时段与翻页并发，取数 **5.7s → 2.8s** |
| 代码瘦身 | ✅ `formatter.py` 701 → 约 480 行；`main.py` 377 → 约 290 行（移除营地专用报告与死代码） |
| 发现的真 bug | ✅ 指令层验证脚本抓到 `_resolve_wgid` 三返回值被按二元解包（`/wot <昵称>` 直接抛 ValueError），已修复并复验 |
| 单测 | ✅ **150/150 通过**（删除失效用例 + 新增"删掉的段落不得再出现""按场次排序""全量展示""盒子效率仅在可取到时追加"等断言） |

### ✅ v0.2.2 已完成（2026-10-16）

| 项 | 说明 |
|----|------|
| 单车合并表 | ✅ `core/merge.py` + `tests/test_merge.py`（8 项）：营地近30天口径 × 盒子效率对照，只显示营地有战绩的车 |
| 候选车清单对齐 | ✅ 盒子「常用坦克」车名优先查询（`extra_tank_names`），并按"盒子也有的车优先"排序 |
| 实网验证 | ✅ 盒子站点已恢复：`/wot loy1234` 真实回复 1393 字符，单车表含 `UDES 15/16：营地WN8 3,203 ｜ 盒子效率 1516 ｜ 近30天 38 场` |
| 单测 | ✅ **160/160 通过** |

### ✅ v0.2.1 已完成（2026-10-16）

| 项 | 说明 |
|----|------|
| 官方 wgid 通道 | ✅ `core/wgid.py` + `tests/test_wgid.py`（15 项）：昵称 → wgid 不再依赖被限流的盒子站点 |
| 限流体验 | ✅ 盒子 403 时不再只回错误文案，而是"一行提示 + 营地速览" |
| 单测 | ✅ **149/149 通过** |

### ✅ v0.2.0 已完成（2026-10-16）

| 项 | 说明 |
|----|------|
| 官方坦克营地接入 | ✅ `core/camp_model.py` / `camp_parser.py` / `camp_client.py`（免签 JSON，async httpx，零新依赖） |
| `/wot 营地 <昵称>` 指令 | ✅ 完整营地报告（三时段 + 近30天场均 + 常用坦克 + 逐场），支持 `#<wgid>` 绕过盒子 |
| `/wot <昵称>` 营地速览 | ✅ 末尾追加三时段 WN8/场次/胜率/K/D/全服排名（合并后约 1.3k 字符） |
| wgid 解析（含官方搜索） | ✅ `core/wgid.py`：缓存 → 官方搜索(wotgame.cn) → 盒子 p_id 三级回落；**盒子 403 期间营地功能完整可用** |
| 盒子 403 限流处理 | ✅ 403 → `RateLimitedError`；限流时用一行提示 + 营地速览顶替（UA 改为非浏览器标识串） |
| 坦克目录资产 | ✅ `assets/tank_catalog.json`（998 辆，20KB）+ `scripts/build_tank_catalog.py` |
| 双源降级 | ✅ 任一侧失败不影响另一侧（见 §5.4 降级矩阵） |
| 单测 | ✅ **149/149 通过**（新增 114 项：营地解析/抓取/目录/缓存/指令/排版/限流/异常数据/官方搜索） |
| 独立复核 | ✅ 对抗性代码复查 20+ 条意见已逐条处理（inf/NaN 越界、部分失败容错、回显注入、缓存键、空回复等） |
| 实网脚本验证 | ✅ `research/verify_integration.py`（营地取数 1.1~2.3s / 11 请求）+ `research/verify_command_handler.py`（指令层 15 条路径，含桩驱动降级分支） |
| 文档 | ✅ README / AGENTS / metadata(v0.2.0) / research 接入方案与核查脚本 |

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

- **QQ 实机复验（v0.3.4）**：群里/私聊执行 `/wot <昵称>`（现在会**多等约 50s** 出 AI 点评）、
  `/wot 总 <昵称>`、`/wot help`、`/wot3h`。
  重点看两件事：① 官方 Markdown 渲染是否正常；② **消息体量**——常用坦克全量展示后
  实测回复约 2.1k 字符（18 辆车），若 QQ 侧报长度类错误（40034008/40034009/40034011 等），
  可把 `CAMP_TANKS_TOP` 从 0 改成 10~12 截断，或把单车表拆成两条消息。
  加了 AI 点评后实测总长 **2.4k 字符**（点评本身 666 字符）；若 QQ 报长度类错误，
  优先压缩常用坦克行数（`CAMP_TANKS_TOP`）或点评上限（`AI_REVIEW_MAX_CHARS`）。
- 盒子站点限流观察：若 403 频繁，考虑把 `CAMP_CACHE_TTL` 设为 60~120 秒（进程内缓存，仍不落盘）。
- 可选：把营地榜单类接口（三环/坦克战力榜）做成 `/wot 榜 <坦克名>`；发布到插件市场。

### ⚠️ 已知风险

- **AI 点评延迟**：对方插件是浏览器自动化，单次 20~60s；`/wot` 会等它返回后才回复。
  若觉得太慢，可把 `AI_REVIEW_ENABLED` 设为 False，或改成"仅 `/wot 分析 <昵称>` 才触发"。
- **偶游盒子限流**：该站对单 IP 有严格请求配额，密集查询会长时间 403。
  已做的兜底：403 归类为限流 + 官方搜索拿 wgid + 营地数据顶替 + 进程内缓存。
  **换 UA 无效**（已用 A/B 实验证伪），不要在这上面浪费时间。
  注意：盒子车库页（carport）比首页更容易触发 403（实测 5 个分型连发即全 403），**不要加这个请求**。
- **官方搜索的昵称长度下限**：服务端要求 ≥4 个字符（不足 409），2~3 字昵称仍会回落到盒子页面取 p_id；
  若同时盒子不可用，则该昵称的营地数据（三时段 + 常用坦克）拿不到，只回限流提示。
- **官方搜索是模糊匹配**：最多返回 25 条，插件只接受"大小写不敏感的完全同名"或"唯一结果"，
  否则提示"没找到/多个相似玩家"（避免张冠李戴）。
- 站点页面改版 → parser 失效：按「用 research/ 新快照更新 fixtures → 跑单测 → 修 parser」流程处理。
- 营地接口字段变更 → camp_parser 失效：字段全部 `.get()` + 容错，缺关键字段时整体降级为一句提示；
  更新 fixtures（`research/camp_probe/snapshots/`）后跑单测。
- 坦克目录过期（新车未收录）→ 该车在"近 30 天常用坦克"里被跳过，不影响主流程；重跑
  `python scripts/build_tank_catalog.py` 刷新。
- QQ 官方 Markdown 语法范围以官方文档为准（无表格/无代码块）；若未来 QQ 支持表格，把 formatter 的 qq_md
  换成 table 输出即可（两种排版均已实现并测试）。
- 两套评分口径混淆：文案里始终写"战斗力（盒子）"/"WN8（营地）"并标注窗口，文档同步说明不可换算。

---

*文档更新日期：2026-10-16（v0.3.4）*
