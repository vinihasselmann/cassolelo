# Agenda o backup diário no Windows (ambiente de teste com Docker Desktop) (10.3).
#   powershell -ExecutionPolicy Bypass -File infra\backup\windows\register-backup-task.ps1 [-At 03:00]
# Cria a tarefa "Visualizador BIM - backup" para o usuário atual (o Docker Desktop roda
# na sessão dele). O log de cada execução fica em infra\backups\backup.log.
# Para remover: Unregister-ScheduledTask -TaskName 'Visualizador BIM - backup'
param([string]$At = '03:00')
$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$runner = Join-Path $PSScriptRoot 'run-backup.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`"" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At $At
# Se o PC estava desligado no horário, roda assim que ligar; até 2 h de execução
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
  -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName 'Visualizador BIM - backup' -Action $action -Trigger $trigger `
  -Settings $settings -Description 'Backup diário do PostgreSQL do Visualizador BIM (retenção 30 dias)' -Force | Out-Null
Write-Host "Tarefa agendada: todo dia às $At. Teste agora com:"
Write-Host "  Start-ScheduledTask -TaskName 'Visualizador BIM - backup'"
