# Implantação · Visualizador BIM

Como instalar, configurar, atualizar, fazer backup e restaurar o Visualizador BIM.
Vale para os dois ambientes:

| | Ambiente de teste com a fábrica (agora) | Servidor definitivo (TI) |
|---|---|---|
| Máquina | PC Windows dedicado com Docker Desktop | Servidor Linux com Docker Engine |
| `APP_ENV` | `staging` + `DEV_USERS_ENABLED=true` (usuário simulado) | `prod` (exige o login da Fase 11) |
| Backup agendado por | Tarefa Agendada do Windows | timer do systemd |
| Cópias do backup | pasta compartilhada (e SharePoint, se configurado) | pasta compartilhada + SharePoint |
| Webhooks do APS | desligados (sem acesso externo) | quando a TI publicar uma URL HTTPS |

Operação do dia a dia (versão com falha, webhook parado, token do APS, sync manual):
**`docs/RUNBOOK.md`**. Logs, saúde, métricas, alertas e cabeçalhos de segurança:
**`docs/operacao.md`**.

---

## 1. Como a pilha é montada

`infra/docker-compose.prod.yml` sobe sete serviços numa rede interna:

| Serviço | Imagem | O que faz |
|---|---|---|
| `web` | `visualizador-bim-web` (nginx, sem root) | serve o app e repassa `/api` à API. **Única porta aberta** (`HTTP_PORT`). Envia CSP/HSTS/nosniff. |
| `api` | `visualizador-bim-backend` | FastAPI (uvicorn, 2 processos), sem root |
| `worker` | `visualizador-bim-backend` | Arq: processa versões, verificação no Docs a cada 10 min, alertas a cada 5 min |
| `migrate` | `visualizador-bim-backend` | `alembic upgrade head`; roda e sai antes da API e do worker subirem |
| `postgres` | `postgres:16` | banco (volume `pgdata`) |
| `redis` | `redis:7` | fila, tempo real, métricas, limite de taxa (volume `redisdata`) |
| `backup` | `visualizador-bim-backup` | pg_dump/pg_restore 16 + rclone. **Não sobe com `up`**: é chamado pelo agendador |

Imagens: `backend/Dockerfile` (dois estágios: as dependências entram com `uv` num venv,
e o runtime é `python:3.12-slim` sem compiladores), `frontend/Dockerfile` (`npm ci` +
`tsc` + `vite build` → nginx; os cabeçalhos de segurança são gerados no build a partir
de `frontend/security-headers.ts`) e `infra/backup/Dockerfile`.

O servidor precisa de **saída HTTPS** para `developer.api.autodesk.com` e
`cdn.derivative.autodesk.com` (backend e navegadores dos tablets). Entrada: só a porta
do nginx, pela rede interna.

## 2. Requisitos

- **Linux:** Docker Engine 24+ com o plugin Compose v2 (`docker compose version`).
  **Windows (teste):** Docker Desktop 4.30+ com WSL2.
- 2 vCPU, 4 GB de RAM, 20 GB de disco livres (mais o espaço dos backups: cerca de
  1 MB por obra por dia × 30 dias).
- Git (ou uma cópia da pasta do projeto) e acesso ao app APS (Client ID e Secret) liberado
  em **Custom Integrations** do ACC.
- Endereço fixo (IP reservado no DHCP ou nome no DNS interno) para os tablets acessarem.

## 3. Primeira instalação

```bash
git clone <repositório> visualizador-bim && cd visualizador-bim

# 1) segredos (um arquivo por segredo em infra/secrets/, nunca no git)
bash infra/secrets-init.sh                                    # Linux
powershell -ExecutionPolicy Bypass -File infra\secrets-init.ps1   # Windows
#    preencher à mão: infra/secrets/aps_client_secret (e os opcionais, seção 5)

# 2) variáveis (não-secretas)
cp infra/.env.prod.example infra/.env.prod      # e editar (seção 4)

# 3) subir (build das imagens, migrações automáticas)
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d --build --wait

# 4) usuários simulados (só no ambiente de teste; idempotente)
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod run --rm api python -m app.seed

# 5) conferir
curl http://<servidor>:<HTTP_PORT>/api/ready      # {"status":"ready", ... database/redis/aps ok}
```

Depois: abrir `http://<servidor>:<HTTP_PORT>` num tablet, escolher o usuário
"Paula Projetos", cadastrar a obra (escolhendo o arquivo no Docs) e clicar em
"Sincronizar agora". **Agendar o backup** (seção 6) no mesmo dia.

Para não repetir o comando inteiro, os exemplos abaixo usam:

