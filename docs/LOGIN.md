# Login Microsoft (Fase 11) · guia para a TI

O app usa a conta Microsoft corporativa (Entra ID, antigo Azure AD) da Cassol. Quem
entra é identificado pelo **e-mail** (`@cassol.ind.br`); o papel (projetos, fábrica,
admin, leitura) fica no banco do app ou, se a TI quiser, vem de grupos do Entra.

Nenhum segredo é necessário: o app é uma SPA (authorization code + PKCE) e o backend só
**valida** o token com as chaves públicas da Microsoft.

## Pré-requisito: HTTPS

O login **não funciona por HTTP** (só em `http://localhost`): o navegador bloqueia a
criptografia do PKCE fora de contexto seguro e o Entra recusa redirect URI `http://`.
Publique o app com HTTPS (proxy da TI na frente do nginx, `docs/DEPLOY.md` seção 9),
por exemplo `https://bim.cassol.ind.br`.

## 1. Registrar o app no Entra ID (≈ 10 min)

Portal Azure → **Microsoft Entra ID** → **Registros de aplicativo** → **Novo registro**

1. Nome: `Cassol Elo` · Tipos de conta: **somente este diretório** (locatário único).
2. URI de redirecionamento: plataforma **Aplicativo de página única (SPA)** →
   `https://<endereço do app>` (exatamente a origem, sem caminho; ex.
   `https://bim.cassol.ind.br`). Para testar no PC do desenvolvedor, adicione também
   `http://localhost:5173`.
3. Anote, na página **Visão geral**: **ID do aplicativo (cliente)** → `ENTRA_CLIENT_ID`
   e **ID do diretório (locatário)** → `ENTRA_TENANT_ID`.
4. **Expor uma API** → *Adicionar* o URI da ID do aplicativo (aceite o sugerido
   `api://<client id>`) → **Adicionar um escopo**:
   nome `access_as_user`, quem pode consentir **Administradores e usuários**, nome de
   exibição "Acessar o Cassol Elo". (Outro nome ou URI? Informe em `ENTRA_API_SCOPE`,
   ex. `api://bim.cassol.ind.br/acesso`.)
5. **Manifesto**: `"requestedAccessTokenVersion": 2` (em versões antigas do portal,
   `"accessTokenAcceptedVersion": 2`). O app aceita v1 também, mas v2 é o recomendado.
6. (Opcional) **Permissões de API** → *Conceder consentimento do administrador* para o
   escopo `access_as_user`, assim ninguém vê a tela de consentimento no primeiro acesso.

## 2. Papéis por grupo (opcional)

Sem grupos, o papel é o da tabela `users` do app: quem entra pela primeira vez fica
**leitura** e um admin promove pela linha de comando (seção 4).

Com grupos, a TI controla o papel pelo Entra:

1. Crie grupos de segurança, ex. `Cassol Elo - Admin`, `- Projetos`, `- Fábrica`.
2. No registro do app → **Configuração de token** → *Adicionar declaração de grupos* →
   **Grupos de segurança** (no access token, formato **ID do grupo**).
3. `ENTRA_ROLE_GROUPS=admin=<id do grupo>;projetos=<id>;fabrica=<id>`. A ordem é a
   prioridade (quem está em dois grupos fica com o primeiro). Quem não está em nenhum
   fica **leitura**. Se o token vier sem grupos (claim desligada ou pessoa em mais de
   200 grupos), vale o papel da tabela.

## 3. Variáveis (`infra/.env.prod`)

| Variável | Exemplo | Para que serve |
|---|---|---|
| `ENTRA_CLIENT_ID` | `aaaaaaaa-…` | ID do aplicativo (cliente). Obrigatório com `APP_ENV=prod` |
| `ENTRA_TENANT_ID` | `11111111-…` | ID do diretório (locatário). Obrigatório com `APP_ENV=prod` |
| `ENTRA_API_SCOPE` | vazio | escopo pedido pelo app; vazio = `api://<ENTRA_CLIENT_ID>/access_as_user` |
| `ALLOWED_EMAIL_DOMAINS` | `cassol.ind.br` | só esses domínios entram (vírgulas para mais de um) |
| `BOOTSTRAP_ADMIN_EMAILS` | `vhbastos@cassol.ind.br` | sempre admin ao entrar: o primeiro admin não depende de grupo nem de comando |
| `ENTRA_ROLE_GROUPS` | vazio | papel pelo grupo (seção 2) |

O frontend lê client id, tenant e escopo em `GET /api/auth/config`: não é preciso
recompilar a imagem para trocar de ambiente.

## 4. Administrar usuários

No dia a dia, pela tela **Usuários** do app (link no cabeçalho, só para admin):

- **cadastrar pelo e-mail** antes do primeiro acesso, já com papel e obras (o nome vem da
  conta Microsoft no primeiro login, se ficar em branco);
- **papel** (leitura, fábrica, projetos, admin) e **ativo/desativado**;
- **obras que vê**: *todas* (padrão, inclusive as cadastradas depois) ou *só as
  escolhidas*. Obra nova não entra sozinha na lista de quem é restrito, exceto a que a
  própria pessoa cadastra. O admin vê sempre todas.

Proteções: o admin não se desativa nem tira o próprio papel de admin, e o último admin
ativo não perde o papel. Papel de `BOOTSTRAP_ADMIN_EMAILS` ou de `ENTRA_ROLE_GROUPS` não
muda pela tela (o próximo login desfaria a troca); a tela explica. Tudo vai para o
`audit_log` com o nome de quem alterou.

Sem a tela (ex.: nenhum admin consegue entrar), pela linha de comando:

```bash
bim exec api python -m app.cli users list
bim exec api python -m app.cli users set-role fulano@cassol.ind.br fabrica --name "Fulano"
bim exec api python -m app.cli users deactivate fulano@cassol.ind.br   # activate desfaz
```

`set-role` cria o usuário se ele ainda não entrou (o nome é corrigido pelo admin; o
login não sobrescreve). Tudo vai para o `audit_log`. Usuário desativado não entra,
mesmo com conta Microsoft válida. Com `ENTRA_ROLE_GROUPS`, o grupo prevalece sobre o
`set-role` no próximo acesso.

## 5. Conferir

1. `curl https://<app>/api/auth/config` → `client_id` e `tenant_id` preenchidos,
   `dev_login: false`.
2. Abrir o app → **Entrar com Microsoft** → conta `@cassol.ind.br` → o cabeçalho mostra
   o nome e o papel.
3. Conta de outro domínio → "E-mail fora dos domínios permitidos".

## Como o backend valida (para auditoria)

`backend/app/auth/entra.py`: assinatura **RS256** pela chave do JWKS do tenant
(`login.microsoftonline.com/<tenant>/discovery/v2.0/keys`, cache de 24 h, nova busca
se a Microsoft girar as chaves); emissor do tenant (v2 ou v1); audiência = o app;
`tid` = o tenant; `exp`/`nbf` (tolerância de 60 s); escopo `access_as_user` no `scp`.
Algoritmos `none`/HS256 são recusados. O usuário sai de `preferred_username`
(ou `email`/`upn`), comparado sem diferenciar maiúsculas. O usuário simulado
(`X-Dev-User`) só existe com `APP_ENV=dev`; `DEV_USERS_ENABLED` foi removido e, se
ainda estiver no `.env`, o backend recusa subir fora de dev.
