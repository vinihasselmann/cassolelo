# Montagens no Docs: IFC e NWD da obra 9480 (2026-11-13)

Arquivos analisados, todos no projeto TESTE PLATAFORMA FABRICA > Project Files:
- `9480-EST-MON-SE3-PRO-R00.ifc`: v1, 10.058 objetos;
- `9480-EST-MON-SE3-PRO-R00.nwd`: v1, 21.408 objetos.

A análise usou só GETs (versões, manifest, metadata, árvore e propriedades). Os dois manifests estão `success`, com saída do tipo `svf`.

## Como a montagem aparece

### IFC
- Cada **instância de montagem é um nó** `IfcBuildingElementProxy`:
  - `IFC Attributes > ObjectType` = `Montagem <Categoria de nomenclatura>:<Nome da montagem>` (ex.: `Montagem Pilares estruturais:PP312`);
  - `Tag` = id do elemento no Revit.
- Os **membros** (pilar, consolos, alças, esperas, neoprene, emendas) são filhos desse nó. Cada membro tem `IfcDecomposes` = o nome da montagem.
- Totais: **1.531 montagens** (1.456 Quadro estrutural, 54 Pilares estruturais, 21 Conexões estruturais), com 316 nomes.
- Ficam **fora de montagens** 399 elementos soltos:
  - consolos soltos (68), juntas de dilatação (48), parafusos, porcas e arruelas, Viga-R (33), escadas (15).
- Também há `IfcGroup` ("Grupo de modelos": juntas, canecos).
- Não existe a propriedade "Nome da montagem" nem "Marca".

### NWD (Navisworks do .rvt central com vínculos)
- O 1º nível da árvore são os **vínculos** (`9480-E1312.rvt : 148 : localização Interno`) e os níveis do modelo central.
  - 125 vínculos têm **exatamente uma** montagem: é o caso "um vínculo por peça".
  - 2 vínculos têm duas montagens (`PP308a/b`, `PP304a/b`).
  - O vínculo das lajes (`9480-LAJ-…`) tem 229 nomes de montagem, com peças idênticas repetidas.
- **Não existe um nó de montagem.** Dentro do vínculo, os membros ficam espalhados por categoria (Conexões estruturais, Enrijecedores, Quadro estrutural, Pilares estruturais…). Cada membro tem `Element > Nome da montagem`.
- O "corpo" de concreto da peça é a instância das famílias `CASSOL-PREO-*` em **Quadro estrutural** (lajes alveolares, vigas R/T/L) ou **Pilares estruturais**. Os consolos (`CASSOL-PREO-Consolo`) são **Conexões estruturais**, membros do pilar.
- `Marca` aparece em poucos elementos (255) e com outro sentido (consolos `C14`, vínculos `28`).

## O que a extração atual faz (por isso precisa mudar)
| Arquivo | Regra atual | Resultado |
|---|---|---|
| IFC | qualquer | 1.953 "peças" (cada montagem e cada elemento solto); **0 marcas**, porque o nome só existe dentro de `ObjectType` |
| NWD | Marca ou Nome da montagem | 265 "peças": vínculos, níveis e conexões, nunca as montagens |

## Contagem por nome: IFC × NWD (os dois deveriam bater)
| Prefixo | Peças IFC | Corpos de concreto NWD | Nomes com contagem diferente |
|---|---|---|---|
| PP (pilares) | 55 | 56 | 8 de 24 |
| VP (vigas) | 167 | 168 | 3 de 32 |
| VA (vigas) | 121 | 157 | 39 de 67 |
| LA (lajes) | 1.168 | 1.180 | 51 de 236 |
| EC / LM / E (escadas…) | 20 | 0* | todos |

\* No NWD as escadas não estão em Quadro estrutural nem em Pilares estruturais (falta definir a categoria delas).

Os pilares e as vigas VP quase batem. Já as lajes e as vigas VA divergem por nome: `LA3011` tem 142 montagens no IFC e 1 corpo no NWD; `LA3037` tem 194 contra 191.
**É preciso confirmar se o IFC e o NWD saíram do mesmo estado do modelo.** Uma renumeração das montagens entre as duas exportações explicaria isso.

## Decisões do usuário (2026-11-13)
1. IFC e NWD vieram do mesmo arquivo (NWC exportado e salvo como NWD). As diferenças nas lajes e nas vigas VA continuam abertas.
2. As categorias do corpo da peça são **Pilares estruturais** e **Quadro estrutural** (vigas e lajes alveolares). Escadas são componentes de **Conexões estruturais**.
3. Consolos de pilar costumam ser membros das montagens.
4. Viewer: conferido (abaixo).

