@echo off
chcp 65001 >nul
title RTX 4060 ASR 环境安装

echo ======================================================
echo     B站转文字助手 - RTX4060 专用环境安装
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
:: 3. 安装 RTX4060 Torch
:: ===============================
echo [3/4] 安装 PyTorch GPU (CUDA 12.1)...

pip uninstall -y torch torchvision torchaudio >nul 2>&1

pip install torch torchvision torchaudio ^
--index-url https://download.pytorch.org/whl/cu121

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
:: 5. GPU 验证
:: ===============================
echo 正在检测 CUDA 状态...
echo --------------------------------------

python -c "import torch; print('Torch:',torch.__version__); print('CUDA:',torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'None')"

echo --------------------------------------

echo.
echo ✅ 安装完成（RTX 4060 模式）
echo.

pause
