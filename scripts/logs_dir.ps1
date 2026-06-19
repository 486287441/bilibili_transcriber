# Shared log directory helper.

function Get-ProjectLogsDir {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    $dir = Join-Path $ProjectRoot "logs"
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    return (Resolve-Path -LiteralPath $dir).Path
}

function Write-StartupLog {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    $logFile = Join-Path (Get-ProjectLogsDir -ProjectRoot $ProjectRoot) "startup.log"
    $line = (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " " + $Message
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
}
