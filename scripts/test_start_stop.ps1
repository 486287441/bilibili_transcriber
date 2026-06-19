# Automated regression tests for start.bat / stop.bat helpers.
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\test_start_stop.ps1

param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "server_port.ps1")

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$port = Get-ProjectServerPort -ProjectRoot $ProjectRoot
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$pythonw = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$stopBat = Join-Path $ProjectRoot "stop.bat"
$startBat = Join-Path $ProjectRoot "start.bat"
$stopPs1 = Join-Path $PSScriptRoot "stop_server.ps1"
$startPs1 = Join-Path $PSScriptRoot "start_server.ps1"
$preflightPs1 = Join-Path $PSScriptRoot "start_preflight.ps1"

$failed = 0
$passed = 0

function Assert-True {
    param([bool]$Condition, [string]$Name)
    if ($Condition) {
        Write-Host "[PASS] $Name" -ForegroundColor Green
        $script:passed++
    }
    else {
        Write-Host "[FAIL] $Name" -ForegroundColor Red
        $script:failed++
    }
}

function Assert-ExitCode {
    param(
        [scriptblock]$Action,
        [int]$Expected,
        [string]$Name
    )
    $code = 0
    try {
        & $Action
        $code = $LASTEXITCODE
    }
    catch {
        $code = 1
    }
    Assert-True ($code -eq $Expected) "$Name (exit=$code expected=$Expected)"
}

function Invoke-StopAll {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $stopPs1 -ProjectRoot $ProjectRoot | Out-Null
    Start-Sleep -Seconds 1
}

function Wait-Health {
    param([int]$TimeoutSec = 15)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-OurServerHealth -Port $port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Start-ServerBackground {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $startPs1 -ProjectRoot $ProjectRoot | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "start_server.ps1 failed"
    }
    $ids = Get-ProjectServerProcessIds -ProjectRoot $ProjectRoot
    if ($ids.Count -eq 0) {
        throw "no server process after start"
    }
    return (Get-Process -Id $ids[0] -ErrorAction SilentlyContinue)
}

Write-Host "=== start/stop regression tests (port $port) ===" -ForegroundColor Cyan

# Ensure clean slate
Invoke-StopAll

# 1. stop when idle
Assert-ExitCode { cmd /c "`"$stopBat`"" } 0 "stop.bat when nothing running"

# 2. preflight when idle
Assert-ExitCode { & powershell -NoProfile -ExecutionPolicy Bypass -File $preflightPs1 -ProjectRoot $ProjectRoot } 0 "preflight when port free"

# 3. start server in background, health check
$serverProc = $null
try {
    $serverProc = Start-ServerBackground
    Assert-True (Test-OurServerHealth -Port $port) "start_server.ps1 background health"

    # 3b. start.bat when already running
    Assert-ExitCode { cmd /c "`"$startBat`"" } 0 "start.bat when already running (preflight skip)"

    # 4. preflight detects running server
    Assert-ExitCode { & powershell -NoProfile -ExecutionPolicy Bypass -File $preflightPs1 -ProjectRoot $ProjectRoot } 2 "preflight when our server running"

    # 5. stop.bat via cmd stops listener
    Assert-ExitCode { cmd /c "`"$stopBat`"" } 0 "stop.bat stops running server"
    Start-Sleep -Seconds 1
    Assert-True ((Get-PortListenerProcessIds -Port $port).Count -eq 0) "port released after stop.bat"

    # 6. double stop
    Assert-ExitCode { cmd /c "`"$stopBat`"" } 0 "stop.bat twice is safe"

    # 7. pythonw orphan cleanup
    $w = Start-Process -FilePath $pythonw -ArgumentList "-m", "server" -WorkingDirectory $ProjectRoot -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 4
    Assert-True ($w.HasExited -or (Get-ProjectServerProcessIds -ProjectRoot $ProjectRoot).Count -ge 1) "pythonw server process spawned"
    Assert-ExitCode { cmd /c "`"$stopBat`"" } 0 "stop.bat cleans pythonw orphan"
    Start-Sleep -Seconds 1
    Assert-True ((Get-ProjectServerProcessIds -ProjectRoot $ProjectRoot).Count -eq 0) "no orphan server processes after stop"

    # 8. restart cycle via ps1
    $serverProc = Start-ServerBackground
    Invoke-StopAll
    Assert-True ((Get-PortListenerProcessIds -Port $port).Count -eq 0) "stop_server.ps1 releases port"
    $serverProc = Start-ServerBackground
    Assert-True (Test-OurServerHealth -Port $port) "server healthy after restart cycle"

    # 9. foreign port occupier
    Invoke-StopAll
    $blocker = Start-Process -FilePath $python -ArgumentList "-m", "http.server", "$port", "--bind", "127.0.0.1" -WorkingDirectory $ProjectRoot -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 2
    Assert-ExitCode { & powershell -NoProfile -ExecutionPolicy Bypass -File $preflightPs1 -ProjectRoot $ProjectRoot } 1 "preflight rejects foreign port occupier"
    Stop-Process -Id $blocker.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}
finally {
    Invoke-StopAll
    if ($serverProc -and -not $serverProc.HasExited) {
        Stop-Process -Id $serverProc.Id -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "Results: $passed passed, $failed failed" -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Red" })
if ($failed -gt 0) { exit 1 }
exit 0
