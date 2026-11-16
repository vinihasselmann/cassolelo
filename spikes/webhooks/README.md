# Spike 0.5 · Webhook de nova versão

- `webhook_server.py`: FastAPI com `POST /hooks/aps`. Valida a assinatura
  `x-adsk-signature` (HMAC-SHA1 do corpo bruto com `APS_WEBHOOK_SECRET`),
  rejeita com 401 se for inválida, responde 200 na hora e grava o evento em
  `spikes/out/webhooks.log` (uma linha JSON por evento).
- `manage_webhooks.py`: registra o secret e cria, lista e apaga hooks do
  sistema `data` nos eventos `dm.version.added` e `dm.version.modified`. O
  scope é a pasta do projeto de teste e `hookAttribute = {"obra_id": ...}`.

## Passo a passo

A partir da raiz do repositório, com `spikes/.env` preenchido. Coloque em
`APS_WEBHOOK_SECRET` um valor aleatório longo, por exemplo
`python -c "import secrets; print(secrets.token_hex(32))"`.

1. **Suba o receptor** (porta 8001):

   ```powershell
   spikes/.venv/Scripts/python spikes/webhooks/webhook_server.py
   ```

2. **Exponha a porta local com HTTPS** (o APS precisa alcançar o callback pela internet). Use uma das opções:

   - **Cloudflare Tunnel (rápido, sem conta):** instale com `winget install --id Cloudflare.cloudflared` e rode

     ```powershell
     cloudflared tunnel --url http://localhost:8001
     ```

     Ele imprime uma URL `https://<algo>.trycloudflare.com`. A URL muda a cada execução.
   - **ngrok:** instale com `winget install ngrok.ngrok` e crie uma conta grátis. Rode
     `ngrok config add-authtoken <token>` uma vez e depois

     ```powershell
     ngrok http 8001
     ```

     Use a URL `https://<algo>.ngrok-free.app` exibida. O painel em
     http://127.0.0.1:4040 mostra cada requisição recebida, o que ajuda a depurar.

   Teste: `https://<url-do-túnel>/health` deve responder `{"ok": true, "secret_configured": true}`.

3. **Registre o secret** no APS (antes de criar os hooks):

   ```powershell
   spikes/.venv/Scripts/python spikes/webhooks/manage_webhooks.py set-secret
   ```

4. **Crie os hooks** na pasta do projeto de teste (o id da pasta vem do `list_docs.py`):

   ```powershell
   spikes/.venv/Scripts/python spikes/webhooks/manage_webhooks.py create `
       --folder urn:adsk.wipprod:fs.folder:co.xxxx `
       --callback https://<url-do-túnel>/hooks/aps --obra-id OBRA-TESTE
   ```

5. **Publique uma revisão** de um modelo nessa pasta e acompanhe `spikes/out/webhooks.log`.

6. **Limpeza:** os comandos são `manage_webhooks.py list` e `manage_webhooks.py delete --all`.
   Com o Cloudflare Tunnel rápido a URL muda a cada execução. Nesse caso, apague os hooks e
   crie de novo com a URL nova.

## Observações

- O APS desativa um hook se o callback falhar repetidamente. Se o `list`
  mostrar `inactive`, recrie o hook.
- `dm.version.added` chega quando o arquivo entra no Docs, o que pode ser antes
  de a conversão terminar. O app vai precisar consultar o manifest depois
  (anotar o tempo observado em `docs/decisoes-fase-0.md`).
- Para projetos na Europa, use `APS_REGION=EMEA`. O script envia `x-ads-region`.

## Aceite

Publicar uma revisão no Docs gera uma entrada no log em poucos minutos.
