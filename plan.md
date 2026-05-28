# Telegram 触发入口（极小改动）计划

## 目标

在不改动现有核心链路的前提下，新增 Telegram Bot 触发入口：

- 现有：剪切板链接 -> 转写 -> 飞书文档
- 新增：Telegram 消息链接 -> 转写 -> 飞书文档 -> Telegram 回传飞书链接



# bot

Done! Congratulations on your new bot. You will find it at t.me/bili_transcriber_bot. You can now add a description, about section and profile picture for your bot, see /help for a list of commands. By the way, when you've finished creating your cool bot, ping our Bot Support if you want a better username for it. Just make sure the bot is fully operational before you do this.  
  
Use this token to access the HTTP API:  
`8800413768:AAHu1vQdiq_i-F3Z5e_ecr1IYhg_uFaN9uI`  
Keep your token **secure** and **store it safely**, it can be used by anyone to control your bot.  
  
For a description of the Bot API, see this page: [https://core.telegram.org/bots/api](https://core.telegram.org/bots/api)

## 约束

- 不重构现有架构
- 不改核心转写/发布逻辑
- 不新增复杂队列、权限、调度系统
- 只做轻量增量功能

## 最小实现路径

1. **先创建 Telegram Bot（当前优先）**
  - 通过 BotFather 创建机器人
  - 获取 `BOT_TOKEN`
  - 获取目标会话 `CHAT_ID`
2. **新增 Telegram 输入适配层**
  - 新建一个轻量监听脚本（长轮询）
  - 从消息文本提取 B 站链接
3. **复用现有 pipeline**
  - 把提取到的链接直接走当前已有下载/转写/飞书流程
  - 不复制核心逻辑，尽量调用现有函数
4. **新增 Telegram 输出回传**
  - 成功：回复飞书文档链接
  - 失败：回复简短错误信息，便于重试

## 交付清单（最小版）

- `plan.md`（本文件）
- `.env` 增加 Telegram 相关配置项（Token、Chat ID）
- 一个 Telegram 入口脚本（例如 `telegram_bot.py`）
- README 增加简短使用说明

## 验收标准

- Telegram 发一条包含 B 站链接的消息
- 程序完成既有转写+飞书流程
- Telegram 收到最终飞书文档链接

