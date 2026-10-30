# Локальная копия Quant Analytics для записи демо, если сервер недоступен.
# Запуск из папки репозитория в PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\local-demo.ps1
# Цены — настоящие с Мосбиржи (ISS), режим только учебный. Ключи вводятся скрыто
# и записываются только в файл .env на этом компьютере (в git он не попадает).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Say($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Secret($prompt) {
  $s = Read-Host -AsSecureString $prompt
  $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
  try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}
function Hex($n) { -join ((1..$n) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) }) }
function SetEnv($lines, $name, $value) {
  $found = $false
  $out = foreach ($l in $lines) { if ($l -match "^$name=") { $found = $true; "$name=$value" } else { $l } }
  if (-not $found) { $out += "$name=$value" }
  return ,$out
}

Say "Проверка Docker"
docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker не запущен. Откройте Docker Desktop, дождитесь зелёного статуса и запустите скрипт снова." }

if (-not (Test-Path .env)) {
  Say "Создаю .env (один раз)"
  $lines = Get-Content .env.example -Encoding UTF8
  $lines = SetEnv $lines "APP_ENV" "development"
  $lines = SetEnv $lines "SECRET_KEY" (Hex 32)
  $pg = Hex 16
  $lines = SetEnv $lines "POSTGRES_PASSWORD" $pg
  $lines = SetEnv $lines "APP_DB_PASSWORD" $pg
  $lines = SetEnv $lines "PHONE_SIGNIN_REQUIRED" "false"
  $lines = SetEnv $lines "LIVE_TRADING_ENABLED" "false"
  $lines = SetEnv $lines "NEXT_PUBLIC_APP_NAME" "Quant Analytics"
  Write-Host "Ключ ИИ-ассистента (AITUNNEL_API_KEY, как на сервере). Пусто — ассистент будет выключен."
  $ai = Secret "AITUNNEL_API_KEY"
  if ($ai) { $lines = SetEnv $lines "AITUNNEL_API_KEY" $ai; $lines = SetEnv $lines "LLM_ENABLED" "true" }
  Write-Host "Логин и пароль Мосбиржи (passport.moex.com). Пусто — котировки ISS без входа."
  $mu = Read-Host "MOEX_USERNAME"
  if ($mu) { $lines = SetEnv $lines "MOEX_USERNAME" $mu; $lines = SetEnv $lines "MOEX_PASSWORD" (Secret "MOEX_PASSWORD") }
  [IO.File]::WriteAllLines((Join-Path (Get-Location) ".env"), $lines, (New-Object Text.UTF8Encoding $false))
  Remove-Variable ai, pg -ErrorAction SilentlyContinue
}

$C = @("compose", "-f", "docker-compose.yml", "-f", "docker-compose.demo-local.yml")
$SVC = @("postgres", "redis", "mlflow", "backend", "celery-pipeline", "celery-ingestion", "celery-execution", "celery-beat", "frontend")

Say "Сборка образов (первый раз 20–40 минут)"
$env:COMPOSE_PARALLEL_LIMIT = "1"
docker @C build backend frontend
if ($LASTEXITCODE -ne 0) { throw "Сборка не прошла — пришлите скрин последних строк." }

# Старый локальный запуск (контейнеры apex-*) может занимать порты 8000 и 3000.
# Останавливаем, но не удаляем: данные остаются, запустить снова — docker start ИМЯ.
$old = docker ps --filter "name=^apex-" --format "{{.Names}}"
if ($old) {
  Say "Останавливаю старый локальный запуск (не удаляю): $($old -join ', ')"
  docker stop $old | Out-Null
}

Say "База данных"
docker @C up -d postgres redis
for ($i = 0; $i -lt 30; $i++) { docker @C exec -T postgres pg_isready -U apex -d apex_intel *> $null; if ($LASTEXITCODE -eq 0) { break }; Start-Sleep 3 }
docker @C run --rm --no-deps backend alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "Миграции базы не прошли — пришлите скрин." }
# Пароль роли приложения (та же операция, что scripts/setup-appuser-role.sh на сервере).
$appPass = ((Get-Content .env -Encoding UTF8 | Where-Object { $_ -match '^APP_DB_PASSWORD=' } | Select-Object -Last 1) -replace '^APP_DB_PASSWORD=', '').Trim()
docker @C exec -T postgres psql -U apex -d apex_intel -v ON_ERROR_STOP=1 -c "ALTER ROLE appuser WITH LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '$appPass';" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Не удалось задать пароль роли базы — пришлите скрин." }
Remove-Variable appPass

Say "Запуск сервисов"
docker @C up -d @SVC
if ($LASTEXITCODE -ne 0) { throw "Запуск не прошёл — пришлите скрин." }

Say "Жду, пока поднимется сервер приложения"
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
  try { Invoke-WebRequest -UseBasicParsing http://localhost:8000/api/v1/health -TimeoutSec 5 | Out-Null; $ok = $true; break } catch { Start-Sleep 5 }
}
if (-not $ok) { docker @C logs --tail 40 backend; throw "Сервер приложения не ответил за 5 минут — пришлите скрин." }

Say "Загрузка цен Мосбиржи для демо-бумаг"
docker @C exec -T backend python -m app.scripts.stand_data_check --sync

Say "Учётная запись для записи видео"
$email = Read-Host "Почта для входа (например demo@quantanalyticsclub.ru)"
docker @C exec backend python -m app.scripts.grant_access --email $email --create

Say "Готово: откройте http://localhost:3000 и войдите с этой почтой"
Start-Process "http://localhost:3000"
