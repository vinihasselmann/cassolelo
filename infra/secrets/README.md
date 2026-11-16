# Segredos (um arquivo por segredo)

Esta pasta fica **fora do git** (só este README é versionado). Cada arquivo tem só o
valor, sem aspas. O Docker monta em `/run/secrets/<nome>` e o backend lê de lá
(`SECRETS_DIR`). Permissão: só o administrador do servidor (Linux: `chmod 600`,
dono root; Windows: só o usuário que roda o Docker).

| Arquivo | Conteúdo | Obrigatório |
|---|---|---|
| `postgres_password` | senha do PostgreSQL | sim |
| `database_url` | `postgresql+asyncpg://bim:<senha>@postgres:5432/bim` | sim |
| `aps_client_secret` | Client Secret do app APS | sim |
| `aps_webhook_secret` | secret da assinatura dos webhooks (32+ caracteres aleatórios) | vazio sem webhooks |
| `metrics_token` | token do coletor de métricas (`Authorization: Bearer`) | pode ficar vazio |
| `alert_teams_webhook_url` | URL do fluxo do Teams (Workflows) | vazio = sem Teams |
| `smtp_password` | senha do SMTP | vazio = sem e-mail |
| `rclone_conf` | configuração do rclone (pasta compartilhada / SharePoint) | vazio = só backup local |

Gerar tudo de uma vez com valores aleatórios onde cabe: `infra/secrets-init.ps1`
(Windows) ou `infra/secrets-init.sh` (Linux). Ver `docs/DEPLOY.md`.
