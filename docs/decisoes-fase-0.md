# Decisões e resultados da Fase 0 · Spike APS/Docs

> **Status (2026-11-11): parcialmente preenchido com testes reais.** Acesso, leitura do
> .rvt, viewer e pipeline do app foram validados contra o Autodesk Docs. Ficam
> pendentes: .nwd, comparação entre versões e licença (webhooks adiados para o servidor definitivo; catálogo começa vazio por decisão).

## 1. Acesso ao ACC

| Item | Resultado |
|---|---|
| Client ID liberado em Custom Integrations (data / quem liberou) | 2026-11-11, pelo responsável do ACC da Cassol. Token 2-legged (`data:read viewables:read`) funcionando. |
| Região dos dados (US / EMEA) | US (`APS_REGION=US`). |
| `list_docs.py` mostra o projeto de teste e a pasta dos modelos | Sim. Hub "Cassol Pré-Fabricados" (8 projetos visíveis); projeto **TESTE PLATAFORMA FABRICA** > Project Files > `30.327-01 - MODELO - ORC.rvt`. |

## 2. Formatos testados (`read_model.py` + viewer)

| Formato | Arquivo / versão | Conversão automática no Docs? | Tempo até `success` | JSON gerado | Abre no viewer | Marca lida? | Contagem por categoria = quantitativo do Revit? |
|---|---|---|---|---|---|---|---|
| .rvt | `30.327-01 - MODELO - ORC.rvt` v1 (publicado 2026-11-11 13:59 UTC) | **Sim** (manifest `success`, SVF2, sem POST /job) | < 3 min (já estava `success` na primeira leitura) | Sim (`spikes/out`, 1,9 MB; leitura completa em 14 s) | **Sim** (Viewer v7 no app: 4–6 s no desktop, 6–8 s no tablet emulado, Chromium headless, rede do escritório) | Campo existe, mas **vazio** (modelo de orçamento) | 213 Quadro estrutural · 145 Pilares estruturais · 1 Pisos = 359. **Conferir com a tabela do Revit.** |
| .nwd | _pendente (não publicado)_ | | | | | | |
| .ifc | `30.327-01 - MODELO - ORC.ifc` v1 (exportado do .rvt) | **Sim** (SVF2, `success`) | < 3 min | Sim | não testado no viewer ainda | Não há Marca no IFC (o .rvt de origem também não tem) | **359 = 145 IfcColumn + 213 IfcBeam + 1 IfcSlab**, iguais ao .rvt; níveis também iguais |

Diferenças de contagem encontradas e explicação: nenhum componente aninhado neste
modelo. **Bug encontrado e corrigido:** no Revit a árvore é Model > categoria > família >
TIPO > instâncias, e parâmetros de tipo (ex.: "Marca de tipo") aparecem no nó do tipo e
nas instâncias. A regra antiga transformava o tipo em "peça" (9 em vez de 359). Regra
nova: se a propriedade que deu a marca ao nó se repete com o mesmo valor em todos os
filhos, o nó é agrupamento e a extração desce (`app/services/extraction.py`).

## 3. Parâmetro de marca

- Nome real do parâmetro no modelo: **"Marca"** (instância), presente nas 359 peças.
  Também existe "Marca de tipo" (V05, P01…), que **não** serve como MARCA: peças do mesmo
  tipo têm comprimentos diferentes (ex.: 90 vigas V05 com 23 comprimentos).
- Grupo de propriedades em que aparece: "Dados de identidade".
- Valor de `MARK_PROPERTY_NAMES` adotado: **`Marca,Mark`** (padrão, sem mudança).
- % de peças sem Marca: 100% neste arquivo, porque é um modelo de **orçamento** (as marcas
  de produção ainda não existem). Para os testes, a Marca foi simulada (pipeline ao vivo:
  `MARK_PROPERTY_NAMES="Marca,Marca de tipo"` só no worker de teste; fixture: Marca
  simulada por tipo + comprimento). Validar com um modelo de produção quando houver.
