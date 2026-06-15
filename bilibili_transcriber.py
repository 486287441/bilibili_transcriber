import os
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
import re
import shutil
import torch
import pyperclip

# ==========================================
# 依赖环境检查
# ==========================================
try:
    from funasr import AutoModel
    import yt_dlp
except ImportError as e:
    print(f"❌ 缺少必要的库: {e.name}。请执行: pip install funasr modelscope yt_dlp")
    sys.exit(1)

import config
from pipeline import publish_or_fallback_result
from video_urls import SUPPORTED_SITES_LABEL, detect_site, extract_video_url

config.validate()

# --- 核心参数配置 ---
# 强制指定模型下载路径，避免中文用户名路径报错
MODEL_CACHE_DIR = "D:/AI_Models_Cache"
if not os.path.exists(MODEL_CACHE_DIR):
    os.makedirs(MODEL_CACHE_DIR)

# 设置环境变量，确保所有模型都下载到此目录
os.environ["MODELSCOPE_CACHE"] = MODEL_CACHE_DIR

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(_SCRIPT_DIR, "downloads")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)
_SITE_REFERERS = {
    "bilibili": "https://www.bilibili.com",
    "douyin": "https://www.douyin.com",
}

# ==========================================
# 工具函数
# ==========================================


def get_ffmpeg_path(tool_name):
    local_path = os.path.join(_SCRIPT_DIR, f"{tool_name}.exe")
    if os.path.exists(local_path):
        return local_path
    env_path = shutil.which(tool_name)
    return env_path if env_path else None


FFMPEG_EXE = get_ffmpeg_path("ffmpeg")
FFPROBE_EXE = get_ffmpeg_path("ffprobe")


def _resolve_node_js_runtime() -> dict | None:
    """yt-dlp needs a JS runtime (Node 22+) to solve YouTube challenges."""
    if shutil.which("node"):
        return {"node": {}}
    return None


def _base_ydl_opts() -> dict:
    return {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "ffmpeg_location": FFMPEG_EXE,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }
        ],
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": config.YTDLP_SOCKET_TIMEOUT,
        "retries": config.YTDLP_RETRIES,
        "fragment_retries": config.YTDLP_FRAGMENT_RETRIES,
        "file_access_retries": 5,
        "continuedl": True,
    }


def _apply_ytdlp_auth(
    opts: dict,
    site: str,
    *,
    cookiesfrombrowser: tuple[str, ...] | None = None,
    cookiefile: str | None = None,
) -> dict:
    """Attach cookiefile or cookiesfrombrowser for yt-dlp."""
    out = dict(opts)
    out.pop("cookiefile", None)
    out.pop("cookiesfrombrowser", None)

    if cookiesfrombrowser:
        out["cookiesfrombrowser"] = cookiesfrombrowser
        return out

    if cookiefile:
        out["cookiefile"] = cookiefile
        return out

    cookie_file = config.resolve_ytdlp_cookie_file(site)
    browser = config.resolve_cookies_from_browser(site)

    if cookie_file:
        out["cookiefile"] = cookie_file
        return out

    if browser:
        out["cookiesfrombrowser"] = browser
    return out


def _ydl_opts_for_site(
    site: str,
    *,
    cookiesfrombrowser: tuple[str, ...] | None = None,
    cookiefile: str | None = None,
) -> dict:
    """Build yt-dlp options; Bilibili keeps the original referer/cookie behavior."""
    opts = _base_ydl_opts()
    headers = {"User-Agent": _DEFAULT_USER_AGENT}
    referer = _SITE_REFERERS.get(site)
    if referer:
        headers["Referer"] = referer
    opts["http_headers"] = headers

    if site == "youtube":
        node_runtime = _resolve_node_js_runtime()
        if node_runtime:
            opts["js_runtimes"] = node_runtime
        opts["format"] = "bestaudio/best/ba/b"

    return _apply_ytdlp_auth(
        opts,
        site,
        cookiesfrombrowser=cookiesfrombrowser,
        cookiefile=cookiefile,
    )


