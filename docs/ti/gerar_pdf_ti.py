"""Gera o PDF "Cassol Elo · Passo a passo para a TI" (reportlab)."""

from __future__ import annotations

import sys
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    CondPageBreak,
    KeepTogether,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = sys.argv[1]
FONTS = "C:/Windows/Fonts/"
pdfmetrics.registerFont(TTFont("Sans", FONTS + "segoeui.ttf"))
pdfmetrics.registerFont(TTFont("Sans-Bold", FONTS + "segoeuib.ttf"))
pdfmetrics.registerFont(TTFont("Sans-Italic", FONTS + "segoeuii.ttf"))
pdfmetrics.registerFont(TTFont("Mono", FONTS + "consola.ttf"))
pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans-Italic")

AMBER = colors.HexColor("#E8A33A")
AMBER_DARK = colors.HexColor("#9A5B00")
AMBER_SOFT = colors.HexColor("#FDF1DC")
INK = colors.HexColor("#23262B")
MUTED = colors.HexColor("#5D636B")
LINE = colors.HexColor("#DDD9D1")
CODE_BG = colors.HexColor("#F3F1EC")
WARN_BG = colors.HexColor("#FFF4E0")
OK = colors.HexColor("#2F7A4A")

base = dict(fontName="Sans", textColor=INK, alignment=TA_LEFT)


def mk(name: str, **kw: object) -> ParagraphStyle:
    return ParagraphStyle(name, **{**base, **kw})


S = {
    "title": mk("title", fontSize=26, leading=31, fontName="Sans-Bold"),
    "subtitle": mk("subtitle", fontSize=12.5, leading=18, textColor=MUTED),
    "h1": mk("h1", fontSize=17, leading=22, fontName="Sans-Bold", spaceBefore=6, spaceAfter=8, textColor=AMBER_DARK),
    "h2": mk("h2", fontSize=13, leading=17, fontName="Sans-Bold", spaceBefore=12, spaceAfter=5),
    "h3": mk("h3", fontSize=10.5, leading=14, fontName="Sans-Bold", spaceBefore=8, spaceAfter=3),
    "body": mk("body", fontSize=9.6, leading=14, spaceAfter=5),
    "small": mk("small", fontSize=8.4, leading=11.5, textColor=MUTED, spaceAfter=4),
    "cell": mk("cell", fontSize=8.6, leading=11.5),
    "cellb": mk("cellb", fontSize=8.6, leading=11.5, fontName="Sans-Bold"),
    "th": mk("th", fontSize=7.8, leading=10, fontName="Sans-Bold", textColor=MUTED),
    "bullet": mk("bullet", fontSize=9.6, leading=13.6, leftIndent=14, bulletIndent=3, spaceAfter=2.5),
    "code": ParagraphStyle("code", fontName="Mono", fontSize=7.9, leading=10.4, textColor=INK),
    "note": mk("note", fontSize=9.2, leading=13.2),
}
WIDTH = A4[0] - 36 * mm


def c(text: str) -> str:
    """Código inline."""
    return f'<font face="Mono" size="8.6" color="#7A4700">{escape(text)}</font>'


def p(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, S[style])


def bullets(items: list[str], numbered: bool = False, start: int = 1) -> list[Paragraph]:
    out = []
    for i, t in enumerate(items, start):
        mark = f"{i}." if numbered else "•"
        out.append(Paragraph(t, S["bullet"], bulletText=mark))
    return out


def checklist(items: list[str]) -> list[Paragraph]:
    return [Paragraph(t, S["bullet"], bulletText="\u25a1") for t in items]


def code(text: str) -> Table:
    t = Table([[Preformatted(text.strip("\n"), S["code"])]], colWidths=[WIDTH])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


def note(text: str, kind: str = "warn") -> Table:
    bg, bar = (WARN_BG, AMBER) if kind == "warn" else (colors.HexColor("#EAF4EE"), OK)
    t = Table([["", Paragraph(text, S["note"])]], colWidths=[3, WIDTH - 3])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), bar),
                ("BACKGROUND", (1, 0), (1, 0), bg),
                ("LEFTPADDING", (1, 0), (1, 0), 9),
                ("RIGHTPADDING", (1, 0), (1, 0), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 0),
            ]
        )
    )
    return t


