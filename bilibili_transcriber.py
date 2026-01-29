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

def get_audio_duration(file_path):
    """使用 ffprobe 获取音频总秒数"""
    try:
        cmd = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', file_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return float(result.stdout)
    except Exception:
        return 0

def is_bilibili_url(text):
    return re.search(r'bilibili\.com/video/[a-zA-Z0-9]+', text)

def download_bilibili_audio(url):
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
    
    print(f"\n🎵 正在下载音频资源...")
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
        'no_warnings': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            audio_path = ydl.prepare_filename(info).rsplit('.', 1)[0] + ".mp3"
            return audio_path
    except Exception as e:
        print(f"❌ 下载失败: {e}")
        return None

def transcribe_with_progress(audio_path, model):
    """带进度条的转录核心函数"""
    duration = get_audio_duration(audio_path)
    
    if duration > 0:
        mins, secs = divmod(int(duration), 60)
        est_time = duration / SPEED_FACTOR
        print(f"📊 视频总长: {mins}分{secs}秒")
        print(f"🕒 预估耗时: 约 {int(est_time)} 秒 (RTX 4060 加速中...)")
    
    # 初始化进度条
    pbar = tqdm(total=int(duration), unit="s", desc="📝 语音转文字中", 
                bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]')

    # --- 进度条猴子补丁逻辑 ---
    original_format_timestamp = whisper.utils.format_timestamp

    def patched_format_timestamp(seconds: float, always_include_hours: bool = False, decimal_marker: str = '.'):
        # 只要 whisper 调用此函数输出时间戳，我们就更新进度条位置
        if seconds > pbar.n:
            pbar.n = min(int(seconds), int(duration))
            pbar.refresh()
        return original_format_timestamp(seconds, always_include_hours, decimal_marker)

    # 替换 whisper 内部函数
    whisper.utils.format_timestamp = patched_format_timestamp
    
    print("-" * 45)
    start_time = time.time()
    
    try:
        # 执行转录 (verbose=False 避免干扰进度条)
        result = model.transcribe(
            audio_path, 
            language="zh", 
            fp16=(DEVICE == "cuda"), 
            verbose=False 
        )
        
        # 恢复原函数并关闭进度条
        whisper.utils.format_timestamp = original_format_timestamp
        pbar.n = int(duration)
        pbar.refresh()
        pbar.close()
        
        actual_time = int(time.time() - start_time)
        print("-" * 45)
        print(f"✅ 转录完成！实际耗时: {actual_time} 秒")
        return result["text"]
        
    except Exception as e:
        pbar.close()
        whisper.utils.format_timestamp = original_format_timestamp
        print(f"❌ 转录出错: {e}")
        return None

def main():
    # 环境自检
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("❌ 错误: 未检测到 FFmpeg 环境，请先安装并配置 Path。")
        return

    print(f"🚀 运行设备: {DEVICE.upper()} ({torch.cuda.get_device_name(0) if DEVICE=='cuda' else 'CPU'})")
    print(f"⏳ 正在预加载 AI 模型 ({MODEL_SIZE})...")
    model = whisper.load_model(MODEL_SIZE, device=DEVICE)

    last_clip = ""
    print("\n" + "="*50)
    print("  🎧 B站视频自动转文稿助手 - 已就绪")
    print("  👉 复制B站链接，我将为你处理一切")
    print("="*50 + "\n")

    try:
        while True:
            try:
                clip_text = pyperclip.paste().strip()
            except:
                clip_text = ""

            if clip_text != last_clip and is_bilibili_url(clip_text):
                last_clip = clip_text
                print(f"\n🔍 检测到新链接: {clip_text}")
                
                audio_file = download_bilibili_audio(clip_text)
                if audio_file and os.path.exists(audio_file):
                    text = transcribe_with_progress(audio_file, model)
                    
                    if text:
                        # 构造发送给豆包的 Prompt
                        full_prompt = (
                            "这是 B 站视频转文字的结构，请将可能错误的文字修正并且将格式整理成一篇文章的形式，"
                            "在文章开头给出文章的结构目录。\n\n"
                            f"{text}"
                        )
                        pyperclip.copy(full_prompt)
                        print("📋 润色指令已就绪！正在为您打开豆包...")
                        webbrowser.open("https://www.doubao.com/")
                
                print("\n👀 监听中，请复制下一个链接...")
            
            time.sleep(1.5)
    except KeyboardInterrupt:
        print("\n👋 感谢使用，程序已退出。")

if __name__ == "__main__":
    main()