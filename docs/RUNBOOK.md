# Runbook · Visualizador BIM

O que fazer quando algo dá errado. Cada caso: **sintoma → como confirmar → o que fazer**.
Instalação, variáveis, backup e restauração: `docs/DEPLOY.md`. Logs, métricas e alertas:
`docs/operacao.md`.

Os comandos usam o atalho `bim` (definido no `DEPLOY.md` › 3):

```bash
alias bim='docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod'   # Linux
function bim { docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod @args }  # PowerShell
```

## 0. Primeiro diagnóstico (qualquer problema)

```bash
bim ps                                   # todos "Up"/"healthy"? (migrate "Exited (0)" é normal)
curl http://<servidor>:<porta>/api/ready # banco, Redis e APS: qual está com erro?
bim logs --since 30m api worker | grep -E '"level": "(ERROR|WARNING)"'
```

- Achou um `request_id` na tela de erro ou no navegador (cabeçalho `X-Request-ID`)?
  `bim logs api | grep <request_id>` mostra tudo daquela requisição.
- Métricas (admin): `GET /api/metrics` → `versions_by_status`, `aps_errors_total`,
  `arq_queue_length`, `webhooks_late`.
- Serviço caído: `bim up -d` (sobe o que faltar). Docker Desktop fechado (PC de teste):
  abrir o Docker Desktop; os contêineres voltam sozinhos.

## 1. Uma versão falhou (`failed`) ou ficou sem conversão (`no_translation`)

**Alertas:** "Versão com falha: <obra> VN" ou "Sem conversão há N h". Na tela da
obra › **Versões**, a linha aparece em vermelho com a mensagem.

**Confirmar:**
```bash
bim logs --since 24h worker | grep -E 'process_version\(<id>\)|"version": <id>'
```

| Mensagem | Causa provável | O que fazer |
|---|---|---|
| "Conversão do Docs com status 'failed' …" | o Docs não conseguiu converter o arquivo | abrir o arquivo no Docs (navegador); se não abre lá, **republicar** a partir do Revit/Navisworks. Depois `versions retry` (abaixo) ou esperar a próxima verificação |
| "sem conversão" / `no_translation` | o Docs ainda não converteu ou o formato não gera visualização 3D | esperar (arquivos grandes levam até 1 h); se passar de 2 h, republicar |
| "A conversão do Docs não terminou em 2 horas." | conversão travada no Docs | republicar o arquivo |
| erro de leitura das propriedades (APS 5xx, timeout) | instabilidade do APS | `versions retry`; se repetir, ver https://health.autodesk.com |
| erro do app (traceback no log) | bug | `versions retry` uma vez; se repetir, abrir chamado com o `request_id`/log |

**Reprocessar** (reconsulta a conversão no Docs, só leitura, e enfileira o processamento):
```bash
bim run --rm api python -m app.cli versions retry --version <id da versão>
```
- `conversão pronta; reprocessamento enfileirado` → em segundos a versão vai a `ready`.
- `a conversão do Docs continua 'failed'/'no_translation'` → o problema está no Docs:
  republique o arquivo **com o mesmo nome** (nome diferente vira outro arquivo, não uma
  versão nova; ver `docs/decisoes-fase-0.md`).

Os valores da fábrica **não se perdem** com versão falha: eles ficam na marca, e a
última versão `ready` continua sendo a usada pelo app.

**Nunca** "forçar a conversão" pela API (POST `/modelderivative/v2/designdata/job`): é
pago e bloqueado no Docs. A conversão é sempre do próprio Docs.

## 2. O webhook parou

**Hoje os webhooks estão desligados** (sem URL pública; `PUBLIC_BASE_URL` vazio): as
versões chegam pela verificação a cada 10 min. Esta seção vale quando a URL pública
existir.

**Alerta:** "Webhooks do APS parados" (nenhum webhook em 24 h, mas a verificação
periódica achou versões novas). Métrica `webhooks_late` > 0 = webhooks recebidos e não
processados.

**Confirmar:**
```bash
bim run --rm api python -m app.cli hooks list        # status "active"? callbackUrl certa?
bim logs --since 24h api | grep '/api/webhooks/aps'  # chegam? 200 ou 401 (assinatura)?
```

| Achado | O que fazer |
|---|---|
| hooks com `status` `inactive` (o APS desativa após muitas falhas de entrega) ou `callbackUrl` antiga | `bim run --rm api python -m app.cli hooks reregister --all` |
| nenhuma linha `/api/webhooks/aps` no log | a URL pública não chega ao servidor: testar `curl -X POST https://<url>/api/webhooks/aps` de fora (deve dar 401). Falar com a TI (proxy/firewall/certificado) |
| `-> 401` | secret de assinatura diferente: `bim run --rm api python -m app.cli hooks set-secret` |
| `-> 200` mas `webhooks_late` > 0 | o worker não está processando: ver seção 5 |

Enquanto isso, nada se perde: a verificação a cada 10 min continua trazendo as versões.

## 3. Token / credenciais do APS com erro (401/403)

