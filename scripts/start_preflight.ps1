# Preflight checks before start.bat launches python -m server.

param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "server_port.ps1")

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$port = Get-ProjectServerPort -ProjectRoot $ProjectRoot

$listenerIds = Get-PortListenerProcessIds -Port $port
if ($listenerIds.Count -eq 0) {
    exit 0
}

if (Test-OurServerHealth -Port $port) {
    Write-Host ('[info] already running: http://127.0.0.1:' + $port + '/')
    exit 2
}

Write-Host ('[error] port ' + $port + ' is used by another program: ' + ($listenerIds -join ', '))
Write-Host '[error] run stop.bat first, or change SERVER_PORT in .env'
exit 1
