# Coordenadas do eixo da peça (spike, 2026-11-16)

**Pergunta:** mostrar X, Y, Z do **eixo** da peça clicada (não do ponto clicado), relativos
ao **ponto base do projeto** do arquivo aberto. O clique só identifica a peça (instância de
montagem).

**Situação:**
- **Método pronto e conferido entre formatos:** RVT × IFC até 0,01 mm; NWD × IFC até 0,01 mm
  nas peças que existem nos dois.
- **Falta a comparação com o Revit:** os valores medidos no Revit não vieram no pedido (os
  campos `[pilar: …]` estavam em branco). Abaixo estão as peças e os valores a conferir.

Spike em [spikes/coordenadas](../spikes/coordenadas/README.md). **O app não foi alterado**,
nem as opções de carga do Viewer.

## 1. Conversão Viewer → arquivo → ponto base do projeto

### Opções de carga atuais (as do app)
`GuiViewer3D`, `doc.getRoot().getDefaultGeometry()` e `viewer.loadDocumentNode(doc, node)`
**sem opções**. O Viewer, então:
- **centraliza** o modelo: `globalOffset` = centro da caixa do modelo, diferente em cada
  arquivo e em cada versão;
- não aplica o ponto de referência: `applyRefPoint: false`;
- deixa a `placementTransform` como identidade.

As coordenadas de mundo do Viewer são as do arquivo **menos** o `globalOffset`.

### O que cada arquivo traz (lido no Viewer)

| Arquivo | Unidade do modelo | `globalOffset` (unidade do modelo) | Ponto de referência |
|---|---|---|---|
| ORC.rvt (v2 = R02) | ft (0,3048 m) | 300,1611; 80,2311; 21,7356 | `aecModelData.refPointTransformation` = **identidade**; `custom values.refPointTransform` = identidade; `angleToTrueNorth` = 0; `georeference.positionLL84` = (-47,9167; -15,8667) (Brasília) |
| ORC.ifc | cm (0,01 m) | 5983,997; 3912,2305; 622,5 | sem `refPointTransformation` no AEC (só níveis e grids); `refPointTransform` = identidade |
| 9480.ifc | cm | 203,6817; 5708,0962; 1083 | idem |
| 9480.nwd | ft | -19,9319; 146,4807; 38,4488 | `refPointTransform` = identidade; **`nwModelToWorldTransform`**: translação (-263,0801; 89,1924; 4,4291) ft = **(-80187,8; 27185,8; 1350,0) mm** |

O AEC do Revit (`Document.getAecModelData`) traz:
- `levels`, com as cotas: TÉRREO 0, Nível 2 3000, EMBARQUE 5200, DESEMBARQUE 9200, COBERTURA 15000 mm;
- `grids`;
- `phases`;
- `refPointTransformation`;
- `locationParameters` (só o nome do lugar).

**Não há um campo "ponto base do projeto" próprio.** O único dado de posição é a
`refPointTransformation`, que é identidade nos arquivos testados.

### Fórmula

```
modelo  = mundo_Viewer + globalOffset                    (unidade do modelo)
pbp     = Rᵀ · (modelo − t)                              (R, t = refPointTransformation:
                                                          colunas X, Y, Z e origem)
mm      = pbp × escala                                   (ft → 304,8; cm → 10; m → 1000)
```

`escala` = `model.getUnitScale()` × 1000. A ordem de `R, t` (hipótese A, acima, ou a inversa,
B: `pbp = R·modelo + t`) só se confirma com um arquivo em que o ponto base esteja deslocado
e girado; com a identidade, as duas dão o mesmo. O spike mostra as duas.

**Consistência entre formatos:** sem nenhuma transformação extra, RVT, IFC e NWD dão a mesma
coordenada para a mesma peça (tabelas abaixo). A `nwModelToWorldTransform` do NWD **não**
é aplicada para isso bater com o IFC.

**O Z confere com os níveis do AEC:**
- o topo dos pilares da R02 sai em 5200 = EMBARQUE;
- a meia altura das vigas de 80 cm sai em 4800, com o topo em 5200.

