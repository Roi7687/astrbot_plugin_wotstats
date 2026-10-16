# astrbot_plugin_wotstats — 坦克世界战绩查询

一个 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 插件：在 QQ 中发送 `/wot <玩家昵称>`，
同时抓取两个数据源并以 Markdown 排版回复：

- **偶游盒子战绩查询站**（https://wot.ouj.com/zhanji/index.html，实际后端 wotbox.ouj.com）——战斗力、近 1500 场、总战绩
- **官方《坦克营地》**（https://camp.wot.360.cn/ ，接口 tbox.wot.360.cn）——WN8 三时段、全服排名、近 30 天常用坦克、逐场战斗
- 昵称 → wgid 由**官方玩家搜索**（wotgame.cn）解析，不依赖被限流的盒子站点

## 功能

- `/wot <昵称>` —— 战绩摘要：盒子数据（战斗力、近 1500 场标准局胜率、场均）**＋ 营地数据**
  （近 7 天 / 近 30 天 / 生涯的 WN8、场次、胜率、K/D、全服排名、近 30 天场均）
  **＋ 常用坦克表：以营地近 30 天为准，列出这段时间打过的全部车（营地数据为主，「盒子效率」能取到时才作为补充追加）**
- `/wot 总 <昵称>`（或 `/wot 总战绩 <昵称>`）—— 总战绩（入伍时间/天数、全时段胜率、总体/场均击毁-占领-防守-发现、最近常用坦克）
- `/wot help` —— 用法帮助
- 昵称**区分大小写**；中文昵称可直接输入（如 `/wot 坦克玩家甲`）

> ⚠️ 「战斗力」（盒子口径）与「WN8」（官方营地口径）是**两套不同体系，不能互相换算**，插件里始终分别标注。

## 数据源与格式

- 抓取方式：**纯 HTTP GET**（盒子为服务端渲染 HTML，营地/官方搜索为其免签 JSON 接口）；
  无需登录 / Cookie / 浏览器自动化 / 额外依赖（只用 AstrBot 自带的 httpx）。
- wgid 解析：**官方玩家搜索**（`wotgame.cn/zh-cn/community/accounts/search/?name=<昵称>`，1 次请求、
  大小写不敏感、免登录，要求昵称 ≥4 字符）→ 失败时回落盒子个人战绩页 `input#p_id` → 进程内缓存 6h。
  因此**盒子被限流时营地功能依然可用**。
- 查无此人：盒子对不存在的昵称仍返回 HTTP 200，按页面内 `.not-find-user` 提示块判定；
  营地接口 `errno=0` 但 `nick_name` 为空时同样判为查无此人。
- **限流降级**：盒子站点对单 IP 有严格请求配额（HTTP 403）。插件把 403 归类为限流，
  自动改用营地数据并给出一行提示；任一侧失败都不会拖垮另一侧。
- 回复排版：QQ 官方机器人平台使用**原生 Markdown 消息**（msg_type=2；QQ 官方 Markdown 语法暂不支持表格，
  采用标题/加粗/列表排版，详见 AGENTS.md 调研记录）；其他平台自动回退为纯文本。
- **运行时零落盘**：不写任何数据文件。仅有两处**进程内**缓存（不落盘）：
  昵称→wgid 映射（默认 6 小时）与营地查询数据（默认关闭，`CAMP_CACHE_TTL=0`）。
- 坦克目录：`assets/tank_catalog.json`（车名→tank_id，只读静态资产，由 `scripts/build_tank_catalog.py` 生成），
  用于把逐场战斗里的车名翻译成 tank_id 以查询“近 30 天常用坦克”。

## 配置

全部配置集中在 `core/config.py`（无需 `_conf_schema.json`）：

| 常量 | 默认 | 说明 |
|---|---|---|
| `REPLY_STYLE` | `auto` | `auto`（QQ 官方→qq_md，其余→plain）/ `qq_md` / `plain` / `table` |
| `CAMP_ENABLED` | `True` | `/wot <昵称>` 是否附带营地数据（三时段 + 常用坦克表） |
| `CAMP_SCAN_DAYS` | 30 | 「常用坦克」的时间窗（天）：这期间打过的车都会列出 |
| `CAMP_TANKS_TOP` | 0 | 常用坦克展示条数：**0 = 全部**（想缩短回复可改成 10~12） |
| `CAMP_TANKS_SCAN` | 60 | 最多为多少辆车查近 30 天单车数据（请求数上限） |
| `CAMP_BATTLE_PAGE_SIZE` / `CAMP_BATTLE_BATCH` | 100 / 3 | 逐场翻页的单页条数 / 一次并发翻几页（用于枚举车辆） |
| `CAMP_CACHE_TTL` | 0 | 营地查询数据进程内缓存秒数（0=不缓存） |
| `WGID_CACHE_TTL` | 21600 | 昵称→wgid 进程内缓存秒数 |
| `USER_AGENT` | 非浏览器标识串 | 两个站点共用；**不要**改成浏览器 UA（盒子会 403） |

## 安装

将本目录（astrbot_plugin_wotstats）放入 AstrBot 的 plugins 目录，重启 AstrBot 即可。无额外依赖。

## 开发者

开发与维护约定见 [AGENTS.md](AGENTS.md)；解析回归测试基于 tests/fixtures/ 的真实站点/接口快照。

```bash
python -m unittest discover -s tests -t .        # 单元测试（150 项，不联网）
python research/verify_integration.py loy1234    # 端到端实网验证（可选 --fixture-box 离线）
python research/verify_command_handler.py        # 指令层验证（含桩驱动降级分支）
```

> 注：research/ 为本地开发调研目录（站点快照/核查脚本/接入方案），不随仓库分发。
