@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

echo ======================================================
echo   Video Transcriber - Stop Server
echo ======================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_server.ps1"
set EXIT_CODE=%ERRORLEVEL%

echo.
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