**Hipótese a confirmar no Revit:** como a `refPointTransformation` é identidade, as
coordenadas "do arquivo" acima são relativas à **origem interna** do Revit. Elas serão
relativas ao **ponto base do projeto** se ele estiver na origem interna. Se não estiver, a
diferença entre a medida do Revit e a do spike é a posição do ponto base (uma translação, e
uma rotação se houver), e entra no lugar de `t`/`R` na fórmula.

## 2. Eixo da peça (método)

Implementado em `spikes/coordenadas/axis.js` (puro, testado com peças sintéticas inclinadas,
giradas em planta, com consolo, dente e neoprene).

1. **Clique → peça.**
   - Do nó clicado, sobe até o elemento. Os sólidos do IFC (`IfcExtrudedAreaSolid::…`) e os
     nós intermediários não têm categoria nem classe.
   - Do elemento, sobe até a **montagem**, se houver (`Montagem…`, `IfcElementAssembly`).
2. **Membro principal de concreto.**
   - Na montagem, cada elemento filho é um membro.
   - Ficam fora: armaduras, alças, esperas, emendas, insertos, conexões, neoprene e aberturas
     (`IfcOpeningElement`).
   - Entre os de **material concreto** (no elemento ou nos sólidos dele), vale o de maior
     volume da malha.
   - A geometria do membro junta todos os sólidos de concreto dele: o engastamento e o
     consolo entram.
3. **Geometria:** triângulos de cada fragmento do membro.
   - A malha do SVF2 vem **normalizada**: a posição é a matriz da lista de fragmentos
     (`getFragmentList().getWorldMatrix`), não a do objeto de render.
   - No Viewer, `enumNodeFragments` e `enumNodeChildren` **param** se o callback devolver um
     valor verdadeiro.
4. **Direção principal (PCA):**
   - usa os momentos **exatos** da superfície de cada triângulo, ∫x dA e ∫x·xᵀ dA (usar só os
     centroides desvia a direção alguns mm);
   - depois refina o eixo com 9 cortes perpendiculares ao longo da peça, mantendo só os de
     **menor seção** (o corpo prismático; consolo e dente aumentam a seção);
   - a reta do eixo passa pelos centros desses cortes. Funciona com peça inclinada e girada
     em planta.
5. **Extremos:**
   - ao longo do eixo, cortando de fora para dentro;
   - descarta o trecho cuja seção é menor que 20% da do corpo: no RVT o SVF2 junta o
     **neoprene** da família ao concreto numa malha só (25 mm além da ponta da viga).
6. **Pontos:**
   - **Pilar:** X, Y = centro da seção (no eixo); Z = base (pé do eixo, inclusive o
     engastamento). O topo também é mostrado.
   - **Viga:** início e fim do eixo longitudinal, na meia altura da seção.
   - **Laje:**
     - normal = menor direção da PCA;
     - X, Y = centro da caixa orientada em planta;
     - Z = face inferior.

Tipo pela categoria (Revit pt/en, classe IFC); sem categoria, pela forma.

## 3. Resultados

### Mesmo projeto em RVT e IFC (ORC, R02)

As coordenadas são do arquivo, em mm (origem interna do Revit; ver a hipótese acima).

| Peça (ElementId) | Ponto | RVT | IFC | maior diferença |
|---|---|---|---|---|
| Pilar 6657283 (60×60) | base | -73175,4; 141594,4; -1400,0 | igual | 0,01 mm |
| Pilar 6657308 (60×60) | base | -26213,8; 102934,1; -1400,0 | igual | 0,00 mm |
| Viga 6657266 (40×80) | início · fim | -66726,8; 151958,7; 4800,0 · -58764,1; 147361,4; 4800,0 | igual | 0,01 mm |
| Viga 6658541 (40×80) | início · fim | 161593,4; 40084,6; 4800,0 · 170788,0; 40084,6; 4800,0 | igual | 0,01 mm |
| Piso 6665472 (moldado, 290 × 228 m) | centro inferior | 65193,7; 51567,3; 4865,0 | 65146,5; 51503,8; 4864,5 | 79 mm (*) |

