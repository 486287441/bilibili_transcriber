import importlib
import subprocess
import sys
import time
import re
import os

# 自动安装依赖
def install_and_import(package, import_name=None):
    import_name = import_name or package
    try:
        importlib.import_module(import_name)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    finally:
        globals()[import_name] = importlib.import_module(import_name)

for pkg in [
    ("pyperclip",),
    ("yt-dlp", "yt_dlp"),
    ("openai-whisper", "whisper"),
    ("torch",),
    ("webbrowser",)
]:
    install_and_import(*pkg)

def is_bilibili_url(text):
    return re.match(r'https?://(www\.)?bilibili\.com/video/[a-zA-Z0-9]+', text)

def download_audio(url, output_dir="downloads"):
    global yt_dlp
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "%(title)s.%(ext)s")
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_path,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        audio_file = os.path.splitext(filename)[0] + ".mp3"
        return audio_file

def transcribe_audio(audio_path):
    global whisper
    model = whisper.load_model("small")
    result = model.transcribe(audio_path, language="zh")
    return result["text"]

def main():
    global pyperclip, webbrowser
    last_clip = ""
    print("请复制B站视频链接，程序会自动处理...")
    while True:
        try:
            clip = pyperclip.paste()
            if clip != last_clip and is_bilibili_url(clip):
                print(f"检测到B站链接: {clip}")
                audio_file = download_audio(clip)
                print("音频下载完成，正在转文字...")
                text = transcribe_audio(audio_file)
                prompt = (
                    "这是B站视频转文字的结构，请将可能错误的文字修正并且将格式整理成一篇文章的形式，"
                    "在文章开头给出文章的结构目录。\n\n"
                    f"{text}"
                )
                pyperclip.copy(prompt)
                print("已复制到剪贴板，正在打开豆包...")
                webbrowser.open("https://www.doubao.com/")
                last_clip = clip
            time.sleep(2)
        except KeyboardInterrupt:
            print("程序已退出。")
            break

if __name__ == "__main__":
    main()