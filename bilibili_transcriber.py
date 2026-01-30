import os
import sys
import time
import re
import shutil
import webbrowser
import subprocess
from tqdm import tqdm

# ==========================================
# 依赖环境检查
# ==========================================
try:
    import torch
    import whisper
    import yt_dlp
    import pyperclip
    import whisper.utils
except ImportError as e:
    print(f"❌ 缺少必要的库: {e.name}。请根据 README 安装依赖。")
    sys.exit(1)

# --- 核心参数配置 ---
MODEL_SIZE = "small"    # 4060 推荐 small 或 medium
DOWNLOAD_DIR = "downloads"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
SPEED_FACTOR = 12.0     # 4060 运行 small 模型的预估倍速

# --- FFmpeg 路径检测逻辑 ---
def get_ffmpeg_path(tool_name):
    """优先检测脚本根目录，其次检测系统环境变量"""
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{tool_name}.exe")
    if os.path.exists(local_path):
        return local_path
    env_path = shutil.which(tool_name)
    if env_path:
        return env_path
    return None

FFMPEG_EXE = get_ffmpeg_path("ffmpeg")
FFPROBE_EXE = get_ffmpeg_path("ffprobe")

def get_audio_duration(file_path):
    if not FFPROBE_EXE: return 0
    try:
        cmd = [FFPROBE_EXE, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return float(result.stdout)
    except Exception: return 0

def is_bilibili_url(text):
    return re.search(r'bilibili\.com/video/[a-zA-Z0-9]+', text)

def download_bilibili_audio(url):
    if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)
    print(f"\n🎵 正在下载音频资源...")
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'ffmpeg_location': FFMPEG_EXE,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        'quiet': True, 'no_warnings': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            audio_path = ydl.prepare_filename(info).rsplit('.', 1)[0] + ".mp3"
            return audio_path
    except Exception as e:
        print(f"❌ 下载失败: {e}"); return None

def transcribe_with_progress(audio_path, model):
    """带进度条的转录核心函数"""
    duration = get_audio_duration(audio_path)
    if duration > 0:
        mins, secs = divmod(int(duration), 60)
        print(f"📊 视频总长: {mins}分{secs}秒")
    
    pbar = tqdm(total=int(duration), unit="s", desc="📝 语音转文字中", 
                bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]')

    original_format_timestamp = whisper.utils.format_timestamp
    def patched_format_timestamp(seconds: float, always_include_hours: bool = False, decimal_marker: str = '.'):
        if seconds > pbar.n:
            pbar.n = min(int(seconds), int(duration))
            pbar.refresh()
        return original_format_timestamp(seconds, always_include_hours, decimal_marker)

    whisper.utils.format_timestamp = patched_format_timestamp
    start_time = time.time()
    
    try:
        result = model.transcribe(
            audio_path, 
            language="zh", 
            fp16=(DEVICE == "cuda"), 
            verbose=False,
            condition_on_previous_text=False, # 防止幻觉重复
            initial_prompt="以下是B站视频的简体中文转录内容。", # 引导简体轨道
            no_speech_threshold=0.6 
        )
        
        whisper.utils.format_timestamp = original_format_timestamp
        pbar.n = int(duration); pbar.refresh(); pbar.close()
        print("-" * 45 + f"\n✅ 转录完成！实际耗时: {int(time.time() - start_time)} 秒")
        return result["text"]
    except Exception as e:
        pbar.close(); whisper.utils.format_timestamp = original_format_timestamp
        print(f"❌ 转录出错: {e}"); return None

def main():
    if not FFMPEG_EXE or not FFPROBE_EXE:
        print("❌ 错误: 未检测到 FFmpeg 或 ffprobe。"); return

    print(f"🚀 运行设备: {DEVICE.upper()} ({torch.cuda.get_device_name(0) if DEVICE=='cuda' else 'CPU'})")
    print(f"⏳ 正在预加载 OpenAI Whisper ({MODEL_SIZE})...")
    model = whisper.load_model(MODEL_SIZE, device=DEVICE)

    last_clip = ""
    print("\n" + "="*50 + "\n   🎧 B站视频自动转文稿助手 - 已就绪\n   👉 复制B站链接，我将为你处理一切\n" + "="*50 + "\n")

    try:
        while True:
            try: clip_text = pyperclip.paste().strip()
            except: clip_text = ""

            if clip_text != last_clip and is_bilibili_url(clip_text):
                last_clip = clip_text
                print(f"\n🔍 检测到新链接: {clip_text}")
                
                audio_file = download_bilibili_audio(clip_text)
                if audio_file and os.path.exists(audio_file):
                    text = transcribe_with_progress(audio_file, model)
                    
                    if text:
                        # 1. 结构化 Prompt 合成
                        full_prompt = f"""### 任务指令 ###
你是一位专业的文字整理助手。请对下方【转文字结果】进行处理：
1. 修正原文中明显的同音错别字；
2. 将全文统一转换为【简体中文】；
3. 保持原文内容和文字，严禁增删改动原意，仅进行合理的自然段划分；
4. 在文章开头补充一个结构清晰的目录。

### 转文字结果 ###
{text}

---"""
                        # 2. 存入剪贴板
                        pyperclip.copy(full_prompt)
                        print("📋 任务完成！指令已复制到剪贴板。")
                        
                        # 3. 强制唤醒浏览器
                        print("🌐 正在尝试唤醒浏览器打开豆包...")
                        try:
                            os.system('start https://www.doubao.com/')
                        except:
                            pass
                        
                        # 4. 自动清理本地音频
                        try:
                            if os.path.exists(audio_file):
                                os.remove(audio_file)
                                print(f"🗑️ 已清理临时文件。")
                        except:
                            pass
                
                print("\n👀 监听中，请复制下一个链接...")
            
            time.sleep(1.5)
    except KeyboardInterrupt:
        print("\n👋 感谢使用，程序已退出。")

if __name__ == "__main__":
    main()