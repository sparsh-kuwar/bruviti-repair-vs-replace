# One command on Windows (PowerShell):   .\run.ps1
# Same as run.sh: create .venv, install pinned dependencies, start API + UI on
# port 8000. Safe to re-run. Set $env:PYTHON to choose an interpreter.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$py = $env:PYTHON
if (-not $py) {
    foreach ($candidate in @("py", "python", "python3")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            & $candidate -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { $py = $candidate; break }
        }
    }
}
if (-not $py) { Write-Error "Python 3.9+ is required (set `$env:PYTHON to override)."; exit 1 }

if (-not (Test-Path ".venv\Scripts\python.exe")) { & $py -m venv .venv }
& .venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$port = if ($env:PORT) { $env:PORT } else { "8000" }
& .venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port $port
