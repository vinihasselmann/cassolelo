# Progresso

| Fase | Nome | Status |
|------|------|--------|
| 0 | Spike APS/Docs | aceites com o Docs real feitos para .rvt (2026-11-11); faltam .nwd/.ifc, versões, webhooks, licença |
| 1 | Fundação | concluída localmente, com Docker (falta CI no GitHub) |
| 2 | Vínculo com o Docs e versões | aceite com o Docs real em 2026-11-13: 2.1/2.2 ok, 2.3 parcial (webhooks adiados), 2.4 pendente; defeito: 2 obras no mesmo arquivo |
| 3 | Leitura de propriedades e validação de marcas | código pronto (3.1–3.2, fixtures sintéticas); aceite pendente do APS |
| 4 | Visualizador | código pronto (4.1–4.2); aceite no tablet real pendente do APS |
| 5 | Busca | aceite ok com os modelos reais já processados (2026-11-13); falta o Viewer real; 4 observações de usabilidade |
| 6 | Parâmetros da fábrica | pronto (6.1–6.4; aceite ok; catálogo começa vazio) |
| 7 | Reconciliação de versões | pronto (7.1–7.2; aceite ok; sync real da V2 ok) |
| 8 | Distribuição automática e tempo real | pronto (8.1–8.2; aceite ok) |
| 9 | Exportação | pronto (9.1; aceite ok; 9.2 não será feito) |
| 10 | Endurecimento | pronto (10.1–10.3; aceite ok, 2026-11-12); falta instalar no PC de teste da fábrica |
| 11 | Login e piloto | não iniciada |

## Fase 0 · Spike APS/Docs

Código e testes de todos os passos prontos (0.1 a 0.5). **Nenhum aceite foi feito ainda:** todos dependem de credenciais reais e da liberação no ACC.
Verificação (em `spikes/`): `ruff check .` OK · `ruff format --check .` OK · `mypy .` (strict) OK · `pytest`: 52 testes passando.
Configuração comum em `spikes/pyproject.toml`; dependências de desenvolvimento em `spikes/requirements-dev.txt`; saídas em `spikes/out/` (no .gitignore).

### 0.1 · Listar o Docs — código pronto, aceite pendente
- `spikes/aps_docs/list_docs.py`: token 2-legged (`data:read viewables:read`); hubs → projetos → topFolders; listagem recursiva de uma pasta com paginação; árvore com nome, tipo e id.
- 401/403 → "app não liberado em Custom Integrations"; o token nunca é impresso.

### 0.2 · Versões, manifest e propriedades — código pronto, aceite pendente
- `spikes/aps_docs/read_model.py`: versões (número, autor, data); URN do derivativo em base64 url-safe sem padding; manifest (404 ou sem SVF/SVF2 → "arquivo sem conversão no Docs" e para); vista 3D (master); árvore e propriedades com espera em 202 e `forceget=true` em 413.
- Por elemento: dbId, externalId, nome, categoria (propriedade de `CATEGORY_PROPERTY_NAMES` ou categoria da árvore) e Marca (`MARK_PROPERTY_NAMES` em todos os grupos, sem diferenciar maiúsculas).
- Elemento = nó com Marca (componentes aninhados não contam) ou folha sem Marca acima. Saída em `spikes/out/<item>_v<n>.json` e resumo no terminal.
- Só GET no Model Derivative; um teste garante que não há POST /job. `APS_REGION` (US/EMEA/AUS).

### 0.3 · Comparar versões — código pronto, aceite pendente
- `spikes/aps_docs/compare_versions.py`: agrupa por (Marca, categoria); gera `spikes/out/compare.csv` (separador `;`, UTF-8 com BOM, para o Excel) com situação mantida/quantidade alterada/nova/removida, contagem de externalId novos/removidos e dimensões divergentes (`DIMENSION_PROPERTY_NAMES`).

### 0.4 · Viewer — código pronto, aceite pendente
- `spikes/viewer/`: FastAPI com `/token` (apenas `viewables:read`, cache até 60 s antes de expirar), `/config`, `index.html` com o Viewer v7 (`AutodeskProduction2`, `streamingV2`). O painel mostra dbId, externalId, Marca e Categoria; o clique seleciona todas as peças da mesma marca e categoria.
- O JavaScript da página não tem teste automatizado; ele é verificado no aceite manual.

### 0.5 · Webhooks — código pronto, aceite pendente
- `spikes/webhooks/webhook_server.py`: `POST /hooks/aps` valida `x-adsk-signature` (HMAC-SHA1), responde 200 e grava em `spikes/out/webhooks.log`.
- `spikes/webhooks/manage_webhooks.py`: `set-secret`, `create` (dm.version.added e dm.version.modified, scope na pasta, `hookAttribute.obra_id`), `list`, `delete`.
- README com ngrok e Cloudflare Tunnel.

### Fechamento
- `docs/decisoes-fase-0.md` criado como modelo; precisa ser preenchido com os resultados reais.

### Falta
- Preencher `spikes/.env` e executar os aceites de 0.1 a 0.5 com modelos reais (.rvt, .nwd, .ifc).
- Pontos a confirmar nos testes reais: nome da propriedade de categoria em cada formato; se o escopo `data:read` basta para criar webhooks e registrar o secret; se a contagem por elemento bate com o quantitativo do Revit.
- Ações manuais: liberação em Custom Integrations; resposta da Autodesk sobre a licença; forma de publicação que gera conversão; conversa com a fábrica sobre o catálogo.
- Preencher `docs/decisoes-fase-0.md`. Se algo bloquear a Opção C, reavaliar com a gerência antes da Fase 1.

## Fase 1 · Fundação

Verificação (2026-11-10, Windows, PostgreSQL 16.14 portátil em localhost:5432, sem Docker), com `REQUIRE_DB=1`:
- `make lint`: OK (ruff, ruff format, mypy strict, ESLint, tsc).
- `make test`: **backend 99/99** (inclui os 22 de banco e migração), **frontend 8/8**.
- `make migrate` e `make seed`: OK. `npm run build`: OK.
- Aceite no servidor real: `/api/me` sem header → 401; X-Dev-User 1/2/3/4 → projetos/fabrica/admin/leitura; id inexistente → 401. O mesmo resultado sai pelo proxy do Vite (`make dev-local`).

### 1.1 · Esqueleto do monorepo — pronto
- `backend/`: FastAPI (`GET /api/health`), pydantic-settings (`infra/.env`, `backend/.env`), SQLAlchemy 2 async + asyncpg, Alembic async, ruff, mypy strict, pytest + pytest-asyncio. Dependências gerenciadas com uv (`uv.lock`).
- Testes de banco isolados: cada sessão de testes cria um banco `bim_test_*`, aplica as migrações e apaga o banco no fim; cada teste roda numa transação desfeita (savepoints).
- `frontend/`: Vite 6 + React 18 + TS strict, ESLint (typescript-eslint strict), Vitest 3 + Testing Library, TanStack Query, react-router, layout com cabeçalho "Visualizador BIM".
- `infra/docker-compose.yml` (postgres:16, redis:7, volumes nomeados, healthchecks, portas só em 127.0.0.1), `infra/.env.example`, `infra/dev.py`.
- `Makefile`: `dev`, `test`, `lint`, `migrate` (e `up`, `down`, `seed`, `install`). Funciona no Windows com o make do ezwinports.
- `.github/workflows/ci.yml`: jobs de backend (postgres e redis como serviços; lint, migração do zero, testes) e de frontend.

### 1.2 · Usuário simulado e papéis — pronto (testes de integração pendentes de Postgres)
- `backend/app/auth/`: `current_user` (header X-Dev-User; só com APP_ENV=dev, senão 401), `require_role(*papéis)` (403) e `CurrentUser`. Os endpoints importam só de `app.auth`.
- Seed idempotente (`make seed`) com 4 usuários, um por papel, gravado com auditoria. `GET /api/me`; `GET /api/dev/users` (só em dev, para o seletor).
- Frontend: `src/api/client.ts` envia X-Dev-User em toda requisição (usuário guardado só em memória); seletor no cabeçalho mostra o papel vindo de `/api/me`. O teste encontrou e corrigiu um bug de cache ao trocar de usuário.

### 1.3 · Modelo de dados — pronto (testes pendentes de Postgres)
- Modelos em `app/models/` e migração `0001_initial`; `docs/DATA_MODEL.md` atualizado com o que mudou.
- Unicidades em marks (obra_id, code, category) e param_values (mark_id, def_id); GIN em elements.props; `row_version` com concorrência otimista; `audit.record(...)` + `audit.snapshot(...)`.
- Testes: upgrade → downgrade → upgrade; modelos = migração (autogenerate sem diferenças); constraints; GIN; StaleDataError; auditoria; seed idempotente.

### 1.4 · Cliente APS — pronto
- `app/aps/`: `auth.py` (cache por conjunto de escopos até 60 s antes de expirar; só aceita `data:read` e `viewables:read`), `client.py` (retentativas exponenciais com jitter em 429/5xx/rede, respeita Retry-After, renova o token uma vez em 401, logs sem tokens), `data_management.py`, `derivatives.py` (202 → espera; 413 → `forceget=true`; 404 no manifest → "arquivo sem conversão no Docs"), `schemas.py`.
- POST /job e AEC Data Model bloqueados em `check_allowed`. Os testes garantem que nada é enviado e que nenhum outro módulo cita esses endpoints.
- Fixtures em `backend/tests/fixtures/aps/` são **sintéticas**: ainda não há respostas reais da Fase 0. Veja o README da pasta para trocar pelas reais.

### Pendências da Fase 1
- ~~`make dev` com docker compose~~: feito em 2026-11-10 (WSL2 + Docker Desktop; veja "Docker" abaixo).
- Ver o CI verde no GitHub (o repositório ainda não tem remoto).
- Trocar as fixtures sintéticas do APS pelas reais quando os aceites da Fase 0 rodarem.

### Docker (2026-11-10)
- Docker Desktop 4.99 com WSL2. `make up` sobe postgres:16 e redis:7 (7.4.12) saudáveis; migrações `0001`–`0003` e seed aplicados no banco do container.
- Para o engine subir, foi preciso habilitar o Virtual Machine Platform (`wsl --install --no-distribution` como admin) e **reiniciar** (não basta desligar).
- **Correção:** `DATABASE_URL`/`REDIS_URL` agora usam `127.0.0.1`, não `localhost` (`infra/.env.example` e o default de `redis_url` em `app/config.py`, com teste em `tests/test_config.py`). No Windows, `localhost` tenta `::1` primeiro; o compose publica só em `127.0.0.1` e a recusa demora ~2 s. Isso estourava o `conn_timeout=2` do Arq (worker não subia) e deixava cada conexão ao Postgres 2 s mais lenta: os testes do backend caíram de 224 s para 18 s. Quem já tem `infra/.env` precisa trocar o host nas duas linhas.

### Postgres local sem Docker (obsoleto)
Não é mais necessário; pode ser apagado. Binários portáteis em `%LOCALAPPDATA%\visualizador-bim\pgsql`, dados em `%LOCALAPPDATA%\visualizador-bim\data`, usuário/senha conforme `infra/.env`. O servidor não sobe sozinho depois de reiniciar o Windows:

```powershell
$pg = "$env:LOCALAPPDATA\visualizador-bim"
& "$pg\pgsql\bin\pg_ctl.exe" -D "$pg\data" -l "$pg\postgres.log" -o "-p 5432 -c listen_addresses=localhost" start
& "$pg\pgsql\bin\pg_ctl.exe" -D "$pg\data" stop     # para parar
```

Quando o Docker estiver instalado: pare este servidor (a porta 5432 é a mesma do compose), rode `make dev` e, se quiser, apague a pasta `visualizador-bim`.

## Fase 2 · Vínculo com o Docs e versões

Verificação (2026-11-10, Postgres portátil, `REQUIRE_DB=1`): `make lint` OK; `make test` com backend 127/127 e frontend 18/18. Migração `0002` aplicada no banco de dev. Smoke test no servidor real: `/api/acc/hubs` sem credenciais APS → 502 "Credenciais do app APS inválidas ou ausentes no servidor."; papel fábrica → 403; sync de obra inexistente → 404.

### 2.1 · Cadastro de obra com seletor do Docs — pronto
- `GET /api/acc/hubs`, `/api/acc/hubs/{hub}/projects`, `/api/acc/hubs/{hub}/projects/{project}/top-folders` (fora do prompt, mas necessário para entrar no projeto) e `/api/acc/projects/{project}/folders/{folder}`. Só projetos/admin. Pastas ocultas são filtradas; cada arquivo vem com `supported` (.rvt/.nwd/.ifc).
- `GET/POST /api/obras`, `GET/PATCH /api/obras/{id}`. Criar e editar: só projetos/admin. O backend confere no Docs que o arquivo existe e é suportado, e grava `acc_item_name`. Código duplicado → 409. Não deixa trocar o arquivo de obra com versões sincronizadas (409). Tudo auditado.
- Erros do APS e de negócio viram `{"detail", "code"}` em português (`app/api/errors.py`): 403 do Docs → mensagem de Custom Integrations.
- Frontend: rota `/obras` (lista + "Nova obra", só para projetos/admin) e `AccPicker` (hub › projeto › pastas › arquivo, com breadcrumb). Mensagens para pasta vazia, pasta sem modelos suportados, nenhum hub e falta de permissão.

### 2.2 · Sincronizar versões — pronto
- `app/services/versions.py::sync_versions`: insere as versões que faltam com `INSERT ... ON CONFLICT DO NOTHING` (idempotente mesmo com duas sincronizações ao mesmo tempo). Grava número, acc_version_id, urn, autor, data, comentário e status `pending`, com auditoria (um `batch_id` por sincronização). Faz commit e **depois** enfileira `process_version` (job id `process_version:<id>`, sem duplicar).
- Fila fora do ar: as versões ficam salvas e a resposta informa `enqueue_failed`; a tela avisa.
- `app/workers/`: `ArqQueue`, stub `process_version` (só log) e `WorkerSettings` (`make worker`).
- `POST /api/obras/{id}/sync` (projetos, fábrica e admin) e `GET /api/obras/{id}/versions`.
- Frontend: `/obras/:id/versoes` com histórico (versão, autor, data, comentário, situação) e "Sincronizar agora".
- Testes: sync 2× não duplica; só versões novas são inseridas e enfileiradas; fila fora do ar mantém as versões; auditoria; papéis; endpoints.

### 2.3 · Webhooks e verificação periódica — pronto
- `POST /api/webhooks/aps`: valida `x-adsk-signature` (401 se inválida, 503 sem secret), grava em `webhook_events` com idempotência (header de entrega ou SHA-256 do corpo), faz commit, responde e **só depois** enfileira `sync_obra` (a resposta não espera o Redis). A obra é encontrada por `hookAttribute.obra_id` ou por pasta + arquivo; evento sem obra é guardado e não enfileira.
- `app/aps/webhooks.py` (reaproveita o spike) e `python -m app.cli hooks register|list|delete --obra <id>` e `hooks set-secret`. Ao criar uma obra com `PUBLIC_BASE_URL` definido, os hooks são registrados em segundo plano; se falhar, o cadastro não é desfeito.
- Worker Arq: `sync_obra` (marca o evento como processado) e cron `sync_all_obras` a cada 10 min (obras ativas e vinculadas; uma obra com erro não para as outras). Migração `0003`: `obras.active`, `webhook_events.obra_id`.
- Guia de operação: `docs/webhooks.md`.

### 2.4 · Versão sem conversão — pronto
- `app/services/translation.py`: o sync consulta o manifest de cada versão nova (só GET, nunca converte). `success` com SVF/SVF2 → `pending` + `process_version`; `inprogress` → `translating`; sem derivativo, 404 ou sem SVF → `no_translation`; `failed` → `failed` com as mensagens. Falha ao consultar → `translating` (nova tentativa).
- Cron `check_translations` a cada 2 min: `translating` → reconsulta; depois de 2 h → `failed` ("A conversão do Docs não terminou em 2 horas.").
- Aba Versões: aviso exato do prompt na linha da versão `no_translation`; "verificação automática a cada 2 min" em `translating`; mensagem de sincronização com os contadores; atualiza a lista a cada minuto.

### Verificação (2026-11-10, Postgres portátil, `REQUIRE_DB=1`)
- `make lint` OK; `make test` com backend 161/161 e frontend 19/19. Migrações até `0003` aplicadas no banco de dev.
- Corrigido o isolamento dos testes: `make_settings` lia o `infra/.env` local. Agora ignora `.env` e variáveis de ambiente (com teste de regressão).
- Smoke test no servidor real: webhook com assinatura válida → 200 `queued` em 210 ms; o mesmo evento de novo → 200 `duplicate` (1 linha gravada); assinatura inválida → 401. Sem Redis, a falha de enfileiramento fica no log e a resposta não espera.

### Falta para o aceite da Fase 2
- **Tudo depende do Docs real** (Custom Integrations + `APS_CLIENT_ID`/`APS_CLIENT_SECRET`, hoje vazios em `infra/.env`): publicar uma revisão e ver a versão aparecer sozinha; desligar o túnel e ver a verificação de 10 min encontrar a versão; publicar sem conversão e ver o aviso.
- A confirmar com o APS real (detalhes em `docs/webhooks.md`): se o escopo `data:read` basta para o Webhooks API, o header de id de entrega, os campos `lineageUrn`/`parentFolderUrn` e a chave do comentário da versão.
- Versões `pending` cujo enfileiramento falhou não são reenfileiradas automaticamente (o `process_version` ainda é stub). Avaliar na Fase 3.

### Validação com Redis real (2026-11-10, Docker)
- `make lint` OK; `make test` com backend 162/162 (`REQUIRE_DB=1`, banco do container) e frontend 19/19.
- Ponta a ponta com API (uvicorn) + `make worker`: `process_version` enfileirado pelo `ArqQueue` → executado pelo worker; webhook assinado → `200 queued` em ~360 ms → `sync_obra(obra, evento)` consumido do Redis; sem credenciais APS ele falha com "APS_CLIENT_ID/APS_CLIENT_SECRET não configurados" e o evento fica não processado (o cron de 10 min tenta de novo). Crons `sync_all_obras` e `check_translations` disparando no horário. A obra temporária do teste foi apagada.
- Observação: um `sync_obra` que falha não é reexecutado pelo Arq (`max_tries` só vale para `Retry`); a recuperação é o cron `sync_all_obras`, mas o `webhook_events` correspondente continua com `processed_at` nulo.

