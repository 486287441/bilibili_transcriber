# 视频自动转文稿助手

这是一个基于 **阿里 SenseVoiceSmall** 的全自动视频转文字工具，支持 **B站、YouTube、抖音** 等 yt-dlp 可识别的主流站点。

## 核心功能
* **自动监听触发**：复制视频链接即可触发（如 B站 `BV...`、YouTube、抖音短链），无需手动粘贴。
* **无缝 AI 衔接**：自动合成结构化润色指令，一键跳转豆包 AI，粘贴即得docx或者pdf。

## 如何使用
### 第一步：下载发行版
1. 下载bilibili_transcriber.zip
2. 解压后运行python-3.12.8-amd64.exe（已安装python的跳过此步）
3. 运行一键安装程序，等待显示环境配置完毕
4. 运行启动程序，初次运行可能会卡在“正在启动 B站视频自动转文稿助手...“，这是正常现象，因为初次需要下载AI模型，静待即可

### 第二步：复制链接

前往浏览器复制视频地址（B站 / YouTube / 抖音），剩下的交给助手：
1. **转录中**：命令行会显示转录进度（40分钟视频约 2-4 分钟转完）。
2. **唤醒 AI**：完成后自动打开豆包官网，你只需 **Ctrl + V** 即可开始 AI 总结。

### Telegram Bot 触发（新增）

> **迁移说明**：推荐使用常驻 FastAPI 服务 `python -m server`（M02+）。`dual_entry_service.py` 与 `telegram_bot.py` 为 legacy 入口，Telegram 完整迁入计划在 M04。

1. 在 `.env` 中补充：
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`（可选；填写后仅允许该会话触发）
2. 启动 Telegram 入口：
   - `python telegram_bot.py`
3. 给 Bot 发送包含视频链接的消息（B站 / YouTube / 抖音等）
4. Bot 将复用现有转写与飞书发布流程，并回复飞书文档链接

### 多站点 Cookie（可选）

**YouTube** 需要 Cookie，且 yt-dlp 需通过 **Node.js 22+** 解 JS 挑战（安装 `yt-dlp[default]` 时会带上 `yt-dlp-ejs`）。请确认本机 `node --version` 可用。

**推荐（下载时 Chrome 可保持打开）**：在 `.env` 中保留 cookie 文件路径，程序会在认证失败时自动通过 Chrome 调试接口（CDP）刷新 Cookie：

```env
YTDLP_COOKIE_FILE_YOUTUBE=cookies/www.youtube.com_cookies.txt
# YTDLP_CDP_REFRESH_YOUTUBE=on_failure   # 默认；可选 always / off
```

**一次性设置**：Chrome 需用调试端口启动（之后可一直开着，不必每次下载前关闭）：

1. 完全退出 Chrome（任务管理器确认无 `chrome.exe`）
2. 用以下命令或快捷方式重新打开 Chrome：
   ```
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
   ```
3. 在 Chrome 中登录 [youtube.com](https://www.youtube.com)

也可手动刷新 Cookie（Chrome 可开着）：

```powershell
.venv\Scripts\python export_chrome_cookies.py youtube
```

**不推荐**：`YTDLP_COOKIES_FROM_BROWSER_YOUTUBE=chrome` 需要完全退出 Chrome 才能读取 Cookie 数据库。

也可使用 Netscape 格式 cookie 文件（浏览器插件导出），统一放在项目 `cookies/` 目录：

- `cookies/www.bilibili.com_cookies.txt`
- `cookies/www.youtube.com_cookies.txt`
- `cookies/www.douyin.com_cookies.txt`

详见 `.env.example` 中的 `YTDLP_CDP_REFRESH_YOUTUBE` 与 `YTDLP_COOKIE_FILE_*`。

##  注意事项

### FastAPI 常驻服务（推荐）

```powershell
# 1. 构建前端（首次或 web/ 代码变更后）
cd web
npm install
npm run build
cd ..

# 2. 启动服务（API + Web UI 同端口）
.venv\Scripts\python -m server
```

浏览器打开 `http://127.0.0.1:8765/` 即可使用控制面板。开发时可另开 `cd web && npm run dev`（Vite 代理到 8765）。`MODEL_LOAD_POLICY=lazy`（默认）时启动不加载模型，首次任务才占用 GPU 显存（SenseVoice 约 2–4 GB）。空闲 `model_idle_timeout_minutes`（默认 30）后自动卸载模型。

**勿同时运行** `telegram_bot.py` 或 `dual_entry_service.py`（Telegram 轮询 409 冲突）。

1. **显存保护**：处理超长视频时请关闭浏览器或 3D 游戏以预留显存。
2. **首次运行**：第一次转录会从 ModelScope（国内镜像）下载约 2GB 的模型文件，国内网络通常 2 分钟内完成。
3. **中文路径**：请确保本程序所在的文件夹路径不包含中文，以防 FFmpeg 读写失败。

#  技术路线

1. **音频提取与预处理**
* `yt-dlp`
* `FFmpeg`


2. **核心识别引擎**
* `SenseVoiceSmall`：多语言语音理解模型（330M 参数）。
* `fsmn-vad`：语音端点检测，防止长音频内存堆积。
* `ct-punc`：智能标点恢复模型。


3. **自动化链路**
* `pyperclip`：双向剪贴板交互。
* `ModelScope`：国内模型分发与缓存管理。
