# Plano: filtros e coloração no estilo do Dalux

Referência: `docs/filtros/referencia-dalux.md`. Escrito em 2026-11-13, depois de ler o CLAUDE.md e o código das Fases 5 (busca) e 6 (status e "Colorir por").
**Este documento não contém código.** As decisões em aberto estão no fim (§9).

---

## 1. O que já existe → o que muda

Princípio: **um único motor de filtro no backend** (`app/services/filters.py`). Busca, atalhos, exportação e coloração passam a usá-lo, e nenhuma regra fica implementada duas vezes.

| Hoje (Fases 5/6) | Onde está | Passa a ser |
|---|---|---|
| Busca livre `q` (marca, categoria, `search_text`, valor de parâmetro; sem acento) | `search._text_condition` | Campo **"Pesquisar por objetos"** do filtro, a regra `texto contém`. O SQL atual (`f_unaccent`, `_ilike`) é reaproveitado sem mudança |
| `Nome=valor` (número sem unidade, sem acento) | `search._prop_condition` / `_value_condition` | Operador `é igual a` sobre **propriedade do modelo**. O mesmo código, chamado pelo motor |
| `sem <parâmetro>` | `search.missing` | Operador `está vazio` sobre **parâmetro da fábrica** |
| Filtros Categoria (checkboxes) e Nível (select) | `SearchPanel` + `useMarkSearch` | Menus rápidos **Categoria** e **Nível** no popover; viram etiquetas removíveis |
| Atalhos Pendentes / Parciais / A revisar | `search.Shortcut` + `mark_status.marks_with_status` | **Filtros salvos padrão** ("PADRÃO-Pendentes"…) com regra `status é um de`. O cálculo de status continua só em `mark_status` |
| Atalho "Novas na versão" | `search` (`_previous_ready`) | Filtro salvo padrão com o campo de sistema **"Nova nesta versão"** |
| Atalho "Órfãs" | `search._orphans` | **Sai dos filtros.** Órfã não tem peça na versão, e a "Fila de órfãs" já cobre isso. Hoje está duplicado |
| Atalho "Todas" | — | É o estado "sem filtro" (botão **Remover filtros**) |
| "Colorir por **Status**" | `coloring.colorByStatus` + `/marks/status` | Opção **"Status"** no topo do popover **Colorir** (campo de sistema) |
| "Colorir por **Categoria**" | `coloring.colorByCategory` | Campo de sistema **Categoria** no popover Colorir |
| "Colorir por **Parâmetro**" | `coloring.colorByParam` + `/params/{id}/values` | Qualquer **parâmetro da fábrica** no popover Colorir. Também passa a valer para **qualquer propriedade do modelo** |
| Legenda clicável | `ColorLegend` | Fica como está: clicar seleciona as marcas da cor. Só muda a fonte dos dados |
| Destaque do resultado (resto esmaecido) / "Isolar" | `ViewerAdapter.highlight/isolate` | O filtro aplica uma **ação por regra**: **Isolar** (só o resultado aparece) ou **Ocultar** (o resultado some). Esmaecer o resto continua como modo de exibição |
| Exportar Excel = lista da tela | `export` usa `search.find_marks` | Usa a **definição do filtro ativo** (o mesmo JSON) |
| Lista de marcas à esquerda | `SearchPanel` | Fica. Passa a ser a **lista de resultado** agrupada por Nome da montagem, com a contagem de peças que bateram |

**O que é removido depois da migração:**
- `search.Shortcut` e o parâmetro `shortcut`: viram filtros salvos;
- os filtros de categoria e nível do `SearchPanel`;
- `ColorPanel` (o seletor Status/Parâmetro/Categoria);
- as montagens de cor de `coloring.ts` que passam para o backend (§5.4).

O endpoint `GET /marks/search` fica como **adaptador fino** (traduz os parâmetros antigos para o JSON do filtro) até o frontend migrar. Depois é removido.

## 2. Unidade do filtro

