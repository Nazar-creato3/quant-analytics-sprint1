# Install minimal backend deps and print local dev next steps (Windows).
# Usage from backend/:  .\scripts\run_dev.ps1
#                      .\scripts\run_dev.ps1 -CheckPorts

param(
    [switch]$CheckPorts
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
Write-Host "Installing backend deps from requirements-backend-minimal.txt ..."
& $Python -m pip install -r $MinimalReq

Write-Host ""
Write-Host "Next steps (local dev):"
Write-Host "  1. Postgres (repo root):  docker compose -f docker-compose.local.yml up -d postgres"
Write-Host "  2. Migrate (backend):     .\scripts\run_migrate.ps1"
Write-Host "  3. Seed (backend):        .\scripts\run_seed.ps1"
Write-Host "  4. API (backend):         $Python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
Write-Host ""
Write-Host "Verifying app import ..."
& $Python -c "from app.main import app; print('  app.main import: OK')"
Write-Host "  5. Frontend:              cd ..\frontend; npm run dev"
Write-Host ""
Write-Host "  API docs: http://localhost:8000/docs"
Write-Host "  Dashboard: http://localhost:3000"

if ($CheckPorts) {
    Write-Host ""
    Write-Host "Port check:"
    foreach ($port in @(8000, 3000)) {
        $inUse = $false
        try {
            $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            $inUse = [bool]$listeners
        } catch {
            $match = netstat -ano 2>$null | Select-String -Pattern ":\s*$port\s"
            $inUse = [bool]$match
        }
        if ($inUse) {
            Write-Host "  TCP $port : in use"
        } else {
            Write-Host "  TCP $port : free"
        }
    }
