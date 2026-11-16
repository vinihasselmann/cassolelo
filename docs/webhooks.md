# Webhooks do Docs e verificação periódica

Como uma revisão publicada no Autodesk Docs chega ao app sem ação manual.

```
Docs publica revisão ──webhook──▶ POST /api/webhooks/aps ──fila──▶ job sync_obra ──▶ sync_versions
                                     (assinatura, webhook_events)                         │
worker: cron a cada 10 min ─────────────────────────────▶ sync_all_obras ───────────────┤
                                                                                          ▼
                                                  manifest de cada versão nova (só leitura)
                                         success → pending → process_version (Fase 3)
                                         inprogress → translating (cron a cada 2 min, até 2 h)
                                         sem derivativo → no_translation (aviso na aba Versões)
```

## Peças

| Peça | Onde |
|---|---|
| Receptor (HMAC-SHA1 `x-adsk-signature`, idempotente em `webhook_events`) | `backend/app/api/webhooks.py`, `app/services/webhooks.py` |
| Registro/listagem/remoção de hooks por obra | `python -m app.cli hooks register\|list\|delete --obra <id>` |
| Registro automático ao criar obra | quando `PUBLIC_BASE_URL` está definido |
| Jobs e crons | `app/workers/tasks.py`, `app/workers/settings.py` (`make worker`) |
| Situação da conversão | `app/services/translation.py` |

O id do evento usado para idempotência é o header `x-adsk-delivery-id`, quando o APS o enviar; senão, o SHA-256 do corpo. A obra do evento é encontrada pelo `hookAttribute.obra_id` (gravado no registro) ou, se faltar, pela pasta + arquivo.

## Pôr para funcionar (dev)

1. Em `infra/.env`: `APS_CLIENT_ID`, `APS_CLIENT_SECRET` e `APS_WEBHOOK_SECRET` (valor aleatório longo).
2. Redis rodando (`make up`) e o worker: `make worker`.
3. Expor o backend com HTTPS (o APS precisa alcançar o callback). Use uma das opções:
   - Cloudflare Tunnel: `cloudflared tunnel --url http://localhost:8000` (a URL muda a cada execução);
   - ngrok: `ngrok http 8000`.
4. `PUBLIC_BASE_URL=https://<url-do-túnel>` em `infra/.env` e reinicie o backend.
5. Registre o secret uma vez: `cd backend && uv run python -m app.cli hooks set-secret`.
6. Para obras novas, os hooks são registrados ao criar a obra. Para obras que já existem:
   `uv run python -m app.cli hooks register --obra <id>`.

Com o túnel desligado, a verificação periódica do worker (a cada 10 min) encontra a versão mesmo assim.
Se a URL do túnel mudar, rode `hooks delete` e `hooks register` de novo para cada obra.

## Pontos a confirmar com o APS real

- Se o escopo `data:read` basta para criar hooks e registrar o secret. Se der 403, verificar a documentação de escopos do Webhooks API. O CLAUDE.md só permite `data:read` e `viewables:read`, então qualquer outro escopo precisa de decisão antes.
- Se o APS envia um id de entrega em header (`x-adsk-delivery-id`).
- Os campos `payload.lineageUrn` e `payload.parentFolderUrn` dos eventos `dm.version.*`.