### Aceite com o Docs real (2026-11-13)
API (uvicorn) + worker Arq + Postgres/Redis do Docker, credenciais APS reais.
- **2.1 — passou:** hubs (1,1 s) → projetos → top-folders → "Project Files" com os 3 modelos (`supported=true`); fábrica → 403. Código duplicado → 409; arquivo inexistente no Docs → 404 "Não encontrado no Autodesk Docs."; trocar o arquivo de obra com versões → 409; fábrica criando obra → 403.
- **2.2 — passou nas obras existentes:** sync 2× nas obras 5, 6 e 7 → `created: 0`, sem duplicar (0,3–0,6 s); fábrica pode sincronizar, leitura → 403.
- **2.3 — passou em parte:** o cron `sync_all_obras` rodou ao subir o worker e verificou as 3 obras vinculadas sem erro (a v2 já tinha sido encontrada assim em 2026-11-11). Webhooks continuam adiados para o servidor definitivo (decisão de 2026-11-11).
- **2.4 — não testado:** precisa de um arquivo publicado sem conversão no Docs.
- **Defeito encontrado (CORRIGIDO em 2026-11-13: o cadastro e a troca de arquivo recusam com 409 `file_in_use` um arquivo do Docs já ligado a outra obra, mesmo inativa; obras 14 e 15, criadas assim no teste, foram desativadas):** `model_versions.acc_version_id` é único na tabela toda e o sync usa `ON CONFLICT DO NOTHING`. Uma **segunda obra ligada ao mesmo arquivo do Docs não recebe nenhuma versão**, e o sync responde 200 com `total_in_docs: 2, created: 0` e não avisa nada. Reproduzido com a obra temporária `ACEITE-F2` (id 11, desativada depois do teste). Correção a decidir: bloquear o cadastro (409 "arquivo já vinculado à obra X") ou tornar a unicidade por `(obra_id, acc_version_id)`.

## Fase 3 · Leitura de propriedades e validação de marcas

### 3.1 · Processar a versão — pronto (fixtures sintéticas; aceite com modelo real pendente)
- `app/services/processing.py::process_version` substitui o stub do job: status `processing` (commit) → `metadata` (vista 3D, master primeiro) → árvore + `properties` (só GET; 202 espera, 413 → `forceget=true`) → `ready`. Qualquer erro: rollback e `failed` com a mensagem (erros do APS com o texto em português; erro inesperado com mensagem genérica, detalhe só no log).
- Só processa versões `pending`, `processing` (job interrompido), `ready` (reprocessar) ou `failed`; `translating`/`no_translation` são ignoradas.
- `app/services/extraction.py` (puro, portado do spike 0.2): elemento = nó com Marca (filhos são componentes aninhados) ou folha sem Marca acima. Marca lida por `MARK_PROPERTY_NAMES` em todos os grupos (sem diferenciar maiúsculas); `marks.code` = trim + maiúsculas; `elements.mark_raw` guarda o valor do modelo. Categoria por `CATEGORY_PROPERTY_NAMES` (novo, padrão `Category,Categoria,IfcClass`) ou pela árvore; prefixo "Revit " removido.
- Além de metadata e properties, uso também a árvore do objeto (GET `metadata/{guid}`), como no spike, para não contar componentes aninhados.
- Gravação em lote (1000 linhas por INSERT): apaga os elementos da versão e regrava; marcas com `INSERT ... ON CONFLICT DO NOTHING` em (obra_id, code, category), em ordem fixa (sem deadlock entre versões). Idempotente: reprocessar não duplica marcas e mantém os mesmos ids. Uma falha no reprocessamento desfaz tudo e mantém os elementos anteriores.
- Auditoria: `model_version` `process_start` / `process_ready` (com contagens e tempo) / `process_failed`; `mark` `create` para cada marca nova (`audit.record_many`, um `batch_id` por processamento). Elementos não têm linha própria de auditoria (dados do BIM, recriáveis); a substituição fica no resumo de `process_ready` (`elements`, `elements_deleted`).
- Migração `0004`: `elements.name`. Worker recebe `ctx["settings"]`.
- Testes: `tests/test_extraction.py` e `tests/test_process_version.py` (os 3 formatos, idempotência, reaproveitamento entre versões e não entre obras, 202/413, falhas, versões ignoradas, job com `MARK_PROPERTY_NAMES` configurado).

**Fixtures:** as respostas reais da Fase 0 ainda não existem. `tests/fixtures/aps/models/{rvt,nwd,ifc}/` são **sintéticas**, montadas para o formato típico de cada tipo de arquivo (veja o README da pasta). Trocar pelas reais sanitizadas e reconferir as contagens.

### Desempenho (2026-11-11, Postgres 16 no Docker/WSL2, modelo SINTÉTICO)
`uv run python -m tests.bench_process_version --elements N --marks M` (APS simulado, ~30 propriedades por peça):

| Elementos | Pares marca+categoria | JSON de propriedades | 1º processamento | Reprocessamento |
|---|---|---|---|---|
| 5.000 | 2.450 | 3,9 MB | 1,6 s | 1,4 s |
| 30.000 | 14.700 | 23,7 MB | 8,6 s | 9,0 s |

Não inclui o tempo de download do APS nem a espera em 202. **Falta medir com o maior modelo real.**

### Verificação (2026-11-11, Docker)
- `make lint` OK; `make test` com backend 187/187 (`REQUIRE_DB=1`) e frontend 19/19. Migração `0004` aplicada no banco de dev.
- Smoke test com Redis real: versão `pending` enfileirada → `make worker` (`arq --burst`) → `processing` → `failed` "APS_CLIENT_ID/APS_CLIENT_SECRET não configurados." (sem credenciais, como esperado). O registro temporário foi apagado.

### Falta no 3.1
- Aceite com o Docs real (.rvt, .nwd, .ifc): conferir nomes da propriedade de categoria em cada formato, a contagem contra o quantitativo do Revit e o tempo do maior modelo.
- Continua em aberto (da Fase 2): versões `pending` cujo enfileiramento falhou não são reenfileiradas automaticamente, e não há botão para reprocessar uma versão `failed`.

### 3.2 · Validação de marcas — pronto (fixtures sintéticas; aceite com modelo real pendente)
- `app/services/mark_validation.py`: `build_report` (puro) roda ao fim do `process_version`, na mesma transação, com os elementos como foram gravados. O relatório tem:
  - peças sem Marca (dbid, externalId, categoria, nome);
  - marcas inconsistentes: mesma marca + categoria com valores diferentes em `DIMENSION_PROPERTY_NAMES` (padrão `Comprimento,Largura,Altura,Length,Width,Height`) além de `DIMENSION_TOLERANCE_MM` (padrão 5). Valores convertidos para mm (`mm`, `cm`, `m`, vírgula ou ponto; sem unidade = mm); formatos não numéricos (ex.: pés/polegadas) são comparados como texto. Peça sem a propriedade não gera alerta;
  - totais: peças, marcas, sem Marca, marcas inconsistentes e por categoria.
- Tabela `version_reports` (migração `0005`, JSONB, uma linha por versão, substituída ao reprocessar). O resumo também vai para o `process_ready` do audit_log (`inconsistent_marks`).
- `GET /api/versions/{id}/report`: todos os papéis podem ler; 404 `not_found` (versão inexistente) e 404 `report_not_ready` (ainda não processada).
- Frontend: aba Versões, para projetos/admin, coluna "Validação" (botão em cada versão pronta) e painel "Validação — vN" (padrão: versão pronta mais recente) com contador verde "Nenhum alerta" ou laranja "N alertas: X peças sem Marca, Y marcas inconsistentes", tabelas de marcas inconsistentes, peças sem Marca e totais por categoria. Fábrica e leitura não veem o painel.
- `process_version` passou a receber um `ProcessingConfig` (marca, categoria, dimensões, tolerância), montado do `Settings` pelo worker.
- Testes: `tests/test_mark_validation.py` (dois PP001 de seções diferentes → alerta; peça sem Marca na lista; totais; tolerância; unidades; texto; categorias diferentes; gravação, reprocessamento, API) e `src/features/obras/Validation.test.tsx` (painel, contador verde/laranja, troca de versão, fábrica sem painel, relatório ainda não gerado). Modelo de teste com os casos plantados em `tests/fixtures/aps/models/validacao/`.
- `.gitignore` agora ignora `*.rvt`, `*.rfa`, `*.nwd`, `*.nwc`, `*.ifc` (o modelo `30.327-01 - MODELO - ORC.rvt` colocado nas fixtures não vai para o git; ele só vira fixture depois de publicado no Docs e lido pela API).

### Verificação (2026-11-11, Docker)
- `make lint` OK; backend 205/205 (`REQUIRE_DB=1`), frontend 23/23; `npm run build` OK. Migração `0005` aplicada no banco de dev.
- Benchmark sintético com relatório: 30.000 elementos em 10,0 s (1º) / 8,8 s (reprocessamento).

### Falta para o aceite da Fase 3
- Com o APS liberado: publicar o `30.327-01 - MODELO - ORC.rvt` no Docs, gravar as respostas sanitizadas como fixture e conferir a contagem por categoria contra o quantitativo do Revit.
- Plantar no modelo de teste os casos (marca repetida com seção diferente, peça sem Marca) e ver o painel apontá-los. Confirmar os nomes reais das propriedades de dimensão (`DIMENSION_PROPERTY_NAMES`) e como o Docs formata as unidades.

## Fase 4 · Visualizador

### 4.1 · ViewerAdapter e tela da obra — pronto (sem teste com modelo real: APS ainda não liberado)
- Backend: `GET /api/viewer-token` (todos os papéis) → `{access_token, token_type, expires_in, region}` com `Cache-Control: no-store`. Token 2-legged **só com `viewables:read`**, em cache próprio no `TokenProvider` (o token de dados `data:read viewables:read` nunca sai do backend; teste garante tokens e escopos diferentes).
  - **Expiração curta:** o APS não permite pedir um token 2-legged mais curto (dura ~1 h). O endpoint informa ao navegador no máximo 600 s (`MAX_CLIENT_TTL`), então o Viewer pede outro a cada ≤10 min; o token em si continua válido até o prazo do APS.
  - `ModelVersionOut` ganhou `urn` (id do derivativo, usado pelo Viewer).
- Frontend (`src/viewer/`): `ViewerAdapter.ts` (interface), `ApsViewerAdapter.ts` (Viewer v7 do CDN oficial `.../viewers/7.*`, carregado só ao abrir o modelo; `AutodeskProduction2`, `streamingV2`/`streamingV2_EU`; renovação de token pelo endpoint; `load` mais recente vence se a versão mudar no meio), `viewerContext.ts`/`ViewerProvider.tsx` (fábrica injetável). Tipos mínimos do Viewer locais, sem dependência nova.
- Tela `/obras/:id/modelo` (link "Abrir modelo 3D" na página da obra): barra com obra e **versão ativa** (seletor só com versões prontas; padrão a mais recente; `?versao=<id>` na URL); 3 colunas: lista e filtros (reservado para os próximos passos) | modelo 3D com Enquadrar tudo, Enquadrar seleção, Isolar, Mostrar tudo, Limpar seleção | painel da seleção (dbIds por enquanto). Em tablet na horizontal (≤1180 px) as laterais estreitam (230/290 px); abaixo de 820 px o modelo fica em cima e os painéis embaixo.
- Corrigido: mensagens de erro do Viewer (ex.: falha ao carregar o CDN) apareciam como "Erro inesperado" porque `errorMessage` só conhecia `ApiError`.
- Testes: backend `tests/test_viewer_token.py` (escopo exato, separado do token de dados, cache, TTL ≤ 600, no-store, 401 sem usuário, 502 sem credenciais, região). Frontend `ApsViewerAdapter.test.ts` (Viewer falso: opções do Initializer, renovação de token, cada método, cores, onSelect só do usuário, destroy, erros, CDN injetado uma vez), `isolation.test.ts`, `ModelPage.test.tsx` (3 colunas, versão ativa, troca de versão, URL, ferramentas, seleção, sem versão pronta, erro, destroy).

### Verificação (2026-11-11, Docker)
- `make lint` OK; backend 211/211 (`REQUIRE_DB=1`), frontend 44/44; `npm run build` OK.
- Navegador real (Edge headless, 1180×820 e 800×1180) com backend + Vite: layout de 3 colunas e empilhado conferidos; `/api/viewer-token` sem credenciais → 502 "Credenciais do app APS inválidas ou ausentes no servidor." A obra temporária do teste foi apagada.

### Falta no 4.1
- Abrir um modelo real (depende do APS): conferir carga SVF2, seleção e cores no Viewer de verdade, inclusive em tablet com toque.
- Fixar a versão do Viewer (hoje `7.*`, como no spike) depois de validar com o modelo real.

### 4.2 · Seleção por marca e painel de propriedades — pronto (aceite com modelo real pendente do APS)
- Backend (`app/services/version_data.py`, rotas em `app/api/versions.py`, todos os papéis):
  - `GET /api/versions/{id}/marks` → `[{mark_id, code, category, count, dbids}]` (agregado no banco, ordenado por categoria e código; peças sem Marca não entram).
  - `GET /api/versions/{id}/elements/{dbid}` → dbid, externalId, nome, categoria, `mark_raw`, a marca (com quantidade e dbIds nesta versão) e `groups: [{name, properties: [{name, value}]}]`.
  - Versão inexistente → 404; versão que não está `ready` → 409 `version_not_ready`; peça inexistente → 404.
  - **Ordem das propriedades:** o JSONB do Postgres não guarda a ordem das chaves do Model Derivative; grupos e propriedades saem em ordem alfabética (sem diferenciar maiúsculas).
- Frontend (`features/modelo/`):
  - `selection.ts` (lógica pura): clique simples → a marca inteira da peça, pelos dbIds do endpoint (nunca `getProperties` do Viewer); Ctrl+clique (o Viewer devolve a seleção acumulada) soma marcas e tira a marca de uma peça desmarcada; modo **Seleção múltipla** (para tablet) soma a cada toque e tocar de novo numa marca selecionada a retira; peça sem Marca é selecionada sozinha; clique no vazio limpa (no modo múltiplo mantém).
  - `PiecePanel.tsx`: cabeçalho "PP001 · Structural Columns · 2 peças" (várias marcas: "2 marcas · 4 peças" + lista; "Peça sem Marca"), peça clicada (nome, dbId, externalId), "Parâmetros da fábrica" (vazio), "Propriedades do modelo" somente leitura com grupos recolhíveis e filtro (nome, valor ou grupo; com filtro, os grupos abrem).
  - Ferramentas: Enquadrar tudo, Enquadrar seleção, **Isolar** (liga/desliga; substitui o "Mostrar tudo" do 4.1), Limpar seleção, Seleção múltipla. A coluna esquerda mostra quantas marcas a versão tem; busca e lista ficam para a Fase 5.
  - A tela marca `performance.mark('modelo:pronto')` e `data-load="ready"` quando o modelo aparece (usado pelo E2E).
- **E2E (Playwright 1.49, novo):** `frontend/playwright.config.ts`, `frontend/e2e/` (veja o README da pasta), `make e2e` e job `e2e` no CI. Modo padrão roda sem APS: pilha real (API + Postgres) com a obra de teste **E2E-01** semeada por `backend/tests/e2e_seed.py` e um Viewer falso no lugar do CDN. Modo `E2E_REAL_VIEWER=1` usa o Viewer e o APS reais e falha acima de `E2E_MAX_LOAD_MS` (15 s). Testes: clicar numa peça → marca, quantidade, peças da marca destacadas, grupos de propriedades e filtro; peça sem Marca; Isolar/Limpar; Ctrl+clique (desktop); Seleção múltipla por toque; em tablet (Galaxy Tab S4 na horizontal) e desktop.
- Testes unitários: backend `tests/test_version_data.py`; frontend `selection.test.ts` e `ModelPage.test.tsx` (seleção por marca, Ctrl+clique, modo múltiplo, filtro e grupos).

### Verificação (2026-11-11, Docker)
- `make lint` OK; backend 218/218 (`REQUIRE_DB=1`), frontend 53/53; `make e2e` 7 passaram + 1 pulado (Ctrl+clique não roda no projeto tablet); `npm run build` OK.
- Tempo até o modelo aparecer no E2E com Viewer falso: ~0,5 s (só mede app + API; **não vale para o aceite**).
- A obra E2E-01 fica no banco de dev (é a obra de teste; o seed é idempotente).

### Falta para o aceite da Fase 4
- Com o APS liberado, no tablet real e na rede da fábrica: `E2E_REAL_VIEWER=1 E2E_OBRA_ID=<obra> E2E_BASE_URL=<servidor> npx playwright test` (ou abrir a tela e medir) — o modelo deve aparecer em até 15 s; clicar numa peça deve destacar todas as peças da marca.
- Confirmar que o `objectid` do Model Derivative (gravado como `elements.dbid`) é o mesmo dbId do Viewer no SVF2 do Docs (esperado, mas não verificado sem modelo real).

## Fase 5 · Busca

### 5.1 · Busca, filtros e atalhos — pronto
- Migração `0006`: `elements.level` (de `LEVEL_PROPERTY_NAMES`), `elements.search_text` (nome, categoria, marca, nível e valores de `SEARCH_PROPERTY_NAMES`: tipo, família e tipo, seção, material) e tabela `version_property_names` (grupos de cada propriedade na versão). Tudo preenchido pelo `process_version`; versões já processadas precisam ser reprocessadas para ter nível e nomes de propriedade.
- `GET /api/versions/{id}/marks/search` (`app/services/search.py`), busca no nível das PEÇAS e agrupada por marca:
  - `q`: cada palavra precisa aparecer no código da marca, na categoria, no `search_text` ou num valor de parâmetro da fábrica da marca (sem diferenciar maiúsculas; `%` e `_` tratados como texto);
  - `category`/`level` (vários); `prop=Nome=valor` (vários; nome sem diferenciar maiúsculas, valor exato como texto ou número) via `props @> {"Grupo": {"Nome": valor}}` com o índice GIN, grupos tirados de `version_property_names`;
  - `missing=<parâmetro>` ("sem <parâmetro>"): marcas sem valor (nulo ou vazio) no parâmetro da fábrica, global ou da obra; parâmetro inexistente → 422 `unknown_param` com mensagem clara;
  - `shortcut`: `all`, `new` (marcas sem peças na versão pronta anterior; na primeira versão vem vazio com aviso), `orphans` (órfãs abertas da obra, com 0 peças), `pending`/`partial`/`review` vazios com aviso até as Fases 6 e 7;
  - paginação (`page`, `page_size` até 500) e ordenação por marca (`order`); a resposta traz também `mark_ids` e `dbids` do resultado INTEIRO, para o 3D destacar todas as peças.