**Alerta:** "Credenciais do APS com erro (401/403)". `/api/ready` com `aps` em erro; na
tela, "Credenciais do app APS inválidas" ou "Sem permissão no Autodesk Docs".

O token de acesso **renova sozinho** (2-legged, cache com renovação antes de expirar).
Erro persistente quer dizer **credencial ou permissão**, não token vencido:

| Causa | Como confirmar | O que fazer |
|---|---|---|
| Client Secret trocado/expirado no portal da Autodesk | `/api/ready` → `aps: 401` | gerar o secret novo em https://aps.autodesk.com (app do Visualizador), gravar em `infra/secrets/aps_client_secret`, `bim up -d --force-recreate api worker` |
| app removido de **Custom Integrations** do ACC | 403 ao navegar no Docs | admin do ACC: Account Admin › Custom Integrations › adicionar o Client ID de novo |
| projeto/pasta sem acesso | 403 só numa obra | dar acesso ao app no projeto do ACC |
| `APS_CLIENT_ID` errado | 401 logo após uma mudança | conferir `infra/.env.prod`, `bim up -d api worker` |

Conferir depois: `curl http://<servidor>:<porta>/api/ready` → `"aps": {"ok": true}`.

## 4. Rodar o sync manual

- **Pela tela** (projetos, fábrica ou admin): obra › **"Sincronizar agora"**. Mostra
  quantas versões há no Docs, quantas são novas e quantas foram para processamento.
- **Pela linha de comando** (mesmo efeito do botão, com o resultado de cada obra):
  ```bash
  bim run --rm api python -m app.cli sync --obra <id>   # uma obra
  bim run --rm api python -m app.cli sync --all         # todas as ativas vinculadas
  ```
  Saída: `obra 1: 2 no Docs, 1 nova(s), 1 para processar, 0 convertendo, 0 sem conversão, 0 com falha`.
  Rodar de novo não duplica nada. O worker também faz isto sozinho a cada 10 min e ao
  reiniciar (`bim restart worker`).
- **Pela API** (script/integração): `POST /api/obras/{id}/sync` com o usuário de um papel
  permitido.

## 5. O worker não processa (fila parada)

**Sintoma:** versões ficam em `pending`/`processing`; `arq_queue_length` cresce.

```bash
bim ps worker ; bim logs --since 30m worker | tail -50
bim restart worker
```
Jobs interrompidos voltam a rodar (status `processing` é reprocessável). Se o Redis
caiu: `bim up -d redis` (dados persistidos em `redisdata`).

## 6. Backup

**Alertas:** "Backup do banco falhou" ou "Backup do banco atrasado" (mais de 26 h sem
backup bom).

```bash
# log
Get-Content infra\backups\backup.log -Tail 40          # Windows (teste)
journalctl -u bim-backup.service --since -2d           # Linux
# rodar agora
bim --profile backup run --rm backup
```

| Achado | O que fazer |
|---|---|
| `FALHOU a cópia para pasta:…` | pasta compartilhada fora/sem permissão/senha trocada. O backup local está ok. Testar: `bim --profile backup run --rm backup rclone --config /run/secrets/rclone_conf lsf <remote>` |
| `FALHOU a cópia para sharepoint:…` | token do rclone expirado ou app sem permissão: refazer o bloco `[sharepoint]` (DEPLOY › 6) |
| `pg_dump: error: connection …` | banco fora: `bim up -d postgres` e rodar de novo |
| `No space left on device` | disco cheio: liberar espaço; conferir `BACKUP_RETENTION_DAYS` |
| sem nenhuma linha nova no log | a tarefa não rodou: Windows › Agendador de Tarefas › "Visualizador BIM - backup" (PC ligado e logado? Docker Desktop aberto?); Linux › `systemctl list-timers bim-backup.timer` |

Restaurar: `docs/DEPLOY.md` › 7.

## 7. Usuário bloqueado com "Muitas alterações em pouco tempo" (429)

Mais de `RATE_LIMIT_WRITES_PER_MIN` (120) escritas por minuto do mesmo usuário. Uso
normal não chega perto (o lote conta como uma). Esperar o tempo indicado. Se for
legítimo (ex.: script de importação), aumentar o valor no `.env.prod` e
`bim up -d api`. A métrica `rate_limited_total` conta os bloqueios.

## 8. O modelo 3D não abre (o resto funciona)

1. O arquivo abre no Docs pelo navegador? Se não, é conversão (seção 1).
2. No navegador do tablet (F12/depuração remota), erro de **CSP** (`Refused to load…`)?
   A Autodesk pode ter mudado domínios do Viewer: ajustar `frontend/security-headers.ts`,
   `bim up -d --build web`.
3. Rede da fábrica bloqueando `*.autodesk.com` (HTTPS e WebSocket `wss://`): falar com a TI.

## Contatos e escalonamento

| Assunto | Quem |
|---|---|
| Servidor, rede, firewall, URL pública, SharePoint | TI |
| ACC/Docs (Custom Integrations, permissões, arquivos) | admin do ACC (escritório de projetos) |
| App (erro com traceback, comportamento errado) | responsável pelo sistema, com o `request_id` e o horário |
