#!/usr/bin/env bash
# Cria os arquivos de segredo que faltam em infra/secrets (10.3). Nunca sobrescreve.
#   sudo bash infra/secrets-init.sh
# Depois preencha à mão: aps_client_secret (e, se usar, alert_teams_webhook_url,
# smtp_password, rclone_conf).
set -euo pipefail
dir="$(cd "$(dirname "$0")" && pwd)/secrets"
mkdir -p "$dir"
chmod 700 "$dir"
umask 077

rand() { od -An -N24 -tx1 /dev/urandom | tr -d ' \n'; }  # hexadecimal (seguro em URL)

put() {  # put <nome> <valor>
  if [[ -e "$dir/$1" ]]; then echo "  mantido   $1"; return; fi
  printf '%s' "$2" > "$dir/$1"
  echo "  criado    $1"
}

if [[ -e "$dir/postgres_password" ]]; then pw="$(tr -d '\r\n' < "$dir/postgres_password")"; else pw="$(rand)"; fi
put postgres_password "$pw"
put database_url "postgresql+asyncpg://bim:${pw}@postgres:5432/bim"
put aps_webhook_secret "$(rand)"
put metrics_token "$(rand)"
for n in aps_client_secret alert_teams_webhook_url smtp_password rclone_conf; do put "$n" ""; done
chmod 600 "$dir"/* 2>/dev/null || true
chmod 644 "$dir/README.md" 2>/dev/null || true
[[ -s "$dir/aps_client_secret" ]] || echo "AVISO: preencha $dir/aps_client_secret com o Client Secret do app APS."