def table(header: list[str], rows: list[list[str]], widths: list[float], first_bold: bool = True) -> Table:
    data = [[Paragraph(h.upper(), S["th"]) for h in header]]
    for r in rows:
        data.append(
            [Paragraph(v, S["cellb" if (i == 0 and first_bold) else "cell"]) for i, v in enumerate(r)]
        )
    total = sum(widths)
    t = Table(data, colWidths=[WIDTH * w / total for w in widths], repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, AMBER),
                ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


def section(num: str, title: str) -> list:
    return [CondPageBreak(60 * mm), p(f"{num}  {title}".strip(), "h1")]


def step(title: str) -> Paragraph:
    return p(title, "h2")


# --------------------------------------------------------------------------- conteúdo

story: list = []

# Capa
story += [
    Spacer(1, 40 * mm),
    p("CASSOL ELO", "small"),
    p("Passo a passo para a TI", "title"),
    Spacer(1, 4),
    p("Login com a conta Microsoft (HTTPS e Entra ID), servidor definitivo, backup e manutenção", "subtitle"),
    Spacer(1, 14 * mm),
    table(
        ["", ""],
        [
            ["O que é", "App web interno (PWA) que liga o escritório de projetos à fábrica de pré-moldados: abre os modelos do Autodesk Docs no navegador ou tablet e registra os parâmetros de produção."],
            ["Onde roda", "Um servidor da empresa, em contêineres Docker. Os usuários só usam o navegador (PC e tablets); nada é instalado nas máquinas deles."],
            ["Situação hoje", "Funciona em ambiente de teste por " + c("http://") + ", com usuário simulado. Falta o login corporativo, que depende de HTTPS e do registro no Microsoft Entra ID."],
            ["Versão do documento", "19/11/2026"],
        ],
        [1, 3.4],
    ),
    Spacer(1, 10 * mm),
    note(
        "<b>Por onde começar:</b> a Parte A (login) é o que bloqueia o uso pela fábrica. "
        "Dentro dela, o HTTPS (A1 a A5) vem antes do registro no Entra (A6), porque o endereço "
        "HTTPS é usado no registro."
    ),
    PageBreak(),
]

# Resumo
story += section("", "Resumo do que a TI precisa fazer")
story += [
    table(
        ["#", "Tarefa", "Prioridade", "Resultado entregue"],
        [
            ["A1", "Endereço e registro DNS", "Login (obrigatório)", "Nome definido, ex.: " + c("bim.cassol.ind.br")],
            ["A2", "Certificado TLS", "Login (obrigatório)", "Certificado válido nos PCs e nos tablets"],
            ["A3", "Proxy reverso HTTPS", "Login (obrigatório)", "443 → app, com os requisitos da tabela A3"],
            ["A4", "Firewall e ajuste da porta do app", "Login (obrigatório)", "Só a 443 aberta aos usuários"],
            ["A5", "Conferir o HTTPS", "Login (obrigatório)", "Lista A5 marcada"],
            ["A6", "Registrar o app no Entra ID", "Login (obrigatório)", "Client ID e Tenant ID"],
            ["A7", "Grupos de acesso no Entra", "Opcional", "IDs dos grupos"],
            ["A8", "Configurar e aceitar o login", "Login (com o responsável do app)", "Login testado em PC e tablet"],
            ["B1–B6", "Servidor definitivo, backup, migração", "Produção", "App no servidor Linux, backup diário com cópia fora"],
            ["C1–C2", "Webhooks e alertas", "Opcional", "Versões novas na hora; alertas por Teams/e-mail"],
            ["D", "Manutenção contínua", "Sempre", "Certificado renovado, backups conferidos"],
        ],
        [0.55, 2.4, 1.5, 2.6],
    ),
    Spacer(1, 8),
    p("Arquitetura, com o HTTPS:", "h3"),
    code(
        """
Navegador / tablet --HTTPS 443--> Proxy da TI --HTTP--> Servidor do app (Docker)
                                                     web       nginx: app e /api
                                                     api       FastAPI
                                                     worker    processamento
                                                     postgres  banco de dados
                                                     redis     fila e tempo real

Saída (servidor e tablets): HTTPS para developer.api.autodesk.com
                            e cdn.derivative.autodesk.com
Login: navegador <-> login.microsoftonline.com
       (o servidor só valida o token com as chaves públicas da Microsoft)
"""
    ),
]

