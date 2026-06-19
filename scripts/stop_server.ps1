# Stop bilibili_transcriber server: release port + clean project python/pythonw orphans.

param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "server_port.ps1")
. (Join-Path $PSScriptRoot "logs_dir.ps1")

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$port = Get-ProjectServerPort -ProjectRoot $ProjectRoot

function Stop-ProcessIds {
    param([int[]]$ProcessIds)

    foreach ($procId in $ProcessIds) {
        if ($procId -le 0) { continue }
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if (-not $proc) { continue }
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Write-Host ('[OK] stopped PID=' + $procId + ' (' + $proc.ProcessName + ')')
    }
}

$listenerIds = Get-PortListenerProcessIds -Port $port
if ($listenerIds.Count -eq 0) {
    Write-Host ('[info] port ' + $port + ' is not listening')
}
else {
    Write-Host ('[info] stopping listeners on port ' + $port + '...')
    Stop-ProcessIds -ProcessIds $listenerIds
}

$orphanIds = Get-ProjectServerProcessIds -ProjectRoot $ProjectRoot
if ($orphanIds.Count -gt 0) {
    Write-Host '[info] cleaning leftover project server processes...'
    Stop-ProcessIds -ProcessIds $orphanIds
}

Start-Sleep -Seconds 1

$stillListening = Get-PortListenerProcessIds -Port $port
if ($stillListening.Count -gt 0) {
    Write-Host ('[warn] port ' + $port + ' still in use: ' + ($stillListening -join ', '))
    Write-Host '[warn] check Task Manager or change SERVER_PORT in .env'
    exit 1
}

$leftover = Get-ProjectServerProcessIds -ProjectRoot $ProjectRoot
if ($leftover.Count -gt 0) {
    Write-Host ('[warn] leftover server PIDs: ' + ($leftover -join ', '))
    exit 1
}

Write-Host '[done] server stopped'
Write-StartupLog -ProjectRoot $ProjectRoot -Message 'stopped server'
exit 0
