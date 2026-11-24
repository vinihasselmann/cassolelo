# Parâmetros por peça · P0: verificação da identidade das peças

Data: 2026-11-16. Leitura do banco de desenvolvimento, sem código de produto e sem chamadas ao APS.

**Pergunta:** um valor gravado numa peça física (ex.: data de fabricação de UMA unidade de um pilar que tem 6 iguais) consegue acompanhar essa peça de uma versão do modelo para a seguinte? Com qual chave?

## 1. O que foi comparado

| Par | Versões (id) | Situação |
|---|---|---|
| ORC.rvt v1 → v2 | 5 → 14 | mesmo arquivo no Docs, 2 versões |
| REC v1 → v2 | 12 → 13 | mesmo arquivo, sincronizado duas vezes (V2 real do Docs) |
| ORC v2 → R02 | 14 → 6 | a revisão R02 salva como **arquivo novo** (o que o escritório costuma fazer) |
| ORC.rvt × ORC.ifc | 5 × 7 | mesmo modelo exportado para IFC |
| 9480 IFC × 9480 NWD | 28 × 29 | mesma obra (R00), com montagens, em dois formatos |
| E2E-REV v1 → v2 | 8 → 9 | modelo sintético dos testes (peças apagadas e recriadas de propósito) |

**Não havia** duas versões do mesmo IFC nem do mesmo NWD. A estabilidade entre versões nesses formatos foi deduzida (seção 3), não medida.

## 2. Resultados

### Revit (.rvt): o externalId é o UniqueId do elemento

| Par | Peças | Mesmo externalId | Mesmo dbId | Mesma categoria |
|---|---|---|---|---|
| ORC v1 → v2 | 359 → 359 | **359** | 359 | 359 |
| REC v1 → v2 | 359 → 359 | **359** | **146** | 359 |
| ORC v2 → R02 (arquivo novo) | 359 → 359 | **359** | **146** | 359 |
| E2E-REV (sintético) | 12 → 12 | 8 | 8 | 8 (4 apagadas e recriadas) |

- O **UniqueId sobrevive** entre versões e até no "Salvar como" de um arquivo novo (R02): 359 de 359.
- O **dbId do Viewer não serve**: mudou em 213 das 359 peças entre duas versões do mesmo arquivo.
- O UniqueId é único dentro de cada versão (359 distintos em 359, em todas as versões).
- O UniqueId **muda** quando o projetista **apaga e recria** a peça. Copiar e colar também gera uma peça nova, com UniqueId novo. É o caso das 4 peças do E2E-REV, e nele nenhuma chave de modelo salva o valor.

### IFC exportado do Revit: o GlobalId é derivado do UniqueId

- O externalId do IFC no app é o GlobalId (22 caracteres) codificado em base64.
- Recalculando o GlobalId a partir do UniqueId do Revit (o mesmo algoritmo do exportador IFC da Autodesk), **359 de 359** peças da ORC batem com o IFC.
- Consequência: um IFC exportado do Revit é **tão estável quanto o Revit**, e a mesma peça tem a mesma chave nos dois formatos.

### Montagens (9480, IFC)

- No IFC da 9480, a peça do app é a **montagem** (`IfcBuildingElementProxy::Montagem`, 1576 das 1930 peças), com GlobalId próprio; as famílias de dentro são membros.
- O GlobalId da montagem vem do UniqueId da **instância de montagem** do Revit. É estável enquanto a montagem não for desfeita e refeita, mas **desmontar e montar de novo gera uma montagem nova** (chave nova). Isso é comum quando o projetista corrige uma montagem, e precisa ser confirmado com a equipe e medido quando chegar a R01 da 9480.

### NWD (Navisworks): não há chave confiável

- O externalId do NWD é um **caminho na árvore** (`10/1/2/0/0/0`), em que o 1º número é a posição do arquivo dentro do NWD. Muda se a ordem ou o conteúdo da árvore mudar.
- As propriedades com cara de identificador **se repetem**:
  - `Item > GUID`: 1580 valores, 1465 distintos;
  - `Element > IfcGUID`: 1578 valores, 1464 distintos. Esse é um parâmetro gravado no Revit numa exportação anterior, copiado junto quando se copia o elemento.