- `GET /api/versions/{id}/marks/facets`: categorias e níveis com nº de peças (filtros da tela).
- `ViewerAdapter.highlight(ids)` (novo): resultado em destaque, resto esmaecido (ghosting do Viewer); `isolate(ids)` agora ESCONDE o resto.
- Frontend (`SearchPanel.tsx`, `useMarkSearch.ts`, `searchQuery.ts`): campo de busca fixo no topo da coluna, debounce de 250 ms, exemplos clicáveis tirados da versão (prefixo de marca, nível, categoria); sintaxe `Nome=valor` e `sem <parâmetro>`; atalhos Todas/Pendentes/Parciais/A revisar/Novas na versão/Órfãs; filtros por categoria (com nº de peças) e nível; lista de marcas com quantidade, paginada (50); clicar seleciona e enquadra a marca; "Selecionar todas" seleciona o resultado. Com busca ativa o 3D destaca o resultado e esmaece o resto; "Isolar" esconde o resto (alvo: a seleção ou, sem ela, o resultado).
- Testes: `tests/test_search.py` (14: marca exata, texto, seção, várias palavras, curingas, categoria, nível, `Nome=valor`, `sem <parâmetro>` com escopo da obra, novas, órfãs, atalhos de status, paginação, facets, 409/401), `tests/test_search_perf.py`, Vitest (busca com debounce, destaque/isolar, lista ↔ seleção, Selecionar todas, atalhos, nível, exemplos, erro do "sem", `parseQuery`, `useDebouncedValue`), Playwright (buscar PP001 → destaque e Isolar mostram as peças 10 e 11 e só elas; seção 40x50 → só a peça 11; nível TÉRREO).

### Desempenho (2026-11-11, Postgres 16 no Docker/WSL2): 20.000 elementos, 2.000 marcas
Tempo da chamada inteira da API (FastAPI + Postgres), `tests/test_search_perf.py` (falha acima de 1 s):

| Consulta | ms |
|---|---|
| tudo (1ª página) | 101 |
| marca PP0012 | 50 |
| prefixo PP00 | 60 |
| seção 40x80 (texto livre) | 64 |
| valor de parâmetro F-12 | 46 |
| categoria | 25 |
| nível | 23 |
| propriedade Altura=80.0 cm | 44 |
| sem forma | 46 |
| novas na versão | 46 |
| combinada (texto + 2 níveis + propriedade) | 121 |

### Verificação (2026-11-11, Docker)
- `make lint` OK; backend 233/233 (`REQUIRE_DB=1`), frontend 58/58, `make e2e` 11 passaram + 1 pulado (Ctrl+clique no tablet); `npm run build` OK.
- O modelo de teste `validacao` ganhou `Tipo` e `Restrições > Nível base` (TÉRREO / 1º PAVIMENTO).

### Aceite com os modelos reais já processados (2026-11-13, sem acesso ao ACC)
A busca só lê o banco; usei as versões reais já processadas: ORC.rvt v2 (versão 14, Marcas reais PP001×4, PP002×4, PP005×6), ORC.rvt v1 (versão 5, marca simulada, 359 peças), IFC (versão 7) e 30.327-01-REC (versões 12/13, com "Tipo de forma").
- **Passou:** marca exata (`PP001` → 4 peças), prefixo sem diferenciar maiúsculas (`pp00` → 3 marcas), seção pelo nome do tipo (`60x60` → PP002; `80x80` → PP005; v1 `50x90` → V05 com 90 peças), nível real (`TÉRREO`) e categoria (`Pilares estruturais`) por filtro e no texto livre, `SEÇÃO-Largura=80.000 cm` → PP005 e `=60.000 cm` → PP001+PP002 (nome sem diferenciar maiúsculas), combinação texto + nível + categoria, curingas `%`/`_` tratados como texto, paginação, atalhos `new`/`orphans`/`pending`/`review`, papel leitura pode buscar. `sem Tipo de forma` → 422 claro onde o parâmetro não existe; na REC → 0 (as 3 marcas têm F-11/12/13, correto). Respostas de 12 a 80 ms.
- **Nomes de propriedade confirmados no modelo real:** `LEVEL_PROPERTY_NAMES` (Revit e IFC por `IfcSpatialContainer`: TÉRREO 145, EMBARQUE 190, DESEMBARQUE 15, COBERTURA 9) e `SEARCH_PROPERTY_NAMES` (tipo/seção; no IFC `ObjectType` e `IfcColumn` no texto de busca).
- Playwright (Viewer falso): "buscar PP001 → destaque e Isolar" e "seção + nível no 3D" 4/4 (tablet e desktop).
- **Observações (não são falhas da especificação; decidir com a fábrica):**
  1. ~~busca sensível a acento~~ (corrigido abaixo): `terreo` não acha `TÉRREO` (no tablet é comum digitar sem acento); correção possível com `unaccent` no Postgres;
  2. ~~`Nome=valor` numérico não casa~~ (corrigido abaixo) com valor com unidade: `SEÇÃO-Largura=60` → 0, precisa digitar `60.000 cm`;
  3. `ARMADO` não é encontrado: `TECNOLOGIA-Aço` está em `REVIEW_PROPERTY_NAMES`, não em `SEARCH_PROPERTY_NAMES` (só configuração);
  4. no IFC e nas peças sem Marca a busca não retorna nada, porque o resultado é agrupado por marca (o IFC da Cassol não traz Marca).
- Não testado: a busca com o **Viewer real** (precisa do token do APS).

### Ajustes pedidos depois do aceite (2026-11-13)
- **Sem acento:** migração `0009` (extensão `unaccent` + função `f_unaccent`, IMMUTABLE). Texto livre, nome e valor de `Nome=valor`, órfãs e nome do parâmetro no `sem <parâmetro>` comparam sem maiúsculas e sem acentos: `terreo` acha `TÉRREO`; `secao-largura=60` acha `SEÇÃO-Largura`.
- **Número sem unidade:** em `Nome=valor`, se o valor digitado é número (ponto ou vírgula) acha o número do modelo com qualquer unidade: `SEÇÃO-Largura=60` / `60,0` / `60 cm` / `60cm` → `60.000 cm`; com unidade, ela precisa bater (`50 mm` não acha `50.0 cm`); `5` não acha `50`; valor com outros dígitos continua texto (`Tipo=40` não acha `Pilar 40x40`). O valor de texto também passou a ignorar maiúsculas/acentos. O filtro deixou de usar o containment (índice GIN): a consulta já é limitada à versão e o teste de desempenho (20.000 peças, < 1 s) continua passando.
- **Nenhum parâmetro fixo:** revisado o código. Nenhum parâmetro da fábrica é criado ou exigido pelo app (catálogo começa vazio; "Tipo de forma" só aparece como dado de teste). `REVIEW_PROPERTY_NAMES` padrão agora é só o tipo (`Nome do tipo,Type Name,ObjectType`), sem `Armadura,TECNOLOGIA-Aço`; dicas da busca sem nomes de exemplo ("sem forma"). O placeholder do cadastro de parâmetro ("Ex.: Tipo de forma, Ciclo de cura...") ficou, por ser só sugestão.
- Testes novos: `test_text_ignores_accents`, `test_property_number_without_unit`, `test_any_factory_parameter_name_works_without_accents`; padrão de revisão em `test_reconcile.py`.
- Verificação: ruff, ruff format, mypy strict OK; backend **466/466** (`REQUIRE_DB=1`); ESLint, tsc OK; frontend **112/112**; `make e2e` **26 passaram + 6 pulados** (Viewer real e toque). Migração `0009` aplicada no banco de dev; conferido nos modelos reais (v14: `terreo`, `secao-largura=60`, `SEÇÃO-Largura=80 cm`, `nome do tipo=r-80x80cm-p05`).

### Falta para o aceite da Fase 5
- Com o APS: confirmar no modelo real os nomes das propriedades de nível e tipo/seção (`LEVEL_PROPERTY_NAMES`, `SEARCH_PROPERTY_NAMES`) e, para IFC, se o nível vem como propriedade (senão, tirar do pavimento na árvore).
- "sem <parâmetro>" já funciona na API e na tela, mas só terá uso real quando os parâmetros da fábrica forem cadastrados (Fase 6).

## Identificação das peças por obra (2026-11-13; itens 1 e 2 das sugestões)

Motivo: nos projetos internos a peça tem Marca E Nome da montagem (montagens detalhadas pela equipe), e modelos de terceiros podem trazer o identificador do pilar em qualquer parâmetro. Decisão registrada no CLAUDE.md: o padrão continua em `MARK_PROPERTY_NAMES`, mas cada obra pode ter a sua regra, e **qualquer papel** pode defini-la, com auditoria.

### 1 · Regra por obra — pronto
- Migração `0010`: `obras.mark_property_names` e `obras.category_property_names` (JSONB, em ordem de prioridade; nulo = padrão do servidor).
- `app/services/mark_rule.py`: limpa a lista (espaços, vazios, repetidos sem diferenciar maiúsculas; de 1 a 10 nomes), grava com auditoria (`obra` / `mark_rule`). Se a regra mudou, reprocessa a **versão ativa** (job `process_version(version_id, orphan_missing=True)` com id de job novo).
- `process_version` usa a regra da obra (`ProcessingConfig.for_obra`). Em cada peça vale o primeiro parâmetro da lista que tiver valor. Com `orphan_missing`, toda marca da obra **com valores** que ficou sem peças vira órfã aberta (`reason: mark_rule`), **mesmo com uma versão só**: sem isso a reconciliação, que só compara com a versão anterior, não veria a troca. Não duplica a órfã e respeita as órfãs já arquivadas.
- API: `GET/PUT /api/obras/{id}/mark-rule` (todos os papéis). `PUT` com `null` volta ao padrão. A resposta diz qual versão foi reprocessada e se a fila aceitou (fila fora do ar: a regra fica salva e a tela avisa).

### 2 · Assistente "Qual parâmetro identifica as peças?" — pronto
- `app/services/mark_candidates.py` + `GET /api/versions/{id}/mark-candidates`. Simula cada propriedade das peças como se fosse a marca: peças com valor, nº de marcas, marcas e peças **inconsistentes** (dimensões diferentes na mesma marca, mesma regra do relatório de validação), exemplos.
- Sinais ruins, que vão para o fim: quase um valor por peça (≥ 90%: GUID, id), mesmo valor em todas e "parece medida" (número + unidade: volume, comprimento). Dimensões e propriedades de categoria não são candidatas. A regra atual sempre aparece. `dimensions_checked=false` quando o modelo não tem as dimensões configuradas (ex.: o IFC da Cassol); a tela avisa que a inconsistência não foi conferida.
- Só lê `elements.props` do banco (nenhuma chamada ao APS). Nos modelos reais leva de 60 a 370 ms (359 peças).
- Tela: nova aba **"Identificação das peças"** na obra (`/obras/:id/identificacao`): lista de prioridade (subir, descer, remover, adicionar), categoria opcional, tabela de candidatos com "Usar como principal", "Salvar regra", "Voltar ao padrão" e o aviso de reprocessamento e órfãs.

### Conferido nos modelos reais (só leitura; a regra das obras reais não foi alterada)
- ORC v2 / R02 (Revit): "Marca" (em uso) tem 14 peças e 3 marcas, nenhuma inconsistente. As alternativas por tipo ("Marca de tipo", "Nome do tipo") cobrem as 359 peças, mas 319 delas ficam em marcas inconsistentes: o modelo de orçamento realmente não tem um identificador por peça. Na primeira versão do assistente, IfcGUID, Volume e Comprimento do corte apareciam no topo; foi isso que motivou os sinais "quase único" e "parece medida".
- IFC: sem dimensões configuradas (`SEÇÃO-*` são nomes do Revit), a coluna Inconsistentes não é conferida. Para conferir, acrescentar em `DIMENSION_PROPERTY_NAMES` os nomes de dimensão do IFC exportado.

### Verificação
- ruff, ruff format, mypy strict OK; backend **480/480** (`REQUIRE_DB=1`; 11 testes novos em `tests/test_mark_rule.py` + rotas na matriz de papéis); ESLint, tsc OK; frontend **116/116** (4 novos em `Identification.test.tsx`); `make e2e` 26 passaram + 6 pulados. Migração `0010` aplicada no banco de dev.

### Falta
- **Montagens** (item "o que vira peça": o consolo como membro do pilar, uma instância de montagem = uma peça): depende de ver no SVF2 do Docs como montagens e vínculos aparecem no .rvt, .nwd e .ifc da obra nova. Aguarda o ACC voltar.
- ~~Itens 3 e 4~~: feitos (abaixo).

### 3 · Identificadores divergentes — pronto (2026-11-13)
- Relatório de validação (`mark_validation.divergent_pieces`): com mais de um parâmetro na regra, lista as peças em que eles têm valores **diferentes** (ex.: Nome da montagem PP012 × Marca P12). Vale o primeiro; os outros são apelidos. Novo `totals.divergent_pieces` + lista `divergent`. Relatórios antigos não têm o campo (a tela trata).
- Busca: os valores de todos os parâmetros da regra entram no `search_text`, então a peça é encontrada pela Marca e pelo Nome da montagem.
- Tela (aba Versões > Validação): o contador soma "peças com identificadores divergentes" e aparece a tabela "Identificadores divergentes".

### 4 · Migração assistida ao trocar a regra — pronto (2026-11-13)
- Antes de reprocessar, o app guarda uma fotografia **peça (externalId) → marca antiga** da versão. Depois, para cada marca antiga com valores que sumiu:
  - **todas as peças foram para UMA marca nova**, o destino não tem outro valor e todos os parâmetros se aplicam a ele → os valores vão juntos. É a mesma religação da tela de órfãs (`review.relink`, refatorado em `plan_relink` + `relink` com `actor` opcional): órfã `relinked`, auditoria `mark_value` com `source: mark_rule` e autoria de quem trocou a regra (o id vai no job);
  - senão (peças divididas, sem marca, destino com outro valor ou parâmetro que não se aplica) → **órfã aberta**, com o motivo gravado na auditoria do processamento (`rule_orphans`). Nada é apagado: a marca antiga mantém os valores.
- Testes: `test_rule_change_moves_values_when_pieces_go_to_one_new_mark` (PP001 → P1 leva o valor; PP002 → P1 com outro valor fica órfã; PP003 intocada), divergência no relatório e busca pelo apelido.

### Montagens (IFC e NWD da obra 9480) — análise feita; implementação aguardando aprovação
- Relatório completo em `docs/montagens.md` (só GETs).
- No IFC a montagem é um nó `IfcBuildingElementProxy` com `ObjectType = "Montagem <categoria>:<nome>"` e os membros como filhos. No NWD não há nó de montagem: os membros carregam `Nome da montagem` dentro de cada vínculo, e o "corpo" é a instância de Pilares estruturais ou Quadro estrutural.
- A extração atual não serve para nenhum dos dois: no IFC dá 0 marcas; no NWD, 265 "peças" que são vínculos e níveis. A proposta de regra está no relatório.
- **Divergência a confirmar:** pilares e vigas VP batem entre IFC e NWD, mas lajes (51 nomes) e vigas VA (39 nomes) não.

### Montagens — implementado (2026-11-13, tarde)
Respostas do usuário: IFC e NWD vieram do mesmo arquivo; o corpo da peça é Pilares estruturais ou Quadro estrutural; escadas são Conexões estruturais; consolos fazem parte das montagens. Detalhes e números em `docs/montagens.md`.
- **IFC:** a montagem (`IfcBuildingElementProxy`, `ObjectType = "Montagem <cat>:<nome>"`) é a peça, com `Montagem > Nome da montagem` e a categoria de nomenclatura sintéticas. `IfcGroup` não é peça.
- **NWD/.rvt:** modo montagens por obra (`obras.piece_category_names`; aba Identificação: "Modelo com montagens"), em `app/services/assemblies.py`. A peça é o corpo; num vínculo com uma montagem só, a peça é o nó do vínculo; montagem sem corpo (escada) é 1 peça.
- **Clique em qualquer parte:** `elements.member_dbids` (migração 0011, GIN). `get_element` cai no membro e `/marks` devolve `member_dbids` para o índice do 3D.
- **Real:** obras 12 (IFC) e 13 (NWD) cadastradas no banco de dev com a regra `Nome da montagem`.
  - IFC: 1.930 peças, 316 marcas, 399 sem marca (elementos soltos).
  - NWD: 1.580 peças, 358 marcas, 1 sem marca.
  - PP312 = 1 peça nos dois. Clique num membro → peça pela API nos dois.
- **Viewer real:** IFC abre em ~5 s e o clique num membro seleciona a marca. NWD abre em ~4 a 6 s, mas **o clique não seleciona**: os Ambientes do Revit ficam na frente, e mesmo escondendo-os o Viewer devolve seleção vazia. Pendente.
- Teste E2E do Viewer real: em vez de uma grade de cliques às cegas, pergunta ao Viewer (`clientToWorld`) onde há peça ou membro conhecido e clica ali. ORC e IFC passam.

### IFC como formato da obra (2026-11-13, fim do dia)
- Decisão do usuário: **ignorar o NWD; usar o IFC**. A obra 13 (NWD) foi desativada.
- IFC: o corpo da montagem (membro de maior volume) empresta as propriedades à peça (`Corpo · ...`).
- Dimensões padrão: `NetVolume` no lugar de `Length/Width/Height`, porque o IFC troca os eixos em peças idênticas e isso dava falsos alertas.
- `Nome=valor` aceita unidade com expoente (`m^3`, `m²`).
- Obra 12 reprocessada: 0 inconsistentes; busca por seção ok; Viewer real 3/3 (desktop ~6 s, tablet emulado ~11 s).
- Verificação: ruff, ruff format, mypy OK; backend **492/492**; ESLint, tsc OK; frontend **119/119**; `make e2e` 26 + 6 pulados; E2E real na obra 12: 3 passaram.

### Verificação (montagens)
- ruff, ruff format, mypy strict OK; backend **491/491** (8 novos em `tests/test_assemblies.py` + modo montagens na API da regra); ESLint, tsc OK; frontend **119/119**; `make e2e` 26 passaram + 6 pulados. Migração `0011` aplicada no banco de dev.

### Verificação (2026-11-13, itens 3 e 4)
- ruff, ruff format, mypy strict OK; backend **483/483**; ESLint, tsc OK; frontend **117/117**; `make e2e` 26 passaram + 6 pulados.

## Fase 6 · Parâmetros da fábrica