- Propriedade de categoria confiável: **a árvore** (1º nível abaixo da raiz). O SVF2 deste
  .rvt não traz propriedade "Category"; as categorias vêm em português, sem o prefixo
  "Revit ".
- Outras propriedades úteis confirmadas: nível em `Restrições > Nível base` (pilares) e
  `Nível de referência` (vigas) — EMBARQUE, DESEMBARQUE, COBERTURA, TÉRREO; tipo/seção em
  `Dados de identidade > Nome do tipo` (ex.: `I90-50x90cm-V05`).

## 4. Comparação entre versões (`compare_versions.py`)

- Versões comparadas: _pendente_. A R02 (14 pilares com Marca real: PP001×4, PP002×4,
  PP005×6; 6 pilares trocados de `R-60x60cm-P01`/660 cm para `R-80x80cm-P05`/690 cm) foi
  publicada como outro arquivo; o caso fica como cenário da Fase 7 (reconciliação). Dentro
  de cada marca as peças são idênticas: a validação corretamente aponta 0 inconsistências.
- Valor de `DIMENSION_PROPERTY_NAMES` adotado: **`SEÇÃO-Altura,SEÇÃO-Largura,PEÇA-Comprimento`**
  na frente dos nomes genéricos (valores como `660.000 cm`, lidos corretamente em mm).
- Marcas com dimensões divergentes: com a "Marca de tipo" simulada, 7 das 9 divergem em
  `PEÇA-Comprimento` (esperado; mostra a validação funcionando com dado real).

## 5. Forma de publicação que gera conversão

**Upload pelo navegador, arrastando o arquivo para a pasta do Docs.** O .rvt e o .ifc
foram convertidos automaticamente (SVF2) sem clicar em "processar".

**Regra de publicação (importante):** o Docs só cria uma NOVA VERSÃO quando o arquivo é
publicado com o **mesmo nome** na mesma pasta. A R02 foi publicada como
`...-ORC-R02.rvt` e virou outro item (outro arquivo, v1). Como cada obra do app liga-se a
um item, as revisões precisam manter o nome do arquivo (o número da revisão fica no
histórico de versões do Docs, não no nome).

## 6. Webhooks

**Decisão (2026-11-11): adiado para o servidor definitivo** (URL fixa). Até lá, a verificação
periódica (10 min) e o "Sincronizar agora" cobrem a chegada de versões. O código
(validação da assinatura, idempotência, escolha da obra pelo arquivo do evento) está
pronto e testado. Precisa de uma URL pública (túnel) apontando para o backend e do registro dos
hooks (`python -m app.cli hooks register --obra <id>`). Até lá, a verificação periódica
(10 min) e o "Sincronizar agora" cobrem a chegada de versões — o sync manual foi testado
com o Docs real (1 s, versão importada e processada).

## 7. Licença da visualização por conta de serviço

Pergunta feita à Autodesk (data, canal, contato): _pendente_
Resposta: _pendente_
(Tecnicamente funciona: o viewer abre com token 2-legged só `viewables:read`.)

## 8. Catálogo inicial da fábrica

**Decisão (2026-11-11): não haverá catálogo inicial.** O catálogo começa vazio e a fábrica cadastra os parâmetros pela tela quando começar a usar o app. (Referência: o modelo já traz dados de produção somente leitura, como `TECNOLOGIA-Forma`, `CASSOL-Linha de Produção`, `TECNOLOGIA-Concreto`, `TECNOLOGIA-Aço`, `PEÇA-Status` e `PEÇA-Quadrante de Montagem`.)

## 9. Conclusão

- [x] Nenhum bloqueio técnico encontrado para a Opção C até aqui: o Docs converte o .rvt
  sem POST /job, as propriedades vêm pela Model Derivative (só GET), o viewer abre com
  token 2-legged `viewables:read`, e o app processa o modelo real ponta a ponta.
- [ ] Ainda em aberto antes de produção: licença (item 7), .nwd/.ifc, comparação entre
  versões com um modelo **com Marca**, webhooks.