## Regra implementada
- **IFC (automático):** a peça é o `IfcBuildingElementProxy` cujo `ObjectType` começa com `Montagem `.
  - O nome e a categoria de nomenclatura viram a propriedade sintética `Montagem > Nome da montagem` / `Category`.
  - Os filhos (membros) ficam em `elements.member_dbids`.
  - `IfcGroup` não é peça.
  - Elementos fora de montagens continuam como peças sem marca e aparecem no relatório.
- **NWD/.rvt (modo montagens da obra, aba "Identificação das peças"):** implementado em `app/services/assemblies.py`.
  - As instâncias são agrupadas por (vínculo, Nome da montagem).
  - **Corpo** = instância de Pilares estruturais ou Quadro estrutural; cada corpo é uma peça.
  - Montagem sem corpo (escada, laje maciça) = 1 peça.
  - Num vínculo com uma montagem só, **a peça é o nó do vínculo**: no 3D destaca tudo, consolos incluídos. As propriedades vêm do corpo.
  - A "Marca" do próprio vínculo (ex.: `28`) é ignorada.
  - Níveis, ambientes e vínculos sem montagem não são peças.
- Regra da obra: `Nome da montagem`.
- **Clique em qualquer parte:** `elements.member_dbids` (migração 0011). A API acha a peça pelo dbId de um membro, e `/marks` leva os membros para o índice do 3D.

## Resultado com os arquivos reais (processados pelo worker, 9 s)
| | IFC (obra 12) | NWD (obra 13) |
|---|---|---|
| Peças / marcas | 1.930 / 316 | 1.580 / 358 |
| Sem marca | 399 (elementos soltos: consolos, juntas, parafusos, vigas R/L) | 1 |
| PP312 | 1 peça, 59 membros | 1 peça (nó do vínculo), 199 membros |
| LA3037 | 194 | 191 |
| Clique num membro → peça | ✓ (API e Viewer real) | ✓ na API; ✗ no Viewer real (abaixo) |

## Viewer real (manifest `svf`)
- O ORC.rvt, que já funcionava, também aparece como `svf` no manifest. Isso é só como o Docs descreve a saída.
- **IFC:** abre em ~5 s no desktop e em 19 s no tablet emulado (acima do limite de 15 s do teste). O clique numa alça (membro) selecionou a marca da laje (LA3155, 37 peças).
- **NWD:** abre em ~4 a 6 s. **O clique não funciona:**
  - os **Ambientes** do Revit (volumes de sala, 17 elementos por nível) ficam por cima das peças e recebem o clique;
  - mesmo escondendo os Ambientes, o Viewer não devolveu seleção ao clicar numa viga.
  Precisa de investigação: modo de seleção do Viewer para NWD, ou esconder o que não é peça. Outra opção é exportar o NWD sem Ambientes.

## Pendências
- Clique no Viewer para o NWD (acima).
- ~~IFC: 399 elementos fora de montagens~~: confirmado pelo usuário (2026-11-13) que são insertos, juntas de dilatação etc. e **não têm marca mesmo**. Ficam como peças sem marca (clicáveis no 3D, listadas no relatório).
- NWD: gerar de novo **sem a geometria dos Ambientes** (passo a passo passado ao usuário) e publicar com o mesmo nome (v2), depois repetir o teste de clique no Viewer real.
- Lajes (51 nomes) e vigas VA (39 nomes) com contagens diferentes entre IFC e NWD.

## Decisão: o formato é o IFC (2026-11-13)
O usuário decidiu ignorar o NWD. A obra 13 (NWD) foi **desativada** no banco de dev, sem apagar nada. O código do modo montagens do NWD/.rvt continua no app e testado, mas sem uso.

Ajustes no IFC:
- **Corpo da peça** = o membro de **maior volume** (pilar, viga, laje, escada). As propriedades dele entram na peça como `Corpo · <grupo>`, antes das do nó da montagem. Assim tipo e seção (`ObjectType`, ex.: `R-30x50cm`) e volume valem para a busca, a validação e a revisão entre versões.
- **Dimensões padrão:** sai `Length,Width,Height`, entra `NetVolume`.
  - No IFC exportado, peças idênticas vêm com Length e Width **trocados** (LA3016: 469,5 × 0,08 cm em umas, 0,08 × 469,5 em outras) e GrossVolume errado junto. O NetVolume é igual.
  - No IFC o comprimento do pilar não vem; uma mudança de comprimento aparece no volume.
- **Busca `Nome=valor`:** aceita unidade com expoente (`NetVolume=2.504` acha `2.504 m^3`).

Resultado na obra 12 (IFC), reprocessada pelo worker em 4 s:
- 1.930 peças, 316 marcas, 399 sem marca (insertos, juntas: não têm marca mesmo), **0 inconsistentes**;
- "30x50" acha PP311 a PP315.

Viewer real: abre em ~6 s no desktop e ~11 s no tablet emulado. O clique num membro selecionou VA3074. O teste do Viewer real passa (3/3).