### 6.1 · Catálogo de parâmetros — pronto
- `GET /api/param-defs` (todos os papéis; `?obra_id=` = globais + os da obra; `?include_inactive=true` inclui excluídos), `POST`, `PATCH /{id}`, `DELETE /{id}` (**só fábrica e admin**; projetos e leitura → 403). Serviço em `app/services/param_defs.py`; tudo passa por `audit.record` com o usuário.
- Regras (mensagens em português): nome obrigatório (espaços normalizados, até 200) e **único sem diferenciar maiúsculas** entre os ativos — global não repete nenhum ativo; o de obra não repete um global nem outro da mesma obra (obras diferentes podem repetir) → 409; tipo `text|number|list|date|bool`; unidade só em `number`; opções só em `list` (mínimo 2, sem repetidas sem diferenciar maiúsculas); categorias sem repetidas, vazias = todas; escopo `obra` exige obra existente.
- Com valores (preenchidos: não nulos e não vazios): **o tipo não muda** (409) e **opções em uso não saem** (409 com a lista). Decisão minha, pelo mesmo motivo: **escopo/obra também não mudam** com valores (senão haveria valores em marcas fora do escopo).
- **Excluir é lógico** (`active=false`): os valores continuam em `param_values` e a auditoria da exclusão guarda a lista `{mark_id, value}`. O nome pode ser recriado depois. Editar/excluir um excluído → 404. A busca "sem <parâmetro>" ignora excluídos.
- Migração `0007`: índices únicos por `lower(name)`, só entre ativos.
- Resposta traz `values_count` (marcas com valor), `options_in_use` e `created_by_name`.
- Frontend (`features/params/`, `components/Modal.tsx`): janela "Novo parâmetro / Editar parâmetro" como no mockup (unidade e opções conforme o tipo; categorias da versão, nenhuma marcada = todas; escopo global ou "somente esta obra"; obrigatório; tipo e escopo travados com aviso quando há valores; opções em uso avisadas; erros do servidor na janela) e janela "Catálogo" (lista com tipo, unidade, opções, categorias, escopo, marcas com valor e autor; Editar; Excluir com confirmação lembrando que os valores ficam na auditoria). "+ Novo parâmetro" na barra lateral (seção "Parâmetros da fábrica", com "Catálogo") e no painel da marca (já com a categoria da marca marcada). Projetos/leitura veem o catálogo só para leitura.
- O painel da marca lista os parâmetros que se aplicam à categoria dela (valores na 6.2).
- Testes: `tests/test_param_defs.py` (27: criação e auditoria, 403 por papel, cada validação, tipos, categorias, escopo, nome único em todos os casos, renomear, recriar excluído, tipo travado com valores, valores vazios não travam, opções em uso, escopo travado, troca para lista, auditoria da edição, exclusão lógica com valores na auditoria, listagem por obra); Vitest (criar pela barra lateral, número/escopo/erros, catálogo editar/excluir com confirmação, projetos só leitura, painel com parâmetros aplicáveis e categoria pré-marcada).

### Verificação (2026-11-11, Docker)
- `make lint` OK; backend 260/260 (`REQUIRE_DB=1`), frontend 63/63, `make e2e` 11 passaram + 1 pulado; `npm run build` OK. Migração `0007` aplicada no banco de dev.

### 6.2 · Valores por marca — pronto
- `GET /api/obras/{id}/marks/{mark_id}/values` (todos os papéis): só os parâmetros **ativos que se aplicam** à marca (escopo global ou desta obra; categoria compatível), em ordem alfabética, com valor, `row_version`, quem/quando alterou e `last_change_by/at`. Marca de outra obra → 404.
- `PUT .../values` (**só fábrica e admin**): `{changes: [{def_id, value, row_version}]}` só com os campos alterados; **tudo ou nada**. Normalização por tipo (`app/services/mark_values.py`): número aceita vírgula decimal (`"1,5"` → 1.5); lista só aceita as opções (sem diferenciar maiúsculas; grava a forma do catálogo); data ISO `AAAA-MM-DD`; sim/não booleano; texto com espaços normalizados (até 1000); vazio/nulo apaga (a linha fica com valor nulo). Parâmetro que não se aplica ou repetido → 422.
- **Controle otimista:** o cliente manda a `row_version` que leu (nula se não havia valor). Se não bate → **409 `stale`** com `changed_by_name`, `changed_at` e `conflict_def_ids`, sem gravar nada; o `version_id_col` do SQLAlchemy cobre a corrida entre a checagem e o UPDATE. Os erros de domínio agora podem levar campos extras no corpo.
- **Auditoria por campo:** cada campo alterado vira um registro (`entity="mark_value"`, `entity_id`=marca, ação `set`/`update`/`clear`, antes/depois com marca, parâmetro e valor), um `batch_id` por salvamento; campos sem mudança não geram registro nem sobem a versão.
- `GET .../history`: alterações da marca, mais recentes primeiro, com o nome do usuário.
- Frontend (`features/params/MarkValuesSection.tsx`): no painel, com UMA marca selecionada, "Parâmetros da fábrica" mostra só os que se aplicam, rótulo com unidade e `*` nos obrigatórios, valores formatados (número com vírgula, data dd/mm/aaaa, Sim/Não), "Última alteração: nome · data" e "Histórico". **Editar → Salvar/Cancelar** (Esc cancela), um campo por tipo; envia só o que mudou, com a versão lida. Em 409: "Fulano alterou esta marca há X min" com **Recarregar**; 422 aparece no formulário. Projetos e leitura veem sem "Editar". Peça sem Marca: aviso; várias marcas: edição em lote (6.3).
- Ao salvar, o catálogo (nº de marcas com valor) e a busca (valores entram no texto livre e no "sem <parâmetro>") são atualizados.
- E2E: o seed da obra E2E-01 cria o parâmetro "Tipo de forma" (lista F-11/F-12/F-13, escopo da obra) e zera os valores a cada execução (a auditoria fica).
- Testes: `tests/test_mark_values.py` (19: parâmetros aplicáveis, normalização de cada tipo, 9 casos de validação com tudo-ou-nada, repetido, 409 com quem/quando e nada gravado, versão sobe, sem mudança não grava, apagar, auditoria por campo e por lote, histórico, papéis, marca de outra obra); Vitest (exibição, salvar só o que mudou, Esc/Cancelar, 409 com Recarregar, 422, histórico, projetos sem editar, várias marcas/sem Marca); Playwright: **salvar F-12 pela peça 10 do PP001 aparece na peça 11 (mesma marca), não aparece na V-01 e persiste após recarregar**, com a entrada no histórico (tablet e desktop).

### Verificação (2026-11-11, Docker)
- `make lint` OK; backend 279/279 (`REQUIRE_DB=1`), frontend 71/71, `make e2e` 13 passaram + 1 pulado; `npm run build` OK.

### 6.3 · Edição em lote — pronto
- `POST /api/obras/{id}/marks/batch-preview` (todos os papéis) e `/batch-apply` (**só fábrica e admin**), corpo `{mark_ids, changes: {def_id: valor}, mode: overwrite | only_empty}` (`app/services/mark_batch.py`). Todas as marcas precisam ser da obra (senão 404); até 5.000 por lote.
  - **Preview** sem mudanças devolve o resumo dos campos da seleção (a quantas marcas cada parâmetro se aplica, quantas preenchidas, valor comum ou **misto**). Com mudanças, devolve **quantas marcas serão alteradas** (no modo pedido e nos dois modos) e **quantas já têm outro valor**, também por campo.
  - **Apply** grava tudo **numa transação**, com a mesma normalização da 6.2, **só nas marcas em que o parâmetro se aplica** (escopo e categoria). Seleção com categorias misturadas é aceita. Parâmetro que não vale para nenhuma marca selecionada → 422.
    - `only_empty` grava só onde o campo está vazio; apagar não faz nada nesse modo. `overwrite` grava em todas e pode apagar.
    - Auditoria: uma linha por (marca, campo), com o mesmo `batch_id`, ações `set`/`update`/`clear` e `"source": "batch"`. O histórico da marca mostra essas linhas.
- `POST /api/batches/{batch_id}/undo` restaura o valor anterior de cada linha do lote, tudo ou nada, e audita o desfazer em outro lote (`"undo_of"`). Recusas:
  - 409 se o lote já foi desfeito;
  - 409 com `changed_since` se algum campo mudou depois do lote, para não apagar trabalho de outra pessoa;
  - 403 se quem pede não é o autor do lote nem admin;
  - 422 se o lote já é um desfazer.
- Frontend (`features/params/BatchValuesSection.tsx`, `UndoToast.tsx`). Com **2 ou mais marcas** selecionadas, o painel mostra:
  - "**N marcas selecionadas**" e o aviso "**A seleção mistura categorias (…)**";
  - os valores comuns ou "(valores mistos)", com "X de N" quando o parâmetro não vale para todas.
  - **Editar em lote**:
    - Campos mistos começam em **"(valores mistos: manter)"**. Só os campos alterados vão no lote.
    - Ao clicar em **Aplicar**, o preview mostra "N marcas serão alteradas. M já têm outro valor." e os botões **Sobrescrever todas** / **Só nas vazias** / Cancelar.
    - Depois de gravar, aparece o aviso "Valores aplicados a N marcas." com **Desfazer** por 10 s.
  - Os campos de edição foram extraídos para `fieldInput.tsx`/`fieldDraft.ts`, usados pela marca única e pelo lote.
- E2E: o global-setup passa `E2E_PARAM_DEF_ID` para os testes.
- Testes:
  - `tests/test_mark_batch.py` (9):
    - **aplicar a 10 marcas e desfazer volta ao estado anterior** (20 campos, auditoria do lote e do desfazer, não desfaz duas vezes);
    - **only_empty não altera marcas preenchidas**;
    - resumo com misto/comum; contagens do preview; categorias misturadas;
    - apagar em cada modo; desfazer recusado após alteração posterior;
    - papéis e autor do lote; validações.
  - Vitest (6): resumo e misto; aviso de categorias; manter/confirmação/Só nas vazias/Desfazer; Sobrescrever todas; projetos sem editar; o aviso some após 10 s.
  - Playwright (tablet e desktop): seleção múltipla de PP002 (F-11) + V-01 (vazia) → Só nas vazias → só a V-01 recebe F-13 → Desfazer volta ao estado anterior.

### Verificação (2026-11-11, Docker)
- `make lint` OK (ruff, mypy, eslint, tsc); backend 299/299 (`REQUIRE_DB=1`), frontend 77/77, `make e2e` 15 passaram + 1 pulado; `npm run build` OK. Sem migração (usa `param_values` e `audit_log` existentes).

### 6.4 · Status, cores e progresso — pronto
- **Status por marca, calculado na hora** (`app/services/mark_status.py`). Segue a regra do mockup:
  - a base são os parâmetros **obrigatórios** que se aplicam à marca (escopo + categoria); se não há obrigatórios, qualquer parâmetro aplicável conta;
  - nenhum preenchido (ou nenhum parâmetro) → `pending`; todos → `complete`; o resto → `partial`;
  - `review` fica sempre falso até a Fase 7;
  - só entram as marcas com peças na versão; órfãs e peças sem Marca ficam de fora.
- Endpoints (todos os papéis):
  - `GET /api/versions/{id}/marks/status`: `{items: [{mark_id, status}], counts: [{status, marks, pieces}]}`, com os quatro status, mesmo zerados;
  - `GET /api/versions/{id}/progress`: por parâmetro obrigatório, as marcas e peças preenchidas e as marcas e peças em que ele se aplica, mais os totais da versão;
  - `GET /api/versions/{id}/params/{def_id}/values`: valor de um parâmetro em cada marca em que se aplica, para "Colorir por parâmetro". Parâmetro inativo ou de outra obra → 404.
- **Atalhos Pendentes e Parciais** filtram de verdade e combinam com os outros filtros. "A revisar" mostra o aviso da Fase 7.
- Frontend:
  - **"Colorir por" Status | Parâmetro (com seletor) | Categoria** (`ColorPanel`, `coloring.ts`, `useColoring.ts`). As cores vão sempre pelo `ViewerAdapter.setColors`. O padrão é Status.
  - Cores do mockup: pendente `#B9BEC6`, parcial `#E3B341`, completa `#33A06F`, revisar `#E8743B`.
  - A **seleção fica azul `#2F6FEB`**: o `ApsViewerAdapter` chama `setSelectionColor` ao iniciar.
  - Cores por parâmetro: lista pela posição da opção; outros tipos por hash do valor; "Sem valor" em cinza claro, sempre por último. As marcas em que o parâmetro não se aplica ficam sem cor, com nota na legenda.
  - Cores por categoria: paleta pela ordem alfabética.
  - **Legenda sobre o 3D** com o nº de marcas de cada linha. Clicar numa linha **seleciona as marcas** dela, e a seleção pode seguir direto para a edição em lote.
  - **Rodapé com a barra de progresso** de cada obrigatório: "X/Y marcas · A/B peças (P%)", mais os totais da versão. Sem obrigatórios, aparece a mensagem do mockup.
  - Salvar valores (marca ou lote), desfazer e mexer no catálogo atualizam busca, status, cores, progresso e valores por parâmetro (`features/params/invalidate.ts`).
- Viewer falso do E2E: `setThemingColor` grava `data-color` em cada peça, então o teste confere a cor aplicada.
- Testes:
  - `tests/test_mark_status.py` (8): regras puras, contagens, progresso, valores por parâmetro, atalhos.
  - Desempenho com 20 mil peças e 2 mil marcas (`test_search_perf.py`): status em **36 ms**, progresso em **29 ms**, atalho Pendentes em **75 ms**.
  - Vitest: `coloring.test.ts` (4); na tela, 6 testes: cores padrão via `setColors`, legenda seleciona, Categoria/Parâmetro, rodapé, sem obrigatórios, salvar atualiza status/progresso. Os atalhos Pendentes/Parciais/A revisar foram ajustados.

### Aceite da Fase 6 — ok (2026-11-11)
- **API** (`tests/test_phase6_acceptance.py`, 12 marcas de pilar com 2 peças cada):
  - a fábrica cria "Tipo de forma" (obrigatório) → 12 pendentes, 0/12;
  - preenche 1 marca → 1 completa, 1/12 marcas, 2/24 peças;
  - lote de 10 → 11 completas, 11/12, e o atalho Pendentes mostra só o PP012;
  - desfaz → 1 completa, 1/12;
  - edição simultânea: o segundo salvamento leva **409 `stale`** com o nome de quem salvou antes, e o valor dele fica.
- **Tela** (Playwright, tablet e desktop, obra E2E-01, 3 marcas):
  - começa tudo cinza, 0/3;
  - salvar o PP001 pinta as duas peças dele de verde, Completa vira 1 e o progresso vai a 33%;
  - Pendentes lista 2;
  - a legenda "Pendente: 2" seleciona as duas marcas, o lote aplica e tudo fica verde (100%);
  - Desfazer volta ao cinza e a 33%;
  - Colorir por Parâmetro e Categoria funcionam;
  - edição simultânea (outro usuário salva pela API durante a edição) mostra o aviso "alterou esta marca" e, com **Recarregar**, o valor do outro usuário.
- **Viewer real** (`E2E_REAL_VIEWER=1`, obra 30.327-01 ORC do Docs): carrega com as cores ligadas em 5,4 s no desktop e 10,2 s no tablet emulado, e o clique seleciona a marca.

### Verificação (2026-11-11, Docker)
- `make lint` OK (ruff, mypy, eslint, tsc).
- Backend 309/309 (`REQUIRE_DB=1`); frontend 87/87.
- `make e2e`: 17 passaram + 1 pulado; modo real 2/2.
- `npm run build` OK. Sem migração.

### Falta na Fase 6
- Nada. **Decisão (2026-11-11): sem catálogo inicial.** O catálogo começa vazio e a fábrica cadastra os parâmetros pela tela (Catálogo → + Novo parâmetro) quando começar a usar o app.

## Filtros (estilo Dalux) · passo 1: motor no backend (2026-11-13)
Plano: `docs/filtros/plano.md`. O pedido trouxe definições próprias, que prevalecem sobre o plano: a tabela `piece_props` e o formato `mode/logic/rules`. Sem mudanças no frontend.

- **`piece_props` (migração 0013):** uma linha por (peça, campo) com valor. Texto, número (vírgula decimal e unidade aceitas: "40,0 cm" → 40) e data (ISO ou AAAAMMDD), cada um com índice `(version_id, source, key, value_*)`.
  - **model:** propriedades do modelo, chave `"<grupo>/<nome>"`.
  - **system:** `category`, `level`, `mark` (Nome da montagem), `name`, `first_version` e `status`.
  - **factory:** id do parâmetro; o valor da marca vai para cada peça dela, em todas as versões da obra.
- **Tipo dos campos do modelo:** inferido no processamento. Data se todos os valores forem datas; número se todos converterem; senão texto. Fica em `version_property_names.value_type`, com `pieces` e `distinct_values`.
  - Ordem escolhida: **data antes de número**, porque "20261110" também converte em número.
- **Sincronização** (`piece_props.sync_factory`, fábrica + status, todas as versões da obra), chamada em:
  - salvar valores de uma marca;
  - aplicar lote e desfazer lote;
  - "Manter valores" e religar órfã;
  - criar, editar, excluir, incluir ou retirar parâmetro;
  - fim do `process_version`, porque a reconciliação muda o "a revisar".
- **Montagem rápida:** gravação por `COPY` (asyncpg, na mesma transação): 630 mil valores em ~25–38 s, contra 175 s com INSERT. O IFC real da 9480 tem 83 mil valores. Depois de montar, `ANALYZE piece_props`: sem isso a 1ª consulta na versão nova levou 809 ms, contra 24 ms com estatísticas.
- **Backfill:** `python -m app.cli piece-props backfill (--version ID | --all)`. Já rodado no banco de dev, 11 versões.
- **Filtro (`app/services/filters.py`):** Pydantic (`extra=forbid`, até 50 regras). Cada regra vira `elements.id IN (subconsulta em piece_props)` com parâmetros ligados; nenhum texto do usuário entra no SQL. `and`/`or`; sem regras = todas as peças.
  - **Operadores:**
    - texto: eq, ne, contains, not_contains, starts_with, empty, not_empty, in (sem acento e sem maiúsculas);
    - número: eq, ne, gt, gte, lt, lte, between (aceita a ordem invertida), empty, not_empty;
    - data: on, before, after, between, this_month, last_month, last_n_days (N dias contando hoje), empty, not_empty.
  - **Negativos e "vazio" incluem as peças sem valor.**
  - "Hoje" no fuso `DISPLAY_TIMEZONE`.
- **API:**
  - `GET /api/versions/{id}/fields`: source, key, nome, grupo, tipo, distintos, peças. Só os parâmetros da fábrica que valem na obra.
  - `GET /api/versions/{id}/fields/{source}/{key}/values?q=&limit=`: a origem vai na rota porque a chave do modelo contém "/".
  - `POST /api/versions/{id}/filter/evaluate`: mode, logic, totais, peças `{dbid, mark_id}`, `dbids` (peças + todos os membros) e grupos por Nome da montagem `{mark_id, code, category, matched, total}`, com as peças sem marca no fim.
  - Todos os papéis podem ler: o app ainda não tem permissão por obra (Fase 11). A resposta da avaliação é montada direto em JSON: revalidar dezenas de milhares de itens custava mais que a consulta.
