# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

PWA usada no navegador do desktop e do tablet. Não há app nativo.

## Users

- **Engenheiros da fábrica** (usuários principais): usam no desktop e no tablet, muitas vezes no chão de fábrica com luz forte. Abrem o modelo, acham a peça clicando no 3D ou buscando, e preenchem os parâmetros de produção por montagem (marca) ou por peça.
- **Escritório de projetos**: publica os modelos no Autodesk Docs, confere as marcas e a regra de identificação de cada obra e acompanha o que a fábrica preencheu.
- Papéis no app: `projetos`, `fabrica`, `admin`, `leitura` (somente leitura).

## Product Purpose

O ELO é a ferramenta interna da Cassol Pré-Fabricados que liga o escritório de projetos à fábrica. É um visualizador BIM (modelo 3D pelo Autodesk Viewer, a partir do que o Docs publica) com edição de parâmetros de produção por montagem e por peça. Esses parâmetros ficam no banco do app, não no arquivo BIM, e continuam valendo quando sai uma nova versão do modelo.

O produto dá certo quando um engenheiro acha a peça certa em segundos, registra o dado de produção sem ambiguidade e confia que o que salvou ficou salvo, mesmo depois que o projeto publica outra versão.

## Positioning

O ELO não é um visualizador genérico. Ele entende a lógica do pré-moldado: uma marca agrupa N peças físicas idênticas, cada uma é uma unidade numerada (PP001-1, PP001-2…), e o status de produção é calculado por peça e somado por marca. Os dados sobrevivem às versões do modelo por reconciliação, e o que some vira órfão em vez de ser apagado.

## Operating Context

- Fluxo: o escritório publica no Autodesk Docs (ACC) → o ELO lê a versão (SVF2, propriedades) → a fábrica abre a obra, entra no modelo, seleciona ou busca peças e preenche os parâmetros.
- Telas atuais: lista de obras; obra com as abas Versões e Identificação; página do modelo (3D ao centro, painéis laterais recolhíveis à esquerda e à direita).
- Filtros e coloração do modelo seguem o estilo do Dalux (referência em `docs/filtros/referencia-dalux.md`).
- Condições de uso: Wi-Fi fraco ou instável no chão de fábrica; luz forte e tela suja; uso com luvas ou dedos grossos no tablet; uso no computador do escritório e da fábrica.
- Formatos de modelo: Revit (RVT), IFC e NWD. O NWD não tem chave estável por elemento.

## Capabilities and Constraints

- Entidade central: MARCA = (obra, código da marca, categoria). Unidades de peça numeradas, e o número nunca é reaproveitado.
- Parâmetros da fábrica valem por marca ou por peça (definido na criação). Tipos incluem datas (dd/mm/aaaa, validadas; os editores só gravam ao confirmar, e Esc cancela).
- Status de produção: **Pendente / Parcial / Completa / Revisar**, calculado por peça e agregado por marca.
- Reconciliação entre versões; marcas e unidades órfãs ficam visíveis, nunca são apagadas em silêncio. Toda alteração vai para o histórico de auditoria.
- Exportação de planilhas; eventos em tempo real entre usuários.
- O 3D só é acessado pela interface `ViewerAdapter` (Autodesk Viewer v7).
- Até a Fase 11 não há login: o usuário é simulado pelo seletor de usuário de desenvolvimento.
- Textos de interface em português do Brasil.

## Brand Commitments

- Nome: **ELO** / Cassol Elo, da Cassol Pré-Fabricados. Logo existente dos dois quadrados (`frontend/src/components/Logo.tsx`, `frontend/public/favicon.svg`) é fixo.
- Paleta: apenas as cores do logo, âmbar `#F2A31B` e grafite `#3C3C3C`. Fora isso, o visual é livre.
- Tom: corporativo, técnico, sóbrio e denso em informação, como um software de engenharia. Não é landing page.
- Proibido: gradientes, glassmorphism, cartões muito arredondados, sombras grandes, emoji, cores decorativas.
- Uma única cor de destaque. Outras cores só para status (pendente, parcial, completa, revisar).
- O modelo 3D é o protagonista; a interface ao redor deve ser discreta.

## Evidence on Hand

- Documentação de produto e decisões em `docs/` (ROADMAP, PROGRESS, DATA_MODEL, `docs/pecas/`, `docs/filtros/`, `docs/bugs/`).
- Mockup anterior: `docs/mockup.html`; guia de parâmetros: `docs/guia-parametros.html`.
- Não há depoimentos, métricas de uso ou casos publicados. É uma ferramenta interna e nada disso deve ser inventado.

## Product Principles

1. **O modelo primeiro.** Cada pixel fora do 3D precisa se justificar; os painéis servem ao modelo, não competem com ele.
2. **Confiança no dado.** Salvo, falhou ou pendente sempre aparece claramente, sobretudo com rede instável. Nada é apagado ou gravado sem o usuário saber.
3. **Denso, mas legível sob luz forte.** Muita informação por tela, com contraste alto e alvos de toque que funcionam com luva.
4. **Cor é informação.** A cor marca status e a única ação de destaque, nunca decoração.
5. **Um app para dois lugares.** Serve bem tanto ao desktop do escritório quanto ao tablet no chão de fábrica.

## Accessibility & Inclusion

- Contraste alto para leitura sob luz forte (no mínimo WCAG 2.2 AA; preferir mais nas telas do chão de fábrica).
- Alvos de toque grandes no tablet, adequados ao uso com luvas.
- O status nunca pode depender só da cor: usar também texto ou forma, já que a cor do status aparece no modelo 3D e na legenda.