# Parte A
story += [PageBreak(), p("PARTE A", "small"), p("Login com a conta Microsoft", "title"), Spacer(1, 4)]
story += [
    p(
        "O login Microsoft não funciona por " + c("http://") + ": o navegador bloqueia a "
        "criptografia do login (PKCE) fora de conexão segura e o Entra ID recusa endereço de "
        "retorno " + c("http") + ". Por isso o app precisa de um endereço " + c("https://") + " com "
        "certificado confiável antes do registro no Entra. Nenhuma senha ou segredo do Entra é "
        "necessário: o app só valida o token com as chaves públicas da Microsoft."
    ),
]

story += section("A1", "Endereço e DNS")
story += bullets(
    [
        "Escolher o nome definitivo, por exemplo " + c("bim.cassol.ind.br") + ". Ele vai no registro do Entra (A6); trocar depois exige refazer esse registro.",
        "Criar no DNS interno um registro <b>A</b> apontando para o IP do <b>proxy</b> (A3). Se o proxy ficar no próprio servidor do app, é o IP do servidor, que precisa ser fixo (reserva no DHCP ou IP estático).",
        "O nome precisa resolver na rede do escritório <b>e no Wi-Fi da fábrica</b> (tablets).",
    ]
)

story += section("A2", "Certificado TLS")
story += [
    table(
        ["Opção", "Quando usar", "Atenção"],
        [
            ["1. Curinga público " + c("*.cassol.ind.br"), "Se a empresa já tiver um.", "Nenhuma: PCs e tablets confiam sem configuração."],
            ["2. Público só para o nome", "Domínio público e DNS controlado pela TI. Let's Encrypt com validação por DNS (DNS-01) serve para nome interno.", "Agendar a renovação automática."],
            ["3. CA interna (AD CS)", "Se a política exigir a CA da empresa.", "PCs do domínio confiam. <b>Tablets Android não</b>: instalar a raiz da CA em cada tablet (manual ou por MDM). Sem isso, o login falha com aviso de certificado."],
        ],
        [1.4, 2.0, 2.2],
    ),
    Spacer(1, 4),
    *bullets(
        [
            "Instalar o certificado <b>com a cadeia intermediária</b> no proxy.",
            "Certificado autoassinado não serve: o login, o app instalado (PWA) e os webhooks da Autodesk recusam.",
        ]
    ),
]