- **Desempenho** (20 mil peças / 630 mil valores; `tests/test_filters_perf.py`): avaliações entre 160 e 540 ms; `fields` ~100 ms; `values` ~40 ms. IFC real 9480: 21–29 ms.
- **Testes:** `tests/test_filters.py` (64): inferência; campos e valores; cada operador × tipo; datas com hoje fixo, inclusive a virada de ano; e/ou; 422 (campo inexistente nas 3 origens, operador × tipo, valores inválidos, formato inválido, parâmetro fora da obra); injeção de SQL na chave, no valor, no `in` e no `q`; 401/404/409; sincronização (salvar, lote, desfazer, retirar); backfill; processamento real. Mais a matriz de papéis.
- **Verificação:** ruff, ruff format, mypy strict OK; backend **564/564**; frontend 120/120 e E2E 26 + 6 pulados, sem mudanças.

## Filtros (estilo Dalux) · passo 2: filtros salvos e cores no backend (2026-11-13)
> **F3 feito em 2026-11-16** (seção seguinte). Decisões do F2 **confirmadas pelo usuário em 2026-11-16**, mantidas como implementadas: cores por hash estável (paleta de 20, valores podem repetir cor); nome único por escopo valendo para todas as obras; limite de 500 valores no `distinct`.

Sem mudanças no frontend. A busca continua aceitando `shortcut=` (a tela atual não mudou).

- **Migração 0014:** `saved_filters` e `color_schemes` (nome, `scope` personal|shared, dono, `obra_id` nulo = todas as obras, autoria). Nome único sem diferenciar maiúsculas **por escopo**: entre os compartilhados, e entre os pessoais de cada dono.
- **Permissões** (`app/services/saved_filters.py`):
  - pessoal: só o dono vê, edita e exclui; nem o admin vê os dos outros (404);
  - compartilhado: todos veem; criar, editar e excluir exige um papel de **`SHARED_FILTER_ROLES`** (novo, padrão `fabrica,admin`); passar de pessoal para compartilhado também;
  - a resposta traz `editable` para o usuário atual.
- **Atalhos viraram filtros de sistema** (`system_key`: `pending`, `partial`, `review`, `new`, `orphans`). Seed na migração, compartilhados e **não editáveis** (403, inclusive para o admin). A busca lê a definição do banco e passa pelo motor; saiu de `search.py` a lógica própria de status, "novas" e órfãs.
  - Para dar **o mesmo resultado de hoje**, o motor ganhou campos de sistema **calculados na hora**: o status de produção (agora sempre por `mark_status`, sem depender da sincronização de `piece_props`), **"Nova na versão"** e **"Órfã"** (tipo novo `bool`, operadores "é igual a" e "é diferente de" true/false).
  - Órfãs não têm peças na versão: só aparecem quando o filtro usa o campo "Órfã", como marcas com 0 peças. Nelas só valem Nome da montagem e categoria; os outros campos contam como vazios. Na busca, só o texto livre as filtra, como antes.
  - A avaliação devolve `notes` (ex.: "Primeira versão processada...").
- **Esquemas de cores:** `rules` = lista ordenada `{filter: id de filtro salvo | definição inline, color: "#RRGGBB", label}`.
  - Um esquema compartilhado só usa filtros compartilhados; um pessoal usa os compartilhados e os do dono. Um filtro de uma obra só entra em esquema da mesma obra (422).
  - Um filtro usado num esquema não pode ser excluído, nem passar a ser pessoal ou de outra obra (409).
- **API:**
  - `GET/POST /api/saved-filters`, `GET/PATCH/DELETE /api/saved-filters/{id}` (`?obra_id=` lista os que valem na obra; os de sistema vêm primeiro);
  - `GET/POST /api/color-schemes`, `GET/PATCH/DELETE /api/color-schemes/{id}`;
  - `POST /api/versions/{id}/color-scheme/evaluate` com `{scheme_id}` ou `{rules}` (prévia sem salvar). Devolve `colors` (dbId → cor, peças e membros), contagem por regra (`matched`: batem no filtro; `pieces`: ficaram com a cor, porque **a primeira regra que bate vence**), totais e avisos. Todas as regras saem numa consulta só;
  - `POST /api/versions/{id}/colorize` com `{field, mode}`:
    - `distinct`: cor **estável**, um hash CRC32 do valor (sem maiúsculas nem acentos) numa paleta de 20 cores. O mesmo valor tem a mesma cor em qualquer versão e obra; em troca, dois valores podem cair na mesma cor. "Sem valor" em cinza `#9AA0A6`; o status usa as cores do app. Até 500 valores distintos (422 acima disso);
    - `range` (números e datas): 5 faixas de mesma largura com os limites (datas em dias inteiros, sem sobrepor; 1 faixa se todos os valores forem iguais), mais "Sem valor".
- **Auditoria:** criar, editar e excluir **compartilhados** (`saved_filter` e `color_scheme`, com antes e depois). Os pessoais não vão para a auditoria.
- **Testes:**
  - `tests/test_saved_filters.py` (17): seed igual ao código; sistema não editável; **atalho = filtro de sistema** nas 5 situações (mesmas marcas e peças), órfãs com texto livre; nota da 1ª versão; campos `bool`; permissões por papel e configuração de `SHARED_FILTER_ROLES`; pessoais invisíveis para outros; nomes por escopo; validação; lista por obra; auditoria;
  - `tests/test_colors.py` (13): prioridade das regras (e troca de ordem), membros, filtro salvo no esquema, 409 ao excluir filtro em uso, validação das regras e da obra, permissões e auditoria dos esquemas; cor estável fixa por valor (inclusive em outra versão), cinza do sem valor, cores do status, faixas de número e data, valor único, erros;
  - `test_filters_perf.py` também mede as cores com 20 mil peças: esquema de 4 regras 228 ms (era 832 ms com uma consulta por regra), colorir 220–350 ms;
  - a matriz de papéis ganhou as 12 rotas novas (também em `docs/operacao.md`).
- **Verificação:** `make lint` OK (ruff, mypy strict, ESLint, tsc); backend **606/606** (`REQUIRE_DB=1`); frontend **120/120**; `make e2e` 26 passaram + 6 pulados. Migração 0014 aplicada no banco de dev.

## Filtros (estilo Dalux) · passo 3: interface de filtros (2026-11-16)
Pedido: barra inferior, popover Filtro, "Selecionar parâmetro", "Editar filtro", aplicação no 3D, lista agrupada, filtro na URL e E2E.

**Decisões do usuário (2026-11-16):**
- **Modo por regra, estilo Dalux.** Visíveis = regras Isolar (E/OU) menos as que batem em QUALQUER regra Ocultar. Resultado = visíveis que batem nas regras Destacar (E/OU) e no texto. No 3D, o resultado fica normal, o resto visível esmaece e o que não é visível some. Regras novas começam em Isolar.
- **Colorir agora, Cores depois.** O "Colorir por" (Status, Parâmetro, Categoria) foi para o popover "Colorir ▾". "Editar cores" (janela Cores) fica para o passo de coloração e ainda não aparece.
- **Busca, atalhos e Categoria/Nível só no popover.** Saíram da coluna esquerda. Os atalhos são os filtros de sistema em "Filtros salvos".

**Backend (só o necessário para a tela):**
- `filters.py`: cada regra tem um `mode` opcional (sem modo, vale o do filtro; regras antigas continuam iguais). A definição ganhou `q` ("Pesquisar por objetos", mesma regra da busca: código da marca, categoria, texto da peça, valor da fábrica; peças sem marca também entram). `q` e `mode` vazios não são gravados.
- `/filter/evaluate` devolve também `view` (`isolate` | `highlight`) e `hidden_dbids` (peças fora das visíveis quando há esmaecidas).
- **Mudança de semântica:** um filtro só com Ocultar agora devolve as peças que FICAM (antes, as que batiam). Nenhum filtro salvo usava Ocultar.
- `POST /api/obras/{id}/export.xlsx` com `{version_id, filter}`: o Excel traz o resultado do filtro da tela. A aba Sobre descreve as regras ("Categoria é igual a Pilar", `texto "PP"`). O `GET` antigo continua.
- `/api/me` diz `can_share_filters` (papel em `SHARED_FILTER_ROLES`).
- `ViewerAdapter.hide(ids)`: no APS (`viewer.hide`) e no Viewer falso do E2E.

**Frontend (`features/filtro/`):**
- `useActiveFilter`: estado único na URL (`?f=`, JSON com `q`, `l`, `r` e `s` = filtro salvo), debounce de 250 ms e indicador "filtrando…" (na barra e na lista). Trocar de versão mantém o filtro. Um link estragado vira "sem filtro".
- `ViewerToolbar`: barra inferior com Filtro ▾, Ampliar tudo (era o "Enquadrar tudo" do topo) e Colorir ▾; à direita, Remover filtros e Remover coloração (só com algo ativo). Medida não aparece: o adapter ainda não tem a ferramenta. No topo ficaram as ferramentas da seleção (Enquadrar seleção, Isolar, Limpar seleção, Seleção múltipla).
- `FilterPopover`: abre para cima e tem duas partes.
  - **Filtros salvos**, em Sistema, Compartilhados e Meus; o ativo fica marcado (e "alterado" quando muda).
  - **Filtro**: "Pesquisar por objetos" (Enter converte `sem <parâmetro>` e `Nome=valor` em regra), menus rápidos Categoria e Nível ("é um de"), etiquetas removíveis, "+ Adicionar filtro", "Avançado" e "Salvar ▾" (Salvar como novo, Atualizar o filtro e Compartilhar, conforme o papel).
- `FieldPicker` ("Selecionar parâmetro"): busca sem acento; grupos Fábrica, Montagem, Identificação, Dimensões e Outros; tipo e nº de valores. Depois de escolher, um passo com operador e valor: autocompletar para texto, calendário para data (começa em "no mês atual"), lista marcável para "é um de".
- `FilterEditorDialog` ("Editar filtro"): linhas [modo] [parâmetro] [operador] [valor] [×], sempre com a linha nova no fim, "Todas as regras (E)" / "Qualquer regra (OU)", Cancelar e Aplicar. As linhas incompletas são descartadas.
- `FilterResultList`: a lista à esquerda agrupa por Nome da montagem com "N de M peças". Peças sem marca vêm em "(sem marca)"; órfãs aparecem como "órfã".
- Saíram `SearchPanel`, `useMarkSearch` e `searchQuery` (o `typedRule` substitui o `parseQuery`). Também saíram as funções `searchMarks`/`filterQuery` do cliente; a rota `/marks/search` continua no backend e testada.
- A legenda de cores foi para a direita, para não disputar espaço com a barra.

**Testes:**
- Backend:
  - `test_filters.py`: modos por regra (Isolar menos Ocultar, Ocultar sempre OU, Destacar com ocultas, OU em Isolar), regra sem modo, texto livre, API com `q`/`view`/`hidden_dbids`, filtro salvo guarda `mode` e `q`, exportação filtrada com a aba Sobre, `/me`;
  - a matriz de papéis ganhou o `POST` da exportação.
- Vitest:
  - `filterModel.test.ts`: URL ida e volta, definição, regra completa, etiquetas, grupos, "alterado", atalhos de digitação, debounce;
  - bloco "Filtro (F3)" do `ModelPage.test.tsx`, com um motor falso: barra, pesquisa com debounce, filtro salvo, menu rápido, + Adicionar filtro (data no mês atual), Avançado com Ocultar e OU, Cancelar, salvar pessoal, compartilhar por papel, link com filtro, Selecionar todas, erro do motor;
  - cores, banner e exportação adaptados.
- Playwright (Viewer falso, tablet e desktop), "Filtros (F3)":
  1. aplicar um filtro salvo;
  2. regra "Data de expedição: no mês atual";
  3. salvar como pessoal e reabrir;
  4. Remover filtros volta tudo ao normal (e limpa a URL);
  5. link com filtro abre já filtrado noutro navegador.
- Os testes antigos de busca, atalhos e cores foram adaptados à barra e ao popover.
- Semente do E2E: parâmetro "Data de expedição" (data, opcional) na E2E-01, com PP001 = hoje e V-01 = há um ano; a semente também apaga os filtros salvos da obra a cada execução.

**Verificação (2026-11-16):**
- `make lint` OK (ruff, mypy strict, ESLint, tsc).
- Backend **614/614** (`REQUIRE_DB=1`).
- Frontend **136/136**.
- `make e2e` **36 passaram + 6 pulados** (Viewer real e toque).
- `npm run build` OK.

**Falta / pendente:**
- Aceite com o Viewer real (APS): `viewer.hide` depois de `isolate` com fantasma, e desempenho de `hidden_dbids` grandes no tablet.
- Filtro com resultado vazio em modo Isolar: o Viewer real mostra tudo com `isolate([])` (o falso também). Tratar no adapter no passo do visualizador.
- Peças sem marca: a linha "(sem marca)" seleciona todas as peças sem marca do resultado, mesmo quando há mais de uma categoria.
- Próximos passos do plano: janela Cores e coloração pelo backend (feito no passo 4); mini barra da peça, atalhos H/Espaço e Medida.

## Filtros (estilo Dalux) · passo 4: coloração (2026-11-16)
Pedido: popover Colorir com busca e "Cor por gama", legenda flutuante, janela Cores (esquemas), Remover coloração, filtro e coloração juntos, seleção azul por cima, e E2E.

**Backend:** cada item de `/colorize` e cada regra de `/color-scheme/evaluate` trazem `dbids`, as peças do item sem os membros. Clicar na legenda seleciona por eles. `test_colors.py` confere esses `dbids`.

**Frontend (`features/cores/`):**
- **Cores calculadas no backend.** Toda a coloração vem do backend, inclusive Status e Categoria (antes, Categoria e Parâmetro eram calculados na tela). Saíram `modelo/coloring.ts`, `useColoring.ts` e `ColorPanel.tsx`.
- **O que mudou na tela por causa disso:**
  - Categoria e Parâmetro usam as cores estáveis do F2;
  - peças sem marca entram em "Sem valor", em cinza;
  - a legenda conta peças, e o aria-label diz "N marcas · N peças".
- `useModelColoring`: a escolha é "por campo" (distinct ou range) ou "esquema". O padrão continua sendo Status.
- `ColorPopover` ("Colorir ▾"):
  - Status e Categoria fixos no topo;
  - a mesma lista de campos do "Selecionar parâmetro", sem sim/não e sem os campos calculados;
  - "Cor por gama" só ativa para número e data.
- `ColorLegend`: cor, valor e nº de peças. O Status aparece sempre nos 4 estados, em ordem fixa. Clicar num item seleciona as marcas das peças daquele valor (a seleção do app é por marca; peças sem marca vão sozinhas). Tem botão "Ocultar legenda" / "Mostrar legenda" e fica à direita.
- `ColorRulesDialog` ("Editar cores" → "Cores"):
  - seletor de esquemas salvos no topo;
  - tabela com cor (editável), filtro e nº de peças, numa prévia ao vivo do esquema;
  - Adicionar/Editar abre uma janela com "Filtro salvo" ou "Novo filtro" (nome + uma regra; vira filtro salvo pessoal, ou compartilhado se o papel permitir) e a cor;
  - Remover, Mover para cima e Mover para baixo (a ordem é a prioridade);
  - Cancelar e Salvar, como esquema pessoal ou compartilhado (este só para quem pode). Salvar aplica o esquema no modelo. Um esquema que o usuário não pode editar vira um esquema novo ao salvar.
- **Barra inferior:** Filtro ▾ · Ampliar tudo · Editar cores · Colorir ▾. "Remover coloração" volta às cores originais.
- **Filtro e coloração são independentes:** o filtro decide o que aparece, a coloração decide a cor.
- **Seleção azul por cima da coloração** (`ApsViewerAdapter`): as cores de tema do Viewer cobrem o destaque de seleção. Com coloração ativa, as peças selecionadas recebem `SELECTION_COLOR` por cima da cor; ao sair da seleção, voltam à cor da coloração (ou a alfa 0, sem cor). Sem coloração, vale o destaque normal do Viewer.
- `Modal`: com janela dentro de janela, o Esc fecha só a de cima.
- `invalidate.ts`: salvar valores também recarrega filtro, coloração e esquema. No F3 faltava recarregar o filtro.

**Testes:**
- Backend **614/614**.
- Vitest:
  - `coloringModel.test.ts` (status em ordem fixa, gama no título, legenda e aviso do esquema);
  - teste do adapter para a seleção azul por cima e a volta à cor;
  - bloco "Coloração, legenda e progresso" do `ModelPage.test.tsx`: status por padrão, legenda seleciona e oculta, popover com Categoria / busca / Tipo de forma / gama em data, Remover coloração, filtro + coloração juntos, Editar cores com 2 regras (prévia, prioridade, mover, remover, salvar e aplicar).
- Playwright, "Coloração (F4)":
  1. colorir por "Tipo de forma" e conferir a legenda (F-11: 1 marca · 2 peças; Sem valor: 2 marcas · 5 peças), clicar seleciona e a seleção fica azul por cima, ocultar legenda, Remover coloração;
  2. esquema com 2 regras ("Pendentes" de sistema + filtro novo "Térreo" criado na janela): a peça 20 (pendente e no térreo) fica com a cor da 1ª regra, Mover para cima inverte (contagens 4/2 → 3/3 e cores no 3D), salvar, aplicar e reabrir;
  3. cor por gama em "Data de expedição".
- Viewer falso do E2E:
  - mostra `data-base-color` (a cor da coloração sem o azul da seleção); os testes antigos conferem essa cor;
  - as peças ficam menores e longe da legenda.
- A semente apaga também os esquemas de cores da E2E-01.

**Verificação (2026-11-16):**
- `make lint` OK.
- Backend **614/614** (`REQUIRE_DB=1`).
- Frontend **138/138**.
- `make e2e` **42 passaram + 6 pulados**.
- `npm run build` OK.

**Falta / pendente:**
- Aceite no Viewer real: o azul de seleção por tema (`setThemingColor`) e o custo de repintar 20 mil peças ao trocar a coloração, no tablet.
- A coloração não vai para a URL (o filtro vai). Decidir se o link deve levar também a coloração.
- Coloração por campo com mais de 500 valores dá a mensagem do backend (422), sem "Outros".

## Nome "Cassol Elo", logotipo e painéis laterais (2026-11-16)
- **Nome do app: Cassol Elo.**
  - No cabeçalho entra o logotipo "ELO CASSOL", redesenhado em SVG (`components/Logo.tsx`) a partir da imagem enviada: os dois quadrados que se encaixam, mais o nome. Fica vetorial e com fundo transparente.
  - O cabeçalho passou a ser branco com um filete laranja, porque as cores da marca (laranja `#F2A31B`, grafite `#3C3C3C`) não aparecem sobre o azul-escuro anterior.
  - A aba do navegador mostra "Cassol Elo", com o ícone `public/favicon.svg`.
  - O backend também usa o nome novo: título da API, assunto e texto dos alertas, autor do Excel.
