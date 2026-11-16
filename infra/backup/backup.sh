#!/usr/bin/env bash
# Backup diário do PostgreSQL (10.3).
#
#   docker compose -f infra/docker-compose.prod.yml --profile backup run --rm backup
#
# 1. pg_dump em formato custom (-Fc, comprimido) para /backups (BACKUP_DIR no host);
# 2. confere o arquivo com pg_restore --list e grava o .sha256;
# 3. apaga os locais com mais de BACKUP_RETENTION_DAYS (padrão 30);
# 4. copia para cada destino em BACKUP_REMOTES (rclone: pasta compartilhada SMB,
#    SharePoint), com a mesma retenção. Falha num destino não apaga o backup local;
# 5. marca backup_last_ok / backup_last_failed no Redis (alerta "backup atrasado/falhou").
#
# Variáveis: PGHOST, PGPORT, PGUSER, PGDATABASE, senha em /run/secrets/postgres_password,
# BACKUP_RETENTION_DAYS, BACKUP_REMOTES (ex.: "pasta:bim/backups sharepoint:Backups/BIM"),
# config do rclone em /run/secrets/rclone_conf, REDIS_HOST.
set -Eeuo pipefail

RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
DIR="${BACKUP_LOCAL_DIR:-/backups}"
REMOTES="${BACKUP_REMOTES:-}"
RCLONE_CONF="${RCLONE_CONFIG:-/run/secrets/rclone_conf}"
REDIS_HOST="${REDIS_HOST:-redis}"
DB="${PGDATABASE:-bim}"

log() { printf '%s backup: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

mark() {  # mesma chave das métricas do app (obs:marks)
  redis-cli -h "$REDIS_HOST" HSET obs:marks "$1" "$(date +%s)" >/dev/null 2>&1 \
    || log "aviso: não consegui registrar $1 no Redis ($REDIS_HOST)"
}

on_error() {
  log "FALHOU (linha $1). O backup local anterior continua valendo."
  rm -f "${PARTIAL:-}"
  mark backup_last_failed
  exit 1
}
trap 'on_error $LINENO' ERR

if [[ -z "${PGPASSWORD:-}" && -f /run/secrets/postgres_password ]]; then
  PGPASSWORD="$(tr -d '\r\n' < /run/secrets/postgres_password)"
  export PGPASSWORD
fi

mkdir -p "$DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$DIR/bim-$DB-$STAMP.dump"
PARTIAL="$FILE.partial"

log "pg_dump de $DB em $PGHOST -> $(basename "$FILE")"
pg_dump --format=custom --compress=6 --no-owner --no-privileges --file="$PARTIAL" "$DB"
TABLES="$(pg_restore --list "$PARTIAL" | grep -c ' TABLE DATA ' || true)"
if [[ "$TABLES" -lt 1 ]]; then
  log "arquivo sem dados de tabela"
  false
fi
mv "$PARTIAL" "$FILE"
PARTIAL=""
( cd "$DIR" && sha256sum "$(basename "$FILE")" > "$(basename "$FILE").sha256" )
log "ok: $(du -h "$FILE" | cut -f1), $TABLES tabelas"

find "$DIR" -maxdepth 1 -name 'bim-*.dump*' -type f -mtime +"$((RETENTION_DAYS - 1))" -print -delete \
  | sed 's/^/  removido (retenção): /'

REMOTE_FAILED=0
for remote in $REMOTES; do
  log "copiando para $remote"
  if rclone --config "$RCLONE_CONF" copy "$DIR" "$remote" --include 'bim-*.dump*' --max-depth 1 --no-traverse \
     && rclone --config "$RCLONE_CONF" delete "$remote" --include 'bim-*.dump*' --min-age "${RETENTION_DAYS}d"; then
    log "ok: $remote"
  else
    log "FALHOU a cópia para $remote"
    REMOTE_FAILED=1
  fi
done

if [[ "$REMOTE_FAILED" -ne 0 ]]; then
  mark backup_last_failed
  exit 2
fi
mark backup_last_ok
log "concluído"