def _refresh_youtube_cookies_via_cdp() -> str | None:
    """Pull fresh YouTube cookies from running Chrome via CDP."""
    if not config.youtube_cdp_refresh_on_failure() and not config.youtube_cdp_refresh_before_download():
        return None
    try:
        from export_chrome_cookies import export_site_cookies

        print("🔄 正在从 Chrome 刷新 YouTube Cookie（无需关闭浏览器）...")
        path = export_site_cookies("youtube")
        print(f"✅ Cookie 已更新: {path}")
        return str(path)
    except Exception as exc:
        print(f"⚠️ Chrome CDP 刷新 Cookie 失败: {exc}")
        return None


def _youtube_auth_attempts() -> list[tuple[str, dict]]:
    """Build YouTube auth attempts: cookie 文件优先，仅 .env 显式配置时才尝试浏览器。"""
    attempts: list[tuple[str, dict]] = []
    seen: set[tuple[str | None, tuple[str, ...] | None]] = set()

    def _add(label: str, **kwargs) -> None:
        opts = _ydl_opts_for_site("youtube", **kwargs)
        key = (opts.get("cookiefile"), tuple(opts.get("cookiesfrombrowser") or ()))
        if key in seen:
            return
        seen.add(key)
        attempts.append((label, opts))

    cookie_file = config.resolve_ytdlp_cookie_file("youtube")
    if cookie_file:
        _add(f"cookie 文件 ({cookie_file})", cookiefile=cookie_file)

    if config.YTDLP_COOKIES_FROM_BROWSER_YOUTUBE or config.YTDLP_COOKIES_FROM_BROWSER:
        configured = config.resolve_cookies_from_browser("youtube")
        if configured:
            _add(f"浏览器 Cookie ({':'.join(configured)})", cookiesfrombrowser=configured)

    if not attempts:
        attempts.append(("无 Cookie", _ydl_opts_for_site("youtube")))
    return attempts


def _is_network_error(error: Exception | None) -> bool:
    if not error:
        return False
    msg = str(error).lower()
    return any(
        marker in msg
        for marker in (
            "read timed out",
            "timed out",
            "connectionpool",
            "connection aborted",
            "connection reset",
            "urlopen error",
            "network is unreachable",
            "temporary failure",
            "http error 503",
            "http error 502",
            "http error 429",
        )
    )


def _is_auth_error(error: Exception | None, *, site: str) -> bool:
    if not error or _is_network_error(error):
        return False
    msg = str(error).lower()
    if site == "youtube":
        return any(
            marker in msg
            for marker in (
                "sign in to confirm",
                "not a bot",
                "no longer valid",
                "requested format is not available",
                "challenge solving failed",
                "could not copy",
                "dpapi",
                "cookies",
            )
        )
    return False


def _describe_ytdlp_auth(ydl_opts: dict) -> str:
    if ydl_opts.get("cookiefile"):
        return f"cookie 文件 ({ydl_opts['cookiefile']})"
    browser = ydl_opts.get("cookiesfrombrowser")
    if browser:
        return f"浏览器 Cookie ({':'.join(browser)})"
    return "无 Cookie"


def _run_ytdlp_download(url: str, ydl_opts: dict):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        audio_path = ydl.prepare_filename(info).rsplit(".", 1)[0] + ".wav"
        meta = {
            "title": (info.get("title") or "未命名视频").strip(),
            "url": (info.get("webpage_url") or url).strip(),
        }
        return audio_path, meta


def _youtube_format_error(error: Exception | None) -> bool:
    if not error:
        return False
    msg = str(error).lower()
    return "requested format is not available" in msg or "challenge solving failed" in msg


def _youtube_browser_locked(error: Exception | None) -> bool:
    if not error:
        return False
    msg = str(error).lower()
    return "could not copy" in msg and "cookie" in msg


def _youtube_stale_cookies(error: Exception | None) -> bool:
    if not error:
        return False
    msg = str(error).lower()
    return "no longer valid" in msg or "sign in to confirm" in msg


