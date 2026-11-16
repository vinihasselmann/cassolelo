# e2e

Testes Playwright (`make e2e` ou `cd frontend && npx playwright test`). Projetos:
`tablet` (Galaxy Tab S4 na horizontal) e `desktop`.

## Modo padrão (sem APS)
Precisa do Postgres (`make up` + `make migrate`). O Playwright sobe backend (:8001) e
Vite (:5174); o `global-setup.ts` roda `backend/tests/e2e_seed.py`, que cria os
usuários simulados e a obra **E2E-01** com o modelo de teste
`backend/tests/fixtures/aps/models/validacao`, processado pelo mesmo `process_version`
do worker. O script do Viewer (CDN) é trocado por `fake-viewer/viewer3D.js`, que desenha
cada peça como um botão; o token do Viewer é simulado.

**Banco próprio (10.2):** neste modo o `playwright.config.ts` troca o `DATABASE_URL` para
o banco **`bim_e2e`** e o Redis para o db 1; o `global-setup.ts` cria e migra o banco
(`backend/tests/e2e_db.py`, que recusa qualquer outro nome). Dados criados à mão no
banco de dev não mudam mais os resultados. Cuidado com o `reuseExistingServer`: um
backend antigo na porta 8001 (ligado a outro banco) seria reaproveitado; derrube-o antes.

**CSP (10.2):** a página roda com a CSP do app (`security-headers.ts`) e cada teste
falha se houver violação, com o Viewer falso ou o real. Só a telemetria do Viewer ao
Mixpanel é bloqueada de propósito.

## Modo real (aceite da Fase 4)
```
E2E_REAL_VIEWER=1 E2E_OBRA_ID=<id> [E2E_BASE_URL=http://servidor:porta] [E2E_MAX_LOAD_MS=15000] npx playwright test
```
Usa o Viewer v7 e o APS de verdade, clica no centro do modelo, confere o painel e
falha se o modelo levar mais que `E2E_MAX_LOAD_MS` para aparecer. O tempo sai no
terminal e nas anotações do relatório (`npx playwright show-report`).

## Reconciliação (Fase 7)
- O seed cria também a obra **E2E-REV** (fixtures `revisao_v1` → `revisao_v2`, os 7 casos).
  O teste "aceite da Fase 7" roda o seed de novo para começar do estado "v2 acabou de
  chegar": PP001 a revisar (40x60 → 40x80) e PP004/PP005 órfãs.
- Com o Viewer real, na obra criada por `backend/tests/real_revisions.py --create-obra`:
```
E2E_REAL_VIEWER=1 E2E_OBRA_ID=<id> E2E_REC_OBRA_ID=<id> npx playwright test -g "Viewer real"
```
