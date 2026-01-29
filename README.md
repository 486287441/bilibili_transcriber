# 功能
监测系统剪贴板，识别到 B 站视频链接后自动提取视频语音并转换为文字；将转写结果拼接提示语 **「这是 B 站视频转文字的结果，请修正可能错误的文字，并将内容格式整理为文章形式，同时在文章开头补充结构目录」**，同步复制至剪贴板，最后自动打开豆包网页端，方便后续编辑处理。
# 前置工作
1. ffmpeg 的环境配置，https://ffmpeg.org/download.html
2. 安装依赖包 pip install -r requirements.txt
3. 安装CUDA 版 PyTorch
	pip install torch torchvision torchaudio --index-url [https://download.pytorch.org/whl/cu124](https://download.pytorch.org/whl/cu124)
# 技术路线
Python
1.  B 站视频的音频版下载
		you-get
2. 语音转文字
		OpenAI Whisper small
3. 监测剪切板自动触发
		pyperclip
