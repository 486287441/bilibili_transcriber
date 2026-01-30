@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title B站转文稿助手 - 环境检查与配置

echo ======================================================
echo       B站转文稿助手 (SenseVoice ASR)
echo ======================================================

:: 1. 检查 Python 环境
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python 环境！
    echo ------------------------------------------------------
    echo 解决办法：
    echo 1. 请访问 https://www.python.org/ 下载并安装 Python 3.10+
    echo 2. 重要：安装时请务必勾选 "Add Python to PATH"
    echo 3. 安装完成后重新运行此脚本。
    echo ------------------------------------------------------
    pause
    exit
)

:: 2. 检测并安装基础依赖
echo [1/3] 正在检查/安装 ASR 基础依赖...
python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install funasr modelscope yt-dlp pyperclip tqdm -i https://pypi.tuna.tsinghua.edu.cn/simple

:: 3. 智能安装 PyTorch (GPU/CPU)
echo [2/3] 正在检测硬件加速环境...
nvidia-smi >nul 2>&1
if %errorlevel% equ 0 (
    echo >>> 检测到 NVIDIA 显卡，准备安装 GPU 版 PyTorch (CUDA 12.1)...
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
) else (
    echo >>> 未检测到 NVIDIA 显卡，将使用 CPU 进行计算 (速度较慢)...
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
)

:: 4. 运行环境自检
echo [3/3] 正在进行系统兼容性自检...
echo ------------------------------------------------------
python -c "import torch; import funasr; print('PyTorch 版本:', torch.__version__); print('ASR 框架: FunASR (SenseVoice)'); print('计算设备:', 'GPU (CUDA)' if torch.cuda.is_available() else 'CPU'); print('设备名称:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')"
if %errorlevel% neq 0 (
    echo [警告] 自检发现异常，请检查报错信息。
) else (
    echo ✅ 环境配置完成！
)
echo ------------------------------------------------------

:: 5. 自动运行主程序 (如果有)
if exist "main.py" (
    echo [启动] 正在为您开启主程序...
    python main.py
) else (
    echo [提示] 环境已就绪。请运行您的 Python 脚本 (例如: python main.py)
)

pause