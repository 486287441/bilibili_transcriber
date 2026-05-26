$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$legacy = Join-Path $root ([char]0x5bf9 + [char]0x8bdd + ' html')
$serve = Join-Path $root 'prd-html'
$servePy = Join-Path $root 'scripts\prd-serve.py'

New-Item -ItemType Directory -Force -Path $serve | Out-Null
Copy-Item -Path (Join-Path $legacy 'index.html') -Destination (Join-Path $serve 'index.html') -Force

try {
    Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
} catch { }
Start-Sleep -Milliseconds 500

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
$args = @($servePy, $serve, '3000', $legacy)
if (-not $py) {
    $py = 'py'
    $args = @('-3') + $args
}

Start-Process -FilePath $py -ArgumentList $args -WorkingDirectory $serve -WindowStyle Hidden
Write-Host 'PRD preview: http://127.0.0.1:3000'
Write-Host 'Use Ctrl+F5 if page looks wrong. choices.json mirrors to legacy folder.'