story += section("A3", "Proxy reverso HTTPS")
story += [
    p("Pode ser o proxy que a TI já usa (nginx, IIS, F5 ou outro), no próprio servidor do app ou em outra máquina. Requisitos:"),
    table(
        ["Item", "Valor", "Por quê"],
        [
            ["Entrada", "Porta 443, TLS 1.2 ou 1.3", "HTTPS."],
            ["Porta 80", "Redirecionar (301) para " + c("https://"), "Quem digitar " + c("http://") + " chega ao endereço certo."],
            ["Destino", "<b>Tudo</b> (" + c("/") + " e " + c("/api/") + ") para " + c("http://<servidor>:<porta do app>"), "App e API ficam no mesmo endereço; o nginx do app separa."],
            ["Cabeçalhos enviados", "Manter o " + c("Host") + "; enviar " + c("X-Forwarded-For") + " e " + c("X-Forwarded-Proto: https"), "Logs e links corretos."],
            ["Sem buffer de resposta", "Pelo menos em " + c("/api/obras/*/events"), "Atualização ao vivo (Server-Sent Events). Com buffer, a tela de um usuário não vê o que o outro grava, sem erro visível."],
            ["Tempo limite de leitura", "1 hora", "A conexão ao vivo fica aberta (o app manda um sinal a cada 20 s)."],
            ["Tamanho do envio", "Até 10 MB", "Importação de Excel (até 5 MB) e lotes grandes."],
            ["Cabeçalhos do app", "Não remover nem reescrever", "O app já envia CSP, HSTS, nosniff etc."],
            ["Compressão", "Desligada para " + c("text/event-stream"), "A compressão acumula a resposta ao vivo."],
        ],
        [1.3, 2.2, 2.4],
    ),
    p("Exemplo com nginx", "h3"),
    code(
        """
server {
    listen 80;
    server_name bim.cassol.ind.br;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name bim.cassol.ind.br;

    ssl_certificate     /caminho/bim.cassol.ind.br.crt;   # com a cadeia intermediária
    ssl_certificate_key /caminho/bim.cassol.ind.br.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    client_max_body_size 10m;

    location / {
        proxy_pass http://SERVIDOR-DO-APP:8080;   # porta do app (HTTP_PORT, ver A4)
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Connection "";
        proxy_buffering off;          # atualização ao vivo
        proxy_read_timeout 1h;
        proxy_send_timeout 1h;
    }
}
"""
    ),
    p("Exemplo com IIS (URL Rewrite + Application Request Routing)", "h3"),
]
story += bullets(
    [
        "Instalar os módulos <b>URL Rewrite</b> e <b>Application Request Routing (ARR)</b>.",
        "ARR, no nível do servidor › <i>Server Proxy Settings</i>: <i>Enable proxy</i> ligado; <i>Time-out</i> = 3600 s; <i>Response buffer threshold</i> = <b>0</b>. No " + c("applicationHost.config") + ": " + c('preserveHostHeader="true"') + ".",
        "Site com binding HTTPS 443, o nome de A1 e o certificado de A2. Em <i>URL Rewrite › View Server Variables</i>, liberar " + c("HTTP_X_FORWARDED_PROTO") + ".",
        "Desligar a compressão dinâmica para " + c("text/event-stream") + ".",
        "Regra no " + c("web.config") + " do site (abaixo) e uma regra de redirecionamento HTTP → HTTPS.",
    ],
    numbered=True,
)
story += [
    code(
        """
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="Cassol Elo" stopProcessing="true">
          <match url="(.*)" />
          <serverVariables>
            <set name="HTTP_X_FORWARDED_PROTO" value="https" />
          </serverVariables>
          <action type="Rewrite" url="http://SERVIDOR-DO-APP:8080/{R:1}" />
        </rule>
      </rules>
    </rewrite>
    <security>
      <requestFiltering>
        <requestLimits maxAllowedContentLength="10485760" />
      </requestFiltering>
    </security>
  </system.webServer>
</configuration>
"""
    ),
    p("Os nomes dos campos variam um pouco entre versões do IIS. O que importa são os requisitos da tabela acima.", "small"),
]

story += section("A4", "Firewall e porta do app")
story += [
    p("<b>Proxy na mesma máquina do app:</b> o app sai da porta 80 e passa a aceitar só conexões locais. No arquivo " + c("infra/.env.prod") + " do servidor:"),
    code(
        """
HTTP_BIND=127.0.0.1
HTTP_PORT=8080
"""
    ),
    p("<b>Proxy em outra máquina:</b> o app continua na porta atual, e o firewall do servidor aceita essa porta <b>só vindo do proxy</b>."),
    p("Em ambos os casos, o firewall do proxy libera a <b>443</b> (e a 80, para o redirecionamento) para as redes do escritório e da fábrica. A porta HTTP antiga deixa de ser usada diretamente pelos usuários. No PC Windows de teste a regra atual é a \"Visualizador BIM\" (porta 80); ajustá-la ou removê-la conforme o caso."),
    p("Para aplicar a mudança no app, a partir da pasta do projeto no servidor:"),
    code(
        """
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d --wait
"""
    ),
]

story += section("A5", "Conferir o HTTPS")
story += checklist(
    [
        c("https://bim.cassol.ind.br") + " abre o app sem aviso de certificado num PC <b>e num tablet da fábrica</b>.",
        c("http://bim.cassol.ind.br") + " redireciona para " + c("https://") + ".",
        c("https://bim.cassol.ind.br/api/health") + " responde " + c('{"status":"ok"}') + ".",
        "A resposta traz o cabeçalho " + c("Strict-Transport-Security") + " (é o app que envia).",
        "Atualização ao vivo: abrir a mesma obra em dois navegadores, preencher um valor num deles e ver o outro mudar em poucos segundos, sem recarregar.",
    ]
)
story += [
    code(
        """
curl -I https://bim.cassol.ind.br/
curl https://bim.cassol.ind.br/api/health
"""
    ),
    note(
        "<b>Renovação do certificado.</b> Com o HTTPS ativo, o app pede aos navegadores que usem só "
        "HTTPS nesse endereço por um ano (HSTS). Se o certificado vencer, ninguém entra até ele ser "
        "renovado, e não há como voltar para " + c("http://") + " nesse nome. Deixe a renovação "
        "agendada ou com alerta."
    ),
]

