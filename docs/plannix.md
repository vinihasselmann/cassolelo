# Importação da planilha do Plannix

Decisões de 2026-11-24. Código em `backend/app/services/plannix_import.py`.

O Plannix é o sistema de produção da fábrica. A fábrica exporta dele uma planilha e a
envia pelo botão **Importar Excel** da obra; o app reconhece que é do Plannix e preenche,
**por peça**, as datas das etapas de produção.

## Parâmetros

| Coluna do Plannix | Parâmetro no app | Etapa |
|---|---|---|
| Data CD | Corte e dobra | corte e dobra |
| Data AR | Armação | armação |
| Data FO | Forma | forma |
| Data FA | Forma e armação | forma e armação |
| Data CO | Concretagem | concretagem |
| Data Aca | Acabamento | acabamento |

- Da biblioteca, por peça, tipo data, valem para todas as categorias e são
  **obrigatórios** (contam no status da peça; decisão de 2026-11-24). A primeira
  importação de cada obra os cria (se ainda não existem) e os inclui na obra.
- Nome, tipo, por marca / por peça e escopo não mudam (422): a importação acha o
  parâmetro pelo nome. "Obrigatório" e as categorias podem ser editados.
- `source = plannix`: **só a importação grava**. Na tela ficam só leitura (etiqueta
  "Plannix"); a edição manual, uma a uma ou em lote, dá 422. O Excel exportado pelo app
  mostra as colunas, mas a importação dele as ignora.
- Um parâmetro **criado à mão** com o mesmo nome (na biblioteca ou na obra) bloqueia a
  importação: renomeie ou exclua antes. O "concretagem" que existia foi excluído para isso.
- As colunas "Data … - Qualidade", os status e as demais colunas não são importados.

## Como a linha acha a peça

1. **Obra:** a coluna Sigla tem de ser o código da obra (422 se for de outra obra ou se a
   planilha misturar obras).
2. **Recusadas:** linha com "Status de Projeto" vazio é peça recusada na produção
   (algumas com " /R" no nome) e fica de fora. A peça refeita vem em outra linha.
3. **Marca:** o prefixo mais longo de "Peça", cortando em "-" ou espaço, que existe na
   versão ativa ("LA3008-LP15 7X9,5-75%-125" → LA3008; "P-06" → P-06, marca com
   hífen). Sem nenhum no modelo, vale o mais curto (antes do primeiro "-" ou espaço). A
   mesma marca em duas categorias é erro. Marca que não está no modelo aparece só como informação.
4. **Peça:**
   - pelo **Código** do Plannix, se uma importação anterior já o guardou na unidade
     (`piece_units.plannix_code`); assim a ligação não muda se a Seq. mudar no Plannix;
   - senão, **Seq. n/total → unidade n** da marca (PP301 13/20 → PP301-13); ao aplicar, o
     Código fica guardado na unidade.
   - Se a unidade n já tem outro Código, ou se n passa do número de peças do modelo, a
     linha fica sem peça (aviso).
   - Quantidade diferente entre o Plannix e o modelo: liga assim mesmo e avisa "Conferir".
5. **Seq. convertida em data pelo Excel:** "1/2" vira 01/fev (formato dia/mês: n = dia,
   total = mês) e "1/36" vira jan/1936 (formato mês/ano: n = mês, total = ano com dois
   dígitos). O app desfaz pelo formato da célula.

Peças da mesma marca são idênticas, e a ligação n → n é uma convenção: o número do app
segue a sequência de montagem e o Seq. do Plannix conta as cópias. Depois da primeira
importação, quem manda é o Código.

## Gravação

- O Plannix manda nas 6 datas: **sempre sobrescreve** e **célula vazia apaga** (a peça
  refeita depois de uma recusa chega sem datas). Não há "Também alterar".
- Prévia antes de gravar (nada gravado), conferência pelo `fingerprint` (409 se algo
  mudou no meio), um lote só com **Desfazer** das datas, auditoria `piece_value` com
  `"source": "plannix"` e `piece_unit` / `plannix_link` para cada Código guardado. O
  Desfazer devolve as datas; os Códigos e os parâmetros criados ficam.
- O primeiro valor por peça trava a numeração da obra, como na edição manual.

## Amostra analisada

`plannix/tabela.xlsx`, obra GARDEN PARK (Sigla 9480): 1.474 linhas, 65 colunas, 297
nomes de peça. Na prévia contra o modelo 9480-EST-MON-SE3-PRO-R00: 1.464 peças lidas, 10
recusadas, 1.186 ligadas, 44 sem peça no modelo, 52 marcas (234 linhas) fora do modelo e
22 marcas com quantidade diferente (ex.: LA3011 com 142 no modelo e 1 no Plannix, e LA3123
com 141 no Plannix e nenhuma no modelo, que parece uma renomeação).
