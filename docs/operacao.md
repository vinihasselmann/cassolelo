# Operação · logs, saúde, métricas e alertas

Guia para a TI acompanhar o Visualizador BIM em produção (Fase 10.1). As variáveis
ficam em `infra/.env` (modelo: `infra/.env.example`).

## Logs

- Saída padrão (stdout) da API e do worker, **uma linha JSON por evento**
  (`LOG_FORMAT=json`; `text` para ler no terminal).
- Campos: `ts` (UTC), `level`, `logger`, `msg`. Também, quando houver:
  - `request_id`: o mesmo do cabeçalho `X-Request-ID` da resposta. Um `X-Request-ID` válido enviado pelo proxy é reaproveitado.
  - `user` (`{id, name}`), `obra`, `job` (`process_version`, `sync_obra`, `check_alerts`) e `version`.
  - extras do evento, como `status` e `duration_ms` na linha de acesso.
- Cada requisição gera uma linha `app.access` com `method`, `path`, `status` e `duration_ms`. O `/api/health` fica de fora, para não poluir.
- **Sem segredos:** tokens (Bearer, JWT), `client_secret`, `access_token`, senhas, a assinatura `x-adsk-signature` e senha embutida em URL (`redis://user:senha@…`) são trocados por `[REDACTED]` na mensagem e no traceback.

## Saúde

| Rota | Uso | Resposta |
|---|---|---|
| `GET /api/health` | vivo (liveness) | 200 `{"status": "ok"}`, sem tocar em dependências |
| `GET /api/ready` | pronto (readiness / balanceador) | 200 se banco, Redis e APS respondem; **503** com o motivo de cada checagem |

No `/api/ready`, o APS é testado obtendo o token 2-legged (fica em cache). Sem `APS_CLIENT_ID`, a checagem é "skipped" em dev e **falha** nos outros ambientes.

## Métricas

`GET /api/metrics` (JSON) ou `GET /api/metrics?format=prometheus`. Acesso: usuário admin,
ou o coletor com `Authorization: Bearer <METRICS_TOKEN>`.

| Métrica | O que é |
|---|---|
| `versions_processed_total{status=ready\|failed}` | versões processadas pelo worker |
| `processing_seconds` (`count`, `sum`, `max`, `avg`) | tempo de processamento |
| `aps_errors_total{kind=auth\|forbidden\|not_found\|no_translation\|http\|network}` | falhas de leitura no APS |
| `webhooks_received_total` e `webhook_last_received_at` | webhooks recebidos |
| `webhooks_late` | webhooks com obra ainda não processados após 10 min |
| `periodic_new_versions_total` | versões que só a verificação periódica encontrou (webhook não avisou) |
| `arq_queue_length` | jobs na fila do worker |
| `versions_by_status`, `versions_no_translation_over_2h` | situação das versões (do banco) |

Contadores e tempos ficam no Redis (API e worker somam juntos). Os números de versões
e webhooks são calculados do banco a cada leitura.

## Alertas

O worker avalia a cada 5 min e envia por **Teams** e/ou **e-mail**:

| Alerta | Quando | Repete depois de |
|---|---|---|
| Versão com falha | versão em `failed` (atualizada nos últimos 7 dias) | não repete (30 dias) |
| Sem conversão | versão em `no_translation` há mais de 2 h | não repete (30 dias) |
| Webhooks parados | nenhum webhook em 24 h **e** a verificação periódica achou versões novas. Só com `PUBLIC_BASE_URL` (webhooks configurados) | 24 h |
| Credenciais do APS | erro 401/403 do APS nos últimos 15 min | 6 h |
| Backup falhou | o último backup (ou a cópia para um destino remoto) falhou depois do último sucesso. Só com `BACKUP_MAX_AGE_HOURS` > 0 | uma vez por falha |
| Backup atrasado | nenhum backup bem-sucedido em `BACKUP_MAX_AGE_HOURS` (26 h no `.env.prod`) | 24 h |

Configuração:

- **Teams:** no canal, crie um fluxo em *Workflows* → "Post to a channel when a webhook request is received" e coloque a URL em `ALERT_TEAMS_WEBHOOK_URL`. A mensagem vai como cartão adaptativo.
- **E-mail:** `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS=true` e `ALERT_EMAIL_TO` (lista separada por vírgulas).
- **Links:** `APP_BASE_URL` (ex.: `https://bim.cassol.local`) faz os alertas levarem o link da obra.
- **Testar o canal:** `cd backend && uv run python -m app.cli alerts test`.
- Sem nenhum canal configurado, os alertas só aparecem no log (`level=WARNING`, `msg` começando com `ALERTA`).

