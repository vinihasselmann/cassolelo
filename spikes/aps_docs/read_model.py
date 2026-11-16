"""Spike 0.2 - Versões, manifest e propriedades de um item do Autodesk Docs.

Só usa chamadas de LEITURA: Data Management (versões) e Model Derivative GET
(manifest, metadata, properties). NÃO chama POST /job nem a AEC Data Model API:
se o Docs não converteu o arquivo, o script informa e para.

USO (a partir da raiz do repositório, com spikes/.env preenchido):

    spikes/.venv/Scripts/python spikes/aps_docs/read_model.py \
        --project b.xxxxxxxx --item urn:adsk.wipprod:dm.lineage:xxxxxxxx [--version N]

- project_id e item_id vêm do list_docs.py (item = linha [items]).
- Sem --version usa a versão mais recente.
- Saída: spikes/out/<item>_v<n>.json e um resumo no terminal.

Variáveis de ambiente (spikes/.env):
    MARK_PROPERTY_NAMES      nomes do parâmetro de marca (padrão "Marca,Mark")
    CATEGORY_PROPERTY_NAMES  propriedades de categoria (padrão "Category,Categoria,IfcClass");
                             se nenhuma existir, usa a categoria da árvore do modelo
    APS_REGION               US (padrão), EMEA ou AUS

O que conta como elemento: nó da árvore 3D que tem Marca (os filhos dele são
componentes aninhados e não são contados) ou folha sem Marca acima dela.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from list_docs import BASE_URL as BASE_URL
from list_docs import ENV_FILE, NOT_PROVISIONED_MSG, get_token
from list_docs import ApsError as ApsError

OUT_DIR = Path(__file__).resolve().parent.parent / "out"
DEFAULT_MARK_NAMES = "Marca,Mark"
DEFAULT_CATEGORY_NAMES = "Category,Categoria,IfcClass"
MD_PREFIX = {
    "US": "/modelderivative/v2/designdata",
    "EMEA": "/modelderivative/v2/regions/eu/designdata",
    "AUS": "/modelderivative/v2/regions/aus/designdata",
}
NO_TRANSLATION_MSG = "arquivo sem conversão no Docs"


class NoTranslationError(ApsError):
    """O Docs não gerou derivativo visualizável para esta versão."""


# --------------------------------------------------------------------------- helpers


def env_list(name: str, default: str) -> list[str]:
    return [s.strip() for s in os.getenv(name, default).split(",") if s.strip()]


def to_urn(derivative_id: str) -> str:
    """URN do derivativo em base64 url-safe sem padding.

    O Data Management normalmente já devolve o id codificado; se vier cru
    ("urn:adsk..."), codifica.
    """
    if derivative_id.startswith("urn:"):
        return base64.urlsafe_b64encode(derivative_id.encode()).decode().rstrip("=")
    return derivative_id.replace("+", "-").replace("/", "_").rstrip("=")


def find_prop(props: dict[str, Any], names: list[str]) -> str | None:
    """Procura, em todos os grupos, a primeira propriedade com um dos nomes (sem
    diferenciar maiúsculas), na ordem de preferência de `names`."""
    for wanted in names:
        key = wanted.casefold()
        for group in props.values():
            if not isinstance(group, dict):
                continue
            for prop_name, value in group.items():
                if prop_name.casefold() != key:
                    continue
                if isinstance(value, list):
                    value = value[0] if value else None
                if value is not None and str(value).strip():
                    return str(value).strip()
    return None


def safe_name(item_id: str) -> str:
    tail = item_id.rsplit(":", 1)[-1]
    return re.sub(r"[^A-Za-z0-9._-]", "_", tail) or "item"


def _clean_category(value: str) -> str:
    return value.removeprefix("Revit ").strip()


# --------------------------------------------------------------------------- dados


@dataclass
class VersionInfo:
    id: str
    number: int
    author: str
    created: str
    name: str
    derivative_urn: str | None


def parse_version(d: dict[str, Any]) -> VersionInfo:
    a = d.get("attributes") or {}
    deriv = (((d.get("relationships") or {}).get("derivatives") or {}).get("data") or {}).get("id")
    return VersionInfo(
        id=str(d.get("id")),
        number=int(a.get("versionNumber") or 0),
        author=str(a.get("createUserName") or a.get("lastModifiedUserName") or "?"),
        created=str(a.get("createTime") or a.get("lastModifiedTime") or "?"),
        name=str(a.get("displayName") or a.get("name") or "?"),
        derivative_urn=to_urn(str(deriv)) if deriv else None,
    )


class ModelReader:
    def __init__(
        self,
        http: httpx.Client,
        token: str,
        region: str = "US",
        sleep: Callable[[float], None] = time.sleep,
        poll_seconds: float = 5.0,
        max_wait_seconds: float = 600.0,
    ) -> None:
        if region not in MD_PREFIX:
            raise ApsError(f"APS_REGION inválida: {region} (use {', '.join(MD_PREFIX)})")
        self._http = http
        self._headers = {"Authorization": f"Bearer {token}"}
        self._md = MD_PREFIX[region]
        self._sleep = sleep
        self._poll = poll_seconds
        self._max_wait = max_wait_seconds

    def _req(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        resp = self._http.get(url, headers=self._headers, params=params)
        if resp.status_code in (401, 403):
            path = resp.request.url.path
            raise ApsError(NOT_PROVISIONED_MSG.format(status=resp.status_code, path=path))
        return resp

    @staticmethod
    def _ok(resp: httpx.Response) -> dict[str, Any]:
        if resp.is_error:
            path = resp.request.url.path
            raise ApsError(f"Erro HTTP {resp.status_code} em {path}: {resp.text[:300]}")
        body: dict[str, Any] = resp.json()
        return body

    # Data Management ------------------------------------------------------

    def versions(self, project_id: str, item_id: str) -> list[VersionInfo]:
        url: str | None = f"/data/v1/projects/{project_id}/items/{item_id}/versions"
        out: list[VersionInfo] = []
        while url:
            resp = self._req(url)
            if resp.status_code == 404:
                raise ApsError("Item não encontrado (HTTP 404). Confira --project e --item.")
            body = self._ok(resp)
            out.extend(parse_version(d) for d in body.get("data") or [])
            url = ((body.get("links") or {}).get("next") or {}).get("href")
        return sorted(out, key=lambda v: v.number, reverse=True)

    # Model Derivative (somente GET) ----------------------------------------

    def manifest(self, urn: str) -> dict[str, Any]:
        resp = self._req(f"{self._md}/{urn}/manifest")
        if resp.status_code == 404:
            raise NoTranslationError(NO_TRANSLATION_MSG)
        return self._ok(resp)

    def views(self, urn: str) -> list[dict[str, Any]]:
        body = self._ok(self._req(f"{self._md}/{urn}/metadata"))
        views: list[dict[str, Any]] = (body.get("data") or {}).get("metadata") or []
        return views

    def _poll_json(self, url: str) -> dict[str, Any]:
        """GET que trata 202 (ainda processando: espera e repete) e 413 (resposta
        grande demais: repete com forceget=true)."""
        params: dict[str, str] = {}
        waited = 0.0
        while True:
            resp = self._req(url, params or None)
            if resp.status_code == 202:
                if waited >= self._max_wait:
                    raise ApsError(f"Propriedades ainda em processamento após {waited:.0f}s.")
                self._sleep(self._poll)
                waited += self._poll
                continue
            if resp.status_code == 413 and "forceget" not in params:
                params["forceget"] = "true"
                continue
            return self._ok(resp)

    def tree(self, urn: str, guid: str) -> list[dict[str, Any]]:
        body = self._poll_json(f"{self._md}/{urn}/metadata/{guid}")
        objs: list[dict[str, Any]] = (body.get("data") or {}).get("objects") or []
        return objs

    def properties(self, urn: str, guid: str) -> list[dict[str, Any]]:
        body = self._poll_json(f"{self._md}/{urn}/metadata/{guid}/properties")
        coll: list[dict[str, Any]] = (body.get("data") or {}).get("collection") or []
        return coll


def check_manifest(manifest: dict[str, Any]) -> str:
    status = str(manifest.get("status", "?"))
    progress = str(manifest.get("progress", ""))
    if status in ("pending", "inprogress"):
        raise ApsError(f"Conversão do Docs em andamento ({progress}). Tente de novo mais tarde.")
    if status != "success":
        msgs = [
            m.get("message", "")
            for d in manifest.get("derivatives") or []
            for m in d.get("messages") or []
        ]
        raise ApsError(f"Conversão do Docs com status '{status}'. {' | '.join(msgs)[:500]}")
    viewable = any(
        str(d.get("outputType", "")).lower() in ("svf", "svf2")
        for d in manifest.get("derivatives") or []
    )
    if not viewable:
        raise NoTranslationError(NO_TRANSLATION_MSG)
    return f"{status} ({progress})"


def choose_3d_view(views: list[dict[str, Any]]) -> dict[str, Any]:
    views3d = [v for v in views if v.get("role") == "3d"]
    if not views3d:
        raise ApsError("O derivativo não tem vista 3D.")
    master = [v for v in views3d if v.get("isMasterView")]
    return (master or views3d)[0]


# --------------------------------------------------------------------------- extração


def _count_descendants(node: dict[str, Any]) -> int:
    stack = list(node.get("objects") or [])
    n = 0
    while stack:
        cur = stack.pop()
        n += 1
        stack.extend(cur.get("objects") or [])
    return n


def extract_elements(
    tree: list[dict[str, Any]],
    props_collection: list[dict[str, Any]],
    mark_names: list[str],
    category_names: list[str],
) -> tuple[list[dict[str, Any]], int]:
    """Devolve (elementos, componentes aninhados ignorados)."""
    by_id = {p.get("objectid"): p for p in props_collection}
    elements: list[dict[str, Any]] = []
    nested = 0

    # pilha: (nó, profundidade, categoria da árvore)
    stack: list[tuple[dict[str, Any], int, str | None]] = [(n, 0, None) for n in reversed(tree)]
    while stack:
        node, depth, tree_cat = stack.pop()
        if depth == 1:
            tree_cat = str(node.get("name") or "")
        children = node.get("objects") or []
        info = by_id.get(node.get("objectid")) or {}
        props: dict[str, Any] = info.get("properties") or {}
        mark = find_prop(props, mark_names)
        if depth > 0 and (mark or not children):
            category = find_prop(props, category_names) or tree_cat or "(sem categoria)"
            elements.append(
                {
                    "dbid": node.get("objectid"),
                    "external_id": info.get("externalId"),
                    "name": info.get("name") or node.get("name"),
                    "category": _clean_category(category),
                    "mark": mark,
                    "props": props,
                }
            )
            nested += _count_descendants(node)
            continue
        stack.extend((c, depth + 1, tree_cat) for c in reversed(children))
    return elements, nested


@dataclass
class Stats:
    total: int
    by_category: list[tuple[str, int]]
    without_mark: int
    top_marks: list[tuple[tuple[str, str], int]]


def compute_stats(elements: list[dict[str, Any]], top: int = 10) -> Stats:
    cats = Counter(str(e["category"]) for e in elements)
    marks = Counter((str(e["mark"]), str(e["category"])) for e in elements if e["mark"])
    return Stats(
        total=len(elements),
        by_category=sorted(cats.items(), key=lambda kv: (-kv[1], kv[0])),
        without_mark=sum(1 for e in elements if not e["mark"]),
        top_marks=sorted(marks.items(), key=lambda kv: (-kv[1], kv[0]))[:top],
    )


def format_stats(s: Stats, nested: int) -> Iterator[str]:
    yield f"Total de elementos: {s.total}  (componentes aninhados ignorados: {nested})"
    yield "Por categoria:"
    for cat, n in s.by_category:
        yield f"  {n:>6}  {cat}"
    pct = (100 * s.without_mark / s.total) if s.total else 0.0
    yield f"Sem Marca: {s.without_mark} ({pct:.1f}%)"
    yield "10 marcas com mais peças:"
    for (mark, cat), n in s.top_marks:
        yield f"  {n:>6}  {mark}  [{cat}]"


# --------------------------------------------------------------------------- cli


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lê versões, manifest e propriedades de um item.")
    p.add_argument("--project", required=True, help="project_id (b.xxx)")
    p.add_argument("--item", required=True, help="item_id (urn:adsk.wipprod:dm.lineage:...)")
    p.add_argument("--version", type=int, help="número da versão (padrão: mais recente)")
    return p.parse_args(argv)


def run(
    args: argparse.Namespace, http: httpx.Client, reader_factory: Callable[..., ModelReader]
) -> Path:
    client_id = os.getenv("APS_CLIENT_ID", "").strip()
    client_secret = os.getenv("APS_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ApsError(f"Defina APS_CLIENT_ID e APS_CLIENT_SECRET em {ENV_FILE}")
    region = os.getenv("APS_REGION", "US").strip().upper() or "US"
    mark_names = env_list("MARK_PROPERTY_NAMES", DEFAULT_MARK_NAMES)
    category_names = env_list("CATEGORY_PROPERTY_NAMES", DEFAULT_CATEGORY_NAMES)

    reader = reader_factory(http, get_token(http, client_id, client_secret), region)

    versions = reader.versions(args.project, args.item)
    if not versions:
        raise ApsError("Item sem versões.")
    print("Versões:")
    for v in versions:
        deriv = "com derivativo" if v.derivative_urn else "SEM derivativo"
        print(f"  v{v.number:<4} {v.created:<26} {v.author:<30} {v.name}  ({deriv})")

    if args.version is None:
        chosen = versions[0]
    else:
        match = [v for v in versions if v.number == args.version]
        if not match:
            raise ApsError(f"Versão {args.version} não existe.")
        chosen = match[0]
    print(f"\nVersão escolhida: v{chosen.number} - {chosen.name}")

    if not chosen.derivative_urn:
        raise NoTranslationError(NO_TRANSLATION_MSG)
    urn = chosen.derivative_urn
    print(f"URN: {urn}")

    status = check_manifest(reader.manifest(urn))
    print(f"Manifest: {status}")

    view = choose_3d_view(reader.views(urn))
    print(f"Vista 3D: {view.get('name')} ({view.get('guid')})")
    guid = str(view["guid"])

    tree = reader.tree(urn, guid)
    props = reader.properties(urn, guid)
    elements, nested = extract_elements(tree, props, mark_names, category_names)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{safe_name(args.item)}_v{chosen.number}.json"
    doc = {
        "project_id": args.project,
        "item_id": args.item,
        "version_id": chosen.id,
        "version_number": chosen.number,
        "file_name": chosen.name,
        "author": chosen.author,
        "created": chosen.created,
        "urn": urn,
        "view": {"guid": guid, "name": view.get("name")},
        "mark_property_names": mark_names,
        "category_property_names": category_names,
        "nested_components_ignored": nested,
        "elements": elements,
    }
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    print()
    for line in format_stats(compute_stats(elements), nested):
        print(line)
    print(f"\nJSON salvo em {out}")
    return out


def main(argv: list[str] | None = None, http: httpx.Client | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    load_dotenv(ENV_FILE)
    own_http = http is None
    http = http or httpx.Client(base_url=BASE_URL, timeout=120.0)
    try:
        run(args, http, ModelReader)
    except NoTranslationError as exc:
        print(f"PARADO: {exc}. Publique de forma que o Docs gere a visualização.", file=sys.stderr)
        return 3
    except ApsError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"ERRO de rede: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if own_http:
            http.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