```bash
alias bim='docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod'   # Linux
function bim { docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod @args }  # PowerShell
```

### Particularidades do PC Windows de teste
- Docker Desktop: **Settings › General › "Start Docker Desktop when you sign in"** ligado.
  O Docker Desktop roda na sessão do usuário: o PC precisa ficar **logado** (bloqueado,
  tudo bem) e **sem suspensão** (Opções de energia › nunca suspender).
- Firewall do Windows: liberar a entrada na porta do nginx só para a rede da fábrica:
  `New-NetFirewallRule -DisplayName "Visualizador BIM" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow -Profile Domain,Private`
- Os contêineres têm `restart: unless-stopped`: voltam sozinhos quando o Docker Desktop sobe.

## 4. Variáveis de ambiente (`infra/.env.prod`)

Modelo comentado em `infra/.env.prod.example`. **Nada de segredo aqui.**

| Variável | Padrão | Para que serve |
|---|---|---|
| `APP_ENV` | `staging` | `staging` (teste com a fábrica) ou `prod` (definitivo). Fora de `dev`: sem Swagger, HSTS ligado, credenciais do APS obrigatórias no `/api/ready` |
| `DEV_USERS_ENABLED` | `true` | usuário simulado (X-Dev-User) até a Fase 11. **Só aceito com `staging`**; com `prod` o backend não sobe. Atenção: qualquer pessoa na rede escolhe qualquer usuário, inclusive admin |
| `APP_VERSION` | `local` | etiqueta das imagens (ex.: `2026.11.12`): permite voltar à anterior |
| `COMPOSE_PROJECT_NAME` | `visualizador-bim-prod` | prefixo dos contêineres e volumes |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `json` | logs (ver `docs/operacao.md`) |
| `HTTP_BIND` / `HTTP_PORT` | `0.0.0.0` / `80` | onde o nginx escuta no servidor |
| `APP_BASE_URL` | — | endereço que os usuários usam (links nos alertas; origem do CORS) |
| `CORS_ORIGINS` | vazio | só se o app for servido em OUTRO domínio que a API. `*` é recusado |
| `HSTS_MAX_AGE` | `31536000` | HSTS (só tem efeito com HTTPS); `0` desliga |
| `RATE_LIMIT_WRITES_PER_MIN` | `120` | escritas por usuário por minuto (429 acima); `0` desliga |
| `POSTGRES_USER` / `POSTGRES_DB` | `bim` / `bim` | usuário e banco (a senha é segredo) |
| `APS_CLIENT_ID` | — | Client ID do app APS (não é segredo) |
| `APS_REGION` | `US` | `US`, `EMEA` ou `AUS` (região do hub do ACC) |
| `PUBLIC_BASE_URL` | vazio | URL pública HTTPS do backend para os webhooks. Vazio = webhooks desligados (seção 8) |
| `MARK_PROPERTY_NAMES` e demais `*_PROPERTY_NAMES` | ver `backend/app/config.py` | nomes das propriedades do modelo (marca, categoria, nível, busca, revisão) |
| `ALERT_EMAIL_TO`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_FROM`, `SMTP_STARTTLS` | — | alertas por e-mail (senha é segredo) |
| `BACKUP_MAX_AGE_HOURS` | `26` | alerta "backup atrasado" se não houver backup bom nesse intervalo; `0` desliga |
| `BACKUP_DIR` | `./backups` | pasta **do servidor** com os dumps (relativa a `infra/`) |
| `BACKUP_RETENTION_DAYS` | `30` | retenção local e nos destinos remotos |
| `BACKUP_REMOTES` | vazio | destinos do rclone separados por espaço (seção 6) |

## 5. Segredos (`infra/secrets/`)

Um arquivo por segredo, só com o valor. O Docker monta em `/run/secrets/<nome>` e o
backend lê de lá (`SECRETS_DIR=/run/secrets`, recurso do pydantic-settings). Os
arquivos ficam **fora do git** (`.gitignore`) e com permissão só do administrador
(`secrets-init` já ajusta: `chmod 600` no Linux, ACL do usuário e Administradores no
Windows). Este é o "cofre" do ambiente: no servidor definitivo, a TI pode trocar por
Docker Swarm secrets ou pelo cofre corporativo sem mudar o app (o app só lê arquivos).

| Arquivo | Conteúdo |
|---|---|
| `postgres_password` | senha do PostgreSQL (gerada) |
| `database_url` | `postgresql+asyncpg://bim:<senha>@postgres:5432/bim` (gerada; mesma senha) |
| `aps_client_secret` | Client Secret do app APS (**preencher**) |
| `aps_webhook_secret` | secret da assinatura dos webhooks (gerado) |
| `metrics_token` | token do coletor de métricas (gerado) |
| `alert_teams_webhook_url` | URL do fluxo do Teams (opcional) |
| `smtp_password` | senha do SMTP (opcional) |
| `rclone_conf` | configuração do rclone para as cópias do backup (opcional) |

