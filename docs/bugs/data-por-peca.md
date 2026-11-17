# Bug · editor de DATA por peça (tabela "Parâmetros por peça")

**Relatado em 2026-11-16**, com o parâmetro por peça "concretagem" (data) na obra 9480:
1. Digitar a data fecha a edição e grava o ano errado (05/05/0002).
2. A data não pode ser corrigida.
3. A legenda de status muda para 13 peças.

**Situação:** **corrigido em 2026-11-17** (ver docs/PROGRESS.md, "Bug · editor de data por peça"). Os testes
que reproduzem o bug, no fim de `frontend/e2e/modelo.spec.ts` ("Bug: editor de data por peça"), **passam**.
Status decidido: por peça; contam os obrigatórios, ou todos os aplicáveis quando não há obrigatórios (regra no CLAUDE.md).

## Reprodução

Playwright com o navegador em pt-BR (campo dd/mm/aaaa), obra de teste E2E-PEC, parâmetro por
peça "Data de fabricação":

| Teste | Esperado | Hoje |
|---|---|---|
| Digitar `05052026` na célula vazia | 05/05/2026, uma gravação | **05/05/0002** |
| Célula com 05/05/2026: reabrir e digitar `06062026` | 06/06/2026 | **"—"** (o valor foi apagado) |

**Diagnóstico** (registro de rede e console num teste temporário, célula com 05/05/2026):

```
clique            → editor abre com 2026-05-05
tecla "0"         → PUT 200 {"value": null, "row_version": 1}   (apagou) → editor fecha, foco no BODY
clique            → editor abre vazio
teclas "6","0","5","0" → PUT 200 {"value": "0005-06-05", "row_version": 2} → editor fecha
teclas seguintes  → caem fora do campo (o campo já não existe)
```

- **Console:** nenhum erro do editor. O único erro é um 401 de `/api/me` antes de escolher o
  usuário, normal na tela de obras.
- **Rede:** todas as gravações voltam **200**. Não houve 409 nem 422.

**O banco de dev confirma o mesmo padrão nas peças da 9480** (auditoria `piece_value`, unidade
PP318-11, 18:17–18:19):
- gravações com ano parcial: `0002-05-15`, `0002-05-01`, `0002-01-01`, `0002-11-16`, `0020-11-16`…;
- **`clear`** (valor apagado) logo depois de reabrir;
- a PP318-10 ficou com `0002-05-05`, e a PP310-1 com `0002-11-16`.

## (1) Em que evento o valor é salvo

**No `onChange` do `<input type="date">`, a cada tecla, assim que o campo tem uma data
"válida".**

- `frontend/src/features/pecas/PieceUnitsSection.tsx:24`: `SAVE_ON_CHANGE` inclui `'date'`.
  Lista e sim/não fazem sentido gravar ao escolher; data digitada não.
- `PieceUnitsSection.tsx:78`: no `onChange`, se o tipo está em `SAVE_ON_CHANGE`, chama
  `commit(v)`.
- `PieceUnitsSection.tsx:59-63` (`commit`): fecha o editor (`setEditing(null)`) e grava
  (`save.mutate(text)`).
- `frontend/src/features/params/fieldInput.tsx:21` repassa o `onChange` do input, e
  `fieldInput.tsx:50` usa `<input type="date">`.

No Chromium, o `value` do campo de data é `''` enquanto falta algum segmento, e passa a ser
`AAAA-MM-DD` assim que dia, mês e **um dígito do ano** existem. Com o ano `2`, o valor é
`0002-05-05`, que é uma data válida. O React dispara `onChange` nessa hora: grava e fecha,
e o resto da digitação ("026") se perde.

**O backend aceita o ano 0002:** `backend/app/services/mark_values.py:109-113` (`normalize`,
usado pelos valores por peça) só confere `date.fromisoformat`. Não há faixa de anos plausível.

## (2) Por que "o editor não reabre"

**Na reprodução o editor reabre.** Não é uma condição de abertura, um estado de edição preso,
um erro de API, um 409 de `row_version` desatualizado ou uma validação do backend:
- a condição de abertura é só `editing` igual à célula (`PieceUnitsSection.tsx:57`, `open`);
- o clique (`PieceUnitsSection.tsx:102`) monta o editor de novo;
- os `row_version` enviados estão certos (1, depois 2). Depois de gravar, `onSaved` atualiza o
  cache com a unidade nova (`PieceUnitsSection.tsx`, `setQueryData`).

**O que acontece é pior que "não abrir":**
1. Com uma data já gravada, o campo abre com `2026-05-05`. A primeira tecla num segmento
   (ex.: "0" no dia) deixa o campo incompleto, e o `value` vira `''`.
