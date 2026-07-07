@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

echo ======================================================
echo   Video Transcriber - Start Server (background)
echo   Panel: http://127.0.0.1:8765/
echo   Logs:  logs\
echo ======================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Run the install script first.
  pause
  exit /b 1
)

if not exist "web\dist\index.html" (
  echo [WARN] web\dist missing. Run: cd web ^&^& npm install ^&^& npm run build
  echo.
)

set "DO_RESTART=0"
set "DO_CLEAN=0"
if /i "%~1"=="--restart" set "DO_RESTART=1"
if /i "%~2"=="--restart" set "DO_RESTART=1"
if /i "%~1"=="--clean" set "DO_CLEAN=1"
if /i "%~2"=="--clean" set "DO_CLEAN=1"

if "%DO_RESTART%"=="1" (
  echo [preflight] stopping existing server...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_server.ps1"
  if errorlevel 1 (
    echo [ERROR] could not stop existing server.
    pause
    exit /b 1
  )
  echo.
)

if "%DO_CLEAN%"=="1" (
  echo [preflight] cleaning legacy entry processes...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\clean_legacy.ps1"
  echo [preflight] done.
  echo.
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_preflight.ps1"
set PREFLIGHT=%ERRORLEVEL%
if "%PREFLIGHT%"=="2" (
  echo        use stop.bat or start.bat --restart to restart
  exit /b 0
)
if "%PREFLIGHT%"=="1" (
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_server.ps1"
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] failed to start server, see logs\
  pause
  exit /b %EXIT_CODE%
)

echo.
echo [done] running in background. Stop with stop.bat
echo.
endlocal