story += section("A6", "Registrar o app no Microsoft Entra ID (cerca de 10 min)")
story += [p("Portal Azure → <b>Microsoft Entra ID</b> → <b>Registros de aplicativo</b> → <b>Novo registro</b>.")]
story += bullets(
    [
        "<b>Nome:</b> " + c("Cassol Elo") + ". <b>Tipos de conta:</b> somente as contas deste diretório organizacional (locatário único).",
        "<b>URI de redirecionamento:</b> plataforma <b>Aplicativo de página única (SPA)</b> → " + c("https://bim.cassol.ind.br") + " (exatamente a origem: sem barra no fim e sem caminho). Para o desenvolvedor testar no PC dele, adicionar também " + c("http://localhost:5173") + ".",
        "Na página <b>Visão geral</b>, anotar o <b>ID do aplicativo (cliente)</b> e o <b>ID do diretório (locatário)</b>.",
        "<b>Expor uma API</b> → <i>Adicionar</i> o URI da ID do aplicativo (aceitar o sugerido " + c("api://<client id>") + ") → <b>Adicionar um escopo</b>: nome " + c("access_as_user") + "; quem pode consentir: <b>Administradores e usuários</b>; nome de exibição \"Acessar o Cassol Elo\"; estado <b>Habilitado</b>.",
        "<b>Manifesto:</b> " + c('"requestedAccessTokenVersion": 2') + " (em versões antigas do portal, " + c('"accessTokenAcceptedVersion": 2') + "). Salvar.",
        "(Recomendado) <b>Permissões de API</b> → <i>Adicionar uma permissão</i> → <i>Minhas APIs</i> → Cassol Elo → " + c("access_as_user") + " → depois <b>Conceder consentimento do administrador</b>. Assim ninguém vê a tela de consentimento no primeiro acesso.",
        "<b>Não</b> é preciso criar segredo (client secret) nem certificado para este app.",
    ],
    numbered=True,
)
story += [
    note(
        "Se a TI usar outro nome de escopo ou outro URI da ID do aplicativo, informe o escopo completo "
        "(ex.: " + c("api://bim.cassol.ind.br/acesso") + ") para a variável " + c("ENTRA_API_SCOPE") + ".",
        kind="ok",
    ),
]

story += section("A7", "Grupos de acesso no Entra (opcional)")
story += [
    p("Sem grupos, os papéis (Leitura, Fábrica, Projetos, Admin) e as obras de cada pessoa são definidos pelo administrador do app na tela <b>Usuários</b>. Quem entra pela primeira vez fica como Leitura. Use grupos só se a TI preferir controlar o papel pelo Entra:"),
]
story += bullets(
    [
        "Criar grupos de segurança, ex.: " + c("Cassol Elo - Admin") + ", " + c("Cassol Elo - Projetos") + ", " + c("Cassol Elo - Fábrica") + ".",
        "No registro do app → <b>Configuração de token</b> → <i>Adicionar declaração de grupos</i> → <b>Grupos de segurança</b>, no access token, formato <b>ID do grupo</b>.",
        "Informar os IDs na ordem de prioridade (quem está em dois grupos fica com o primeiro). Quem não está em nenhum fica Leitura.",
    ],
    numbered=True,
)
story += [
    p("Com grupos, o papel não pode ser trocado na tela do app (o grupo prevalece a cada login); as obras de cada pessoa continuam sendo definidas na tela.", "small"),
]