2. O `onChange('')` chama `commit('')`, que **apaga o valor** (`fromDraft` de `''` é `null`;
   na auditoria aparece `clear`) e fecha o editor.
3. Ao reabrir, o campo está vazio. A digitação recomeça e grava de novo assim que o ano tem um
   dígito (`0005-06-05`).

Para quem usa, parece que "não abre" ou "não deixa corrigir": cada tentativa fecha na primeira
tecla, e o foco vai para fora do campo.

**Contribui:** o `onBlur` dos tipos em `SAVE_ON_CHANGE` só fecha (`PieceUnitsSection.tsx:81`),
então não há momento em que a data completa seja confirmada. E o `disabled={save.isPending}`
do botão da célula (`PieceUnitsSection.tsx:101`) bloqueia o clique enquanto a gravação da
tecla anterior está em andamento.

**Não reproduzido aqui:** o seletor de data nativo do tablet (Android/iOS) dispara o
`onChange` só ao escolher no calendário. A digitação por teclado é que quebra. Vale conferir no
tablet real depois da correção.

## (3) Por que o status de 13 peças mudou

**O status é calculado por MARCA e aplicado a todas as peças dela. Os parâmetros por peça
entram na conta peça a peça (unidades preenchidas ÷ peças da marca), como definido no P3.**

- `backend/app/services/piece_props.py:370-380`: um status por (versão, marca), com
  `mark_status.status_of(params, categoria, valores da marca, unidades preenchidas, nº de peças)`.
- `piece_props.py:387-389`: cada peça da marca recebe o status da marca. A legenda de
  "Status de produção" **conta peças**.
- `backend/app/services/mark_status.py:76-91` (`status_of`):
  - `base = required or applicable`: **sem nenhum parâmetro obrigatório que valha para a
    categoria, todos os aplicáveis contam**, inclusive os opcionais;
  - parâmetro por peça: `started` se alguma unidade tem valor; `done` só se todas as peças
    têm;
  - algum começado e nem todos feitos dá **Parcial**.

**Na obra 9480 (id 12)**, o único parâmetro ativo é "concretagem" (data, por peça,
**opcional**), então `base = [concretagem]`:
- preencher **uma** das 13 peças da PP318 deixa `started = 1`, `done = 0`: a **marca** fica
  **Parcial**;
- as **13 peças** dela passam de Pendente para Parcial na legenda: Pendente 1.530 → 1.517 e
  Parcial 0 → 13, exatamente o observado;
- a PP310, de 1 peça, ficou "Completa" com a data `0002-11-16`.

**Isso segue a regra do P3** ("uma marca com só algumas unidades preenchidas fica Parcial"),
mas expõe duas escolhas para decidir:
1. **Status da marca ou da peça?**
   - Hoje cada peça mostra o status da marca. Com parâmetros por peça, faria sentido cada peça
     ter o seu: a PP318-10 preenchida "Completa" e as outras 12 "Pendente".
   - Isso muda o filtro "Parcial", a legenda e o progresso.
2. **Parâmetro opcional definindo status:**
   - Quando a obra não tem obrigatórios, `required or applicable` faz um opcional mudar o
     status. Isso vem da Fase 6 e vale também por marca.
   - Uma alternativa é status só por obrigatórios, ficando "sem status" ou "Pendente" quando
     não há nenhum.

Além disso, as datas inválidas gravadas pelo bug (ano 0002) **contam como preenchidas**, então
o status está errado também nessas peças.

## Dados de dev afetados (para limpar depois da correção)

Valores com ano < 1900 em `piece_values`, parâmetro 16 ("concretagem"):
- PP310-1 = `0002-11-16`;
- PP318-10 = `0002-05-05`;
- PP318-12 = `0002-05-06`.

A PP318-11 já está vazia.

## Correções sugeridas (não aplicadas)

1. **Data não grava a cada tecla:** tirar `'date'` de `SAVE_ON_CHANGE`.
   - Gravar no Enter, ao sair do campo (blur) ou ao escolher no calendário, como texto e
     número.
   - Nunca gravar enquanto o campo estiver incompleto.
   - Esc cancela.
2. **Campo incompleto não apaga:** `''` vindo de um campo de data parcialmente preenchido
   (`input.validity.badInput`) não é "apagar". Apagar só com a ação explícita de limpar.
3. **Backend:** rejeitar datas fora de uma faixa plausível (ex.: 1900–2100) em `normalize`,
   com 422 e mensagem clara. Isso vale para data por marca e por peça.
4. **Status:** decidir os itens 1 e 2 da seção (3) antes de mexer.
5. Limpar os valores de dev listados acima.
