# Spike · Coordenadas do eixo da peça

Página de medição (fora do app) que mostra X, Y, Z do **eixo** da peça clicada, em mm.
O resultado e o método estão em [docs/coordenadas.md](../../docs/coordenadas.md).

## Rodar

A partir da raiz do repositório, com `spikes/.env` preenchido (o mesmo do spike 0.4):

```powershell
spikes/.venv/Scripts/python spikes/coordenadas/server.py      # http://127.0.0.1:8010
```

- No navegador: `http://127.0.0.1:8010/?urn=<URN base64>`. Clique numa peça; o painel mostra
  os pontos do eixo e os dados da conversão.
- Automático (Chromium do Playwright do frontend):
  ```powershell
  node spikes/coordenadas/run.mjs --name orc-rvt --urn <URN> [--dbids 86,90 | --find 6657283 [--all]]
  spikes/.venv/Scripts/python spikes/coordenadas/compare.py orc-rvt orc-ifc
  ```
  `--find` acha a peça pelo ElementId do Revit (nome `[id]` no RVT, `IFC Attributes/Tag` no
  IFC, `Element ID/Value` no NWD); `--all` mede todas as ocorrências (vínculos repetem o id).
  A saída vai para `spikes/out/coordenadas-<nome>.json`.
- `?applyRefPoint=1` / `--applyRefPoint` só para experimentar: **o app não muda as opções
  de carga** (carrega com `loadDocumentNode(doc, node)` sem opções).

## Arquivos

- `axis.js`: matemática pura (PCA da superfície, cortes, eixo de pilar/viga/laje, conversão).
- `coordenadas.js` / `coordenadas.html`: Viewer v7 com as mesmas opções do app.
- `server.py`: página + token `viewables:read` (reaproveita `spikes/viewer/viewer_app.py`).
- `run.mjs`, `compare.py`: medição automática e comparação entre formatos.

## Testes

```powershell
node --test spikes/coordenadas                 # matemática (peças sintéticas)
cd spikes; .venv/Scripts/python -m pytest coordenadas
```
