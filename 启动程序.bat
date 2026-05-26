@echo off
:: 切换代码页到 UTF-8，解决乱码问题
chcp 65001 >nul

:: 切换到当前脚本所在目录（防止路径找不到）
cd /d "%~dp0"

echo ======================================================
echo 🎧 正在启动 B站视频自动转文稿助手...
echo ======================================================

:: 启动 Python 脚本
python "bilibili_transcriber.py"

if %errorlevel% neq 0 (
    echo.
    echo ❌ 程序运行出错，请检查是否已安装环境！
)

pause