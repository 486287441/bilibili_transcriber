# Shared helpers for start.bat / stop.bat (read port, detect our server).

function Get-ProjectServerPort {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    $envFile = Join-Path $ProjectRoot ".env"
    if (Test-Path -LiteralPath $envFile) {
        foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
            if ($line -match '^\s*SERVER_PORT\s*=\s*(\d+)\s*(?:#.*)?$') {
                return [int]$Matches[1]
            }
        }
    }
    return 8765
}

function Test-OurServerHealth {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -ne 200) {
            return $false
        }
        return ($response.Content -match '"status"\s*:\s*"ok"') -and
            ($response.Content -match '"ready"\s*:\s*true')
    }
    catch {
        return $false
    }
}

function Get-PortListenerProcessIds {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -eq 0) {
        return ,@()
    }
    return ,@($listeners | ForEach-Object { [int]$_.OwningProcess } | Sort-Object -Unique)
}

function Get-ProjectServerProcessIds {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    $root = $ProjectRoot.TrimEnd('\')
    $venvPython = Join-Path $root ".venv\Scripts\python.exe"
    $venvPythonW = Join-Path $root ".venv\Scripts\pythonw.exe"

    $serverProcs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $cmd = $_.CommandLine
            if (-not $cmd) { return $false }
            if ($cmd -notmatch '-m\s+server') { return $false }
            return ($cmd -like "*$root*") -or
                ($cmd -like "*$venvPython*") -or
                ($cmd -like "*$venvPythonW*")
        }

    if (-not $serverProcs) {
        return ,@()
    }

    return ,@($serverProcs | ForEach-Object { [int]$_.ProcessId } | Sort-Object -Unique)
}
