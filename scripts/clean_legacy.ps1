# Stop legacy standalone entry processes that conflict with server mode.

$ErrorActionPreference = "SilentlyContinue"

$legacy = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $cmd = $_.CommandLine
        if (-not $cmd) { return $false }
        return ($cmd -like '*dual_entry_service.py*')
    }

if (-not $legacy) {
    exit 0
}

foreach ($proc in $legacy) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host ('(preflight) stopped legacy PID=' + $proc.ProcessId)
}

exit 0