## Segurança (Fase 10.2)

### Cabeçalhos

**API** (o backend envia em toda resposta, inclusive SSE e Excel):
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
`Cross-Origin-Resource-Policy: same-origin`,
`Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`
e, fora de dev, `Strict-Transport-Security: max-age=31536000; includeSubDomains`
(`HSTS_MAX_AGE`, 0 desliga). Swagger (`/docs`) só existe em dev.

**Página do app** (quem servir o `frontend/dist/` precisa enviar; fonte única em
`frontend/security-headers.ts`, `PRODUCTION_HEADERS`):

```
Content-Security-Policy: default-src 'self'; script-src 'self' https://developer.api.autodesk.com blob:; worker-src 'self' blob:; style-src 'self' 'unsafe-inline' https://developer.api.autodesk.com; img-src 'self' data: blob: https://*.autodesk.com; font-src 'self' data: https://*.autodesk.com; connect-src 'self' https://*.autodesk.com wss://*.autodesk.com; media-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

A CSP foi validada com o **Viewer v7 real** carregando o modelo do Docs (SVF2 por
`cdn.derivative.autodesk.com`, https e WebSocket). A telemetria do Viewer
(`api-js.mixpanel.com`) fica **bloqueada de propósito**: não afeta o modelo. Se a
Autodesk mudar domínios, o sintoma é o modelo não abrir e uma violação
`connect-src`/`script-src` no console do navegador.

### CORS

Só o domínio do app: `CORS_ORIGINS` (vírgulas) ou, vazio, a origem de `APP_BASE_URL`.
`*` impede o backend de subir. Servindo app e API no mesmo domínio (recomendado:
proxy com `/` → `dist/` e `/api` → backend), o CORS nem entra em jogo.

### Limite de taxa

`RATE_LIMIT_WRITES_PER_MIN` (padrão 120) escritas por **usuário** por minuto
(POST/PUT/PATCH/DELETE), contadas no Redis e somadas entre instâncias. Acima: **429**
com `Retry-After` e a mensagem "Muitas alterações em pouco tempo…"; a métrica
`rate_limited_total` conta os bloqueios. Leituras não contam; edição em lote conta
como uma escrita. Se o Redis cair, as escritas seguem liberadas (com aviso no log).
O webhook do APS fica fora (não tem usuário; a assinatura protege).

### Matriz de papéis

Coberta inteira por `backend/tests/test_role_matrix.py` (rota nova sem linha na matriz
reprova o teste). Papel negado: 403; sem usuário: 401.

| Rotas | projetos | fábrica | admin | leitura |
|---|:-:|:-:|:-:|:-:|
| Leitura: obras, versões, relatório, busca, facetas, status, progresso, peça, valores, histórico, órfãs, diff, catálogo, eventos (SSE), Excel, token do Viewer, `/api/me`, prévia de lote | ✓ | ✓ | ✓ | ✓ |
| Motor de filtros e cores: campos, valores, avaliar filtro, avaliar esquema de cores, colorir por campo | ✓ | ✓ | ✓ | ✓ |
| Filtros salvos e esquemas de cores **pessoais** (só o dono vê e edita) | ✓ | ✓ | ✓ | ✓ |
| Filtros salvos e esquemas de cores **compartilhados**: criar, editar, excluir (`SHARED_FILTER_ROLES`, padrão fábrica e admin; ver todos podem). Os de sistema (antigos atalhos) ninguém edita | – | ✓ | ✓ | – |
| Navegar no Docs (`/api/acc/*`), cadastrar/editar obra | ✓ | – | ✓ | – |
| Sincronizar agora | ✓ | ✓ | ✓ | – |
| Editar valores, aplicar/desfazer lote, manter valores (revisar), religar/arquivar órfã, criar/editar/excluir parâmetro | – | ✓ | ✓ | – |
| `/api/metrics` (ou Bearer `METRICS_TOKEN`) | – | – | ✓ | – |
| Públicas: `/api/health`, `/api/ready`, `/api/dev/users` (só dev), webhook do APS (assinatura) | | | | |