- Nenhuma delas bate com o IFC da mesma obra: 2 de 1465. No NWD a peça do app é a família; no IFC, a montagem. São objetos diferentes.

### Quantas peças iguais por marca (9480, IFC)

- 316 marcas: 201 com 1 peça e 115 com 2 ou mais. As maiores: LA3037 ×194, LA3016 ×145, LA3011 ×142, LA3008 ×126.
- A tela de parâmetros por peça precisa aguentar marcas com **~200 unidades**: busca, rolagem e preenchimento em lote.

## 3. Conclusões

1. **Chave de identidade da peça = externalId do elemento**: UniqueId no Revit; GlobalId no IFC exportado do Revit, que é o mesmo dado em outro formato. O dbId nunca serve.
2. A chave falha quando o projetista **apaga e recria**, **copia e cola** ou **desfaz e refaz uma montagem**. Nesses casos nenhuma chave do modelo resolve. É preciso uma unidade que **exista no app** e uma forma de religar.
3. **NWD não tem chave estável.** Em obras NWD, os parâmetros por peça só podem funcionar com ligação pela ordem e conferência manual. Recomendação: parâmetro por peça só em obras **RVT ou IFC exportado do Revit**. No NWD, o app avisa e trata tudo como "ligação pela ordem".
4. **A ordem não pode ser a do dbId**, porque ele muda. A ordem de reserva precisa ser estável e sem relação com o Viewer: o **nome** do nível em ordem alfabética (não a altura: COBERTURA vem antes de TÉRREO), depois o nome do elemento, depois o externalId. Ela é arbitrária para peças realmente idênticas, mas reproduzível. *(Corrigido em 2026-11-18: a versão anterior dizia "de baixo para cima", o que o código nunca fez. A sequência de montagem fica no Excel, ordenado pelo centro de gravidade.)*

## 4. Proposta: regra de identidade das unidades de peça

- **Unidade de peça** = cada peça física de uma marca, numerada no app: PP001-1, PP001-2… O número nunca é reaproveitado e, depois de definitivo, nunca é renumerado, mesmo quando uma unidade sai.
- **Numeração pela sequência de montagem (decisão de 2026-11-18).** Ao processar a 1ª versão, a numeração é **provisória** (ordem estável do item 4). Na 1ª abertura do 3D, o navegador calcula o centro de gravidade das peças e manda ao servidor (`PUT /api/versions/{id}/centroids`). Se a versão é a mais recente e **nenhuma unidade da obra tem valor por peça**, cada marca é renumerada pela sequência Z → X → Y (crescente, faixas de 0,10 m, pelo centro de gravidade; de baixo para cima. Histórico: proposta Z → X → Y em 2026-11-18, trocada por X → Y → Z no mesmo dia, e de volta a Z → X → Y em 2026-11-19 a pedido do usuário. As obras numeradas em X → Y → Z guardam essa ordem em `obras.sequence_axes = 'xyz'`, e a ligação pela ordem das versões novas (NWD) segue a ordem da obra, para as peças e os valores não trocarem de lugar), uma única vez, como permutação dos números que a marca já tem, com auditoria por unidade (`piece_unit`/`renumber`). A obra fica `sequence` e os números passam a ser definitivos. O 1º valor por peça gravado antes disso trava a numeração como está (`fixed`). Peças novas de revisões seguintes recebem os próximos números. No Excel, as linhas ficam por marca e número; a posição de cada peça na sequência da obra vai na coluna "Ordem de montagem".
- Nas obras `sequence`, a ligação **pela ordem** (NWD; peça sem par pela chave) usa a sequência de montagem dos centros guardados, a mesma que deu os números. O reprocessamento da mesma versão leva os centros junto. Numa versão nova, as ligações pela ordem são refeitas pela sequência quando o 3D dela manda os centros.
- **Correção de 2026-11-18 na ligação pela ordem:** os valores só decidem quais unidades ficam com peça quando há menos peças que unidades. Antes, as unidades com valores iam na frente do pareamento, e um reprocessamento no NWD passava o valor da PP001-5 para a primeira peça da ordem.
- Cada unidade guarda a **chave do elemento** (externalId) ao qual está ligada. A cada versão processada, as unidades da marca são religadas assim:
  1. **por chave**: unidade cuja chave existe na versão nova continua ligada ao mesmo elemento;
  2. **pela ordem**: unidades sem par e elementos sem par **da mesma marca** são ligados na ordem estável (número da unidade × nível, nome, externalId do elemento). A ligação é marcada **"ligada pela ordem, conferir"**, e a chave da unidade passa a ser a do novo elemento;
  3. **sobrou elemento**: vira unidade nova, vazia, com o próximo número;
  4. **sobrou unidade**: se tiver valores, vira **unidade órfã**, que nunca é apagada em silêncio e pode ser religada à mão; sem valores, só fica registrada.
