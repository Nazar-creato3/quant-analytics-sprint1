# Run Alembic migrations without relying on alembic.exe on PATH (Windows user installs).
# Usage from backend/:  .\scripts\run_migrate.ps1
#                      .\scripts\run_migrate.ps1 upgrade head
#                      .\scripts\run_migrate.ps1 current

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AlembicArgs = @("upgrade", "head")
)

$ErrorActionPreference = "Stop"
$BackendRoot = Split-Path -Parent $PSScriptRoot
Set-Location $BackendRoot

if ($env:PYTHON -and (Test-Path $env:PYTHON)) {
    $Python = $env:PYTHON
} elseif (Test-Path "C:\Python314\python.exe") {
    $Python = "C:\Python314\python.exe"
} else {
    $Python = "python"
}

$MinimalReq = Join-Path $BackendRoot "requirements-backend-minimal.txt"
& $Python -m pip install -r $MinimalReq

# python -m alembic works even when %APPDATA%\Python\Python314\Scripts is not on PATH
& $Python -m alembic @AlembicArgs
