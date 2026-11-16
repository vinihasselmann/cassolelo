# src/viewer

O frontend só acessa o visualizador 3D pela interface `ViewerAdapter` (CLAUDE.md).

| Arquivo | Papel |
|---|---|
| `ViewerAdapter.ts` | Interface: `load(urn)`, `selectDbIds`, `isolate`, `showAll`, `fitTo`, `setColors` (dbId → `#RRGGBB[AA]`), `clearColors`, `onSelect`, `destroy`. |
| `ApsViewerAdapter.ts` | **Único** arquivo que usa o Autodesk Viewer v7: carrega script e CSS do CDN oficial sob demanda, `AutodeskProduction2` + `streamingV2` (`streamingV2_EU` em EMEA), token de `GET /api/viewer-token`. |
| `viewerContext.ts` / `ViewerProvider.tsx` | `useViewerAdapter(ref)` cria e destrói o adapter com a tela; `ViewerFactoryProvider` troca a implementação (testes usam um adapter falso). |
| `isolation.test.ts` | Falha se algum outro arquivo usar `Autodesk.Viewing`, `window.Autodesk` ou o CDN do Viewer. |

`onSelect` só avisa seleções feitas pelo usuário no 3D; `selectDbIds` chamado pelo app não volta pelo listener (evita laço ao selecionar a marca inteira).
