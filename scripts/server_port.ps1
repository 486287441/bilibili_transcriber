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

function Get-ServerHealthInfo {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -ne 200) {
            return $null
        }
        return ($response.Content | ConvertFrom-Json)
    }
    catch {
        return $null
    }
}

function Get-PortListenerProcessIds {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $processIds = @()

    try {
        $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        $processIds += @($listeners | ForEach-Object { [int]$_.OwningProcess })
    }
    catch {
        # Some Windows environments deny Get-NetTCPConnection even for the
        # current user. Fall through to netstat, which remains available.
    }

    if ($processIds.Count -eq 0) {
        $portPattern = ':(' + [regex]::Escape([string]$Port) + ')$'
        foreach ($line in @(& netstat -ano -p tcp 2>$null)) {
            $columns = @($line.Trim() -split '\s+')
            if ($columns.Count -lt 5) { continue }
            if ($columns[0] -ne 'TCP' -or $columns[3] -ne 'LISTENING') { continue }
            if ($columns[1] -notmatch $portPattern) { continue }
            if ($columns[4] -match '^\d+$') {
                $processIds += [int]$columns[4]
            }
        }
    }

    return ,@($processIds | Sort-Object -Unique)
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
