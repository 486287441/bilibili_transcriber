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
    param(
        [Parameter(Mandatory = $true)]
        [string]$ExpectedInstanceId,
        [int]$TimeoutSec = 300
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $health = Get-ServerHealthInfo -Port $port
        if ($health -and $health.status -eq 'ok' -and $health.ready -eq $true) {
            $listenerIds = Get-PortListenerProcessIds -Port $port
            $instanceMatches = ($null -ne $health.instance_id) -and ([string]$health.instance_id -eq $ExpectedInstanceId)
            $listenerPidMatches = ($null -ne $health.process_id) -and ($listenerIds -contains [int]$health.process_id)
            if ($instanceMatches -and $listenerPidMatches) { return $true }
        }
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

try {
    # Keep startup discovery identical to the application runtime: explicit
    # LARK_CLI_PATH, bundled binary, PATH, then the per-user npm directory.
    $larkCli = (& $python -c "from feishu_client import _lark_executable; print(_lark_executable())" 2>$null | Select-Object -Last 1).Trim()
    if (-not $larkCli -or -not (Test-Path -LiteralPath $larkCli)) {
        throw "resolved path is unavailable"
    }
}
catch {
    Write-Host "[error] lark-cli not found; install @larksuite/cli or set LARK_CLI_PATH"
    Write-StartupLog -ProjectRoot $ProjectRoot -Message "ERROR lark-cli missing"
    exit 1
}

try {
    $authOutput = (& $larkCli auth status --json 2>$null | Out-String)
    $authStatus = $authOutput | ConvertFrom-Json
    $userAuth = $authStatus.identities.user
    if (-not $userAuth -or $userAuth.available -ne $true) {
        throw "user authorization unavailable"
    }
}
catch {
    Write-Host "[error] current Windows context cannot access Feishu user authorization"
    Write-Host "[error] start the server from the normal desktop user session; do not use a restricted/sandboxed process"
    Write-StartupLog -ProjectRoot $ProjectRoot -Message "ERROR Feishu user authorization unavailable in current context"
    exit 1
}

$existingListeners = Get-PortListenerProcessIds -Port $port
if ($existingListeners.Count -gt 0) {
    Write-Host "[error] refusing to start: port $port is already listening (PID=$($existingListeners -join ', '))"
    Write-Host "[error] run stop.bat first, or use start.bat --restart"
    Write-StartupLog -ProjectRoot $ProjectRoot -Message "ERROR port occupied before spawn PID=$($existingListeners -join ',')"
    exit 1
}

Write-StartupLog -ProjectRoot $ProjectRoot -Message "starting python -m server (port $port)"

$instanceId = [guid]::NewGuid().ToString('N')
$previousInstanceId = $env:BILIBILI_SERVER_INSTANCE_ID
try {
    $env:BILIBILI_SERVER_INSTANCE_ID = $instanceId
    $proc = Start-Process `
        -FilePath $python `
        -ArgumentList "-m", "server" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -PassThru
}
finally {
    if ($null -eq $previousInstanceId) {
        Remove-Item Env:BILIBILI_SERVER_INSTANCE_ID -ErrorAction SilentlyContinue
    }
    else {
        $env:BILIBILI_SERVER_INSTANCE_ID = $previousInstanceId
    }
}

Write-StartupLog -ProjectRoot $ProjectRoot -Message "spawned PID=$($proc.Id) instance=$instanceId"

if (Wait-ServerHealth -ExpectedInstanceId $instanceId) {
    $health = Get-ServerHealthInfo -Port $port
    $actualPid = [int]$health.process_id
    Write-Host "[done] server running at http://127.0.0.1:$port/ (PID=$actualPid)"
    Write-Host "[info] logs: $logsDir"
    Write-StartupLog -ProjectRoot $ProjectRoot -Message "healthy PID=$actualPid instance=$instanceId"
    exit 0
}

Write-Host "[error] server did not become healthy within 300s (PyTorch 预热可能较慢，见 logs\server.log)"
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