def _print_cookie_hint(site: str, error: Exception | None = None) -> None:
    if site == "youtube":
        if _youtube_browser_locked(error):
            print(
                "💡 无法读取 Chrome Cookie：浏览器正在运行时会锁定数据库。\n"
                "   请完全退出 Chrome（任务管理器确认无 chrome.exe），然后重新复制链接重试。"
            )
            return

        if _youtube_format_error(error):
            has_node = bool(shutil.which("node"))
            print(
                "💡 YouTube 音频格式获取失败（JS 挑战未通过）。请确认：\n"
                f"   1. 已安装 Node.js 22+（当前: {'已检测到 node' if has_node else '未检测到 node'}）\n"
                '   2. 在项目 venv 执行: .venv\\Scripts\\pip install -U "yt-dlp[default]"\n'
                "   3. 完全退出 Chrome 后重试（优先从 Chrome 读取 Cookie）"
            )
            return

        if _youtube_stale_cookies(error):
            print(
                "💡 YouTube Cookie 失效。程序会在失败时自动通过 Chrome 调试接口刷新 Cookie。\n"
                "   前提：Chrome 须用 --remote-debugging-port=9222 启动（仅需设置一次）。\n"
                "   若仍失败，请确认 Chrome 已登录 youtube.com，然后执行：\n"
                "   .venv\\Scripts\\python export_chrome_cookies.py youtube"
            )
            return

        if _is_network_error(error):
            print(
                "💡 下载超时或网络不稳定（Cookie 可能仍然有效）。请：\n"
                "   1. 直接重新复制链接再试一次\n"
                "   2. 检查代理/VPN 是否稳定\n"
                f"   3. 可在 .env 调大 YTDLP_SOCKET_TIMEOUT（当前 {config.YTDLP_SOCKET_TIMEOUT}s）"
            )
            return

        print(
            "💡 YouTube 下载失败。请确认 cookies/www.youtube.com_cookies.txt 为最新导出。"
        )
        return
    if site == "douyin" and not config.has_ytdlp_auth(site):
        print(
            "💡 抖音链接通常需要登录 Cookie。"
            "请在 cookies/ 目录放置 www.douyin.com_cookies.txt，"
            "或在 .env 设置 YTDLP_COOKIE_FILE_DOUYIN / YTDLP_COOKIES_FROM_BROWSER_DOUYIN。"
        )


def download_bilibili_audio(url):
    """Download Bilibili audio; return (wav_path, {title, url}) or (None, None)."""
    return _download_video_audio(url, site="bilibili")


def download_video_audio(url):
    """Download audio from any supported site via yt-dlp."""
    return _download_video_audio(url, site=detect_site(url))


def _download_video_audio(url, *, site: str):
    """Download audio; return (wav_path, {title, url}) or (None, None)."""
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
    site_label = {
        "bilibili": "B站",
        "youtube": "YouTube",
        "douyin": "抖音",
    }.get(site, site)
    print(f"\n🎵 [下载] 正在通过 yt-dlp 提取音频 ({site_label})...")

    if site == "youtube" and config.youtube_cdp_refresh_before_download():
        refreshed = _refresh_youtube_cookies_via_cdp()
        if refreshed:
            print(f"🔐 已预刷新 Cookie: {refreshed}")

    labeled_attempts = (
        _youtube_auth_attempts() if site == "youtube" else [("默认", _ydl_opts_for_site(site))]
    )

    _, first_opts = labeled_attempts[0]
    auth_desc = _describe_ytdlp_auth(first_opts)
    if auth_desc != "无 Cookie":
        print(f"🔐 认证方式: {auth_desc}")

    last_error: Exception | None = None
    idx = 0
    cdp_refresh_tried = False
    while idx < len(labeled_attempts):
        label, opts = labeled_attempts[idx]
        if idx > 0:
            print(f"🔐 认证失败，正在换用: {label}")

        for net_try in range(config.YTDLP_NETWORK_RETRIES):
            if net_try > 0:
                print(
                    f"⚠️ 网络超时，正在重试下载 "
                    f"({net_try + 1}/{config.YTDLP_NETWORK_RETRIES})..."
                )
            try:
                return _run_ytdlp_download(url, opts)
            except Exception as e:
                last_error = e
                if _is_network_error(e) and net_try < config.YTDLP_NETWORK_RETRIES - 1:
                    time.sleep(2 * (net_try + 1))
                    continue
                break

        if site != "youtube" or not _is_auth_error(last_error, site=site):
            break

        if (
            not cdp_refresh_tried
            and config.youtube_cdp_refresh_on_failure()
            and not config.youtube_cdp_refresh_before_download()
        ):
            cdp_refresh_tried = True
            refreshed = _refresh_youtube_cookies_via_cdp()
            if refreshed:
                labeled_attempts.append(
                    (
                        f"CDP 刷新后的 cookie ({refreshed})",
                        _ydl_opts_for_site("youtube", cookiefile=refreshed),
                    )
                )

        if idx >= len(labeled_attempts) - 1:
            break
        idx += 1

    print(f"❌ 下载失败: {last_error}")
    if _is_network_error(last_error):
        print(
            f"💡 这是网络/CDN 超时，不是 Cookie 失效。"
            f"请直接重试同一链接（已自动重试 {config.YTDLP_NETWORK_RETRIES} 次）。"
        )
    else:
        _print_cookie_hint(site, last_error)
    return None, None