- **Unidade = a peça:** uma linha de `elements`. Com montagens, é a instância de montagem; os membros (consolos, alças) não são peças e estão em `member_dbids`.
- **As regras avaliam a peça.** As propriedades do modelo são as da peça, e no IFC isso inclui `Corpo · …`. Os parâmetros da fábrica e o status são os da marca da peça; uma marca vale para todas as suas peças.
- **O resultado é agrupado pela marca** (o Nome da montagem, pela regra de identificação da obra). Cada grupo traz:
  - **peças que bateram** / **peças da marca na versão** (ex.: "PP312 · 1 de 1"; "LA3037 · 12 de 194" num filtro por nível);
  - os dbIds das peças que bateram, para o 3D.
- **Peças sem marca entram no filtro** (hoje a busca as exclui). Ficam num grupo "(sem marca)" no fim da lista. Assim um filtro por "Junta de dilatação" funciona.
- **Isolar / Ocultar** atuam sobre as peças **e os membros delas** (`member_dbids`). Esconder um pilar esconde os consolos dele.

## 3. Campos filtráveis

Todo campo tem uma **chave** estável, um **rótulo**, um **tipo** e uma **origem**. A lista "Selecionar parâmetro" e o popover Colorir usam o mesmo catálogo de campos (`GET …/filter/fields`).

| Origem | Chave | Exemplos | Tipo |
|---|---|---|---|
| **Propriedade do modelo** | `prop:<grupo>/<nome>` | `prop:Corpo · BaseQuantities/NetVolume`, `prop:IFC Attributes/IfcSpatialContainer` | **inferido** por versão: número (todos os valores são número com unidade opcional), data (todos datas), sim/não, senão texto |
| **Parâmetro da fábrica** | `param:<def_id>` | Tipo de forma, Data de expedição | o tipo do parâmetro (texto, número, lista, data, sim/não). **Só os que valem na obra** (biblioteca incluída, ou da obra) |
| **Sistema** | `sys:category` | Categoria | lista |
| | `sys:level` | Nível | lista |
| | `sys:status` | Status de produção (pendente, parcial, completa, revisar) | lista |
| | `sys:mark` | Nome da montagem (o código da marca) | texto |
| | `sys:first_version` | Versão em que a montagem surgiu | número (versão) |
| | `sys:new_in_version` | Nova nesta versão (sem peças na versão pronta anterior) | sim/não |
| | `sys:has_mark` | Tem marca | sim/não |

- **Propriedades com o mesmo nome em grupos diferentes** aparecem separadas no seletor, com o grupo em cinza. A busca no seletor ignora acentos.
- **O tipo das propriedades** é calculado no processamento da versão e gravado com a lista de nomes (§4.3). Isso evita adivinhar a cada consulta.

## 4. Formato, operadores, tabelas

### 4.1 JSON do filtro (versão 1)

```json
{
  "v": 1,
  "text": "pp3",
  "rules": [
    { "action": "isolate", "field": "sys:category", "op": "in", "value": ["Pilares estruturais"] },
    { "action": "isolate", "field": "param:12", "op": "between", "value": ["@month_start", "@today"] },
    { "action": "hide",    "field": "prop:Corpo · BaseQuantities/NetVolume", "op": "lt", "value": 0.1 }
  ]
}
```

- `text`: "Pesquisar por objetos". Cada palavra precisa aparecer (regra atual da busca).
- **Combinação**, igual ao Dalux: resultado = peças que batem **em todas** as regras `isolate` (E), **menos** as que batem em **alguma** regra `hide`.
  - Sem regras `isolate`, o ponto de partida são todas as peças.
  - Regra com valor vazio é ignorada: é a "linha vazia" do Avançado.
- `value` pode ter **valores relativos**, resolvidos no servidor com `DISPLAY_TIMEZONE`: `@today`, `@month_start`, `@month_end`, `@days:-30`, `@active_version`. É isso que faz "Peças expedidas **no mês**" funcionar todo mês sem editar o filtro.
- `"v"` permite mudar o formato no futuro, com migração dos filtros salvos.
- A validação fica no backend (Pydantic): campo inexistente, operador incompatível com o tipo e valor inválido dão 422 com mensagem em português.

### 4.2 Operadores por tipo