- **Painéis laterais.** Botões nas bordas do 3D (‹ ›) escondem e mostram a coluna esquerda (marcas e filtros) e a direita (peça). As colunas usam variáveis de largura (`--left`/`--right`) e posição fixa na grade.
  - A escolha fica no navegador (`localStorage`, `usePanels.ts`); sem armazenamento, vale só na visita.
  - Ao trocar, a tela dispara um `resize` para o Viewer redesenhar no tamanho novo.
- **Testes:** Vitest com cabeçalho, logotipo e link; painéis com aria-expanded, persistência e reabrir.
- **Verificação (2026-11-16):** `make lint` OK; backend 614/614; frontend 139/139; `make e2e` 42 passaram + 6 pulados.
- **Pendente:**
  - o logotipo usa as fontes do sistema (Arial Black). Se houver o arquivo vetorial oficial (SVG/AI/PDF), trocar pelo traçado original;
  - conferir no Viewer real se o redesenho acompanha a mudança de largura.

## Parâmetros: biblioteca por obra e exclusão visível (2026-11-13)
Pedido: excluir um parâmetro criado por engano, e incluir ou retirar parâmetros da biblioteca em obras específicas.
- O "Excluir" já existia, mas ficava escondido no Catálogo e dependia do `window.confirm`. Agora a confirmação é dentro do app.
- **Decisão do usuário:** um parâmetro da **biblioteca** (antes "global") **não vale para nenhuma obra até ser incluído nela**. Os "só desta obra" continuam como antes.
- **Migração `0012`:** tabela `obra_params`. Backfill: os globais ativos foram incluídos nas obras onde já tinham valores (no dev: "concretagem" nas obras 5 e 12; "teste" na 12).
- **Regra única `param_defs.in_obra(obra)`:** usada na lista, na busca ("sem <parâmetro>"), no status e progresso, nos valores da marca, na exportação e na religação de órfãs.
- **API:**
  - `POST`/`DELETE /api/obras/{id}/params/{def_id}` (Fábrica e Admin; auditoria `obra_param` include/exclude; retirar guarda os valores, que voltam ao incluir);
  - `GET /param-defs?obra_id&library=true` com `in_obra` e `obras_count`;
  - criar da biblioteca de dentro de uma obra já inclui nela (`include_in_obra_id`).
- **Tela (Catálogo):**
  - seções "Nesta obra" e "Biblioteca: não usados nesta obra";
  - botões Incluir nesta obra, Retirar desta obra, Excluir da biblioteca (sai de todas as obras) e Excluir (só desta obra), todos com confirmação dentro do app.
- **Verificação:** ruff, mypy OK; backend **497/497** (novos: incluir/retirar/valores preservados/papéis/criação já incluída; testes antigos ajustados com `include_params`); ESLint, tsc OK; frontend **120/120**; `make e2e` 26 + 6 pulados. Migração aplicada no banco de dev.
- **Falta:** atualizar o guia da fábrica (`docs/guia-parametros.html`) com biblioteca, incluir e retirar.

## Fase 7 · Reconciliação de versões

### 7.1 · Motor de reconciliação — pronto
- `app/services/reconcile.py`, só com funções **puras** (sem banco):
  - `build_snapshots(elements, config)` agrupa as peças por marca: código normalizado como na extração, mais a categoria. Lê **só** as propriedades de revisão, guardando os valores distintos entre as peças da marca. Peças sem Marca não formam marca.
  - `reconcile(prev, curr, config)` classifica cada marca em `unchanged | count_changed | changed | new | removed`, ordenadas por (código, categoria), com totais por classe e um diff campo a campo (`PropDiff(property, before, after)`). `summary()` gera o texto da nota, ex.: "Seção: 40x60 → 40x80"; uma propriedade que some ou aparece vira "—".
- Regras:
  - a identidade é **código + categoria**: mesmo código em outra categoria conta como removed + new, e marca renomeada também;
  - posição, rotação e externalId **não contam** (peça movida, ou apagada e recriada no Revit, continua `unchanged`);
  - **dimensões** (`DIMENSION_PROPERTY_NAMES`) são comparadas em mm, com conversão de unidades e a tolerância `DIMENSION_TOLERANCE_MM`;
  - **propriedades de revisão** (`REVIEW_PROPERTY_NAMES`, nova; padrão vazio, ou seja, só dimensões) são comparadas como texto, sem diferenciar maiúsculas nem espaços;
  - numa marca inconsistente, compara-se o conjunto de valores das peças;
  - `changed` tem precedência sobre `count_changed`, e as duas quantidades ficam no resultado;
  - marca repetida na entrada → `ValueError`.
- Config: `REVIEW_PROPERTY_NAMES` em `app/config.py` e `infra/.env.example`; `ReconcileConfig.from_settings`.
- Testes (`tests/test_reconcile.py`, 22, escritos antes da implementação):
  - **os 7 casos**: inalterada; peça movida; apagada e recriada (externalId novo); 12→14 = count_changed; seção 40x60→40x80 = changed com diff; PP001→PP001A = removed + new; removida;
  - **bordas**: tolerância e unidades (cm/mm/m); texto sem diferenciar maiúsculas; changed com quantidade; outra categoria; propriedade que aparece ou some; marca com peças divergentes; propriedades fora da config ignoradas; peças sem Marca; código normalizado; primeira versão (tudo new); revisão completa com totais e ordem; marca repetida; config por env;
  - **fixture real do Docs** (ORC.rvt, 33 peças, 19 marcas simuladas): contra si mesma, tudo unchanged, lendo o formato real "40.000 cm"; e o cenário da R02 (pilar trocado para 80x80 / `R-80x80cm-P05`), com o diff de `SEÇÃO-Largura` e `Nome do tipo`.

### Verificação (2026-11-11)
- `make lint` OK; backend 331/331 (`REQUIRE_DB=1`). Sem migração; o banco entra na 7.2.

### 7.2 · Aplicar na chegada da versão — pronto
- **Migração `0008`** (aplicada no banco de dev):
  - `marks.review_status ∈ {ok, review}`, com padrão `ok` (os antigos `pending`/`issue` nunca foram usados) e índice parcial das marcas em revisão;
  - `orphans.status` ganha `returned` (a marca voltou);
  - tabela **`version_diffs`** (`version_id` único, `prev_version_id`, `diff` JSONB).
- **Chegada da versão** (`app/services/version_reconcile.py`): roda no fim do `process_version`, **na mesma transação** dos elementos e do relatório; se falhar, nada fica pela metade (teste com falha simulada). Compara com a **versão pronta anterior** da obra:
  - `changed` + marca com valores → `review_status = review` e `review_note` com o diff ("Seção: 40x60 → 40x80"), auditado;
  - `removed` + com valores → **órfã aberta**, auditada; sem valores → só fica registrado;
  - `new`/`count_changed` → registrados. Novas peças de marca existente **herdam os valores** sozinhas, porque o valor é da marca;
  - `new` de uma marca com órfã aberta → a órfã vira `returned`.
  - O `version_diffs.diff` guarda os totais por classe, o que foi feito (review, órfãs, returned), as propriedades usadas e as marcas não inalteradas, com diff, contagens e ação. Reprocessar é idempotente.
- **Status/atalhos:** marca em `review` tem status **Revisar** (laranja), com precedência. Os atalhos **A revisar**, **Novas na versão** e **Órfãs** funcionam.
- **Resolver a revisão:**
  - `POST /api/marks/{id}/review/keep` ("Manter valores") limpa a revisão e audita `review_keep`;
  - **editar e salvar** valores da marca (individual ou em lote) também resolve, auditado como `review_resolved`;
  - **desfazer o lote devolve a revisão** (`review_restored`).
- **Órfãs:**
  - `GET /api/obras/{id}/orphans?status=open|relinked|archived|returned|all` lista as órfãs com os valores;
  - `POST /api/orphans/{id}/relink {target_mark_id, overwrite?}` copia os valores para a marca de destino. Cada campo é auditado com `source: relink` e a órfã fecha como `relinked`.
    - Se o destino já tem outro valor no mesmo parâmetro → **409 `relink_conflict`** com a lista; para gravar, é preciso confirmar com `overwrite`.
    - Parâmetros que não valem para a categoria do destino ficam de fora (`skipped`).
    - Destino = a própria marca ou outra órfã → 422; destino de outra obra → 404.
  - `POST /api/orphans/{id}/archive` fecha sem copiar.
  - **Os valores nunca são apagados:** ficam na marca antiga e na auditoria.
- `GET /api/versions/{id}/diff`: o diff gravado mais as contagens atuais (`review_open`, `orphans_open`). Sem diff → 404 `diff_not_ready`.
- **Frontend:**
  - **Banner da versão nova** ("Versão 2 comparada com a 1: N novas · N a revisar · N órfãs"): os números abrem os atalhos ou a janela de órfãs; dá para fechar.
  - **Alerta laranja** no painel da marca com o diff linha a linha e **Manter valores / Editar** (projetos e leitura só veem).
  - Janela **Fila de órfãs** com os valores de cada uma:
    - **Religar** entra no modo "clique na marca de destino no 3D ou na lista". A confirmação mostra origem → destino e os valores, avisa quando as categorias são diferentes e, em conflito, oferece "Sobrescrever e religar".
    - **Arquivar** pede confirmação.
  - A legenda subiu para não encostar na barra do Viewer v7.
- **Seed do E2E:** nova obra **E2E-REV**, com v1 → v2 das fixtures `revisao_v1/v2` (`tests/make_revisao_fixture.py`, os 7 casos plantados) e `REVIEW_PROPERTY_NAMES=Seção`. O teste reexecuta o seed para começar do estado "v2 acabou de chegar".
- **Revisões reais da Fase 0** (`tests/real_revisions.py`, só GET no APS):
  - O ORC.rvt é de orçamento (sem Marca) e a R02 foi publicada como outro arquivo. Por isso a Marca da R02 é copiada para as peças da v1 com o **mesmo externalId** (14 peças: a R02 foi salva a partir do ORC).
  - A reconciliação real deu **PP001 e PP002 inalteradas e PP005 `changed`**: `SEÇÃO-Altura 60 → 80 cm; SEÇÃO-Largura 60 → 80 cm; PEÇA-Comprimento 660 → 690 cm` (a troca plantada na R02).
  - Com `--create-obra`, a ferramenta criou no dev a obra **30.327-01-REC** (id 10; v1 = ORC, v2 = R02, URNs reais), processada pelo `process_version`. **Resultado: PP005 a revisar com o diff real, 0 órfãs.**
- Testes:
  - `tests/test_version_reconcile.py` (16): primeira versão; os 7 casos na chegada com as ações certas; **nenhum valor some sem passar pela fila de órfãs**; peças novas herdam; status e atalhos; reprocessar idempotente; marca que volta fecha a órfã; falha desfaz tudo; manter valores; editar/lote resolve e desfazer devolve; listar, religar (cópia, auditoria, conflito/overwrite, outra categoria, validações e papéis), arquivar e diff indisponível.
  - Vitest (7): banner com atalhos; alerta com Manter valores; Editar; projetos sem botões; arquivar; religar pelo 3D; religar pela lista com conflito.
  - Playwright: **aceite da Fase 7** na E2E-REV (tablet e desktop) e o **teste com o Viewer real** na obra 30.327-01-REC (`E2E_REC_OBRA_ID=10`, tablet e desktop): PP005 a revisar com `SEÇÃO-Largura: 60.000 cm → 80.000 cm`.

### Aceite da Fase 7 — ok (2026-11-11)
- **Os 7 casos passam:** no motor puro (`test_reconcile.py`), na chegada da versão pelo `process_version` (`test_version_reconcile.py`) e na tela (E2E-REV).
- **Nenhum valor some sem passar pela fila de órfãs:** um teste confere que toda marca com valores está na nova versão ou numa órfã aberta, e que os valores das removidas continuam gravados. Religar e arquivar não apagam nada.
- **Uma marca com seção alterada fica laranja e mostra 40x60 → 40x80:**
  - na E2E-REV, as peças 10 e 11 ficam `#E8743B`, a legenda mostra "Revisar: 1" e o alerta diz "Seção: 40x60 → 40x80";
  - no modelo real, o PP005 mostra 60x60 → 80x80.

### Verificação (2026-11-11, Docker)
- `make lint` OK; backend **347/347** (`REQUIRE_DB=1`); frontend **94/94**.
- `make e2e`: 19 passaram + 3 pulados (o Ctrl+clique no tablet e os dois testes que só rodam com o Viewer real).
- Viewer real: 2/2 na obra 30.327-01-REC.
- `npm run build` OK.

### `REVIEW_PROPERTY_NAMES` (2026-11-11)
- Padrão: **`Nome do tipo,Type Name,ObjectType,Armadura,TECNOLOGIA-Aço`**: o tipo (Revit `Nome do tipo`; IFC `ObjectType`) e a armadura (o modelo da Cassol só traz `Construção > TECNOLOGIA-Aço`, ARMADO / ARMADO E PROTENDIDO). Também está em `infra/.env.example`.
- As dimensões (`DIMENSION_PROPERTY_NAMES`) continuam disparando. A lista final será ajustada com a fábrica conforme o uso.

### Sync com a V2 real no Docs (2026-11-11)
- O ORC.rvt foi publicado de novo com o **mesmo nome** e virou a **v2 do mesmo item**, publicada às 17:36 UTC.
  - Ao subir, o worker encontrou a versão pela **verificação periódica** (`cron:sync_all_obras`), sem clique em "Sincronizar agora", e enfileirou o processamento.
  - O processamento terminou `ready` em 88,6 s: o APS respondia 202 na primeira leitura das propriedades de uma versão recém-publicada. As 359 peças foram gravadas e a reconciliação rodou.
- A v2 traz as Marcas reais da R02 (PP001×4, PP002×4, PP005×6).
  - A v1 dessa obra tinha sido processada no teste da Fase 0 com Marca **simulada** ("Marca de tipo": P01, V05...). Por isso o diff deu **9 removidas** (as marcas simuladas) e **3 novas** (as reais).
  - Nenhuma das removidas tinha valores, então **nenhuma órfã foi criada e nada se perdeu**.
- Próximo teste real útil: preencher valores nas marcas da v2 (PP001, PP002, PP005) e publicar uma **V3** com o mesmo nome. Por exemplo, trocar a seção do PP002 e apagar o PP001: o PP002 deve ficar a revisar e o PP001 virar órfã.

## Fase 8 · Distribuição automática e tempo real

### 8.1 · Eventos em tempo real — pronto
- **`GET /api/obras/{id}/events`** (Server-Sent Events, todos os papéis), em `app/api/events.py`:
  - assina o canal da obra **antes** de repor o histórico, para não perder nada;
  - **reconexão com `Last-Event-ID`** (cabeçalho ou `?last_event_id=`), repondo o que se perdeu, até 1000 eventos guardados por obra durante 7 dias;
  - **heartbeat a cada 20 s** (`SSE_HEARTBEAT_SECONDS`) e `retry: 3000`;
  - cabeçalhos `Cache-Control: no-cache` e `X-Accel-Buffering: no`.
  - **A conexão com o banco é devolvida antes do fluxo começar:** a checagem de usuário e obra roda numa dependência com `scope="function"`. Na primeira versão, cada aba aberta prendia uma conexão do Postgres enquanto o SSE durasse (o E2E travou por isso). Um teste agora garante que duas conexões SSE abertas não seguram nenhuma sessão.
- **Barramento** (`app/services/events.py`):
  - `RedisEventBus`: `XADD` num stream por obra (histórico para a reconexão; o id do stream é o id do evento) + `PUBLISH` no canal da obra (entrega ao vivo). Configurado na API e no worker.
  - `MemoryEventBus`: mesmo contrato, para os testes.
- **Publicação só depois do COMMIT:** os serviços chamam `events.emit(...)` dentro da transação. Um gancho `after_commit` do SQLAlchemy publica, e o rollback descarta, então ninguém é avisado de algo que não foi gravado. Falha ao publicar só é registrada no log; nunca desfaz a gravação.
- **Eventos e onde são emitidos.** Todos levam `type`, `obra_id`, `at` e `actor {id, name}` (`null` = sistema/worker).
  - `version_ready`: no fim do `process_version` (Fase 3), com contagens e o resumo do diff.
  - `version_failed`: falha no processamento (Fase 3), ou conversão do Docs que falhou ou não existe (Fase 2, `translation`).
  - `values_changed`: salvar valores (6.2: marca, categoria, campos, antes e depois); "Manter valores" (7.2: `review: "kept"`); valores copiados ao religar (7.2: `source: "relink"`).
  - `batch_applied` / `batch_undone`: lote e desfazer (6.3).
  - `orphan_changed`: religar e arquivar (7.2).
  - `param_def_changed`: criar, editar e excluir parâmetro (6.1). Um parâmetro global vai para **todas** as obras.
- **Frontend:**
  - **Cliente SSE sobre `fetch` em fluxo** (`api/events.ts`). Não usa `EventSource` porque ele não envia o cabeçalho `X-Dev-User`. Reconecta com Last-Event-ID, espera de forma crescente (3 → 30 s) e considera a conexão morta depois de 60 s sem nenhum byte; para se a obra não existir.
  - **`useObraEvents(obraId)`** (`features/live/`), ligado na tela do modelo e na página da obra:
    - invalida as queries afetadas: versões; valores, histórico, status, cores, progresso, busca, diff, órfãs e catálogo;
    - mostra **avisos discretos** no canto ("J. Silva alterou PP003", "… alterou 10 marcas em lote", "… religou a órfã PP004 a PP004A", "… criou o parâmetro …"), **só para ações de outros usuários**; somem em 6 s.
  - **Banner "Nova versão disponível: vN acabou de ficar pronta"** com **Carregar**. A versão aberta agora fica fixa na URL (`?versao=`), então uma versão nova não troca o modelo sozinha.
