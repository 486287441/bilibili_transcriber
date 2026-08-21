[CmdletBinding()]
param(
    [ValidateSet("auto", "cuda", "cpu")]
    [string]$TorchMode = "auto",
    [string]$TorchIndexUrl = "",
    [switch]$SkipSystemInstall,
    [switch]$SkipLarkLogin,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
Set-Location -LiteralPath $ProjectRoot

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = @($machine, $user) -join ";"
}

function Get-CommandPath([string]$Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { return $command.Source }
    return $null
}

function Install-WingetPackage([string]$Id) {
    if ($SkipSystemInstall -or $CheckOnly) { return }
    $winget = Get-CommandPath "winget"
    if (-not $winget) {
        throw "$Id is missing and winget is unavailable. Install it, then rerun install.ps1."
    }
    Write-Step "Installing $Id with winget"
    & $winget install --id $Id -e --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget failed to install $Id." }
    Refresh-ProcessPath
}

function Get-Python312 {
    $py = Get-CommandPath "py"
    if ($py) {
        $resolved = (& $py -3.12 -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1)
        if ($LASTEXITCODE -eq 0 -and $resolved) { return $resolved.Trim() }
    }

    foreach ($name in @("python", "python3")) {
        $candidate = Get-CommandPath $name
        if (-not $candidate) { continue }
        $minor = (& $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null | Select-Object -Last 1)
        if ($LASTEXITCODE -eq 0 -and $minor -and $minor.Trim() -eq "3.12") {
            return $candidate
        }
    }

    $localPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path -LiteralPath $localPython) { return $localPython }
    return $null
}

function Get-LarkCli([string]$Python) {
    $resolved = (& $Python -c "from feishu_client import _lark_executable; print(_lark_executable())" 2>$null | Select-Object -Last 1)
    if ($LASTEXITCODE -eq 0 -and $resolved -and (Test-Path -LiteralPath $resolved.Trim())) {
        return $resolved.Trim()
    }
    return $null
}

if (-not [Environment]::Is64BitOperatingSystem) {
    throw "Only Windows x64 is supported."
}

