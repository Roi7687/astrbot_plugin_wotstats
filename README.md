# astrbot_plugin_wotstats — 坦克世界战绩查询

一个 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 插件：在 QQ 中发送 `/wot <玩家昵称>`，
抓取**偶游盒子战绩查询站**（https://wot.ouj.com/zhanji/index.html，实际数据后端 wotbox.ouj.com）的
服务端渲染 HTML 并解析，以 Markdown 排版回复玩家的近期战绩。

## 功能

- `/wot <昵称>` —— 查询玩家**近期战绩**（战斗力、近 1500 场标准局胜率、场均数据、常用坦克、最近对局、盒子评价）
- `/wot 总 <昵称>`（或 `/wot 总战绩 <昵称>`）—— 查询**总战绩**（入伍时间/天数、全时段胜率、总体/场均击毁-占领-防守-发现、最近常用坦克）
- `/wot help` —— 用法帮助
- 昵称**区分大小写**；中文昵称可直接输入（如 `/wot 坦克玩家甲`）

## 数据源与格式

- 抓取方式：**纯 HTTP GET 服务端渲染 HTML**（无需登录 / Cookie / 浏览器自动化）；站点改版维护见 research/ 与 AGENTS.md。
- 查无此人：站点对不存在的昵称仍返回 HTTP 200，插件按页面内 `.not-find-user` 提示块判定并友好回复。
- 回复排版：QQ 官方机器人平台使用**原生 Markdown 消息**（msg_type=2；QQ 官方 Markdown 语法暂不支持表格，
  采用标题/加粗/列表排版，详见 AGENTS.md 调研记录）；其他平台自动回退为纯文本。
- **不落盘、不缓存**：插件运行时零文件写入（无数据缓存/无状态文件），只做“抓取 → 提取 → 回复”。

## 安装

将本目录（astrbot_plugin_wotstats）放入 AstrBot 的 plugins 目录，重启 AstrBot 即可。

## 开发者

开发与维护约定见 [AGENTS.md](AGENTS.md)；页面解析回归测试基于 tests/fixtures/ 的真实站点快照。

> 注：research/ 为本地开发调研目录（真实页面快照/截图），不随仓库分发。
