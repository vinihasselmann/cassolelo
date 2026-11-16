# Executado pela Tarefa Agendada: roda o contêiner de backup e grava o log (10.3).
$ErrorActionPreference = 'Continue'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
Set-Location $repo
$logDir = Join-Path $repo 'infra\backups'
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir 'backup.log'

# Docker Desktop pode ainda estar subindo logo depois de ligar o PC
for ($i = 0; $i -lt 30; $i++) {
  docker info *> $null
  if ($LASTEXITCODE -eq 0) { break }
  Start-Sleep -Seconds 10
}

"==== $(Get-Date -Format s) ====" | Out-File -Append -Encoding utf8 $log
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod --profile backup run --rm backup *>&1 |
  Out-File -Append -Encoding utf8 $log
$code = $LASTEXITCODE
"exit=$code" | Out-File -Append -Encoding utf8 $log
exit $code