| Tipo | Operadores |
|---|---|
| Texto | é igual a · é diferente de · contém · não contém · começa com · é um de · está vazio · não está vazio |
| Número | = · ≠ · > · ≥ · < · ≤ · entre · está vazio · não está vazio (valor aceita unidade, igual ao `Nome=valor` atual) |
| Data | é em · antes de · depois de · entre · nos últimos N dias · neste mês · está vazio · não está vazio |
| Lista (parâmetro lista, categoria, nível, status) | é um de · não é nenhum de · está vazio |
| Sim/não | é sim · é não · está vazio |

Texto sempre sem diferenciar maiúsculas nem acentos (`f_unaccent`, migração 0009).

### 4.3 Tabelas novas e mudanças (migração 0013)

- **`saved_filters`**: filtros salvos, compartilhados.
  - Colunas: `id`, `scope` (`obra` | `global`), `obra_id` (nulo no global), `name`, `definition JSONB`, `position`, `active`, autoria (`created_*`/`updated_*`), `row_version`.
  - Nome único por escopo, sem diferenciar maiúsculas, só entre ativos (igual a `param_defs`).
  - `global` = os **PADRÃO-…** da empresa, que aparecem em todas as obras.
  - Exclusão lógica. Toda alteração vai para `audit_log` (`saved_filter`).
- **`color_rules`**: a janela "Cores", por obra.
  - Colunas: `obra_id`, `position`, `saved_filter_id`, `color` (`#RRGGBB`), autoria. PK `(obra_id, position)`.
  - Salvar substitui a lista inteira numa transação, com `row_version` da obra para não sobrescrever a edição de outro usuário.
  - A ordem define a prioridade: a peça fica com a cor da **primeira** regra cujo filtro ela satisfaz.
- **`marks.first_version_id`**: versão em que a marca surgiu.
  - Preenchido no `process_version` quando a marca ganha peças pela primeira vez.
  - Backfill na migração: a menor versão com elementos da marca.
- **`version_property_names`** ganha:
  - `value_type` (texto, número, data, sim/não);
  - `pieces` (quantas peças têm a propriedade);
  - `distinct_values` (quantos valores diferentes).
  Calculados no processamento. Sustentam o seletor de campos e a coloração sem varrer o JSONB.
- **Seed dos filtros PADRÃO** na migração: Pendentes, Parciais, A revisar, Completas, Novas nesta versão. Assim os atalhos de hoje continuam lá, agora como filtros.

### 4.4 Endpoints

| Método e rota | Faz |
|---|---|
| `GET /api/versions/{id}/filter/fields?q=` | Catálogo de campos (§3): chave, rótulo, grupo, tipo, nº de peças. Pesquisável |
| `GET /api/versions/{id}/filter/values?field=&q=` | Valores distintos de um campo, com contagem de peças (menus rápidos, lista de valores no Avançado, legenda). Limite de 200 |
| `POST /api/versions/{id}/filter` | Avalia o JSON → grupos (marca, peças que bateram / total), paginado; `dbids` e `member_dbids` do resultado inteiro (para o 3D); totais. Substitui `/marks/search` |
| `POST /api/versions/{id}/coloring` | Coloração: `{field, ranges?}` (por valor, ou **por gama** com N faixas entre mín. e máx.) ou `{rules: true}` (as Cores da obra) → grupos `{rótulo, cor, nº de marcas, nº de peças, dbids}` |
| `GET/POST/PATCH/DELETE /api/obras/{id}/saved-filters` | Filtros salvos da obra + os globais (somente leitura aqui); reordenar com `PATCH position` |
| `GET/POST/PATCH/DELETE /api/saved-filters` | Filtros PADRÃO (globais) |
| `GET/PUT /api/obras/{id}/color-rules` | Tabela "Cores" (lista ordenada inteira) |
| `POST /api/obras/{id}/export.xlsx` | Passa a receber o JSON do filtro ativo (hoje recebe os parâmetros da busca) |

- Leitura: todos os papéis.
- Escrita de filtros e Cores: **ver §9.1**.
- Eventos SSE novos: `saved_filter_changed` e `color_rules_changed`, para as outras abas atualizarem.

## 5. Interface (React)

