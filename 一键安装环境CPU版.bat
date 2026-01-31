@echo off
chcp 65001 >nul
title ASR 环境安装（CPU 专用版）

echo ======================================================
echo     B站转文字助手 - CPU 模式环境安装
echo     （无显卡依赖 / 稳定兜底）
echo ======================================================
echo.

:: ===============================
:: 1. 检查 Python
:: ===============================
echo [1/4] 检查 Python...

python --version
if %errorlevel% neq 0 (
    echo ❌ 未检测到 Python，请先安装 Python 3.10+
    pause
    exit
)

echo.

:: ===============================
:: 2. 升级 pip
:: ===============================
echo [2/4] 升级 pip...

python -m pip install --upgrade pip ^
-i https://pypi.tuna.tsinghua.edu.cn/simple

echo.

:: ===============================
:: 3. 安装 CPU 版 Torch
:: ===============================
echo [3/4] 安装 PyTorch (CPU 版)...

pip uninstall -y torch torchvision torchaudio >nul 2>&1

pip install torch torchvision torchaudio ^
--index-url https://download.pytorch.org/whl/cpu

if %errorlevel% neq 0 (
    echo ❌ Torch 安装失败
    pause
    exit
)

echo.

:: ===============================
:: 4. 安装 requirements.txt
:: ===============================
echo [4/4] 安装项目依赖...

if not exist requirements.txt (
    echo ❌ 未找到 requirements.txt
    pause
    exit
)

pip install -r requirements.txt ^
-i https://pypi.tuna.tsinghua.edu.cn/simple

echo.

:: ===============================
:: 5. 验证
:: ===============================
echo 正在检测运行环境...
echo --------------------------------------

python -c "import torch; print('Torch:',torch.__version__); print('CUDA:',torch.cuda.is_available()); print('Device: CPU')"

echo --------------------------------------

echo.
echo ✅ 安装完成（CPU 模式）
echo ⚠️ 转录速度会明显慢于 RTX4060
echo.

pause
