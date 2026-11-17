# Bug · rolagem fantasma na tela da obra

**Status:** corrigido em 2026-11-17.

## Sintoma

Na tela da obra, com o painel lateral esquerdo aberto (Gerenciar + lista de Marcas), a **página inteira** ganhava uma rolagem longa e aparecia uma grande área vazia abaixo do rodapé. Com o painel fechado, nada disso acontecia.

## Diagnóstico

Rodamos um script no navegador (Playwright) que compara `document.documentElement.scrollHeight` com `window.innerHeight` e lista os elementos cujo `getBoundingClientRect().bottom` passa da janela. Ele mostra só o ponto de fuga, isto é, o elemento que passa da janela com um pai que não passa. Para cada um, informa tag, classes, altura, `position`, `overflow` e o pai.

| Cenário | `innerHeight` | `documentElement.scrollHeight` | `body.scrollHeight` |
|---|---|---|---|
| Viewer **falso**, 316 marcas **sem status**, 1440×900, painel aberto | 900 | 900 | 900 |
| Viewer **real**, obra 9480-SE3-IFC (316 marcas **com status**), 1440×900, painel aberto | 900 | **2208** | 900 |
| Idem, painel fechado | 900 | 900 | 900 |
| Idem, 1180×820, painel aberto | 820 | **2250** | 820 |

A cadeia de contêineres estava correta:

- `.app` tinha 900px, e `.app__main` tinha 843px com `overflow: hidden`;
- `.model-page` (grid) e `.model-cols` mediam 740px;
- `.model-left` tinha 740px com `overflow: auto`, e o conteúdo da lista (2176px) rolava por dentro.

A diferença entre `body` (900) e `html` (2208) indicava algo posicionado em relação à página inteira (o bloco de contenção inicial), fora de qualquer recorte. A prova:

- Dentro do painel esquerdo havia **51 elementos `position: absolute`**: o `h2.sr-only` do painel e um `span.sr-only` por linha de marca (o status, "…, Completa", lido só pelo leitor de tela).
- O maior deles terminava em **`bottom = 2208`**, exatamente o `scrollHeight` do documento.
- Ao esconder só esses 51 elementos, o documento voltou a **900**.

Os suspeitos da investigação foram descartados:

- **Lista sem limite de altura:** não é. A lista já rolava dentro do `.model-left`.
- **Filhos de grid/flex sem `min-height: 0`:** não era o caso; as alturas batiam com a janela.
- **Elementos internos do Autodesk Viewer, inclusive a barra nativa:** nenhum passava da janela.

O Viewer real entrou na história só porque a obra real tinha status por marca. As marcas simuladas do primeiro teste não tinham status, e por isso não reproduziram o bug.

## Causa

O texto `.sr-only` é `position: absolute`. Nenhum ancestral dele era posicionado: nem a linha da marca, nem o painel, nem o shell. Por isso o bloco de contenção dele era o **bloco inicial (a página)**.

Um `overflow` só recorta descendentes cujo bloco de contenção esteja dentro dele. O `overflow: auto` do painel e o `overflow: hidden` do `main` não recortavam esses textos. Cada `span` ficava na altura da sua linha na lista (até 2208px), e o documento crescia junto. Com o painel fechado, a lista some e o problema também.

Isso foi uma regressão: o status com texto para leitor de tela entrou na lista de marcas no passo de layout do mesmo dia.

## Correção (na raiz)

Tudo em `frontend/src/styles.css`:

- **Shell** `.app`: `position: relative; height: 100dvh; overflow: hidden`. O shell vira o recorte final de tudo, inclusive de elementos absolutos sem outro ancestral posicionado. O documento nunca rola. Janelas e avisos (`position: fixed`) não são afetados.
- **Tela da obra** `.model-page`: grid de linhas fixas `auto auto minmax(0, 1fr) auto` (barra · avisos · área de trabalho · rodapé), com `overflow: hidden`.
- **Área de trabalho** `.model-cols`: `grid-template-rows: minmax(0, 1fr)`, com colunas em `min-height: 0`.
- **Painéis** `.model-left` e `.model-right`: `position: relative` e `overflow: auto` (`overscroll-behavior: contain`). Tudo o que está dentro deles, inclusive absolutos, é recortado e rola por dentro. A tabela por peça continua com a sua própria rolagem.
- **Linha de lista** `.list-item`: `position: relative`, que ancora o `.sr-only` na própria linha.
- **Contêiner do viewer** `.model-viewer`: `position: relative; overflow: hidden; container-type: size`. Nada do Viewer vaza, e os popovers da barra limitam a altura ao espaço do 3D (`calc(100cqh - 140px)`).
- **Tela estreita** (até 820px, painéis empilhados): continua rolando o `main`, de propósito, mas dentro do shell. O documento fica parado.

O Viewer passou a ser avisado pelo `ViewerAdapter`. Antes, um `resize` falso era disparado na janela. Agora, ao abrir ou fechar um painel lateral, a tela chama `ViewerAdapter.resize()` depois do novo layout (`requestAnimationFrame`). A implementação real chama `viewer.resize()` do Viewer v7.

## Testes

- **Playwright** (`e2e/modelo.spec.ts`, "Tela da obra não rola como página"):
  - em 1440×900 e 1180×820, com 316 marcas **com status**;
  - com o painel esquerdo aberto, fechado e aberto de novo, `document.documentElement.scrollHeight === window.innerHeight` e `scrollY === 0`;
  - a lista rola por dentro (`.model-left` com `scrollTop > 0`, sem mexer na página);
  - ao fechar o painel, o Viewer recebe `resize`.
- **Vitest** (`ModelPage.test.tsx`): esconder um painel chama `viewer.resize()`.
- **Verificação com o Viewer real** na obra 9480-SE3-IFC (316 marcas): `scrollHeight` 2208 → **900**.

## Script de diagnóstico (para reusar)

Rode no console do navegador com a tela aberta:

```js
const H = innerHeight;
console.log({ innerHeight: H, html: document.documentElement.scrollHeight, body: document.body.scrollHeight });
for (const el of document.querySelectorAll('body *')) {
  const b = el.getBoundingClientRect(), p = el.parentElement?.getBoundingClientRect();
  if (b.bottom > H + 1 && b.height > 0 && (!p || p.bottom <= H + 1)) {
    const cs = getComputedStyle(el);
    console.log(el.tagName, el.className, Math.round(b.height), cs.position, cs.overflowY, '← pai:', el.parentElement?.tagName, el.parentElement?.className);
  }
}
// absolutos/fixos e onde terminam (fuga do recorte)
console.table([...document.querySelectorAll('body *')]
  .filter((e) => ['absolute', 'fixed'].includes(getComputedStyle(e).position))
  .map((e) => ({ el: `${e.tagName}.${e.className}`, bottom: Math.round(e.getBoundingClientRect().bottom) }))
  .filter((r) => r.bottom > H));
```