Trocar um segredo: editar o arquivo e recriar os serviços que o usam
(`bim up -d --force-recreate api worker`). **Trocar a senha do banco** exige também
`ALTER USER bim PASSWORD '...'` no Postgres (o `POSTGRES_PASSWORD_FILE` só vale na
criação do volume).

## 6. Backup

**O que é:** `pg_dump` em formato custom (comprimido), conferido com
`pg_restore --list`, com `.sha256`, em `BACKUP_DIR`. Arquivos com mais de
`BACKUP_RETENTION_DAYS` (30) dias são apagados, no local e nos destinos remotos. O
resultado é marcado no Redis e o worker alerta (Teams/e-mail) se o backup **falhar** ou
ficar **atrasado** (mais de `BACKUP_MAX_AGE_HOURS`). Script: `infra/backup/backup.sh`.

```bash
bim --profile backup run --rm backup          # rodar agora (o agendador chama isto)
```

### Agendar (diário, 03:00)
- **Windows (teste):** `powershell -ExecutionPolicy Bypass -File infra\backup\windows\register-backup-task.ps1`
  Cria a tarefa "Visualizador BIM - backup" (roda ao ligar se o PC estava desligado às
  03:00). Log em `infra\backups\backup.log`. Testar: `Start-ScheduledTask -TaskName 'Visualizador BIM - backup'`.
- **Linux (definitivo):** copiar `infra/backup/systemd/bim-backup.{service,timer}` para
  `/etc/systemd/system/`, ajustar `WorkingDirectory`, e
  `sudo systemctl daemon-reload && sudo systemctl enable --now bim-backup.timer`.
  Log: `journalctl -u bim-backup.service`.

### Cópias fora do servidor (rclone)
O rclone grava direto nos destinos, sem montar nada no host. Configuração em
`infra/secrets/rclone_conf`; destinos em `BACKUP_REMOTES`. Falha num destino não apaga
o backup local, mas marca "backup falhou" (alerta).

**Pasta compartilhada (SMB)**, ex.: `\\arquivos\Backups\BIM`:

```ini
[pasta]
type = smb
host = arquivos
user = svc-bim-backup
domain = CASSOL
pass = <senha ofuscada: docker run --rm rclone/rclone:1.69.3 obscure 'SENHA'>
```
`BACKUP_REMOTES=pasta:Backups/BIM` (compartilhamento/pasta). A conta precisa só de
gravar e apagar nessa pasta.

**SharePoint** (biblioteca de documentos). A TI registra um app no Entra ID com
permissão `Sites.Selected` (concedida só ao site dos backups) ou `Files.ReadWrite.All`, e
gera o bloco do rclone numa estação com `rclone config` (tipo `onedrive`,
`drive_type = documentLibrary`, informando client_id/secret e escolhendo o site e a
biblioteca). Resultado, colado no mesmo `rclone_conf`:

```ini
[sharepoint]
type = onedrive
client_id = <id do app>
client_secret = <secret do app>
drive_type = documentLibrary
drive_id = <id da biblioteca>
token = {"access_token":"...","refresh_token":"...","expiry":"..."}
```
`BACKUP_REMOTES="pasta:Backups/BIM sharepoint:Backups/BIM"`. O `token` é renovado pelo
próprio rclone. Se a TI preferir autenticação só por aplicativo (sem usuário), conferir
na versão do rclone em uso a opção de *client credentials* do backend onedrive. **Até a
TI fornecer o app, o SharePoint fica desligado** (só local + pasta).

Teste de um destino: `bim --profile backup run --rm backup rclone --config /run/secrets/rclone_conf lsf pasta:Backups/BIM`.

## 7. Restauração

Script: `infra/backup/restore.sh`. Confere o `.sha256`, **exige banco vazio** (ambiente
limpo) e imprime as contagens das tabelas principais.

```bash
bim up -d --wait postgres redis                       # só banco e Redis
bim --profile backup run --rm backup restore.sh latest   # ou o nome do arquivo .dump
bim up -d --wait                                      # migrate (alembic) + api, worker, web
```

Por cima de um banco com dados (ex.: voltar o servidor no tempo), o script recusa. Para
forçar, apagando o banco atual: pare `api`/`worker` (`bim stop api worker`) e rode
`... run --rm -e RESTORE_CONFIRM=bim backup restore.sh <arquivo> --force`.
**Faça um backup antes.**

