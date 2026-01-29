@echo off
chcp 65001
title B站转文稿助手 - 环境部署

echo ======================================================
echo 🚀 正在为您配置 B站转文稿助手 运行环境...
echo ======================================================

:: 1. 检查 Python 是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 未检测到 Python，请先安装 Python 并勾选 "Add to PATH"！
    pause
    exit
)

:: 2. 安装基础依赖
echo 📦 正在安装基础依赖库 (requirements.txt)...
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

:: 3. 安装 PyTorch (显卡加速版)
echo ⚡ 正在安装 GPU 版本的 PyTorch (RTX 4060 加速专用)...
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

echo ======================================================
echo ✅ 环境配置完成！
echo 👉 现在你可以双击运行 "bilibili transcriber.py" 了。
echo ======================================================
pause