story += section("A8", "Entregar ao responsável do app e testar o login")
story += [
    table(
        ["Dado", "Exemplo", "Variável no servidor"],
        [
            ["ID do aplicativo (cliente)", c("aaaaaaaa-bbbb-…"), c("ENTRA_CLIENT_ID")],
            ["ID do diretório (locatário)", c("11111111-2222-…"), c("ENTRA_TENANT_ID")],
            ["Escopo, se diferente do padrão", c("api://…/access_as_user"), c("ENTRA_API_SCOPE")],
            ["IDs dos grupos (se A7)", c("admin=<id>;projetos=<id>;fabrica=<id>"), c("ENTRA_ROLE_GROUPS")],
            ["Endereço HTTPS", c("https://bim.cassol.ind.br"), c("APP_BASE_URL")],
        ],
        [1.6, 2.1, 1.5],
    ),
    p("Nenhum desses dados é senha. No " + c("infra/.env.prod") + " do servidor, além de preencher a tabela acima:", "body"),
]
story += bullets(
    [
        "Conferir " + c("ALLOWED_EMAIL_DOMAINS=cassol.ind.br") + " e " + c("BOOTSTRAP_ADMIN_EMAILS=vhbastos@cassol.ind.br") + " (primeiro administrador do app).",
        "<b>Apagar</b> a linha " + c("DEV_USERS_ENABLED=true") + ", se existir: a versão atual se recusa a iniciar com ela fora do ambiente de desenvolvimento.",
        "Atualizar e reiniciar o app (procedimento B6).",
    ]
)
story += [p("Teste de aceite (com o responsável do app):", "h3")]
story += checklist(
    [
        c("https://bim.cassol.ind.br/api/auth/config") + " mostra " + c("client_id") + " e " + c("tenant_id") + " preenchidos e " + c('"dev_login": false') + ".",
        "Entrar com " + c("vhbastos@cassol.ind.br") + ": entra como Administrador e vê o link \"Usuários\".",
        "Entrar com uma conta da fábrica: entra como Leitura; o administrador troca o papel na tela Usuários.",
        "Uma conta de fora da Cassol é recusada (\"E-mail fora dos domínios permitidos\").",
        "Num tablet da fábrica: o login abre, volta ao app e o ícone instalado (PWA) continua funcionando.",
    ]
)

# Parte B
story += [PageBreak(), p("PARTE B", "small"), p("Servidor definitivo", "title"), Spacer(1, 4)]
story += [p("Hoje o app roda num PC Windows de teste com Docker Desktop. Para produção, o plano é um servidor Linux da TI. O guia técnico completo está no projeto, em " + c("docs/DEPLOY.md") + "; abaixo, o que cabe à TI.")]

story += section("B1", "Requisitos do servidor")
story += [
    table(
        ["Item", "Requisito"],
        [
            ["Sistema", "Linux com Docker Engine 24+ e o plugin Compose v2 (" + c("docker compose version") + ")."],
            ["Capacidade", "2 vCPU, 4 GB de RAM, 20 GB de disco livres, mais o espaço dos backups (cerca de 1 MB por obra por dia × 30 dias)."],
            ["Rede: entrada", "Só a porta do app, vinda do proxy (A3/A4)."],
            ["Rede: saída", "HTTPS (443) para " + c("developer.api.autodesk.com") + " e " + c("cdn.derivative.autodesk.com") + " (servidor <b>e</b> tablets) e para " + c("login.microsoftonline.com") + " (servidor e navegadores)."],
            ["Endereço", "IP fixo e o nome de A1."],
            ["Acesso", "Git (ou cópia da pasta do projeto) e um usuário administrador para o responsável do app."],
            ["Autodesk", "O app APS (Client ID e Client Secret) liberado em <b>Custom Integrations</b> do ACC. Já existe para o ambiente de teste."],
        ],
        [1.1, 4.4],
    ),
]

story += section("B2", "Instalação")
story += [
    code(
        """
git clone <repositório> visualizador-bim && cd visualizador-bim

# 1) segredos (um arquivo por segredo em infra/secrets/, nunca no git)
bash infra/secrets-init.sh
#    preencher à mão: infra/secrets/aps_client_secret

# 2) variáveis (não secretas): copiar o modelo e editar (APP_ENV=prod, ENTRA_*, APP_BASE_URL...)
cp infra/.env.prod.example infra/.env.prod

# 3) subir (build das imagens e migrações automáticas)
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d --build --wait

# 4) conferir
curl http://127.0.0.1:8080/api/ready     # {"status":"ready", ...}
"""
    ),
    p("Segredos ficam em arquivos em " + c("infra/secrets/") + ", com permissão só do administrador: senha do banco (gerada), Client Secret do APS, secret dos webhooks (gerado), token de métricas (gerado) e, opcionais, URL do Teams, senha SMTP e a configuração do rclone (B4). Se a TI tiver um cofre corporativo, ele pode substituir esses arquivos sem mudar o app.", "body"),
]