### 5.1 Barra inferior do visualizador (`ViewerToolbar`)
- Botões: **Filtro ▾** · **Medida** · **Ampliar tudo** · **Editar cores** · **Colorir ▾**.
- À direita, só quando houver algo ativo: **Remover filtros** · **Remover coloração**.
- Substitui a barra atual (Enquadrar tudo / Enquadrar seleção / Isolar / Limpar seleção / Seleção múltipla). "Enquadrar seleção" e "Isolar" passam para a mini barra (§5.5). Limpar seleção e Seleção múltipla ficam onde já estão, na lateral.

### 5.2 Popover **Filtro** (`FilterPopover`)
- **Filtros salvos:** lista (PADRÃO primeiro, depois os da obra). Clicar aplica.
- **Pesquisar por objetos:** é o `text` do JSON.
- **Menus rápidos:** Categoria e Nível, com valores e contagens vindos de `filter/values`. "Arquivo" não se aplica: a obra tem um arquivo (ver §9.3).
- **Etiquetas** das regras ativas, cada uma com ×. O texto é gerado da regra: "Data de expedição neste mês ×".
- **+ Adicionar filtro** → `FieldPicker` ("Selecionar parâmetro": lista pesquisável de §3, agrupada por origem).
- **Avançado** → `FilterEditorDialog` ("Editar filtro"): linhas `[Isolar|Ocultar] [campo] [operador do tipo] [valor] [×]`, uma linha vazia no fim, **Cancelar / Aplicar**.
- **Salvar ▾:** "Salvar como novo…", "Atualizar «nome»", "Renomear", "Excluir".

### 5.3 Estado único do filtro (`useActiveFilter`)
- Guarda o JSON ativo. **A busca da coluna esquerda edita o mesmo `text`**: são duas entradas para um estado só, sem lógica duplicada.
- `searchQuery.parseQuery` vira um tradutor de atalhos de digitação para regras: `Nome=valor` vira regra de propriedade; `sem X` vira "X está vazio".

### 5.4 Popover **Colorir** e janela **Cores**
- **`ColorPopover`:** "Status" fixo no topo, depois o mesmo `FieldPicker`. A caixa **"Cor por gama"** só fica ativa para campos numéricos e de data. A legenda continua a `ColorLegend`.
- **`ColorRulesDialog` ("Cores"):** tabela de cor + filtro salvo. Botões Adicionar, Editar, Remover, Mover para cima/baixo, Cancelar e Salvar.
- **A coloração passa a ser calculada no backend** (`/coloring`), um caminho só para status, parâmetro, propriedade e Cores. Em `coloring.ts` ficam as paletas e a conversão para `Map<dbId, cor>`.
- **Colorir por campo e Cores são exclusivos:** ativar um substitui o outro. Isso evita duas camadas de cor ao mesmo tempo (ver §9.4).

### 5.5 Mini barra da peça e atalhos (`PieceMiniBar`)
- Ao clicar numa peça: **Ocultar**, **Isolar**, **Corte** (caixa de corte em volta da peça) e Enquadrar.
- Teclado: **H** oculta a seleção; **Espaço** amplia nela; **Esc** limpa. Os atalhos não disparam quando o foco está num campo de texto.
- **`ViewerAdapter`** ganha `hide(ids)`, `sectionBox(ids)`, `clearSection()` e `toggleMeasure()`. Só o `ApsViewerAdapter` conhece as extensões do Viewer (Autodesk.Measure, Autodesk.Section), como manda o CLAUDE.md.

## 6. Etapas de entrega

Cada etapa sai com testes, lint, typecheck e o PROGRESS.md atualizado.

1. **Motor e campos (backend):**
   - migração 0013 (tipos de propriedade, `first_version_id`);
   - `filters.py`;
   - `filter/fields`, `filter/values`, `POST filter`;
   - `/marks/search` e a exportação passam a delegar ao motor.
   Os testes atuais de busca têm de passar sem mudança; isso prova a equivalência.
