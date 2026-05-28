@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

echo ======================================================
echo 启动双入口模式：
echo 1) 剪贴板监听（bilibili_transcriber.py）
echo 2) Telegram 监听（telegram_bot.py）
echo ======================================================
echo.

echo [预处理] 清理旧 Telegram 进程...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*telegram_bot.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>nul
echo [预处理] 完成。
echo.

start "Bilibili Clipboard Listener" cmd /k "cd /d ""%~dp0"" && python bilibili_transcriber.py"
start "Bilibili Telegram Bot" cmd /k "cd /d ""%~dp0"" && python telegram_bot.py"

echo 已启动两个窗口。关闭对应窗口即可停止对应服务。
echo.
pause
