@echo off
chcp 65001
title B站转文稿助手 - 智能环境部署

echo ======================================================
echo 🚀 正在为您配置 B站转文稿助手 运行环境...
echo ======================================================

:: 1. 检查并自动安装 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo 🔍 未检测到 Python，正在尝试自动安装...
    winget install -e --id Python.Python.3.10 --scope machine --override "/passive PrependPath=1"
    if %errorlevel% neq 0 (
        echo ❌ 自动安装失败！请手动安装 Python。
        pause & exit
    )
    echo ✅ Python 安装成功！请【重新运行】此脚本以继续。
    pause & exit
)

:: 2. 安装基础依赖
echo 📦 正在安装基础依赖库...
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

:: 3. 智能检测 NVIDIA 显卡并安装对应 Torch
echo 🔎 正在检测硬件环境...
nvidia-smi >nul 2>&1
if %errorlevel% equ 0 (
    echo ⚡ 检测到 NVIDIA 显卡，准备安装 GPU 加速版 PyTorch (约 2GB)...
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 --force-reinstall
) else (
    echo 💻 未检测到 NVIDIA 显卡，准备安装轻量化 CPU 版 (约 400MB)...
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu --force-reinstall
)

echo ======================================================
echo ✅ 环境配置完成！
echo 🚀 运行设备自检：
python -c "import torch; print('---'); print('可用加速设备:', 'GPU (CUDA)' if torch.cuda.is_available() else 'CPU'); print('设备详情:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '核心已就绪'); print('---')"
echo ======================================================
echo 👉 现在可以运行 "启动程序.bat" 了。
pause