story += section("B3", "Variáveis principais de produção")
story += [
    table(
        ["Variável", "Valor em produção"],
        [
            [c("APP_ENV"), c("prod") + " (exige login Microsoft configurado)"],
            [c("ENTRA_CLIENT_ID") + " / " + c("ENTRA_TENANT_ID"), "os de A6"],
            [c("APP_BASE_URL"), c("https://bim.cassol.ind.br")],
            [c("HTTP_BIND") + " / " + c("HTTP_PORT"), "conforme A4"],
            [c("APS_CLIENT_ID") + " / " + c("APS_REGION"), "os do app APS (região do hub do ACC)"],
            [c("BACKUP_REMOTES"), "destinos das cópias do backup (B4)"],
            [c("ALERT_EMAIL_TO") + ", " + c("SMTP_*"), "alertas por e-mail (C2)"],
        ],
        [2.2, 3.3],
        first_bold=False,
    ),
]

story += section("B4", "Backup")
story += bullets(
    [
        "O app faz " + c("pg_dump") + " do banco, confere o arquivo e guarda 30 dias em " + c("infra/backups/") + ". Se o backup falhar ou atrasar mais de 26 h, avisa por Teams/e-mail (C2).",
        "<b>Agendar diariamente às 03:00</b> (Linux, systemd): copiar " + c("infra/backup/systemd/bim-backup.service") + " e " + c(".timer") + " para " + c("/etc/systemd/system/") + ", ajustar " + c("WorkingDirectory") + " e rodar " + c("sudo systemctl daemon-reload && sudo systemctl enable --now bim-backup.timer") + ".",
        "<b>Cópia fora do servidor (pasta de rede):</b> criar uma conta de serviço (ex.: " + c("svc-bim-backup") + ") com permissão só de gravar e apagar numa pasta, ex.: " + c("\\\\arquivos\\Backups\\BIM") + ". Passar ao responsável do app o servidor, o compartilhamento e a conta. A senha vai ofuscada no " + c("infra/secrets/rclone_conf") + ".",
        "(Opcional) <b>SharePoint:</b> registrar um app no Entra com " + c("Sites.Selected") + " concedida só ao site dos backups (ou " + c("Files.ReadWrite.All") + "), com client id e secret, para uma segunda cópia.",
        "Uma vez por trimestre: restaurar um backup num ambiente limpo para conferir (procedimento em " + c("docs/DEPLOY.md") + ", seção 7).",
    ]
)
story += [
    code(
        """
[pasta]
type = smb
host = arquivos
user = svc-bim-backup
domain = CASSOL
pass = <senha ofuscada: docker run --rm rclone/rclone:1.69.3 obscure 'SENHA'>
"""
    ),
]

story += section("B5", "Migração do teste para o definitivo")
story += bullets(
    [
        "Combinar uma janela com a fábrica (o app fica alguns minutos fora).",
        "No PC de teste: rodar um backup e copiar o arquivo " + c(".dump") + " (e o " + c(".sha256") + ") para " + c("infra/backups/") + " do servidor novo.",
        "No servidor novo, com o banco ainda vazio: subir só banco e Redis, restaurar e subir o resto:",
    ],
    numbered=True,
)
story += [
    code(
        """
alias bim='docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod'

bim up -d --wait postgres redis                            # só banco e Redis
bim --profile backup run --rm backup restore.sh latest     # restaura o último .dump
bim up -d --wait                                           # migrações, api, worker e web
"""
    ),
]
story += bullets(
    [
        "Apontar o DNS (A1) e o proxy (A3) para o servidor novo e desligar o app no PC de teste.",
        "Conferir com o responsável do app: obras, parâmetros preenchidos e login.",
    ],
    numbered=True,
    start=4,
)

story += section("B6", "Atualizar o app")
story += [
    p("Quando o responsável do app pedir uma atualização (sempre com backup antes):"),
    code(
        """
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod --profile backup run --rm backup
git pull
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d --build --wait
curl http://127.0.0.1:8080/api/ready
"""
    ),
    p("As migrações do banco rodam sozinhas na subida. Para poder voltar à versão anterior, definir " + c("APP_VERSION") + " (ex.: " + c("2026.11.20") + ") no " + c(".env.prod") + " a cada atualização.", "body"),
]