# ==========================================
# SenseVoice 核心逻辑
# ==========================================


def load_sensevoice_model():
    """初始化阿里 SenseVoiceSmall 组合模型"""
    print(f"⏳ 正在预加载 SenseVoiceSmall (路径: {MODEL_CACHE_DIR})...")
    try:
        model = AutoModel(
            model="iic/SenseVoiceSmall",
            vad_model="iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
            punc_model="iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
            device=DEVICE,
            disable_update=True,
            hub="ms",
        )
        return model
    except Exception as e:
        print(f"❌ 模型加载失败: {e}")
        sys.exit(1)


def transcribe_offline(audio_path, model):
    """离线转录函数"""
    start_time = time.time()
    print(f"📝 [转写] SenseVoice 处理中...")

    try:
        res = model.generate(
            input=audio_path,
            cache={},
            language="zh",
            use_itn=True,
            batch_size_s=120,
        )

        if res and len(res) > 0:
            text = res[0]["text"]
            clean_text = re.sub(r"\[.*?\]", "", text).strip()

            print("-" * 45 + f"\n✅ [转写] 完成，耗时 {int(time.time() - start_time)} 秒")
            return clean_text
        return None
    except Exception as e:
        print(f"❌ 转录过程中出错: {e}")
        return None


def _cleanup_audio(audio_file):
    try:
        if audio_file and os.path.exists(audio_file):
            os.remove(audio_file)
            print("🗑️ 已清理临时 wav 文件。")
    except OSError:
        pass


def process_video_url(url, model, *, open_browser=True):
    """
    Run download -> transcribe -> publish flow for one supported video URL.
    Returns: (success, feishu_url, message)
    """
    audio_file, meta = download_video_audio(url)
    if not (audio_file and os.path.exists(audio_file) and meta):
        return False, None, "下载音频失败"

    try:
        text = transcribe_offline(audio_file, model)
        if not text:
            return False, None, "转写失败"

        ok, doc_url = publish_or_fallback_result(
            text,
            title=meta["title"],
            url=meta["url"],
            open_browser=open_browser,
        )
        if not ok:
            return False, None, "发布失败（已执行回退流程）"
        return True, doc_url, "完成"
    finally:
        _cleanup_audio(audio_file)


def process_bilibili_url(url, model, *, open_browser=True):
    """Backward-compatible alias for process_video_url."""
    return process_video_url(url, model, open_browser=open_browser)


# ==========================================
# 主程序
# ==========================================


def main():
    if not FFMPEG_EXE:
        print("❌ 错误: 未检测到 FFmpeg。请将 ffmpeg.exe 放在脚本同级目录。")
        return

    device_name = (
        torch.cuda.get_device_name(0) if DEVICE == "cuda" else "CPU"
    )
    print(f" 运行设备: {DEVICE.upper()} ({device_name})")

    model = load_sensevoice_model()

    last_clip = ""
    print(
        "\n"
        + "=" * 50
        + f"\n   视频转文字助手 - 已就绪\n"
        f"   👉 复制视频链接（{SUPPORTED_SITES_LABEL}）→ 转写 → DeepSeek → 飞书\n"
        + "=" * 50
        + "\n"
    )

    try:
        while True:
            try:
                clip_text = pyperclip.paste().strip()
            except Exception:
                clip_text = ""

            video_url = extract_video_url(clip_text)
            if clip_text != last_clip and video_url:
                last_clip = clip_text
                print(f"\n🔍 检测到新链接 ({detect_site(video_url)}): {video_url}")
                ok, _, msg = process_video_url(video_url, model, open_browser=True)
                if not ok:
                    print(f"❌ {msg}")

                print("\n👀 监听中，请复制下一个链接...")

            time.sleep(1.5)
    except KeyboardInterrupt:
        print("\n👋 程序已安全退出。")


if __name__ == "__main__":
    main()
