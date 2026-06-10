@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

echo ======================================================
echo Starting single-process dual-entry service
echo  Entry 1: Clipboard and Telegram listeners
echo  Entry 2: One model instance with serialized task queue
echo ======================================================
echo.

if /i "%~1"=="--clean" (
  echo [preflight] Cleaning old Python service instances...
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*telegram_bot.py*' -or $_.CommandLine -like '*bilibili_transcriber.py*' -or $_.CommandLine -like '*dual_entry_service.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>nul
  echo [preflight] Done.
  echo.
) else (
  echo [preflight] Skipped old-instance cleanup. Use start.bat --clean when needed.
  echo.
)

echo Starting unified service in this window...
echo.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" dual_entry_service.py
) else (
  python dual_entry_service.py
)
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" (
  echo.
  echo [error] Service exited with code %EXIT_CODE%.
  echo Common cause: incompatible sentencepiece version. Try: pip install sentencepiece==0.2.0
  pause
  exit /b %EXIT_CODE%
)