# Parte C
story += [PageBreak(), p("PARTE C", "small"), p("Opcionais", "title"), Spacer(1, 4)]
story += section("C1", "Webhooks da Autodesk (versões novas na hora)")
story += [
    p("Hoje o app verifica o Autodesk Docs a cada 10 minutos e tem o botão \"Sincronizar agora\"; isso basta para operar. Se a TI quiser que uma versão nova apareça na hora:"),
]
story += bullets(
    [
        "Publicar na internet <b>apenas</b> " + c("POST /api/webhooks/aps") + ", com certificado público válido (a Autodesk recusa autoassinado e CA interna). O resto do app continua só na rede interna.",
        "Informar a URL pública ao responsável do app, que ativa os webhooks (" + c("PUBLIC_BASE_URL") + " e um comando de registro).",
        "A chamada é autenticada pela assinatura " + c("x-adsk-signature") + "; requisições sem assinatura válida são recusadas.",
    ]
)
story += section("C2", "Alertas por Teams e e-mail")
story += bullets(
    [
        "<b>E-mail:</b> servidor SMTP, porta, usuário, remetente e se usa STARTTLS; a senha vai num arquivo de segredo. Destinatários em " + c("ALERT_EMAIL_TO") + ".",
        "<b>Teams:</b> um fluxo (Workflows/Power Automate) \"enviar para canal quando receber uma solicitação HTTP\"; a URL do fluxo vai num arquivo de segredo.",
        "Alertas enviados: backup falhou ou atrasou; versão do modelo com falha ou sem conversão há mais de 2 h; credenciais da Autodesk com erro; webhooks parados (se C1). O monitoramento de \"servidor fora do ar\" fica com a ferramenta da TI, pelo endereço " + c("/api/ready") + ".",
    ]
)

# Parte D
story += section("D", "Manutenção contínua")
story += [
    table(
        ["Quando", "O quê"],
        [
            ["Antes de vencer", "Renovar o certificado (A2). Com HSTS, certificado vencido tira o app do ar para todos."],
            ["Diário (automático)", "Backup às 03:00 com cópia na pasta de rede; o app avisa se falhar."],
            ["Trimestral", "Restaurar um backup num ambiente limpo e conferir."],
            ["Mensal", "Atualizações de segurança do sistema operacional e do Docker (reiniciar fora do horário da fábrica)."],
            ["Tablet novo", "Se a CA for interna (A2, opção 3), instalar a raiz no tablet antes de entregar."],
            ["Pessoa sai da empresa", "Desativar a conta no Entra bloqueia o acesso (em até 1 h, quando o token atual vence). Para bloquear na hora, o administrador do app desativa a pessoa na tela Usuários."],
        ],
        [1.3, 4.2],
    ),
    Spacer(1, 10),
    note(
        "<b>Dúvidas sobre o app</b>: responsável de produto do Cassol Elo. Documentação técnica no "
        "repositório do projeto: " + c("docs/LOGIN.md") + " (login), " + c("docs/DEPLOY.md") + " (servidor, backup, "
        "restauração) e " + c("docs/operacao.md") + " (operação, logs, papéis). O nome "
        + c("bim.cassol.ind.br") + " é exemplo: troque pelo nome escolhido em todos os passos.",
        kind="ok",
    ),
]


def decorate(canvas, doc) -> None:  # noqa: ANN001
    canvas.saveState()
    w, h = A4
    canvas.setFillColor(AMBER)
    canvas.rect(0, h - 5, w, 5, stroke=0, fill=1)
    if doc.page > 1:
        canvas.setFont("Sans", 7.8)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 11 * mm, "Cassol Elo · Passo a passo para a TI · 19/11/2026")
        canvas.drawRightString(w - 18 * mm, 11 * mm, f"Página {doc.page}")
    canvas.restoreState()


doc = SimpleDocTemplate(
    OUT,
    pagesize=A4,
    leftMargin=18 * mm,
    rightMargin=18 * mm,
    topMargin=18 * mm,
    bottomMargin=20 * mm,
    title="Cassol Elo · Passo a passo para a TI",
    author="Cassol Elo",
    subject="Login Microsoft (HTTPS e Entra ID), servidor definitivo, backup e manutenção",
)
doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
print("ok", OUT)