(*) O piso é a laje moldada do pavimento inteiro, com capa e aberturas, não uma laje
pré-moldada: o centro da caixa muda com as aberturas e a capa, que o IFC separa e o RVT
junta. **Falta uma laje pré-moldada para validar a regra de laje** (o ORC não tem nenhuma).

Antes de cada correção, as diferenças eram:
- **25 mm** na ponta das vigas: o neoprene, que entrava no RVT e não no IFC. Medindo o IFC
  **com** o neoprene, o resultado ficou igual ao RVT a 0,1 mm, o que confirma a causa;
- **1400 mm** na base dos pilares do IFC: o engastamento é um sólido separado no IFC.

### Mesmo modelo em NWD e IFC (9480, com montagens e vínculos)

- **Pilar 5424311:** o vínculo do Revit se repete, e o mesmo ElementId aparece em 17
  ocorrências no NWD e 15 no IFC.
  - 14 ocorrências coincidem a ≤ 0,01 mm (base e topo).
  - Uma tem a base igual e o topo 600 mm maior no IFC, onde o corpo vem como
    `IfcFacetedBrep`: a geometria exportada difere.
  - Uma difere 7,6 mm em planta, com mesma seção e mesmo comprimento: provavelmente uma
    mudança no modelo entre as duas exportações.
  - Duas existem só no NWD.
- **Viga 5717172**, girada em planta: início e fim iguais a 0,00 mm.
- **Clique num membro da montagem** (alça, espera, consolo): o spike acha o pilar de
  concreto da montagem.

## 4. Comparação com o Revit (pendente)

Meta: até 1 mm. Para fechar, medir no Revit, com **Cota de coordenada relativa ao Ponto
base do projeto**, no `30.327-01 - MODELO - ORC.rvt` (a v2, igual à R02):

| Peça | Ponto | Spike (mm, origem interna) | Revit (mm, ponto base) | Diferença |
|---|---|---|---|---|
| Pilar 6657283 | eixo na base | -73175,4; 141594,4; -1400,0 | | |
| Viga 6657266 | início · fim (meia altura) | -66726,8; 151958,7; 4800,0 · -58764,1; 147361,4; 4800,0 | | |
| Laje pré-moldada (escolher uma) | centro na face inferior | | | |

Também ajuda saber a posição do **ponto base do projeto em relação à origem interna**: uma
cota de coordenada no ponto base com "Relativo a: Origem interna". Se não for zero, ela vira o
`t` (e a rotação, o `R`) da fórmula.

Para os arquivos NWD e IFC, vale o mesmo depois que se souber de qual referência (origem
interna, ponto base ou coordenadas compartilhadas) cada exportação saiu. Nos testados,
saíram iguais ao RVT. A `nwModelToWorldTransform` do NWD é a candidata se um dia não forem.

## 4.1 No app (2026-11-16)

Implementado conforme este documento:
- `frontend/src/viewer/coordinates.ts`: matemática e regras;
- `ApsViewerAdapter`: malha, árvore, AEC e marcador;
- seção "Coordenadas do eixo (ponto base do projeto)" no painel;
- regra de Z em `AXIS_Z_RULE`.

Os testes usam a malha real do pilar 6657283 e da viga 6657266 (até 1 mm dos valores da seção 3). A comparação com o Revit (seção 4) está como `it.todo` em `coordinates.test.ts`, esperando as medidas.

## 5. Limitações conhecidas

- **RVT:**
  - o SVF2 junta todos os materiais de um elemento numa malha (um fragmento por dbId): não dá
    para separar neoprene, capa ou concreto pelo material;
  - por isso a ponta é decidida pela seção (regra dos 20%);
  - um elemento de outra família (aninhado compartilhado) aparece separado e é tratado como
    membro.
- **IFC:** depende do exportador; uma ocorrência saiu com `IfcFacetedBrep` 600 mm diferente
  do NWD.
- **NWD:** o ElementId se repete em vínculos; para comparar formatos foi usada a peça mais
  próxima.
- `globalOffset` muda a cada carga e a cada versão: é sempre lido do modelo carregado.
- Laje: regra validada só com peças sintéticas e com um piso moldado.
