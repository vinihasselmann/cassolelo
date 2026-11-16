# Spike 0.4 · Abrir no Viewer

Servidor FastAPI mínimo e uma página que abre um modelo do Autodesk Docs no
Autodesk Viewer v7 (SVF2, `AutodeskProduction2` / `streamingV2`).

## Como rodar

A partir da raiz do repositório, com `spikes/.env` preenchido (veja `spikes/.env.example`):

```powershell
py -3.12 -m venv spikes/.venv                     # se ainda não existir
spikes/.venv/Scripts/python -m pip install -r spikes/requirements-dev.txt
spikes/.venv/Scripts/python spikes/viewer/viewer_app.py
```

Pegue o URN com o `read_model.py` (linha `URN:`) e abra:

```
http://localhost:8000/?urn=<URN em base64>
```

## O que a página faz

- Pede o token em `GET /token`. O token é 2-legged, só com `viewables:read`,
  e fica em cache no servidor até 60 s antes de expirar. As credenciais
  APS nunca saem do servidor.
- Ao clicar numa peça, o painel lateral mostra dbId, externalId, Marca e
  Categoria (via `getProperties`).
- Em seguida seleciona todas as peças com a mesma Marca **e** a mesma
  categoria (`search` restrito aos atributos de marca + conferência exata
  com `getBulkProperties`).
- Os nomes do parâmetro de marca vêm de `MARK_PROPERTY_NAMES` (`GET /config`).
- Para projetos ACC na Europa, use `APS_REGION=EMEA` (a página troca para `streamingV2_EU`).

## Aceite

Abrir um `.rvt`, um `.nwd` e um `.ifc` e, em cada um, clicar numa peça e ver
todas as peças da mesma marca destacadas.

## Testes

```powershell
cd spikes
.venv/Scripts/python -m pytest viewer
```

Os testes cobrem o servidor (cache do token, escopo, erros, `/config`, página).
O comportamento no navegador é verificado manualmente no aceite.
