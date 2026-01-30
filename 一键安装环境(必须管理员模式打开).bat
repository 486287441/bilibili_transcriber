@echo off
chcp 65001
title B站转文稿助手 - SenseVoice 强化环境部署

echo ======================================================
echo 🚀 正在为您配置 [SenseVoice 版] 运行环境...
echo ======================================================

:: 1. 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo 🔍 未检测到 Python，正在尝试自动安装...
    winget install -e --id Python.Python.3.10 --scope machine --override "/passive PrependPath=1"
    if %errorlevel% neq 0 (
        echo ❌ 自动安装失败！请访问 python.org 手动安装。
        pause & exit
    )
    echo ✅ Python 安装成功！请【重新运行】此脚本。
    pause & exit
)

:: 2. 安装基础依赖 (新增 funasr, modelscope, pyperclip)
echo 📦 正在安装 ASR 核心依赖库...
pip install funasr modelscope yt-dlp pyperclip tqdm -i https://pypi.tuna.tsinghua.edu.cn/simple

:: 3. 智能检测 GPU
nvidia-smi >nul 2>&1
if %errorlevel% equ 0 (
    echo ⚡ 检测到 NVIDIA 4060 系列显卡，安装 GPU 加速版 PyTorch...
    :: 注意：funasr 建议使用 cu118 或 cu121
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
) else (
    echo 💻 未检测到独立显卡，安装 CPU 版...
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
)

echo ======================================================
echo ✅ 环境配置完成！
echo 🚀 正在进行 SenseVoice 兼容性自检...
:: 修改了自检脚本，确保 funasr 也能正常 import
python -c "import torch; import funasr; print('---'); print('ASR 框架: FunASR (SenseVoice)'); print('计算设备:', 'GPU (CUDA)' if torch.cuda.is_available() else 'CPU'); print('显卡型号:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'); print('---')"
echo ======================================================
echo 👉 环境已就绪，现在运行你的 Python 脚本即可。
pause