### Teste de restauração em ambiente limpo (feito em 2026-11-12)
Pilha de produção rodando com a obra real 30.327-01 (2 versões, 718 peças, 3 marcas,
parâmetro "Tipo de forma" preenchido). Passos executados:

1. `bim --profile backup run --rm backup` → `bim-bim-20261112T130450Z.dump` (124 KB, 14 tabelas, `.sha256`).
2. Ambiente **novo e vazio**, outro projeto Compose (volumes novos, porta 8089):
   `HTTP_PORT=8089 COMPOSE_PROJECT_NAME=bim-restore bim -p bim-restore up -d --wait postgres redis`
   (antes: nenhum volume `bim-restore`).
3. `... -p bim-restore --profile backup run --rm backup restore.sh latest` → sha256 conferido; restaurado.
4. `... -p bim-restore up -d --wait` → migrate ok, api/worker/web saudáveis; `/api/ready` = ready.
5. Conferência origem × restaurado, tabela por tabela: **iguais** (users 4, obras 1,
   model_versions 2, marks 3, elements 718, param_values 3, audit_log 18,
   version_reports 2, version_property_names 428); valores da fábrica idênticos
   (PP001=F-1, PP002=F-2, PP005=F-3); busca "PP001" no app restaurado: 1 marca, 4 peças.
6. Restaurar de novo por cima: **recusado** (exit 65); `--force` sem `RESTORE_CONFIRM`: recusado.
7. `... -p bim-restore down -v` (ambiente de teste apagado).

Repetir este teste **a cada 3 meses** e depois de mudanças grandes (versão do Postgres,
servidor novo), anotando a data e o resultado aqui.

## 8. Webhooks do APS e `PUBLIC_BASE_URL`

**Hoje (sem acesso externo):** `PUBLIC_BASE_URL` vazio. Nenhum hook é registrado; as
versões novas chegam pela **verificação a cada 10 min** e pelo **"Sincronizar agora"**
(testados com o Docs real). O alerta "webhooks parados" fica desligado.

**Quando a TI publicar uma URL HTTPS** (ex.: `https://bim.cassol.com.br`):
1. No proxy/firewall, expor para a internet **apenas** `POST /api/webhooks/aps`
   (o resto do app continua só na rede interna). TLS válido (a Autodesk recusa
   certificado autoassinado).
2. `PUBLIC_BASE_URL=https://bim.cassol.com.br` em `infra/.env.prod` e `bim up -d api worker`.
3. Registrar o secret da assinatura: `bim run --rm api python -m app.cli hooks set-secret`.
4. Re-registrar os hooks de todas as obras com a URL nova (apaga os que apontam para
   outra URL; idempotente): `bim run --rm api python -m app.cli hooks reregister --all`.
5. Conferir: `bim run --rm api python -m app.cli hooks list`; publicar uma versão de teste
   no Docs e ver o webhook no log (`app.access POST /api/webhooks/aps -> 200`).

Trocou de domínio de novo? Repita os passos 2 e 4.

## 9. HTTPS

O nginx do app escuta em HTTP (porta `HTTP_PORT`). No servidor definitivo, o TLS fica no
proxy da TI (ou balanceador) na frente, que repassa para `http://servidor:HTTP_PORT`,
mantendo `X-Forwarded-Proto: https`. Com HTTPS, o HSTS enviado pelo app passa a valer.
No ambiente de teste (rede interna, HTTP), o HSTS é ignorado pelo navegador.

## 10. Atualizar o app

```bash
bim --profile backup run --rm backup          # 1) backup antes
git pull                                      # 2) código novo
# 3) (opcional) APP_VERSION=2026.11.20 em .env.prod para manter a imagem anterior
bim up -d --build --wait                      # 4) build + migrate automático + reinício
curl http://<servidor>:<porta>/api/ready
```

**Voltar:** com `APP_VERSION`, volte o valor anterior e `bim up -d`. Se a versão nova
tinha migração de banco, restaure o backup do passo 1 (seção 7).

## 11. Ambiente de teste → definitivo

1. Aceite com a fábrica no ambiente de teste.
2. Fase 11 (login): `APP_ENV=prod`, `DEV_USERS_ENABLED` removido.
3. Servidor Linux da TI: seções 2 a 6 e 9; restaurar o último backup do teste (seção 7)
   para levar as obras e os parâmetros já preenchidos.
4. Repetir o teste de restauração e o teste de carga (`loadtest/locustfile.py`) no servidor.