$driveName = (Get-Item -LiteralPath $ProjectRoot).PSDrive.Name
$drive = New-Object System.IO.DriveInfo("$driveName`:\")
$freeGb = [math]::Round($drive.AvailableFreeSpace / 1GB, 1)
if ($freeGb -lt 15) {
    Write-Warning "Only $freeGb GB is free; a fresh installation should have at least 15 GB available."
}

Write-Step "Checking Python 3.12"
$basePython = Get-Python312
if (-not $basePython) {
    Install-WingetPackage "Python.Python.3.12"
    $basePython = Get-Python312
}
if (-not $basePython) {
    throw "Official CPython 3.12 x64 was not found. Reopen the terminal after installation and rerun this script."
}
Write-Host "Python: $basePython"

Write-Step "Checking Node.js 22+"
$node = Get-CommandPath "node"
if (-not $node) {
    Install-WingetPackage "OpenJS.NodeJS.LTS"
    $node = Get-CommandPath "node"
}
if (-not $node) { throw "Node.js was not found." }
$nodeMajor = [int]((& $node -p "process.versions.node.split('.')[0]").Trim())
if ($nodeMajor -lt 22) {
    if (-not $SkipSystemInstall -and -not $CheckOnly) {
        Install-WingetPackage "OpenJS.NodeJS.LTS"
        $node = Get-CommandPath "node"
        $nodeMajor = [int]((& $node -p "process.versions.node.split('.')[0]").Trim())
    }
    if ($nodeMajor -lt 22) { throw "Node.js 22+ is required; found major version $nodeMajor." }
}
Write-Host "Node: $(& $node --version)"

Write-Step "Checking FFmpeg / FFprobe"
$ffmpeg = Get-CommandPath "ffmpeg"
$ffprobe = Get-CommandPath "ffprobe"
if (-not $ffmpeg -or -not $ffprobe) {
    Install-WingetPackage "Gyan.FFmpeg"
    $ffmpeg = Get-CommandPath "ffmpeg"
    $ffprobe = Get-CommandPath "ffprobe"
}
if (-not $ffmpeg -or -not $ffprobe) {
    throw "Both ffmpeg and ffprobe are required. Reopen the terminal after installation if necessary."
}
Write-Host "FFmpeg: $ffmpeg"
Write-Host "FFprobe: $ffprobe"

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if ($CheckOnly) {
    Write-Step "Read-only check results"
    Write-Host "venv: $(Test-Path -LiteralPath $venvPython)"
    Write-Host "frontend: $(Test-Path -LiteralPath (Join-Path $ProjectRoot 'web\dist\index.html'))"
    if (Test-Path -LiteralPath $venvPython) {
        $lark = Get-LarkCli $venvPython
        Write-Host "lark-cli: $([bool]$lark)"
    }
    exit 0
}

Write-Step "Preparing the Python virtual environment"
if (Test-Path -LiteralPath $venvPython) {
    & $venvPython -c "import sys; assert sys.version_info[:2] == (3, 12); print(sys.version)"
    if ($LASTEXITCODE -ne 0) {
        throw "The existing .venv is broken or is not Python 3.12. It will not be deleted automatically."
    }
}
else {
    & $basePython -m venv (Join-Path $ProjectRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Failed to create .venv." }
}
& $venvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip tooling." }

$hasNvidia = [bool](Get-CommandPath "nvidia-smi")
$effectiveTorchMode = $TorchMode
if ($effectiveTorchMode -eq "auto") {
    $effectiveTorchMode = if ($hasNvidia) { "cuda" } else { "cpu" }
}
if ($effectiveTorchMode -eq "cuda" -and -not $hasNvidia) {
    throw "CUDA was requested, but nvidia-smi was not found."
}
if (-not $TorchIndexUrl) {
    $TorchIndexUrl = if ($effectiveTorchMode -eq "cuda") {
        "https://download.pytorch.org/whl/cu124"
    }
    else {
        "https://download.pytorch.org/whl/cpu"
    }
}

Write-Step "Installing and validating PyTorch ($effectiveTorchMode)"
$torchReady = $false
& $venvPython -c "import torch; raise SystemExit(0 if ('$effectiveTorchMode' == 'cpu' or torch.cuda.is_available()) else 1)" 2>$null
if ($LASTEXITCODE -eq 0) { $torchReady = $true }
if (-not $torchReady) {
    & $venvPython -m pip install torch torchvision torchaudio --index-url $TorchIndexUrl
    if ($LASTEXITCODE -ne 0) { throw "PyTorch installation failed." }
}
& $venvPython -c "import torch; print(torch.__version__); print('cuda=', torch.cuda.is_available()); raise SystemExit(0 if ('$effectiveTorchMode' == 'cpu' or torch.cuda.is_available()) else 1)"
if ($LASTEXITCODE -ne 0) { throw "CUDA validation failed." }

Write-Step "Installing project dependencies"
& $venvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Project dependency installation failed." }
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw "pip check found dependency conflicts." }

Write-Step "Building the frontend"
$npm = Get-CommandPath "npm.cmd"
if (-not $npm) { $npm = Get-CommandPath "npm" }
if (-not $npm) { throw "npm was not found." }
Push-Location (Join-Path $ProjectRoot "web")
try {
    & $npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed." }
    & $npm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
}
finally {
    Pop-Location
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "web\dist\index.html"))) {
    throw "Frontend build finished without web\dist\index.html."
}

Write-Step "Installing and checking lark-cli"
$larkCli = Get-LarkCli $venvPython
if (-not $larkCli) {
    & $npm install -g "@larksuite/cli"
    if ($LASTEXITCODE -ne 0) { throw "lark-cli installation failed." }
    Refresh-ProcessPath
    $larkCli = Get-LarkCli $venvPython
}
if (-not $larkCli) { throw "@larksuite/cli is installed, but the application cannot locate lark-cli." }
Write-Host "lark-cli: $larkCli"
& $larkCli --version

if (-not $SkipLarkLogin) {
    $authOk = $false
    try {
        $auth = ((& $larkCli auth status --json 2>$null | Out-String) | ConvertFrom-Json)
        $authOk = $auth.identities.user.available -eq $true
    }
    catch { $authOk = $false }
    if (-not $authOk) {
        Write-Host "`nConfirm the Feishu authorization in your browser." -ForegroundColor Yellow
        $configPath = Join-Path $HOME ".lark-cli\config.json"
        if (-not (Test-Path -LiteralPath $configPath)) {
            & $larkCli config init --new
            if ($LASTEXITCODE -ne 0) { throw "lark-cli initialization failed." }
        }
        & $larkCli auth login --domain docs --domain wiki --domain drive
        if ($LASTEXITCODE -ne 0) { throw "Feishu user authorization was not completed." }
    }
}

$envFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot ".env.example") -Destination $envFile
    Write-Host "Created .env without writing any secrets."
}

Write-Host "`nBase installation complete." -ForegroundColor Green
Write-Host "Next: select a Feishu wiki destination, set both FEISHU_WIKI_* values, then run start.bat."
Write-Host "After startup, enter the DeepSeek API key only in the local Web settings page."