- A ligação acontece **dentro da marca** (obra + código + categoria), na mesma transação do `process_version`, e cada mudança de ligação vai para o audit_log.
- **Trocar a regra de identificação da obra** (a marca de cada peça muda) aplica o mesmo processo; as unidades da marca que sumiu viram órfãs, como hoje acontece com as marcas.
- Em obra **NWD**, o passo 1 não existe: tudo é pela ordem, e a tela avisa.

## 5. Proposta de texto para o CLAUDE.md (aguardando aprovação)

**Hoje (seção "Regras de arquitetura"):**

> Entidade central: MARCA = (obra, código da marca, categoria). Uma marca agrupa N peças físicas idênticas. Marcas podem se repetir entre obras. Valores de parâmetros ligam-se à marca, nunca à versão.

**Proposta:**

> Entidade central: MARCA = (obra, código da marca, categoria). Uma marca agrupa N peças físicas idênticas, cada uma uma UNIDADE DE PEÇA numerada no app (PP001-1, PP001-2…; o número nunca é reaproveitado). Marcas podem se repetir entre obras.
> Cada parâmetro da fábrica é POR MARCA ou POR PEÇA (escolhido na criação, imutável depois que houver valores). Valores por marca ligam-se à marca; valores por peça ligam-se à unidade de peça. Nunca à versão.
> A unidade liga-se ao elemento do modelo pelo externalId (UniqueId no Revit, GlobalId no IFC); nunca pelo dbId. Sem par pelo externalId, liga-se pela ordem estável dentro da marca, marcada "conferir". Unidade com valores que fica sem peça vira ÓRFÃ (nunca apagar dados em silêncio). NWD não tem chave estável: lá a ligação é sempre pela ordem.

E na regra de reconciliação, acrescentar:

> Reconciliação entre versões por obra + marca + categoria e, dentro da marca, das unidades de peça pelo externalId.

## 6. O que confirmar com a equipe antes do P1

1. **Montagens:** o projetista costuma desfazer e refazer montagens entre revisões? Se sim, a ligação pela ordem será frequente nas obras com montagens, e a tela de conferência (P5) ganha peso.
2. **Etiqueta da fábrica:** a fábrica já identifica cada unidade com uma etiqueta ou código próprio? Se sim, ele pode ser um campo da unidade, para buscar a peça pela etiqueta.
3. **R01 da 9480 (IFC):** quando estiver no Docs, processar e medir a estabilidade dos GlobalId das montagens entre R00 e R01.

## Apêndice: como reproduzir

Consultas no banco de desenvolvimento (`elements` por `version_id`):
- pares de versões: `JOIN elements eb ON eb.version_id = B AND eb.external_id = ea.external_id`, contando o mesmo dbId, a mesma categoria e a mesma marca;
- IFC × Revit: GlobalId = compressão IFC (base 64, 22 caracteres) do GUID de exportação, que é o EpisodeId do UniqueId com os últimos 32 bits em XOR com o ElementId (os 8 dígitos hexadecimais finais do UniqueId);
- NWD: `props->'Item'->>'GUID'` e `props->'Element'->>'IfcGUID'`, contando valores distintos e comparando com o GlobalId do IFC da mesma obra.
