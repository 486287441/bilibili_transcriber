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
from pipeline import publish_or_fallback

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
COOKIE_FILE = os.path.join(_SCRIPT_DIR, "www.bilibili.com_cookies.txt")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

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


def is_bilibili_url(text):
    return re.search(r"bilibili\.com/video/[a-zA-Z0-9]+", text)


def download_bilibili_audio(url):
    """Download audio; return (wav_path, {title, url}) or (None, None)."""
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
    print(f"\n🎵 [下载] 正在通过 yt-dlp 提取音频...")
    ydl_opts = {
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
        "cookiefile": COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
        "http_headers": {
            "Referer": "https://www.bilibili.com",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            ),
        },
    }
    if ydl_opts["cookiefile"] is None:
        del ydl_opts["cookiefile"]
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            audio_path = ydl.prepare_filename(info).rsplit(".", 1)[0] + ".wav"
            meta = {
                "title": (info.get("title") or "未命名视频").strip(),
                "url": (info.get("webpage_url") or url).strip(),
            }
            return audio_path, meta
    except Exception as e:
        print(f"❌ 下载失败: {e}")
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
        + "\n   视频转文字助手 - 已就绪\n"
        "   👉 复制 B 站链接 → 转写 → DeepSeek → 飞书\n"
        + "=" * 50
        + "\n"
    )

    try:
        while True:
            try:
                clip_text = pyperclip.paste().strip()
            except Exception:
                clip_text = ""

            if clip_text != last_clip and is_bilibili_url(clip_text):
                last_clip = clip_text
                print(f"\n🔍 检测到新链接: {clip_text}")

                audio_file, meta = download_bilibili_audio(clip_text)

                if audio_file and os.path.exists(audio_file):
                    text = transcribe_offline(audio_file, model)

                    if text:
                        publish_or_fallback(
                            text,
                            title=meta["title"],
                            url=meta["url"],
                            open_browser=True,
                        )
                    _cleanup_audio(audio_file)

                print("\n👀 监听中，请复制下一个链接...")

            time.sleep(1.5)
    except KeyboardInterrupt:
        print("\n👋 程序已安全退出。")


if __name__ == "__main__":
    main()