- Testes:
  - `tests/test_events.py` (13):
    - payload de `values_changed` com marca, campos e quem; nada publicado sem commit nem em erro 422;
    - lote e desfazer; parâmetro da obra × global (todas as obras); órfã religada + valores copiados + manter valores; `version_ready`/`version_failed` do processamento;
    - SSE: reposição depois do Last-Event-ID, heartbeat, sem duplicar o que já foi reposto; 401/404;
    - **dois clientes num servidor uvicorn de verdade: B edita, A recebe** `values_changed` (com heartbeat), e A **reconecta com Last-Event-ID e recebe o que perdeu**;
    - **sessão do banco não fica presa** com duas conexões SSE abertas;
    - **barramento Redis real** (pub/sub + reposição pelo stream).
  - Vitest: parser SSE (4) e cliente (reconexão com Last-Event-ID, espera crescente); na tela (3): aviso de outro usuário recarrega os valores, a própria edição não avisa; banner de nova versão sem troca automática e Carregar; textos dos avisos.
  - Playwright: **dois navegadores** (projetos olhando o PP002, fábrica editando). O primeiro recebe, sem recarregar, o aviso "<nome> alterou PP002", o valor F-13 no painel e a cor verde na peça; quem editou não recebe aviso. O evento passa pelo proxy do Vite e pelo Redis real.

### Verificação (2026-11-11, Docker)
- `make lint` OK; backend **360/360** (`REQUIRE_DB=1`); `npm run build` OK.
- `make e2e`: **20 passaram + 4 pulados** (o Ctrl+clique no tablet, os dois testes que só rodam com o Viewer real e o teste de dois navegadores no tablet, porque basta um perfil), em 1,3 min.
- **Regressão encontrada pelo E2E e corrigida:** com os valores recarregando em tempo real durante a edição, o formulário passava a mandar a `row_version` NOVA ao salvar. A edição de um colega seria sobrescrita sem o aviso de conflito (aceite da Fase 6). Agora o formulário guarda os valores e as versões lidos **quando a edição começou** (`MarkValuesSection`). Há teste de regressão no Vitest: o colega salva durante a edição, o rascunho é mantido, o salvar leva a versão do início e recebe o aviso "… alterou esta marca".
- Frontend agora **102/102**.

### 8.2 · Versão anterior em modo consulta — pronto
- **Seletor de versão** com rótulos "Rev.03 · data (ativa)". A **ativa** é a versão pronta mais recente.
- **Versão anterior = modo consulta (somente leitura)**, só no frontend (`ModelPage`, `PiecePanel`):
  - faixa **"Visualizando Rev.02 · somente leitura"** com **"Voltar para a versão ativa"**;
  - sem Editar, Editar em lote, Manter valores, "+ Novo parâmetro", Religar e Arquivar;
  - o painel mostra os **valores atuais da marca** (são da marca, não da versão), com o aviso "Valores atuais da marca: valem para a versão ativa (Rev.03). Nesta versão só é possível consultar."
  - O modelo, as propriedades, a busca e as cores são os da versão consultada. Uma marca que sumiu depois, como uma órfã, continua consultável na versão antiga.
- Quando chega uma versão nova com a tela aberta, a versão em uso vira "anterior": a faixa de consulta aparece **junto** com "Nova versão disponível" e o botão **Carregar**. O modelo não troca sozinho, e um rascunho em edição não é descartado.
- Viewer falso do E2E: limpa as peças a cada carga de modelo (troca de versão).
- Novo `tests/e2e_new_version.py`: processa a próxima versão da obra E2E-REV com o `process_version` do worker, **publicando os eventos no Redis real**. O seed apaga as versões extras dessa obra.
- Testes:
  - Vitest: rótulos Rev.NN/(ativa); trocar para a anterior mostra a faixa e "Voltar…" volta; no modo consulta há aviso e valores, e não há Editar, Manter valores, Novo parâmetro nem Editar em lote.
  - Playwright **troca de versão** (tablet e desktop, E2E-REV):
    - Rev.02 ativa → Rev.01 em consulta;
    - PP005, que só existe na Rev.01, é consultável com F-13 e o aviso, sem edição;
    - PP001 mostra o alerta de revisão sem ações e a seção 40x60 da Rev.01;
    - "Voltar para a versão ativa" → Rev.02, seção 40x80 e as ações de volta.

### Aceite da Fase 8 — ok (2026-11-11)
- Playwright, **dois navegadores** (projetos e fábrica) na E2E-REV:
  - a Rev.03 é processada como pelo worker, com eventos no Redis;
  - **os dois** recebem, sem recarregar, "Nova versão disponível: Rev.03…", com a Rev.02 passando a modo consulta, e carregam a Rev.03;
  - a fábrica edita o PP007 e o outro navegador recebe o aviso, o valor e a cor.
- O teste da 8.1 (dois navegadores, edição na mesma versão) continua passando.

### Verificação (2026-11-11, Docker)
- `make lint` OK; backend **360/360** (`REQUIRE_DB=1`); frontend **103/103**; `npm run build` OK.
- `make e2e`: **23 passaram + 5 pulados** (Ctrl+clique no tablet, os dois testes de Viewer real e os dois testes de dois navegadores no tablet), em 2,2 min.

## Fase 9 · Exportação

### 9.1 · Excel por obra — pronto
- **`GET /api/obras/{id}/export.xlsx`** (todos os papéis), em `app/api/export.py` e `app/services/export.py`, com **openpyxl**. Aceita **os mesmos filtros da busca** (`q`, `category`, `level`, `prop`, `missing`, `shortcut`, `order`) e `version_id`; sem ele, usa a versão ativa (pronta mais recente).
  - A busca foi separada em `search.find_marks` (resultado inteiro, na ordem da tela) + paginação. **O Excel é exatamente a lista da tela.** Com filtro de nível, por exemplo, a quantidade de peças é a filtrada, como na lista.
- **Aba "Marcas"** (uma linha por marca):
  - Marca, Categoria, Peças, **Seção**, **Comprimento (cm)** e Status (Pendente, Parcial, Completa, Revisar);
  - **uma coluna por parâmetro ativo** (globais + da obra, ordem alfabética), com **unidade no cabeçalho** ("Ciclo de cura (h)");
  - **Última alteração** e **Autor** (o mesmo "Última alteração" do painel da marca).
  - Seção = Largura x Altura em cm, pelas dimensões do modelo (`SEÇÃO-Largura`/`SEÇÃO-Altura`, com alternativas em inglês e genéricas); sem elas, o nome do tipo. Comprimento em cm, por `PEÇA-Comprimento`/`Comprimento`/`Length`. Peças divergentes na mesma marca mostram os valores juntos ("40x40 / 40x50").
- **Aba "Peças":** Marca, Categoria, externalId, Nível e dbId (só as peças do resultado). **Aba "Sobre":** obra, versão (Rev.NN), filtros, totais, quando e quem gerou.
- **Formato:**
  - cabeçalho em negrito, **congelado**, com **filtro automático** nas duas abas e largura das colunas ajustada;
  - **números como número** (peças, comprimento, parâmetros numéricos);
  - **datas como data do Excel** (`dd/mm/aaaa`; última alteração em `dd/mm/aaaa hh:mm`, no fuso `DISPLAY_TIMEZONE`, padrão America/Sao_Paulo, por isso entrou o `tzdata`);
  - sim/não como "Sim"/"Não";
  - parâmetro que **não se aplica** à categoria da marca: célula vazia e cinza.
- Nome do arquivo: `<obra>_Rev.NN_<data>.xlsx` (Content-Disposition com `filename*` UTF-8); cabeçalhos `X-Export-Marks` e `X-Export-Pieces`.
- **Frontend:** botão **"Exportar Excel"** na barra da obra (tela do modelo). Usa a **versão aberta** e **os filtros ativos** da busca, e mostra "com os filtros ativos" quando há filtro. O download vai por `fetch`, por causa do cabeçalho do usuário simulado; erros aparecem ao lado do botão.
- **Conferido com o modelo real** do Docs (30.327-01, Rev.02): PP005 = 80x80 e 690 cm; PP001/PP002 = 60x60 e 660 cm; Peças com nível e externalId reais.
- Testes:
  - `tests/test_export.py` (4):
    - **mesmas linhas e valores da tela**: busca, status e valores/última alteração/autor de cada marca, e peças = os dbIds do resultado;
    - os mesmos filtros da busca (texto, nível, categoria, "sem", atalho, ordem, Nome=valor);
    - tipos e formatos (número, data, sim/não, não se aplica, seção, comprimento), layout (congelado, filtro), aba Sobre e nome do arquivo;
    - versão e permissões (todos os papéis; 401, 404 sem versão pronta ou de outra obra; 422 em filtro inválido).
  - Vitest (3): nome do arquivo; o botão manda a versão aberta, os filtros e o usuário, e baixa o arquivo; erro ao lado do botão.
  - Playwright (tablet e desktop): busca "PP" → **Exportar Excel** → o .xlsx baixado (lido com openpyxl, `tests/read_xlsx.py`) tem **as mesmas marcas e quantidades da lista na tela** e o **mesmo valor do painel** (PP001 = F-12), além de status, peças, layout e filtros na aba Sobre.

### Verificação (2026-11-11, Docker)
- `make lint` OK; backend **364/364** (`REQUIRE_DB=1`); frontend **106/106**; `npm run build` OK.
- `make e2e`: **25 passaram + 5 pulados**, em 2,5 min.

### 9.2 · Parâmetros da fábrica no Revit (opcional) — não será feito
- **Decisão (2026-11-11):** o 9.2 (script pyRevit/Dynamo gravando os parâmetros da fábrica como Shared Parameters no modelo) esbarra na regra do CLAUDE.md "Nunca escrever no arquivo BIM". O usuário escolheu **pular o passo**. Por isso não foram criados o endpoint `export.json`, o token de serviço nem o script do Revit.

### Aceite da Fase 9 — ok (2026-11-11)
- **O Excel confere com a tela:** testes do backend comparam o arquivo com as rotas que a tela usa (busca com cada filtro, status e valores), e o Playwright compara o .xlsx baixado com a lista e o painel da tela (tablet e desktop). Também conferido com o modelo real do Docs.

## Fase 10 · Endurecimento

### 10.1 · Observabilidade e alertas — pronto
Guia para a TI em **`docs/operacao.md`**.
- **Logs estruturados** (`app/observability/logging.py`):
  - JSON numa linha por evento, com `request_id`, `user` (id e nome), `obra`, `job` e `version` vindos de `contextvars`;
  - middleware ASGI puro (não atrapalha o SSE): gera ou reaproveita o `X-Request-ID`, devolve-o na resposta e registra uma linha `app.access` por requisição (método, caminho, status, duração);
  - o worker põe `job`/`version`/`obra` no contexto de cada job;
  - **mascaramento de segredos** na mensagem e no traceback: Bearer, JWT, `client_secret`, `access_token`, senha, `x-adsk-signature` e senha em URL;
  - `LOG_FORMAT=json|text`, sempre em UTF-8; httpx/uvicorn.access/arq só a partir de aviso.
- **`/api/health`** (vivo) e **`/api/ready`** (banco, Redis e token do APS; 200 ou 503 com o motivo de cada checagem, sem segredos). APS sem credenciais: "skipped" em dev, falha fora de dev.
- **Métricas** (`app/observability/metrics.py`):
  - no Redis, compartilhadas pela API e pelo worker: versões processadas por status, tempo de processamento (count/sum/max), falhas de leitura no APS por tipo (gancho `error_hooks` no `ApsClient`), webhooks recebidos e o último, versões achadas só pela verificação periódica;
  - calculadas na leitura: versões por status, sem conversão há mais de 2 h, **webhooks atrasados** (sem processar após 10 min), **fila do Arq**;
  - `GET /api/metrics` em JSON ou `?format=prometheus`, para admin ou `Bearer METRICS_TOKEN`.
- **Alertas** (`app/observability/alerts.py`, cron do worker a cada 5 min), por **Teams** (Workflows, cartão adaptativo) e/ou **e-mail** (SMTP), configuráveis no `.env`:
  - versão `failed`;
  - `no_translation` há mais de 2 h;
  - nenhum webhook em 24 h com versões novas achadas pela verificação periódica (só com webhooks configurados, `PUBLIC_BASE_URL`);
  - credenciais do APS com 401/403 nos últimos 15 min.
  - **Deduplicação** no Redis (`SET NX EX`), com intervalo próprio por tipo. Falha de um canal não impede o outro.
  - `python -m app.cli alerts test` manda um alerta de teste.
- **No ambiente real** (Postgres, Redis e APS de verdade): `/api/ready` = 200 (banco 53 ms, Redis 8 ms, token APS 441 ms); `/api/metrics` responde para o admin e dá 403 para a fábrica; os logs saem em JSON com `request_id` (o do proxy reaproveitado), usuário e obra.
- Testes: `tests/test_observability.py` (25):
  - mascaramento (7 casos); linha JSON com contexto, extras e traceback mascarado;
  - `request_id`, obra, usuário e linha de acesso pela API; X-Request-ID do proxy aceito ou trocado; middleware com resposta em fluxo;
  - health/ready: ok; 503 com o motivo e sem a senha; APS fora de dev; token APS 401 → falha;
  - métricas de processamento (ok e falha), erros do APS (forbidden/not_found + marca de credencial), webhook recebido; `/api/metrics` em JSON e Prometheus, admin × fábrica × token;
  - alertas: failed e sem conversão com deduplicação e um canal quebrado; webhooks parados (só configurado, com e sem webhook recente, verificação antiga); credenciais APS (recente × antigo); Teams (cartão adaptativo); e-mail (SMTP falso: STARTTLS, login, destinatários); canais pelo `.env`; job do worker.

### Verificação (2026-11-11, Docker)
- `make lint` OK; backend **389/389** (`REQUIRE_DB=1`); frontend **106/106** (sem mudanças); `make e2e` **25 passaram + 5 pulados** (o middleware não afeta o tempo real/SSE). Sem migração.

### 10.2 · Segurança e carga — pronto (2026-11-12)
Guia para a TI em **`docs/operacao.md` › Segurança** (cabeçalhos para o proxy, CORS, limite e matriz).
- **Auditorias:**
  - `pip-audit` (todas as dependências do backend, incluindo dev): **nenhuma vulnerabilidade**.
  - `npm audit`: havia **2 críticas** (`vitest` 3.2 e `tinypool`: path traversal e RCE por prototype pollution) e **2 altas** (`@playwright/test`/`playwright` < 1.55.1: download de navegadores sem checar o certificado), todas em ferramentas de teste.
  - Corrigido: **Vitest 3 → 5.1** (aceita o Vite 6.4 e o Node 24; único ajuste: o mock do `GuiViewer3D` virou `function`, porque o Vitest 4+ exige construtor para `new`) e **Playwright 1.49 → 1.65**, mais o `npm audit fix` sem mudança de versão principal.
  - Restam **9 moderadas**, fora do escopo (alto/crítico): `typescript-eslint`/`minimatch` (lint, dev) e **`react-router-dom` 6** (open redirect com barra invertida em `<Link>`/`useNavigate`; o app não navega para endereços digitados pelo usuário). A correção é a 7.x, que muda a versão principal. **Recomendo planejar essa troca.**
- **Cabeçalhos** (`backend/app/security/headers.py`, ASGI puro, não atrapalha o SSE):
  - na API: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, CORP `same-origin` e CSP `default-src 'none'; frame-ancestors 'none'`;
  - HSTS fora de dev (`HSTS_MAX_AGE`);
  - Swagger (`/docs`, `/openapi.json`) só em dev.
- **CSP do app compatível com o Viewer** (`frontend/security-headers.ts`, fonte única):
  - libera o CDN do Viewer, workers `blob:`, estilos inline do Viewer, `https`/`wss` em `*.autodesk.com` (SVF2), além de `data:`/`blob:` em imagens e fontes;
  - em produção, sem `unsafe-inline` em script, sem `unsafe-eval`, `object-src 'none'` e `frame-ancestors 'none'`;
  - aplicada pelo Vite em dev (com o relaxamento do Fast Refresh/HMR) e em `vite preview` (a de produção); o proxy da TI copia `PRODUCTION_HEADERS`;
  - **validada com o Viewer real** (obra 30.327-01): modelo em **5,3 s no desktop e 5,8 s no tablet emulado**. A única violação é a telemetria do Viewer ao `api-js.mixpanel.com`, **bloqueada de propósito** (não afeta o modelo; nada de uso sai para terceiros).
- **CORS:**
  - `CORS_ORIGINS` ou, vazio, a origem de `APP_BASE_URL` fora de dev; sem origem, nenhum cabeçalho CORS;
  - `*` ou origem inválida impedem o backend de subir;
  - métodos e cabeçalhos limitados ao que o app usa.
- **Limite de taxa** (`backend/app/security/rate_limit.py`):
  - **120 escritas/min por usuário** (`RATE_LIMIT_WRITES_PER_MIN`; 0 desliga), em janela fixa no Redis, compartilhada entre instâncias;
  - acima do limite: **429** com `Retry-After`, mensagem em português, log e métrica `rate_limited_total`;
  - chamado em `current_user`: a Fase 11 troca o login sem mexer no limite;
  - leituras não contam; o lote conta como uma escrita; Redis fora do ar não bloqueia escritas; o webhook fica fora.
- **Matriz de papéis** (`backend/tests/test_role_matrix.py`):
  - revisadas as **42 rotas**; nenhuma correção foi necessária;
  - um teste parametrizado por rota checa os 4 papéis e o anônimo: permitido nunca 401/403, negado 403, anônimo 401;
  - um teste de guarda reprova rota nova sem linha na matriz (confirmado: trocar duas linhas da matriz derruba o teste);
  - também cobre webhook sem assinatura e o usuário simulado/`/api/dev/users` fora de dev;
  - tabela em `docs/operacao.md`.
- **E2E isolado do banco de dev:**
  - a suíte falhava (Excel com 4 colunas a mais, legenda) por causa de 4 parâmetros globais criados à mão no banco de dev em 2026-11-11 ("armadura", "coisa X", "teste1", "refazer"; **não mexi neles**);
  - agora o modo padrão usa o banco **`bim_e2e`** e o Redis db 1 (`playwright.config.ts`), criados e migrados pelo `backend/tests/e2e_db.py` (que recusa outro nome);
  - todo teste E2E falha se houver violação de CSP.
- **Teste de carga** (`loadtest/locustfile.py`, Locust 2.46.7 via `uvx`, fora das dependências do app; usuários `Carga 01..30` em `backend/tests/load_users.py up|down`):
  - cada usuário de carga (papel fábrica) abre a obra (as 11 chamadas da tela e do 3D), busca (texto e atalhos) e edita "Teste de carga" com o `row_version` lido;
  - o parâmetro "Teste de carga" (escopo da obra 5) é criado no início e desativado no fim; usuários desativados depois do teste.

#### Resultado da carga (2026-11-12)
30 usuários simultâneos, rampa de 5/s, **3 min**, pausa de 1 a 3 s entre ações. Rodou no Windows do escritório: backend em 1 processo uvicorn sem `--reload`, Postgres e Redis no Docker, obra **30.327-01** (versão 14, 359 peças, 12 marcas).

