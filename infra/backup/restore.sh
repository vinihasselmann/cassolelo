#!/usr/bin/env bash
# Restauração do PostgreSQL (10.3).
#
#   docker compose -f infra/docker-compose.prod.yml --profile backup run --rm backup \
#     restore.sh latest            # o mais recente de /backups
#   ... restore.sh bim-bim-20261112T030000Z.dump
#   ... restore.sh latest --force  # banco com dados: APAGA e recria antes (pede RESTORE_CONFIRM)
#
# Confere o .sha256, exige banco VAZIO (ambiente limpo) salvo com --force, restaura
# com pg_restore --exit-on-error e imprime as contagens das tabelas principais.
# Depois rode as migrações (serviço migrate) e suba api/worker; ver docs/DEPLOY.md.
set -Eeuo pipefail

DIR="${BACKUP_LOCAL_DIR:-/backups}"
DB="${PGDATABASE:-bim}"
log() { printf '%s restore: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

if [[ -z "${PGPASSWORD:-}" && -f /run/secrets/postgres_password ]]; then
  PGPASSWORD="$(tr -d '\r\n' < /run/secrets/postgres_password)"
  export PGPASSWORD
fi

ARG="${1:-}"
FORCE="${2:-}"
if [[ -z "$ARG" ]]; then
  echo "uso: restore.sh <arquivo.dump|latest> [--force]" >&2
  exit 64
fi
if [[ "$ARG" == "latest" ]]; then
  FILE="$(ls -1t "$DIR"/bim-*.dump 2>/dev/null | head -n1 || true)"
  [[ -n "$FILE" ]] || { log "nenhum backup em $DIR"; exit 66; }
elif [[ "$ARG" == /* ]]; then
  FILE="$ARG"
else
  FILE="$DIR/$ARG"
fi
[[ -f "$FILE" ]] || { log "arquivo não encontrado: $FILE"; exit 66; }

if [[ -f "$FILE.sha256" ]]; then
  ( cd "$(dirname "$FILE")" && sha256sum --check --quiet "$(basename "$FILE").sha256" )
  log "sha256 conferido"
else
  log "aviso: sem $FILE.sha256 (integridade não conferida)"
fi

psql_q() { psql -v ON_ERROR_STOP=1 -X -At -d "$1" -c "$2"; }

TABLES="$(psql_q "$DB" "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")"
if [[ "$TABLES" != "0" ]]; then
  if [[ "$FORCE" != "--force" ]]; then
    log "o banco $DB já tem $TABLES tabelas. Restaure num ambiente limpo ou use --force."
    exit 65
  fi
  if [[ "${RESTORE_CONFIRM:-}" != "$DB" ]]; then
    log "--force apaga o banco $DB. Confirme com RESTORE_CONFIRM=$DB."
    exit 65
  fi
  log "apagando e recriando o banco $DB (--force)"
  psql_q postgres "DROP DATABASE \"$DB\" WITH (FORCE)"
  psql_q postgres "CREATE DATABASE \"$DB\""
fi

log "restaurando $(basename "$FILE") em $DB"
pg_restore --exit-on-error --no-owner --no-privileges --dbname="$DB" "$FILE"

log "contagens:"
for t in alembic_version users obras model_versions marks elements param_defs param_values orphans audit_log; do
  if [[ "$(psql_q "$DB" "SELECT to_regclass('public.$t') IS NOT NULL")" == "t" ]]; then
    printf '  %-16s %s\n' "$t" "$(psql_q "$DB" "SELECT count(*) FROM $t")"
  fi
done
log "concluído. Próximo passo: serviço migrate (alembic upgrade head) e subir api/worker."
