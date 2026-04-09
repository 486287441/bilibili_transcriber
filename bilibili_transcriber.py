import os
import sys
import time
import re
import shutil
import subprocess
import torch
import pyperclip
from tqdm import tqdm

# ==========================================
# 依赖环境检查1
# ==========================================
try:
    from funasr import AutoModel
    from modelscope.utils.constant import DownloadMode
    import yt_dlp
except ImportError as e:
    print(f"❌ 缺少必要的库: {e.name}。请执行: pip install funasr modelscope yt_dlp")
    sys.exit(1)

# --- 核心参数配置 ---
# 强制指定模型下载路径，避免中文用户名路径报错
MODEL_CACHE_DIR = "D:/AI_Models_Cache" 
if not os.path.exists(MODEL_CACHE_DIR):
    os.makedirs(MODEL_CACHE_DIR)

# 设置环境变量，确保所有模型都下载到此目录
os.environ['MODELSCOPE_CACHE'] = MODEL_CACHE_DIR

DOWNLOAD_DIR = "downloads"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# ==========================================
# 工具函数
# ==========================================

def get_ffmpeg_path(tool_name):
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{tool_name}.exe")
    if os.path.exists(local_path): return local_path
    env_path = shutil.which(tool_name)
    return env_path if env_path else None

FFMPEG_EXE = get_ffmpeg_path("ffmpeg")
FFPROBE_EXE = get_ffmpeg_path("ffprobe")

def is_bilibili_url(text):
    return re.search(r'bilibili\.com/video/[a-zA-Z0-9]+', text)

def download_bilibili_audio(url):
    if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)
    print(f"\n🎵 正在通过 yt-dlp 提取音频...")
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'ffmpeg_location': FFMPEG_EXE,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'wav', 'preferredquality': '192'}],
        'quiet': True, 'no_warnings': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # SenseVoice 使用 wav 格式识别率和速度最稳
            audio_path = ydl.prepare_filename(info).rsplit('.', 1)[0] + ".wav"
            return audio_path
    except Exception as e:
        print(f"❌ 下载失败: {e}"); return None

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
            hub="ms" # 使用 ModelScope 下载源，国内速度快
        )
        return model
    except Exception as e:
        print(f"❌ 模型加载失败: {e}")
        sys.exit(1)

def transcribe_offline(audio_path, model):
    """离线转录函数"""
    start_time = time.time()
    print(f"📝 4060 正在全力转录中...")
    
    try:
        # SenseVoiceSmall 识别
        res = model.generate(
            input=audio_path,
            cache={},
            language="zh", 
            use_itn=True,  # 自动数字转换
            batch_size_s=120 # 4060 8G 可以开到 120-200 提高速度
        )
        
        # 提取文本
        if res and len(res) > 0:
            text = res[0]['text']
            # 去除 SenseVoice 的情感/事件标签，如 [HAPPY], [Music]
            clean_text = re.sub(r'\[.*?\]', '', text).strip()
            
            print("-" * 45 + f"\n✅ 转录完成！耗时: {int(time.time() - start_time)} 秒")
            return clean_text
        return None
    except Exception as e:
        print(f"❌ 转录过程中出错: {e}")
        return None

# ==========================================
# 主程序
# ==========================================

def main():
    if not FFMPEG_EXE:
        print("❌ 错误: 未检测到 FFmpeg。请将 ffmpeg.exe 放在脚本同级目录。"); return

    print(f" 运行设备: {DEVICE.upper()} ({torch.cuda.get_device_name(0) if DEVICE=='cuda' else 'CPU'})")
    
    # 初始化模型
    model = load_sensevoice_model()

    last_clip = ""
    print("\n" + "="*50 + "\n   视频转文字助手 - 已就绪\n   👉 复制B站链接，我将自动开始处理\n" + "="*50 + "\n")

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
                    text = transcribe_offline(audio_file, model)
                    
                    if text:
                        full_prompt = f"""### 任务指令 ###
你是一位专业的文字整理助手。请对下方【转文字结果】进行处理：
1. 修正原文中明显的同音错别字；
2. 将全文统一转换为【简体中文】；
3. 保持原文内容和文字，严禁增删改动原意，仅进行合理的自然段划分；
4. 在文章开头补充一个结构清晰的目录。

### 转文字结果 ###
{text}

---"""
                        pyperclip.copy(full_prompt)
                        print("📋 任务完成！指令已复制到剪贴板。")
                        
                        # 唤醒浏览器
                        print("🌐 正在唤醒豆包进行后期处理...")
                        os.system('start https://www.doubao.com/')
                        
                        # 清理临时音频
                        try:
                            if os.path.exists(audio_file):
                                os.remove(audio_file)
                                print(f"🗑️ 已清理临时 wav 文件。")
                        except:
                            pass
                
                print("\n👀 监听中，请复制下一个链接...")
            
            time.sleep(1.5)
    except KeyboardInterrupt:
        print("\n👋 程序已安全退出。")

if __name__ == "__main__":
    main()