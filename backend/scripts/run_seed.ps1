# Install minimal backend deps and run database seed (repo-root scripts/seed.py).
# Usage from backend/:  .\scripts\run_seed.ps1
#                      .\scripts\run_seed.ps1 --admin-email admin@example.com
#                      .\scripts\run_seed.ps1 --ingest

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$SeedArgs = @()
)

$ErrorActionPreference = "Stop"
$BackendRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent $BackendRoot
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

$SeedScript = Join-Path $RepoRoot "scripts\seed.py"
& $Python $SeedScript @SeedArgs
