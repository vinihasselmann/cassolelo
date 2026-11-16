"""Spike 0.1 - Listar o Autodesk Docs (ACC) via APS com token 2-legged.

USO
---
1. Crie um ambiente e instale as dependências (a partir da raiz do repositório):

       py -3.12 -m venv spikes/.venv
       spikes/.venv/Scripts/python -m pip install -r spikes/aps_docs/requirements.txt

2. Copie spikes/.env.example para spikes/.env e preencha APS_CLIENT_ID e
   APS_CLIENT_SECRET. O app precisa estar liberado pelo admin do ACC em
   Account Admin > Custom Integrations.

3. Visão geral (hubs -> projetos -> pastas de topo):

       spikes/.venv/Scripts/python spikes/aps_docs/list_docs.py

   Filtros opcionais: --hub <hub_id>  --project-name <trecho do nome>

4. Conteúdo recursivo de uma pasta (ids copiados da visão geral):

       spikes/.venv/Scripts/python spikes/aps_docs/list_docs.py \
           --project b.xxxxxxxx --folder urn:adsk.wipprod:fs.folder:co.xxxxxxxx

   Opcional: --max-depth N (padrão 10).

Somente leitura (escopos data:read viewables:read). O token nunca é impresso.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

BASE_URL = "https://developer.api.autodesk.com"
TOKEN_PATH = "/authentication/v2/token"
SCOPES = "data:read viewables:read"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

NOT_PROVISIONED_MSG = (
    "Acesso negado (HTTP {status}) em {path}: app não liberado em Custom Integrations. "
    "Peça ao admin do ACC para adicionar o Client ID em "
    "Account Admin > Custom Integrations (ou verifique se o app tem acesso a este projeto)."
)


class ApsError(Exception):
    """Erro de alto nível com mensagem pronta para o usuário."""


@dataclass
class Node:
    name: str
    kind: str
    id: str
    children: list[Node] = field(default_factory=list)


# --------------------------------------------------------------------------- auth


def get_token(http: httpx.Client, client_id: str, client_secret: str) -> str:
    resp = http.post(
        TOKEN_PATH,
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials", "scope": SCOPES},
        headers={"Accept": "application/json"},
    )
    if resp.status_code in (400, 401):
        raise ApsError(
            f"Falha na autenticação (HTTP {resp.status_code}): verifique APS_CLIENT_ID "
            "e APS_CLIENT_SECRET em spikes/.env."
        )
    if resp.status_code == 403:
        raise ApsError(NOT_PROVISIONED_MSG.format(status=403, path=TOKEN_PATH))
    if resp.is_error:
        raise ApsError(f"Erro ao obter token (HTTP {resp.status_code}).")
    token = resp.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise ApsError("Resposta de token sem access_token.")
    return token


# --------------------------------------------------------------------------- data


def _name(item: dict[str, Any]) -> str:
    attrs = item.get("attributes") or {}
    return str(attrs.get("displayName") or attrs.get("name") or item.get("id", "?"))


def _node(item: dict[str, Any]) -> Node:
    return Node(name=_name(item), kind=str(item.get("type", "?")), id=str(item.get("id", "?")))


class DocsClient:
    def __init__(self, http: httpx.Client, token: str) -> None:
        self._http = http
        self._headers = {"Authorization": f"Bearer {token}"}
        self.warnings: list[str] = []

    def _get(self, url: str) -> dict[str, Any]:
        resp = self._http.get(url, headers=self._headers)
        path = resp.request.url.path
        if resp.status_code in (401, 403):
            raise ApsError(NOT_PROVISIONED_MSG.format(status=resp.status_code, path=path))
        if resp.status_code == 404:
            raise ApsError(f"Não encontrado (HTTP 404): {path}. Confira os ids informados.")
        if resp.is_error:
            raise ApsError(f"Erro HTTP {resp.status_code} em {path}: {resp.text[:300]}")
        body: dict[str, Any] = resp.json()
        return body

    def _paged(self, url: str) -> Iterator[dict[str, Any]]:
        next_url: str | None = url
        while next_url:
            body = self._get(next_url)
            for w in (body.get("meta") or {}).get("warnings") or []:
                detail = w.get("Detail") or w.get("detail") or w.get("Title") or str(w)
                self.warnings.append(str(detail))
            yield from body.get("data") or []
            next_url = ((body.get("links") or {}).get("next") or {}).get("href")

    def hubs(self) -> list[Node]:
        return [_node(d) for d in self._paged("/project/v1/hubs")]

    def projects(self, hub_id: str) -> list[Node]:
        return [_node(d) for d in self._paged(f"/project/v1/hubs/{hub_id}/projects")]

    def top_folders(self, hub_id: str, project_id: str) -> list[Node]:
        url = f"/project/v1/hubs/{hub_id}/projects/{project_id}/topFolders"
        return [_node(d) for d in self._paged(url)]

    def folder_tree(self, project_id: str, folder_id: str, max_depth: int = 10) -> list[Node]:
        url = f"/data/v1/projects/{project_id}/folders/{folder_id}/contents"
        nodes: list[Node] = []
        for d in self._paged(url):
            node = _node(d)
            if node.kind == "folders":
                if max_depth > 1:
                    node.children = self.folder_tree(project_id, node.id, max_depth - 1)
                else:
                    node.children = [Node("…", "limite de profundidade", "")]
            nodes.append(node)
        return nodes


# --------------------------------------------------------------------------- render


def render_tree(nodes: list[Node], prefix: str = "") -> list[str]:
    lines: list[str] = []
    for i, node in enumerate(nodes):
        last = i == len(nodes) - 1
        branch = "└── " if last else "├── "
        suffix = f"  {node.id}" if node.id else ""
        lines.append(f"{prefix}{branch}{node.name}  [{node.kind}]{suffix}")
        lines.extend(render_tree(node.children, prefix + ("    " if last else "│   ")))
    return lines


# --------------------------------------------------------------------------- cli


def build_overview(
    docs: DocsClient, hub_filter: str | None, project_filter: str | None
) -> list[Node]:
    hubs = [h for h in docs.hubs() if not hub_filter or h.id == hub_filter]
    for hub in hubs:
        projects = docs.projects(hub.id)
        if project_filter:
            projects = [p for p in projects if project_filter.lower() in p.name.lower()]
        for project in projects:
            project.children = docs.top_folders(hub.id, project.id)
        hub.children = projects
    return hubs


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lista hubs, projetos e pastas do Autodesk Docs.")
    p.add_argument("--hub", help="filtra por hub_id")
    p.add_argument("--project-name", help="filtra projetos pelo trecho do nome")
    p.add_argument("--project", help="project_id (b.xxx) para listar uma pasta")
    p.add_argument("--folder", help="folder_id (urn:adsk.wipprod:fs.folder:...) a listar")
    p.add_argument("--max-depth", type=int, default=10)
    args = p.parse_args(argv)
    if bool(args.project) != bool(args.folder):
        p.error("--project e --folder devem ser usados juntos")
    return args


def main(argv: list[str] | None = None, http: httpx.Client | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    load_dotenv(ENV_FILE)
    client_id = os.getenv("APS_CLIENT_ID", "").strip()
    client_secret = os.getenv("APS_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print(f"Defina APS_CLIENT_ID e APS_CLIENT_SECRET em {ENV_FILE}", file=sys.stderr)
        return 2

    own_http = http is None
    http = http or httpx.Client(base_url=BASE_URL, timeout=30.0)
    try:
        docs = DocsClient(http, get_token(http, client_id, client_secret))
        if args.project:
            title = f"Pasta {args.folder} (projeto {args.project})"
            nodes = docs.folder_tree(args.project, args.folder, args.max_depth)
        else:
            title = "Autodesk Docs"
            nodes = build_overview(docs, args.hub, args.project_name)
    except ApsError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"ERRO de rede: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if own_http:
            http.close()

    print(title)
    print("\n".join(render_tree(nodes)) if nodes else "(vazio)")
    for w in dict.fromkeys(docs.warnings):
        print(f"AVISO da API: {w}", file=sys.stderr)
    if not nodes and not args.project:
        print(
            "Nenhum hub visível: provavelmente o app não foi liberado em Custom Integrations.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
