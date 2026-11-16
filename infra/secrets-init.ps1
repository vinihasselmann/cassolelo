# Cria os arquivos de segredo que faltam em infra/secrets (10.3). Nunca sobrescreve.
#   powershell -ExecutionPolicy Bypass -File infra\secrets-init.ps1
# Depois preencha à mão: aps_client_secret (e, se usar, alert_teams_webhook_url,
# smtp_password, rclone_conf).
$ErrorActionPreference = 'Stop'
$dir = Join-Path $PSScriptRoot 'secrets'
New-Item -ItemType Directory -Force $dir | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding $false

function New-Random([int]$bytes = 24) {
  # hexadecimal: seguro em URL (database_url) e sem caracteres especiais
  $b = New-Object byte[] $bytes
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
  return ($b | ForEach-Object { $_.ToString('x2') }) -join ''
}

function Set-Secret([string]$name, [string]$value) {
  $path = Join-Path $dir $name
  if (Test-Path $path) { Write-Host "  mantido   $name"; return }
  [System.IO.File]::WriteAllText($path, $value, $utf8)
  Write-Host "  criado    $name"
}

$user = 'bim'; $db = 'bim'
$pwPath = Join-Path $dir 'postgres_password'
if (Test-Path $pwPath) { $pw = [System.IO.File]::ReadAllText($pwPath).Trim() } else { $pw = New-Random }
Set-Secret 'postgres_password' $pw
Set-Secret 'database_url' "postgresql+asyncpg://${user}:${pw}@postgres:5432/${db}"
Set-Secret 'aps_webhook_secret' (New-Random)
Set-Secret 'metrics_token' (New-Random)
foreach ($n in 'aps_client_secret', 'alert_teams_webhook_url', 'smtp_password', 'rclone_conf') { Set-Secret $n '' }

# Só o usuário atual e os administradores leem a pasta
icacls $dir /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F" /grant:r "*S-1-5-32-544:(OI)(CI)F" | Out-Null
if ((Get-Item (Join-Path $dir 'aps_client_secret')).Length -eq 0) {
  Write-Warning "Preencha infra\secrets\aps_client_secret com o Client Secret do app APS."
}
