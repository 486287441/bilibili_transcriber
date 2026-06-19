# Start bilibili_transcriber server in background (pythonw), logs under logs/.

param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "server_port.ps1")
. (Join-Path $PSScriptRoot "logs_dir.ps1")

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$port = Get-ProjectServerPort -ProjectRoot $ProjectRoot
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$logsDir = Get-ProjectLogsDir -ProjectRoot $ProjectRoot

function Wait-ServerHealth {
    param([int]$TimeoutSec = 20)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-OurServerHealth -Port $port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "[error] python not found: $python"
    Write-StartupLog -ProjectRoot $ProjectRoot -Message "ERROR python missing"
    exit 1
}

Write-StartupLog -ProjectRoot $ProjectRoot -Message "validating config..."
$validateCode = & $python -c "import config; config.validate(); raise SystemExit(0)"
if (-not $?) {
    Write-Host "[error] config validation failed (see .env)"
    Write-StartupLog -ProjectRoot $ProjectRoot -Message "ERROR config validation failed"
    exit 1
}

Write-StartupLog -ProjectRoot $ProjectRoot -Message "starting python -m server (port $port)"

$proc = Start-Process `
    -FilePath $python `
    -ArgumentList "-m", "server" `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -PassThru

Write-StartupLog -ProjectRoot $ProjectRoot -Message "spawned PID=$($proc.Id)"

if (Wait-ServerHealth) {
    Write-Host "[done] server running at http://127.0.0.1:$port/ (PID=$($proc.Id))"
    Write-Host "[info] logs: $logsDir"
    Write-StartupLog -ProjectRoot $ProjectRoot -Message "healthy PID=$($proc.Id)"
    exit 0
}

Write-Host "[error] server did not become healthy within 20s"
Write-Host "[error] see logs\server.log and logs\startup.log"
Write-StartupLog -ProjectRoot $ProjectRoot -Message "ERROR health check failed PID=$($proc.Id)"

$serverLog = Join-Path $logsDir "server.log"
if (Test-Path -LiteralPath $serverLog) {
    $tail = Get-Content -LiteralPath $serverLog -Tail 8 -ErrorAction SilentlyContinue
    if ($tail) {
        Write-Host "--- server.log tail ---"
        $tail | ForEach-Object { Write-Host $_ }
    }
}

if (-not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}

exit 1