2. **Filtros salvos:** tabela, CRUD, seed PADRÃO, `FilterPopover`, `FieldPicker`, `FilterEditorDialog`, etiquetas. Saem os atalhos e os filtros da coluna esquerda.
3. **Coloração:** `/coloring` (campo, gama, status), `ColorPopover`, tabela e janela **Cores**. Sai o `ColorPanel`.
4. **Visualizador:** `ViewerToolbar`, mini barra, Ocultar/Isolar/Corte/Medida, atalhos H/Espaço, Remover filtros/coloração. E2E com o Viewer falso e aceite no Viewer real (IFC da 9480).

## 7. Testes previstos
- **Motor:** cada operador × cada tipo; valores relativos de data (fuso, virada de mês); Isolar e Ocultar combinados; regra vazia ignorada; texto sem acento; número com unidade; campo de parâmetro fora da obra → 422.
- **Equivalência:** a suíte atual de `test_search.py` rodando sobre o motor novo.
- **Agrupamento:** contagem "bateram / total" por marca; grupo "(sem marca)"; `member_dbids` no resultado.
- **Filtros salvos e Cores:** papéis, nome único, auditoria, `row_version`, SSE, a ordem das Cores define a cor.
- **Desempenho:** a mesma base de `test_search_perf.py` (20.000 peças / 2.000 marcas) e uma de **100.000 peças**, com limite de 1 s por chamada (`filter`, `coloring`, `fields`, `values`).
- **Frontend:** Vitest dos popovers, do editor, das etiquetas, de `useActiveFilter` e dos atalhos de teclado; Playwright: aplicar um PADRÃO, Isolar/Ocultar, colorir por gama, Cores com prioridade.

## 8. Riscos de desempenho e como tratar

| Risco | Tratamento |
|---|---|
| Filtrar propriedades do modelo varre o JSONB das peças (`jsonb_extract_path_text` + conversão de número/data por linha); sem índice útil para `>`/`entre` | Sempre limitado à versão (índice `version_id`); 20 mil peças hoje respondem em < 150 ms. Medir com 100 mil. **Se passar de 1 s:** tabela derivada `element_values` (peça, chave, texto, número, data), gerada no processamento, com índices por (versão, chave, número/data) |
| Catálogo de campos e valores distintos sobre todo o JSONB | Pré-calculado no processamento (`version_property_names.value_type/pieces/distinct_values`); `filter/values` limitado a 200 valores, com busca |
| Filtro por status calcula o status de todas as marcas em Python (`mark_status`) | Medido em < 1 s para 2 mil marcas. Cache por (versão, `max(param_values.updated_at)`), invalidado pelo SSE `values_changed` |
| Coloração por propriedade com muitos valores distintos (ex.: GUID) | Até 20 cores + "Outros"; o seletor avisa "valores demais, use Cor por gama" |
| Muitos dbIds no 3D (20 mil peças + membros) em `isolate/hide/setColors` | Uma chamada em lote ao Viewer (já é assim); usar os nós das peças (o Viewer aplica aos filhos) em vez de listar todos os membros quando possível; medir no tablet |
| Filtros salvos com datas relativas mudam sozinhos | Resolvidos no servidor a cada avaliação (a resposta diz a data usada); nunca guardar a data já resolvida |
| Definições antigas quebram quando um parâmetro é excluído ou retirado da obra | O filtro salvo continua; a regra órfã aparece em vermelho ("parâmetro não está mais nesta obra") e é ignorada na avaliação, nunca silenciosamente |

## 9. Decisões em aberto (para o usuário)
1. **Quem cria e edita** filtros salvos e Cores da obra? E os **PADRÃO** globais (sugestão: só admin)?
2. **Busca na coluna esquerda:** manter o campo lá (ligado ao mesmo estado do filtro, mais prático no tablet) ou deixá-lo só no popover, como no Dalux?
3. **Menu "Arquivo":** no Dalux ele separa os modelos de um projeto. Aqui cada obra tem um arquivo. Omitir, ou trocar por **Versão** (comparar com versões anteriores)?
4. **Colorir × Cores:** exclusivos (recomendado) ou as Cores por cima da coloração por campo?
5. **Filtros pessoais:** além dos compartilhados da obra, cada usuário pode ter os seus? (O Dalux tem os dois.) Isso só faz sentido depois do login real (Fase 11).
6. **Roadmap:** isso entra como uma fase nova (ex.: "5b · Filtros e coloração") antes do piloto?
