@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title B站转文稿助手 - 环境自动配置

echo ===============================================
echo        B站转文稿助手 (SenseVoice)
echo ===============================================
echo.

:: ===============================
:: 1. 检查 Python
:: ===============================
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 未检测到 Python！
    echo 请先安装 Python 3.10+
    echo 并勾选 Add Python to PATH
    pause
    exit
)

echo ✅ Python 已安装
echo.

:: ===============================
:: 2. 升级 pip
:: ===============================
echo [1/4] 正在升级 pip...
python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple

:: ===============================
:: 3. 安装基础依赖
:: ===============================
if not exist requirements.txt (
    echo ❌ 未找到 requirements.txt
    pause
    exit
)

echo.
echo [2/4] 正在安装基础依赖...
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

:: ===============================
:: 4. 安装 PyTorch
:: ===============================
echo.
echo [3/4] 检测显卡环境...

nvidia-smi >nul 2>&1

if %errorlevel% equ 0 (
    echo ✅ 检测到 NVIDIA 显卡
    echo >>> 安装 CUDA 版 PyTorch...
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
) else (
    echo ⚠️ 未检测到显卡
    echo >>> 安装 CPU 版 PyTorch...
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
)

:: ===============================
:: 5. 环境自检
:: ===============================
echo.
echo [4/4] 正在进行环境自检...
echo --------------------------------------

python -c "import torch,funasr,yt_dlp,pyperclip,tqdm; print('PyTorch:',torch.__version__); print('CUDA:',torch.cuda.is_available()); print('FunASR: OK')"

if %errorlevel% neq 0 (
    echo ❌ 自检失败，请查看报错
    pause
    exit
)

echo --------------------------------------
echo ✅ 环境配置完成！
echo.

:: ===============================
:: 6. 启动主程序
:: ===============================
if exist main.py (
    echo 🚀 启动主程序...
    python main.py
) else (
    echo ⚠️ 未找到 main.py
)

pause