| Requisição | Qtde | Mediana | p95 | p99 | Máx |
|---|--:|--:|--:|--:|--:|
| Abrir a obra: `/me`, obras, obra, versões (cada) | 456 | 11–16 ms | 55–64 ms | 88–110 ms | 130 ms |
| Catálogo `param-defs` | 456 | 39 ms | 140 ms | 220 ms | 310 ms |
| Relatório / status / progresso / facetas | 456 | 17–22 ms | 73–84 ms | 100–130 ms | 190 ms |
| Token do Viewer | 456 | 12 ms | 60 ms | 360 ms | 480 ms |
| **Busca** | 1.273 | **18 ms** | **62 ms** | 120 ms | 160 ms |
| Valores da marca (GET) | 795 | 21 ms | 72 ms | 130 ms | 200 ms |
| **Salvar valores (PUT)** | 795 | **44 ms** | **150 ms** | 270 ms | 410 ms |
| **Total** | **7.917** | **19 ms** | **81 ms** | 140 ms | 480 ms |

- **0 falhas, 0 erros 5xx, 0 respostas 429**; 44,8 req/s.
- **38 conflitos 409** (duas pessoas salvando a mesma marca ao mesmo tempo): a trava otimista funcionando, sem perda de dado. Com só 12 marcas, a disputa é maior que a real.
- O tempo do **modelo 3D** vem do CDN da Autodesk e não entra aqui (5–6 s medidos acima).
- Saídas CSV em `loadtest/out/` (fora do git). Para repetir no servidor da TI, siga a docstring do `locustfile.py`.

### Verificação (2026-11-12, Docker)
- `make lint` OK (ruff, ruff format, mypy strict, ESLint, tsc).
- Backend **451/451** (`REQUIRE_DB=1`; +62: matriz 45, segurança 17).
- Frontend **110/110** (+4 da CSP).
- `make e2e` **26 passaram + 6 pulados**, também a partir de um `bim_e2e` recém-criado.
- E2E com o **Viewer real** sob CSP: 3/3.
- Auditorias depois da correção: `pip-audit` limpo; `npm audit` sem alta nem crítica (9 moderadas).
- Sem migração.

### 10.3 · Implantação, backup e runbook — pronto (2026-11-12)
Ambiente: **teste com a fábrica num PC Windows com Docker Desktop**; depois do aceite, o **servidor Linux da TI**. A mesma pilha serve aos dois. Guias: **`docs/DEPLOY.md`** (instalação, variáveis, segredos, backup, restauração, webhooks, atualização) e **`docs/RUNBOOK.md`** (versão com falha, webhook parado, credenciais do APS, sync manual, worker, backup, 429, modelo 3D).
- **Imagens de produção:**
  - `backend/Dockerfile` em dois estágios: dependências com `uv` num venv, runtime `python:3.12-slim` sem compiladores, usuário sem root; uvicorn com 2 processos e `--proxy-headers`; healthcheck. 324 MB.
  - `frontend/Dockerfile`: `npm ci` + `tsc` + `vite build` → `nginx-unprivileged`. Os cabeçalhos do nginx são **gerados no build** a partir de `security-headers.ts` (`nginxHeaders`, com teste). `/api` vai ao backend com `proxy_buffering off` (SSE); SPA com fallback; cache longo em `/assets`. 82 MB.
  - `infra/backup/Dockerfile`: pg_dump/pg_restore 16 + rclone 1.69.3 + redis-cli.
- **`infra/docker-compose.prod.yml`:**
  - postgres, redis, `migrate` (Alembic; roda e sai antes), api, worker, web e `backup` (perfil, sob demanda);
  - rede interna; **só o nginx publica porta**.
- **Segredos por arquivo** (Docker secrets em `/run/secrets`):
  - `SECRETS_DIR` no `config.py` (recurso do pydantic-settings);
  - `infra/secrets/` fora do git, gerada por `infra/secrets-init.{ps1,sh}` (valores aleatórios em hexadecimal, permissões restritas, nunca sobrescreve);
  - modelo de variáveis em `infra/.env.prod.example`.
- **Usuário simulado no ambiente de teste** (decisão de 2026-11-12):
  - até a Fase 11 a fábrica precisa do X-Dev-User; `DEV_USERS_ENABLED=true` só vale com `APP_ENV=staging`, e com `prod` o backend **não sobe**;
  - Swagger desligado e HSTS ativo continuam;
  - **atenção:** qualquer pessoa na rede escolhe qualquer usuário, inclusive admin.
- **Backup** (`infra/backup/backup.sh`):
  - `pg_dump -Fc`, conferido com `pg_restore --list`, `.sha256` e retenção de **30 dias** (local e remoto);
  - cópias pelo **rclone** direto na pasta compartilhada (SMB) e no SharePoint (`BACKUP_REMOTES`), sem montar nada no host; falha num destino não apaga o local;
  - o resultado vai para o Redis (`backup_last_ok`/`backup_last_failed`);
  - **alertas novos: "Backup falhou" e "Backup atrasado"** (`BACKUP_MAX_AGE_HOURS`, 26 h no `.env.prod`; desligado em dev);
  - agendamento: `infra/backup/windows/register-backup-task.ps1` + `run-backup.ps1` (Tarefa Agendada, roda ao ligar se o PC estava desligado, log em `infra/backups/backup.log`) e `infra/backup/systemd/bim-backup.{service,timer}`.
- **Restauração** (`infra/backup/restore.sh`):
  - `latest` ou nome do arquivo; confere o sha256;
  - **exige banco vazio**: `--force` só com `RESTORE_CONFIRM=<banco>`;
  - imprime as contagens; depois o serviço `migrate` atualiza o esquema.
- **Webhooks sem acesso externo** (decisão da TI, 2026-11-12):
  - `PUBLIC_BASE_URL` vazio = webhooks desligados; versões pela verificação a cada 10 min e pelo "Sincronizar agora";
  - pronto para quando houver URL: **`python -m app.cli hooks reregister --all`** apaga os hooks de versão com URL antiga (só os deste app) e registra os de todas as obras ativas com pasta;
  - passo a passo da publicação (só `POST /api/webhooks/aps` exposto) no DEPLOY › 8.
- **Comandos novos para o runbook:**
  - `python -m app.cli versions retry --version N`: só failed/no_translation; reconsulta o manifest (GET, nunca POST /job) e enfileira com id de job novo;
  - `python -m app.cli sync --obra N | --all`: o "Sincronizar agora" com o resultado de cada obra.
- **SharePoint:** o código e o passo a passo estão prontos (rclone `onedrive`/`documentLibrary`). **Fica desligado até a TI registrar o app no Entra ID**; testado com um destino `local` do rclone no lugar da pasta.
- Testes:
  - `test_config.py`: segredos lidos de arquivo, `SECRETS_DIR` no `get_settings`, `DEV_USERS_ENABLED` em dev/staging/prod;
  - `test_role_matrix.py`: staging com usuário simulado (papéis e endurecimento valem);
  - `test_webhooks.py`: `reregister --all` (URL antiga apagada, nova mantida, outro evento intocado; obras sem pasta/inativas ignoradas) e falta de `PUBLIC_BASE_URL`;
  - `test_observability.py`: backup atrasado/falhou/recuperado e desligado;
  - `test_translation.py`: `versions retry` (pronta → enfileira; Docs ainda sem conversão → 1; status errado → 2) e `sync --obra/--all` (idempotente);
  - Vitest: `nginxHeaders`.

### Aceite da Fase 10 — ok (2026-11-12)
Feito nesta máquina com a **pilha de produção** (`docker-compose.prod.yml`, `APP_ENV=staging`, nginx na porta 8088, 2 processos da API), com a obra real **30.327-01** sincronizada do Docs pelo worker (2 versões × 359 peças; v2 com 3 marcas reais) e o parâmetro "Tipo de forma" preenchido.
- **O backup restaura num ambiente limpo:**
  - backup → projeto Compose novo, com volumes vazios → `restore.sh latest` (sha256 ok) → `migrate` + api/worker/web saudáveis;
  - **todas as tabelas iguais à origem** (users 4, obras 1, model_versions 2, marks 3, elements 718, param_values 3, audit_log 18, version_reports 2, version_property_names 428) e valores da fábrica idênticos;
  - busca no app restaurado ok; restaurar por cima de banco com dados é recusado;
  - também testados: retenção (dumps de 40 dias apagados no local e no destino, o de 23 dias mantido), cópia remota pelo rclone e falha de destino (exit 2, dump local mantido). Detalhes no DEPLOY › 7.
- **30 usuários simultâneos sem degradação** (Locust, 3 min, rampa de 5/s, pelo nginx). Comparação com a pilha de dev do 10.2:

| | 10.2 (dev, 1 processo) | 10.3 (produção, nginx + 2 processos) |
|---|--:|--:|
| Requisições / falhas | 7.917 / 0 | **8.188 / 0** |
| Mediana / p95 / p99 (todas) | 19 / 81 / 140 ms | **10 / 68 / 120 ms** |
| Busca: mediana / p95 | 18 / 62 ms | **10 / 22 ms** |
| Salvar valores: mediana / p95 | 44 / 150 ms | 67 / 160 ms |
| Conflitos 409 (mesma marca ao mesmo tempo) | 38 (12 marcas) | 96 (3 marcas) |

  O PUT um pouco mais lento na mediana vem da disputa: 30 pessoas em só 3 marcas, com a trava otimista funcionando (sem perda de dado). Nenhum 5xx e nenhum 429.
- **A matriz de papéis passa inteira:** `test_role_matrix.py` 46/46 (42 rotas × 4 papéis + anônimo, guarda de rota nova, staging).
- **Os alertas disparam nos testes:**
  - automatizados: `test_observability.py`, 26 testes (failed, sem conversão, webhooks parados, credenciais APS, backup; Teams e e-mail);
  - **disparo real na pilha de produção** para um receptor local no papel do Teams: `alerts test` chegou como cartão adaptativo, e o **worker sozinho** (rodada de 5 min) mandou "Backup do banco falhou" depois de uma falha de backup provocada.

### Verificação (2026-11-12, Docker)
- `make lint` OK.
- Backend **463/463** (`REQUIRE_DB=1`; +12).
- Frontend **112/112** (+2).
- `make e2e` **26 passaram + 6 pulados**.
- Imagens construídas e pilha de produção saudável.
- Sem migração.

### Falta (depois do 10.3)
- **Instalar no PC de teste da fábrica:** seguir o DEPLOY › 3 (incluindo "Particularidades do PC Windows"), agendar o backup (`register-backup-task.ps1`), definir `BACKUP_REMOTES` com a pasta compartilhada e o canal dos alertas.
- **Para a TI:** app no Entra ID para o SharePoint; URL pública HTTPS, quando houver, para os webhooks (DEPLOY › 8); servidor Linux definitivo (DEPLOY › 11); TLS no proxy.
- Repetir o teste de restauração a cada 3 meses e o de carga no servidor definitivo.
- Recomendado: `react-router-dom` 6 → 7 (moderada pendente do 10.2); um job de CI que construa as imagens.
- **2026-11-12, preparação do teste real:** o banco de dev foi zerado por engano e **restaurado** em seguida do backup `infra/backups/dev-antes-de-zerar-20261112T133230Z.dump` (contagens idênticas: 6 obras, 9 versões, 30 marcas, 2.003 registros de histórico). Depois, só os parâmetros aleatórios de 2026-11-11 ("armadura", "coisa X", "teste1", "refazer") foram **excluídos pelo serviço do app** (exclusão lógica, com auditoria pela Ana Admin); "Teste de carga" já estava excluído. As obras reais do Docs ficaram sem parâmetros. Restam "Tipo de forma" de obra só nas obras de teste E2E-01, E2E-REV e 30.327-01-REC. A pilha de produção de teste desta máquina (porta 8088) foi removida com os volumes; o PC da fábrica terá instalação nova (DEPLOY › 3).
- **Guia de uso dos parâmetros** para a fábrica: `docs/guia-parametros.html` (publicado como página privada no claude.ai).

## Aceite com o APS real (2026-11-11)

Custom Integrations liberado; credenciais em `infra/.env` e `spikes/.env` (fora do git). Resultados detalhados em `docs/decisoes-fase-0.md`.

- **0.1:** hub "Cassol Pré-Fabricados", projeto **TESTE PLATAFORMA FABRICA** > Project Files > `30.327-01 - MODELO - ORC.rvt`.
- **0.2:** v1 com conversão automática do Docs (SVF2, manifest `success`, sem POST /job); leitura completa em 14 s; 359 peças (213 Quadro estrutural, 145 Pilares estruturais, 1 Pisos). **"Marca" vazia em todas** (modelo de orçamento) — combinado: simular marcas nos testes.
- **App ponta a ponta com o Docs real:** navegação no Docs pela API do app → cadastro da obra `30.327-01` (o backend confere o arquivo) → "Sincronizar" (1 s: versão importada, conversão pronta, processamento enfileirado) → worker processa as 359 peças em **1,5 s** → relatório, facetas (níveis reais EMBARQUE/DESEMBARQUE/COBERTURA/TÉRREO), busca por seção (`50x90`), por marca e por propriedade (`SEÇÃO-Altura=90.000 cm`) funcionando.
- **Viewer real (Playwright `E2E_REAL_VIEWER=1 E2E_OBRA_ID=<obra>`):** modelo aparece em **4–6 s no desktop e 6–8 s no tablet emulado** (Chromium headless, rede do escritório); no desktop, clicar numa peça real selecionou a marca inteira ("V01 · Quadro estrutural · 27 peças") e o painel carregou a peça pelo dbId do Viewer → **`elements.dbid` = dbId do Viewer no SVF2 do Docs** (confirmado). No tablet emulado o toque do Chromium não chega ao reconhecedor de gestos do Viewer: lá o teste seleciona pela lista; **toque fica para o tablet real**.
- **Bug encontrado e corrigido** (`app/services/extraction.py`): no Revit, parâmetros de TIPO (ex.: "Marca de tipo") aparecem no nó do tipo e nas instâncias; a regra antiga fazia do tipo a "peça" (9 em vez de 359). Agora, se a propriedade que deu a marca ao nó se repete com o mesmo valor em todos os filhos, o nó é agrupamento e a extração desce. Testes novos em `tests/test_extraction.py`.
- **Fixtures reais:** `tests/record_fixture.py` grava respostas do APS sanitizadas (só GET; descarta propriedades do nó raiz; subconjunto por tipo; `--simulate-marks`). Gravada `tests/fixtures/aps/models/rvt_real` (52 nós, 33 peças, Marca simulada) + `tests/test_real_fixture.py` (5 testes, incluindo o caso "Marca de tipo" que expôs o bug).
- **Configuração:** `DIMENSION_PROPERTY_NAMES` agora começa com `SEÇÃO-Altura,SEÇÃO-Largura,PEÇA-Comprimento` (nomes reais); nível e tipo/seção já batiam com os padrões; categoria vem da árvore (português, sem "Revit ").
- A obra `30.327-01` (id 5) fica no banco de dev, processada com marcas simuladas ("Marca de tipo"); reprocessar com o worker padrão deixa todas as peças sem marca.
- Verificação: backend 287/287, frontend 71/71, `make e2e` 13 passaram + 1 pulado; E2E real 2/2.

### Pendências que dependem de ação externa
- Publicar na pasta de teste: um **.nwd** e um **.ifc**; uma **segunda versão** do .rvt (comparação e reconciliação); idealmente um modelo **de produção com Marca**.
- Conferir 213/145/1 com o quantitativo do Revit.
- Webhooks: definir o túnel (URL pública) para registrar os hooks.
- Medição no **tablet real**, na rede da fábrica (aceite da Fase 4), incluindo seleção por toque.
- Licença da visualização por conta de serviço (pergunta à Autodesk) e conversa do catálogo com a fábrica.

### R02, IFC e webhooks (2026-11-11, tarde)

- **Publicação:** pelo navegador, arrastando para a pasta. **A R02 virou outro arquivo** (`...-ORC-R02.rvt`), não a v2 do original: o Docs só versiona com o **mesmo nome**. Regra registrada em `docs/decisoes-fase-0.md`; para testar a reconciliação (Fase 7) a revisão precisa ser publicada com o nome do original.
- **R02 no app** (obra `30.327-01-R02`, config padrão, sem simulação): 359 peças, **3 marcas reais** (PP001×4, PP002×4, PP005×6), 345 sem marca, 0 inconsistentes (peças de cada marca idênticas — correto). A troca de seção plantada (6 pilares `R-60x60cm-P01` 660 cm → `R-80x80cm-P05` 690 cm) é mudança ENTRE versões: cenário da Fase 7.
- **IFC no app** (obra `30.327-01-IFC`): a primeira leitura deu 1984 "elementos" (geometria, aberturas, eixos). **Extração corrigida para IFC:** peça = nó com `IFC Attributes > IfcClass` de produto físico; filhos = geometria; IfcProject/Site/Building/BuildingStorey = espaciais (desce); IfcGrid/IfcOpeningElement/IfcSpace/IfcAnnotation… ignorados. Resultado: **359 = 145 IfcColumn + 213 IfcBeam + 1 IfcSlab**, níveis por `IfcSpatialContainer` iguais aos do .rvt (TÉRREO 145, EMBARQUE 190, DESEMBARQUE 15, COBERTURA 9). Padrões: `LEVEL_PROPERTY_NAMES` + `IfcSpatialContainer`, `SEARCH_PROPERTY_NAMES` + `ObjectType`. O IFC não traz Marca (nem o .rvt de origem).
- **Fixture IFC real** `tests/fixtures/aps/models/ifc_real` (sanitizada: `--redact` troca o nome do projeto, propriedades de projeto/site/edifício descartadas) + testes em `tests/test_real_fixture.py`. `tests/record_fixture.py` ganhou `--type-depth` (Revit 3, IFC 5) e `--redact`.
- **Webhooks — correção:** com várias obras na mesma pasta, o hook é um só (o APS não aceita repetido) e o evento chegava com o `obra_id` de quem registrou. Agora **o arquivo do evento (pasta + lineage) decide a obra**; o `hookAttribute` é reserva; arquivo da pasta que não é de nenhuma obra → `no_obra` (guardado, sem sincronizar). Teste novo em `tests/test_webhooks.py`.
- **Webhooks — túnel:** baixar e executar o `cloudflared` foi bloqueado pela proteção do ambiente. **Decisão (2026-11-11): webhooks ficam para o servidor definitivo** (URL fixa, Fases 8/10). Até lá, versões chegam pela verificação a cada 10 min e pelo "Sincronizar agora" (testados com o Docs real). Ao expor o backend, publicar só a rota do webhook (instância com `APP_ENV` diferente de `dev`, sem usuário simulado).
- Verificação: backend 290/290, frontend 71/71, `make e2e` 13 + 1 pulado.
