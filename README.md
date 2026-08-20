# Bilibili Transcriber — AI 部署手册


## 安装空间与硬件优先级

本项目按 **NVIDIA CUDA 强制优先**设计。只要电脑存在 NVIDIA 显卡，Agent 就必须让 Fun-ASR 和 PaddleOCR 两个模型都使用 GPU；CUDA 不可用时应修复驱动和安装包，不能直接改走 CPU。只有确认电脑没有 NVIDIA 显卡时，才允许采用 CPU 路线。不得为了省事默认安装 CPU 版。

首次完整安装建议目标磁盘至少预留 **15 GB**，推荐预留 **20 GB 以上**；处理视频还需要额外临时空间。当前版本的典型占用如下：

| 内容 | 典型磁盘占用 | 说明 |
| --- | ---: | --- |
| Git 仓库源码 | 约 45 MB | 不含虚拟环境、模型、视频和日志。 |
| Python CUDA 环境及依赖 | 约 8～10 GB | 当前实测 `.venv` 约 8.75 GB；PyTorch、Paddle GPU wheel 与版本会影响大小。 |
| 前端依赖与构建产物 | 约 50～150 MB | 当前 `node_modules` 约 46 MB，整个 `web` 目录约 120 MB。 |
| PP-OCRv5 OCR 模型 | 约 21 MB | [`PP-OCRv5_mobile_det`](https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/pipeline_usage/OCR.html) 约 4.7 MB，`PP-OCRv5_mobile_rec` 约 16 MB；缓存元数据会略增。 |
| Fun-ASR-Nano-2512 | 约 2.15 GB | [官方模型页](https://www.modelscope.cn/models/FunAudioLLM/Fun-ASR-Nano-2512)标注约 2.15 GB；另有约数 MB 的 VAD 模型，建议为 ASR 缓存预留至少 2.3 GB。 |
| 项目完整基础安装 | 约 11～13 GB | 不含后续下载的视频、音频、转写稿、日志和重复缓存。 |

GPU 建议使用 NVIDIA RTX 系列、可用显存至少 8 GB。Agent 必须分别验证 `torch.cuda.is_available()` 与 `paddle.device.is_compiled_with_cuda()`；两个结果都为 `True` 才算 CUDA 路线配置完成。模型大小会随上游版本更新而变化，以上是当前版本的部署预算，不是永久不变的精确值。

## 用户如何把任务交给 AI

把下面这段话连同仓库链接发给 Codex、Claude Code、Cursor Agent 等能够实际操作电脑的 AI：

```text
请把这个项目部署到我的 Windows 电脑：
https://github.com/486287441/bilibili_transcriber

先完整阅读根目录 README.md，并严格执行其中的“AI 部署协议”。请自行检查环境、安装依赖、配置并授权飞书 CLI、构建前端、启动并验证服务。服务打开后，引导我访问 DeepSeek Key 页面，并让我亲自在本机 Web 设置的“API 配置”中填写 Key 和选择模型；不要索要、读取或代填我的 Key。不要覆盖已有的 .env、cookies、data、downloads、logs 或未提交代码。完成后报告访问地址、验证结果、启动/停止方法和遗留问题。
```

如果不希望 AI 提交真实视频，再加一句：

```text
只做无副作用的健康检查，不要运行真实视频 E2E，也不要创建测试飞书文档。
```

---

## AI 部署协议

如果你是部署本项目的 AI，请把本节视为执行约束。

### 完成标准

只有同时满足以下条件，才可以宣布部署成功：

1. 项目位于确定、可长期保留的目录，而非临时目录。
2. `.venv\Scripts\python.exe` 可用，Python 核心依赖能导入。
3. 检测到 NVIDIA 显卡时，PyTorch 与 PaddlePaddle 必须都通过 CUDA 验证；只有确认没有 NVIDIA 显卡时才允许使用 CPU。
4. FFmpeg 与 FFprobe 均能被程序找到。
5. `web\dist\index.html` 已构建。
6. 官方 `lark-cli` 已安装，并完成 user 身份授权。
7. 飞书知识库参数已经配置；用户已被引导在本机设置页亲自填写 DeepSeek API Key。
8. Windows 启动文件夹中的 `哔哩哔哩 Transcriber.lnk` 已创建，且目标严格指向项目根目录的 `哔哩哔哩 Transcriber.exe`，工作目录与图标均正确。
9. `start.bat` 能启动服务。
10. `/api/health` 返回 HTTP 200、`status: "ok"`、`ready: true`。
11. `http://127.0.0.1:<端口>/` 能打开 Web 页面。

“执行过安装命令”不等于“部署完成”。必须检查退出码和最终状态。

### 安全与权限边界

- 可以做只读探测、克隆仓库、在项目目录创建虚拟环境、安装依赖、构建前端和创建被 `.gitignore` 排除的本地配置。
- 不得覆盖现有 `.env`；若它存在，只检查缺项，永远不要打印内容。
- 不得删除或重建现有 `.venv`、`cookies`、`data`、`downloads`、`logs`，除非先解释原因并获得明确同意。
- 不得对有本地改动的仓库执行 `git reset --hard`、`git clean -fd` 或强制 checkout。
- 不得要求用户把 API Key、Cookie 或飞书 token 粘贴到聊天。DeepSeek Key 必须由用户亲自在本机 Web 设置页填写；Agent 只检查“已配置”状态。
- 首次启动会自动注册 Windows 登录自启；启动前必须告知用户。
- 真实 E2E 会下载视频与大模型、消耗 DeepSeek 额度并创建飞书文档。未经同意不要执行。
- 分阶段执行并逐步验证；失败时读完整错误，不要机械重复同一命令。

### 最终报告必须包含

安装目录、仓库版本、Python/Node/FFmpeg/lark-cli 版本、NVIDIA CUDA（或无 NVIDIA 时的 CPU）路线、服务 URL、健康检查结果、是否创建登录自启、是否运行真实视频测试，以及任何本地源码适配。

---

## 项目简介

这是一个驻留在 Windows 本机的视频转文稿服务。服务监听系统剪贴板中的视频链接，任务会进入持久化队列，并按以下路线获取文本：

1. B 站官方 CC 字幕；
2. PaddleOCR PP-OCRv5 识别画面硬字幕；
3. yt-dlp + FFmpeg 下载音频，再用 Fun-ASR-Nano-2512 本地识别。

之后程序调用 DeepSeek 做纠错、整理和总结，并通过 `lark-cli` 将 Markdown 写入指定飞书知识库。队列、历史、文稿和日志均保存在本机。

支持 B 站（含 `b23.tv`）、YouTube（普通视频、Shorts、`youtu.be`）和抖音常见视频/笔记链接。

主要能力包括队列排序、取消和重试，WebSocket 进度，剪贴板监听，字幕/OCR/ASR 路线选择，模型懒加载和空闲卸载，历史记录、重新处理、文稿追问，以及 DeepSeek 失败时的豆包回退。

## 当前版本的真实约束

| 项目 | 当前行为 |
| --- | --- |
| 操作系统 | 仅支持 Windows 10/11 x64。服务代码使用 `winreg`，脚本使用 Windows 进程和启动文件夹 API。 |
| 网络 | 强制绑定 `127.0.0.1`，仅本机访问；默认端口 `8765`。 |
| Python | 推荐官方 CPython 3.12 x64；不要使用 MSYS2 Python 或 Python 3.14。 |
| Node.js | 构建前端需要 Node；YouTube 的 yt-dlp JS challenge 需要 Node 22+。 |
| FFmpeg | `ffmpeg` 与 `ffprobe` 必须同时在 PATH，或同时放到项目根目录。 |
| 云服务 | `config.validate()` 要求 DeepSeek 三项与飞书两项齐全后才允许启动。 |
| 模型 | ASR 使用 `FunAudioLLM/Fun-ASR-Nano-2512` 和 VAD；OCR 使用 PP-OCRv5，首次使用通常需联网下载。 |
| 模型缓存 | ModelScope 缓存目前硬编码为 `D:/AI_Models_Cache`。 |
| 前端 | FastAPI 只托管构建后的 `web/dist`。 |
| 自启 | 每次启动都会校准 Windows 启动文件夹中的 `哔哩哔哩 Transcriber.lnk`。 |

### 没有 D 盘时

先执行 `Test-Path 'D:\'`。若返回 `False`，当前源码导入时可能无法创建模型缓存。AI 应告知用户，并对 `bilibili_transcriber.py` 做最小本地适配：

```python
MODEL_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "bilibili_transcriber", "modelscope")
```

最终报告必须说明此修改。不要为了满足硬编码而执行磁盘分区等危险操作；若用户要求 Git 工作区完全干净，应暂停并说明限制。

## 架构与入口

```text
浏览器 / 系统剪贴板
        ↓
FastAPI + WebSocket（server/，127.0.0.1:8765）
        ├── SQLite 队列与历史（data/queue.db）
        ├── B站 CC 字幕
        ├── PaddleOCR 硬字幕
        └── yt-dlp + FFmpeg + FunASR
                         ↓
                DeepSeek 两阶段整理
                         ↓
                  lark-cli → 飞书
```

- `start.bat`：用户后台启动入口。
- `stop.bat`：停止端口监听和项目残留服务进程。
- `python -m server`：前台诊断入口。
- `server/app.py`：FastAPI 应用与生命周期。
- `server/worker.py`：队列与转写路线。
- `bilibili_transcriber.py`：下载、FFmpeg、FunASR。
- `pipeline.py`：DeepSeek、飞书和豆包回退。
- `web/`：Vue 3 + Vite 前端。

---

## Windows 标准部署流程

以下使用 PowerShell。AI 必须把示例路径替换为实际绝对路径。

### 0. 确认目录和仓库状态

```powershell
$ProjectRoot = 'D:\Apps\bilibili_transcriber'
git clone https://github.com/486287441/bilibili_transcriber.git $ProjectRoot
Set-Location $ProjectRoot
```

目录已存在时，不要重新克隆覆盖；先检查：

```powershell
git status --short
git remote -v
git branch --show-current
```

只有工作区干净且用户同意更新时才执行 `git pull --ff-only`。ZIP 解压版没有 `.git` 也可以运行。

### 1. 系统预检

```powershell
[System.Environment]::OSVersion.VersionString
[Environment]::Is64BitOperatingSystem
Get-PSDrive -PSProvider FileSystem
Get-Command git,python,py,node,npm,ffmpeg,ffprobe,lark-cli,nvidia-smi -ErrorAction SilentlyContinue
```

分别运行版本命令。Python 选择顺序：

1. 优先 `py -3.12`；
2. 否则寻找官方 CPython 3.12；
3. 用 `python -c "import sys; print(sys.executable); print(sys.version)"` 核实路径；
4. 若路径位于 `msys64`，不要使用；
5. 若只有 3.13/3.14，安装 3.12，避免 Paddle/FunASR wheel 兼容问题。

缺少系统工具时，在用户同意后可用 `winget`。先用 `winget search` 核对 ID：

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id Gyan.FFmpeg -e
```

安装后重新打开 PowerShell 刷新 PATH，不要因旧终端未刷新而重复安装。

### 2. 创建 Python 虚拟环境

若 `.venv` 已存在，先验证：

```powershell
& "$ProjectRoot\.venv\Scripts\python.exe" -c "import sys; print(sys.executable); print(sys.version)"
```

出现 `Unable to create process` 表示它记录的基础 Python 已移动。先说明原因并取得同意，再重建，不能直接删除用户环境。

新建环境：

```powershell
Set-Location $ProjectRoot
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
```

若无 `py`，用已确认的官方 Python 3.12 绝对路径执行 `-m venv .venv`。后续始终显式调用项目解释器，无需激活。

### 3. 优先安装 CUDA 版 PyTorch

`requirements.txt` 不包含 PyTorch。Agent 必须先运行 `nvidia-smi`；检测到 NVIDIA GPU 时，必须安装 CUDA wheel。仓库当前建议 CUDA 12.4：

```powershell
& .\.venv\Scripts\python.exe -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
```

PyTorch wheel 自带 CUDA runtime，通常无需另装 CUDA Toolkit。驱动不兼容时查看 [PyTorch 官方安装矩阵](https://pytorch.org/get-started/locally/)，不要强行修改源码的 `DEVICE`。

只有确认没有 NVIDIA GPU 时，才安装 CPU wheel：

```powershell
& .\.venv\Scripts\python.exe -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

```powershell
& .\.venv\Scripts\python.exe -c "import torch; print(torch.__version__); print('cuda=',torch.cuda.is_available()); print('runtime=',torch.version.cuda); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

### 4. 优先安装 GPU 版 Paddle，再安装项目依赖

RTX / NVIDIA 环境必须先从 Paddle 官方 CUDA 12.6 索引安装 GPU 引擎：

```powershell
& .\.venv\Scripts\python.exe -m pip uninstall -y paddlepaddle
& .\.venv\Scripts\python.exe -m pip install paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
```

只有确认没有 NVIDIA GPU 时，才安装 CPU 引擎：

```powershell
& .\.venv\Scripts\python.exe -m pip install paddlepaddle==3.3.0
```

```powershell
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -c "import torch,funasr,modelscope,paddle,paddleocr,yt_dlp,fastapi,uvicorn,openai,PIL; print('Python dependencies OK'); print('paddle_cuda=', paddle.device.is_compiled_with_cuda())"
& .\.venv\Scripts\python.exe -m pip check
```

NVIDIA 电脑还必须执行真实 OCR GPU 冒烟测试：

```powershell
& .\.venv\Scripts\python.exe .\scripts\test_ocr_gpu_runtime.py
```

输出必须同时满足 `"torch_cuda": true` 和 `"ocr_device": "gpu..."`。这一步会实际初始化 PP-OCRv5，比只检查 wheel 是否支持 CUDA 更可靠。

依赖体积较大，下载可能耗时。PaddlePaddle 与 PyTorch 分别携带推理运行时，必须分别验证 GPU。NVIDIA 路线若任何一个 CUDA 检查或 OCR 冒烟测试失败，部署尚未完成，Agent 必须先排查 wheel、驱动和 CUDA 兼容性，不能静默退回 CPU。

### 5. 验证 FFmpeg

```powershell
ffmpeg -version
ffprobe -version
& .\.venv\Scripts\python.exe -c "import shutil; print('ffmpeg=',shutil.which('ffmpeg')); print('ffprobe=',shutil.which('ffprobe'))"
```

也可把便携版 `ffmpeg.exe`、`ffprobe.exe` 一起放在仓库根目录。只装 FFmpeg 不装 FFprobe 会导致 OCR 视频分析失败。安装后重启服务，模块才会重新解析工具路径。

### 6. 构建前端

Node 必须至少为 22：

```powershell
node --version
npm --version
Set-Location "$ProjectRoot\web"
npm ci
npm run build
Set-Location $ProjectRoot
Test-Path .\web\dist\index.html
```

最后必须返回 `True`。构建会从 jsDelivr 下载字体、用 `.venv` 中的 Pillow 生成 favicon，再执行 Vite。因此需要网络，且 Python 环境必须先完成。

### 7. 安装并授权飞书 CLI

项目需要官方 [Lark/Feishu CLI](https://github.com/larksuite/cli)，命令名必须是 `lark-cli`：

```powershell
npm install -g @larksuite/cli
lark-cli --version
```

按当前 CLI 帮助初始化并授权。常见流程：

```powershell
lark-cli config init --new
lark-cli auth login --domain docs --domain wiki --domain drive
lark-cli auth status
lark-cli doctor
```

让用户本人在浏览器确认授权。参数如因版本变化报错，先运行：

```powershell
lark-cli config init --help
lark-cli auth login --help
lark-cli wiki --help
lark-cli docs --help
```

程序实际以 `--as user` 调用 `wiki +node-create` 和 `docs +update`，所以 bot 身份或只读授权不够。登录用户必须能在目标知识库父节点下创建和编辑文档。

查询知识库：

```powershell
lark-cli wiki +space-list --as user
lark-cli wiki +node-list --as user --space-id my_library
```

若当前版本不支持 `my_library`，从 space-list 获取真实 `space_id` 再查询。不要猜父节点 token；让用户选择目录，并从 JSON 或 Wiki URL 取得。

### 8. 配置飞书目标知识库

仅在文件不存在时复制：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Agent 根据上一步用户选择的知识库位置，在本机 `.env` 填写：

```dotenv
FEISHU_WIKI_SPACE_ID=目标知识库_space_id
FEISHU_WIKI_PARENT_NODE_TOKEN=目标父目录_node_token
```

只验证飞书参数非空，不打印具体值：

```powershell
& .\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; import os; load_dotenv(); n=['FEISHU_WIKI_SPACE_ID','FEISHU_WIKI_PARENT_NODE_TOKEN']; print({x:bool(os.getenv(x,'').strip()) for x in n})"
& .\.venv\Scripts\python.exe -c "import config; config.validate(); print('config OK')"
```

### 9. 按需配置站点 Cookie

推荐把 Netscape 格式 Cookie 放入：

```text
cookies\www.bilibili.com_cookies.txt
cookies\www.youtube.com_cookies.txt
cookies\www.douyin.com_cookies.txt
```

程序会自动寻找。也可在 `.env` 设置：

```dotenv
YTDLP_COOKIE_FILE_BILIBILI=cookies/www.bilibili.com_cookies.txt
YTDLP_COOKIE_FILE_YOUTUBE=cookies/www.youtube.com_cookies.txt
YTDLP_COOKIE_FILE_DOUYIN=cookies/www.douyin.com_cookies.txt
```

浏览器读取方式如 `YTDLP_COOKIES_FROM_BROWSER_YOUTUBE=chrome` 也受支持，但 Chrome 数据库可能被锁。YouTube 辅助导出：

```powershell
& .\.venv\Scripts\python.exe .\export_chrome_cookies.py youtube
```

该脚本可能启动 Chrome，需要用户参与。Cookie 等价于登录凭据，禁止提交、上传或贴入聊天。

### 10. 首次启动与强制开机自启

本项目要求必须启用 Windows 登录自启，不能把它当作可选项。项目根目录必须包含：

```text
哔哩哔哩 Transcriber.exe
favicon.ico
launch_silent.vbs
```

启动服务时，程序会在 Windows 启动文件夹创建一个带图标的入口：

```text
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\哔哩哔哩 Transcriber.lnk
```

该入口不是 Python、BAT 或 VBS 脚本；它的 `TargetPath` 必须直接指向项目根目录的 `哔哩哔哩 Transcriber.exe`，`WorkingDirectory` 必须是项目根目录，`IconLocation` 必须是项目根目录的 `favicon.ico`。这样 Windows“任务管理器 → 启动应用”会把它识别成有名称和图标的桌面程序。采用快捷方式指向项目 EXE，而不是把 EXE 二进制复制一份到 Startup，是因为启动器还需要同目录的 `launch_silent.vbs` 和项目文件；同时也避免升级后 Startup 中残留旧 EXE。

```powershell
Set-Location $ProjectRoot
cmd /c start.bat
```

常用变体：

```powershell
cmd /c "start.bat --restart"
cmd /c "start.bat --clean"
```

`--restart` 先停止再启动；`--clean` 清理旧版入口残留，仅在确有遗留问题时使用。脚本最多等待 300 秒健康就绪。

首次启动后，Agent 必须主动校准并验收自启，不能只相信日志：

```powershell
& .\.venv\Scripts\python.exe -c "from server.autostart import ensure_autostart; print(ensure_autostart())"

$Startup = [Environment]::GetFolderPath('Startup')
$Link = Join-Path $Startup '哔哩哔哩 Transcriber.lnk'
$Shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($Link)
[pscustomobject]@{
  Exists = Test-Path $Link
  TargetPath = $Shortcut.TargetPath
  WorkingDirectory = $Shortcut.WorkingDirectory
  IconLocation = $Shortcut.IconLocation
}
```

验收必须同时满足：`Exists=True`；目标是 `$ProjectRoot\哔哩哔哩 Transcriber.exe`；工作目录等于 `$ProjectRoot`；图标是 `$ProjectRoot\favicon.ico,0`。还应让用户打开“任务管理器 → 启动应用”，确认“哔哩哔哩 Transcriber”已启用且显示项目图标。任何一项不满足都不能宣布部署完成。

诊断时前台运行：

```powershell
& .\.venv\Scripts\python.exe -m server
```

成功后用 `Ctrl+C` 停止。不要与 `start.bat` 同时运行。

服务启动后，Agent 必须让用户本人完成 DeepSeek 配置：

1. 引导用户打开 <https://platform.deepseek.com/api_keys> 创建或复制 API Key。
2. 打开本机页面 <http://127.0.0.1:8765/>，点击右上角“设置”。
3. 在左侧“API 配置”中，由用户亲自填写 DeepSeek API Key，并选择 `DeepSeek V4 Flash` 或 `DeepSeek V4 Pro`。
4. Agent 只通过 `/api/settings/secrets` 确认 `deepseek_configured: true`，不得读取输入框、`.env` 内容或要求用户把 Key 发到聊天中。

### 11. 验收

```powershell
$Port = 8765
Invoke-RestMethod "http://127.0.0.1:$Port/api/health" | ConvertTo-Json
Invoke-RestMethod "http://127.0.0.1:$Port/api/status" | ConvertTo-Json
Invoke-RestMethod "http://127.0.0.1:$Port/api/settings/secrets" | ConvertTo-Json
Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing | Select-Object StatusCode
```

期望健康响应：

```json
{"status":"ok","version":"0.1.0","ready":true}
```

`settings/secrets` 只返回配置掩码。页面应返回 HTTP 200，并且用户填写后 `deepseek_configured` 应为 `true`。若 `.env` 使用其他端口，同步修改 `$Port`。

真实视频测试必须经用户同意；它会下载模型/视频、产生 API 费用并创建飞书文档。成功标准是任务最终完成、历史出现且飞书文档可打开，不只是“成功入队”。

---

## 配置参考

### 服务与云服务

| 变量 | 默认值 | 必填 | 说明 |
| --- | --- | --- | --- |
| `SERVER_HOST` | `127.0.0.1` | 否 | 入口会强制绑定本机。 |
| `SERVER_PORT` | `8765` | 否 | Web/API 端口。 |
| `DEEPSEEK_API_KEY` | 空 | 润色前必填 | 用户通过本机设置页填写；Agent 不接触明文。 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | 是 | OpenAI 兼容基址。 |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | 是 | 初始模型；保存后的 Web 设置优先。 |
| `FEISHU_WIKI_SPACE_ID` | 空 | 是 | 目标知识空间。 |
| `FEISHU_WIKI_PARENT_NODE_TOKEN` | 空 | 是 | 新文档的父节点。 |

### yt-dlp

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `YTDLP_COOKIE_FILE_BILIBILI/YOUTUBE/DOUYIN` | 自动寻找 | 各站 Cookie 文件。 |
| `YTDLP_COOKIE_FILE` | 空 | 通用后备 Cookie。 |
| `YTDLP_COOKIES_FROM_BROWSER_BILIBILI/YOUTUBE/DOUYIN` | 空 | 如 `chrome`、`chrome:Default`。 |
| `YTDLP_COOKIES_FROM_BROWSER` | 空 | 通用浏览器后备。 |
| `YTDLP_SOCKET_TIMEOUT` | `120` | socket 超时秒数。 |
| `YTDLP_RETRIES` | `10` | 下载重试。 |
| `YTDLP_FRAGMENT_RETRIES` | `10` | 分片重试。 |
| `YTDLP_NETWORK_RETRIES` | `3` | 应用层网络重试轮次。 |

站点专用配置优先于通用配置，文件优先于浏览器读取。

### PaddleOCR

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `PADDLEOCR_DEVICE` | `auto` | `auto`、`cpu`、`gpu:0`。 |
| `PADDLEOCR_DETECTION_MODEL` | `PP-OCRv5_mobile_det` | 检测模型。 |
| `PADDLEOCR_RECOGNITION_MODEL` | `PP-OCRv5_mobile_rec` | 识别模型。 |
| `PADDLEOCR_CROP_RATIO` | `0.45` | 分析画面底部比例，代码限制 0.25–0.65。 |
| `PADDLEOCR_FRAME_INTERVAL_SEC` | `2.0` | 常规抽帧间隔（0.5 fps）；短视频自动提高到 1 fps，超长视频降低到约 0.33 fps。 |
| `PADDLEOCR_BATCH_SIZE` | `8` | 单次提交给 PP-OCRv5 的帧数。 |
| `PADDLEOCR_DUPLICATE_HASH_DISTANCE` | `2` | 相邻帧感知哈希距离不超过此值时复用上帧结果。 |
| `PADDLEOCR_FRAME_WIDTH` | `960` | FFmpeg 裁剪字幕区域后的缩放宽度。 |
| `PADDLEOCR_VIDEO_MAX_HEIGHT` | `480` | OCR 检测视频的优先最高分辨率。 |
| `PADDLEOCR_MIN_SCORE` | `0.62` | 置信度阈值。 |
| `PADDLEOCR_DETECTION_SAMPLES` | `12` | 自动硬字幕探测采样数，代码至少取 6。 |

Web 设置保存在 `data/settings.json`，包括剪贴板监听、自动打开飞书、模型加载策略、空闲卸载、DeepSeek 模型及可编辑提示词/模板。飞书正文模板必须保留 `{{body}}`。

---

## 日常操作

```powershell
cmd /c start.bat
cmd /c stop.bat
cmd /c "start.bat --restart"
```

默认页面：<http://127.0.0.1:8765/>。服务会监听剪贴板，复制支持的视频 URL 即自动入队；可在设置中关闭。

| 路线 | 行为 |
| --- | --- |
| `auto` | B 站依次尝试官方字幕、硬字幕、ASR；其他站点主要回退 ASR。 |
| `subtitle` | 优先平台字幕。 |
| `ocr` | 下载视频并识别画面硬字幕。 |
| `asr` | 下载音频并本地语音识别。 |

`stop.bat` 不会删除队列、历史、文稿或日志。

登录自启位于：

```text
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\哔哩哔哩 Transcriber.lnk
```

该快捷方式是项目的强制、自修复启动入口：仅删除它不是永久关闭，因为下次服务启动会重新创建。部署 Agent 不得把自启当成可选配置，也不得在交付时移除它。

## 数据与备份

| 路径 | 内容 | 建议 |
| --- | --- | --- |
| `.env` | API/飞书配置 | 安全备份，绝不提交。 |
| `cookies/` | 站点登录凭据 | 高度敏感。 |
| `data/queue.db` | 队列、历史、统计 | 必须备份。 |
| `data/settings.json` | Web 设置与模板 | 建议备份。 |
| `downloads/transcripts/` | 可信逐字稿 | 建议备份。 |
| `downloads/polished/` | 整理后 Markdown | 建议备份。 |
| `downloads/last_transcript.txt` | 最近原始转写 | 按需。 |
| `logs/server.log`、`startup.log` | 运行/启动日志 | 故障时保留。 |
| `D:/AI_Models_Cache` | ASR/VAD 缓存 | 可重新下载。 |
| `web/dist/` | 前端构建 | 可重新生成。 |

复制 SQLite 备份前先停止服务，避免复制写入中的数据库。升级或迁移至少保留 `.env`、`cookies`、`data` 和重要 `downloads`。

---

## 故障排查

### `.venv not found` / `Unable to create process`

虚拟环境必须在根目录。后者通常表示 `.venv` 记录的基础 Python 已卸载；查看 `.venv\pyvenv.cfg`，获同意后重建并重装 PyTorch/requirements。

### 配置校验失败

```powershell
& .\.venv\Scripts\python.exe -c "import config; config.validate()"
```

检查飞书知识库参数是否完整，不显示实际值。DeepSeek Key 不阻止服务启动；由用户在本机 Web 设置的“API 配置”中填写。

### 8765 端口占用

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health
Get-NetTCPConnection -LocalPort 8765 -State Listen | Select-Object OwningProcess
```

若是本项目，用 `--restart`；若是其他程序，在 `.env` 换 `SERVER_PORT`，不要随意杀死不明进程。

### 后台启动超时

```powershell
Get-Content .\logs\startup.log -Tail 100
Get-Content .\logs\server.log -Tail 200
& .\.venv\Scripts\python.exe -m server
```

前台 traceback 是首要证据。

### 页面 404/空白

检查 `Test-Path .\web\dist\index.html`。为 False 时重新 `npm ci`、`npm run build`。

### Torch/GPU 问题

```powershell
nvidia-smi
& .\.venv\Scripts\python.exe -c "import sys,torch; print(sys.executable); print(torch.__version__,torch.version.cuda,torch.cuda.is_available())"
```

确认使用项目解释器。DLL 错误常见于架构不一致、损坏 venv、缺 Visual C++ Runtime 或 CUDA wheel 不兼容。存在 NVIDIA 显卡时，应按官方兼容矩阵修复 CUDA wheel 或驱动，不得以安装 CPU wheel 作为永久规避方案；只有确认没有 NVIDIA 显卡时才走 CPU 路线。

### PaddleOCR 初始化失败

存在 NVIDIA 显卡时，必须安装匹配环境的 `paddlepaddle-gpu` 并让 OCR 使用 GPU。若 CUDA 初始化失败，应按 Paddle 官方 CUDA/cuDNN 兼容组合修复驱动和 wheel，不能照搬 PyTorch 的版本选择，也不能降级 CPU。只有确认没有 NVIDIA 显卡时，才安装 `paddlepaddle` CPU 版并显式使用 CPU。

### 模型加载卡住

检查网络、磁盘空间、`D:\AI_Models_Cache` 和 `logs/server.log`。首次下载较慢，不要同时启动多个服务。

### YouTube/抖音下载失败

YouTube 先确认 Node 22+、yt-dlp 版本和有效 Cookie：

```powershell
node --version
& .\.venv\Scripts\python.exe -m yt_dlp --version
```

浏览器数据库锁定时完全退出 Chrome 或用 Cookie 文件。抖音通常也需要已登录 Cookie。

### `lark-cli` 找不到或飞书写入失败

```powershell
npm config get prefix
npm list -g --depth=0
Get-Command lark-cli -ErrorAction SilentlyContinue
lark-cli auth status
```

重开终端刷新 npm PATH。写入失败依次检查 user 身份、wiki/docs/drive 权限、space ID、父 token 是否同属该 space，以及用户对父节点的创建/编辑权限。

### DeepSeek 错误

- 401/403：Key 无效、过期或无权限；
- 429：频率或余额/配额问题；
- model not found：模型名与端点不匹配；
- connect error：网络、代理、DNS 或 base URL。

失败时应用会尝试豆包回退并操作剪贴板/浏览器；原文仍备份到 `downloads/last_transcript.txt`。

### 剪贴板未入队

确认 `clipboard_enabled`、URL 格式、活动队列与历史。历史去重会阻止重复 URL；应从历史页面重新处理，不要随意删数据库。

分享日志前仍需人工检查敏感信息。过滤器会遮盖常见 `sk-...`，但无法保证识别所有密钥、URL 参数和私人路径。

---

## 开发和测试

前端热更新（后端需已启动）：

```powershell
Set-Location "$ProjectRoot\web"
npm run dev
```

页面为 <http://127.0.0.1:5173/>，Vite 将 `/api`、`/ws` 代理至 8765。

重点无真实网络回归：

```powershell
& .\.venv\Scripts\python.exe .\scripts\test_text_stats.py
& .\.venv\Scripts\python.exe .\scripts\test_transcript_routes.py
& .\.venv\Scripts\python.exe .\scripts\test_route_pipeline_contracts.py
& .\.venv\Scripts\python.exe .\scripts\test_two_stage_pipeline.py
& .\.venv\Scripts\python.exe .\scripts\test_video_ocr_batches.py
```

启动/停止测试会操作端口和后台进程：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_start_stop.ps1
```

`scripts/test_e2e_url.py` 会走真实完整流水线，没有用户许可不要运行。

## 安全升级

升级前停止服务，检查 `git status`，备份 `.env`、`cookies`、`data`、重要 `downloads`。工作区干净时：

```powershell
git pull --ff-only
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
Set-Location .\web
npm ci
npm run build
Set-Location ..
cmd /c "start.bat --restart"
```

升级后重新健康检查；不要因数据库有自动迁移逻辑而跳过备份。

## AI 最终交付模板

```text
部署结果：成功 / 部分成功 / 失败
安装目录：<绝对路径>
仓库版本：<commit hash 或 ZIP>
系统：<Windows 版本/架构>
Python：<版本和虚拟环境路径>
计算路线：NVIDIA CUDA / 无 NVIDIA 时 CPU（显卡名、torch CUDA 与 Paddle CUDA 是否可用）
Node.js：<版本>
FFmpeg / FFprobe：<版本或路径>
lark-cli：<版本、user 授权是否通过>
前端构建：<是否存在 web/dist/index.html>
配置验证：<飞书是否可用；DeepSeek 是否显示已配置，不显示任何秘密>
服务地址：http://127.0.0.1:<端口>/
健康检查：<HTTP、status、ready>
登录自启：<已创建 / 未创建 / 未验证>
真实视频测试：<未执行 / 成功 / 失败；是否创建文档>
启动：<命令>
停止：<命令>
本地源码适配：<没有则写“无”>
遗留问题：<没有则写“无”>
```

## 安全说明与官方参考

- `.env`、Cookie 和 OAuth token 都是敏感信息；提交前始终运行 `git status`。
- 服务没有登录认证，禁止通过端口转发、反向代理或源码改动直接暴露到局域网/公网。
- 密钥若进入聊天、截图或 Git 历史，应立即撤销并重新生成。
- 仓库当前未声明许可证，不要自行推定再分发或商用权限。

官方资料：

- [项目仓库](https://github.com/486287441/bilibili_transcriber)
- [DeepSeek 开放平台](https://platform.deepseek.com/)
- [Lark/Feishu CLI](https://github.com/larksuite/cli)
- [PyTorch 安装](https://pytorch.org/get-started/locally/)
- [PaddlePaddle 安装](https://www.paddlepaddle.org.cn/install/quick)
- [FFmpeg](https://ffmpeg.org/download.html)
- [Node.js](https://nodejs.org/)

如果当前 checkout 的代码行为与本文冲突，以代码和运行时证据为准。AI 应阅读错误及相关源码后更新判断，不能用 README 的旧假设覆盖事实。
