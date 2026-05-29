@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

echo ======================================================
echo 启动单进程双入口模式：
echo 1) 剪贴板监听 + Telegram 监听
echo 2) 单模型实例 + 串行任务队列
echo ======================================================
echo.

echo [预处理] 清理旧多进程实例...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*telegram_bot.py*' -or $_.CommandLine -like '*bilibili_transcriber.py*' -or $_.CommandLine -like '*dual_entry_service.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>nul
echo [预处理] 完成。
echo.

echo 正在当前窗口启动统一服务...
echo.
python dual_entry_service.py
