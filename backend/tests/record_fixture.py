"""Grava respostas REAIS do APS como fixture de teste, sanitizadas (só GET).

    cd backend && uv run python -m tests.record_fixture --urn <urn base64> --out rvt_real \\
        [--per-type 3] [--simulate-marks] [--type-depth 5] [--redact "<nome do projeto>"]

Salva em tests/fixtures/aps/models/<out>/: manifest.json, metadata.json, tree.json e
properties.json. Sanitização:
- propriedades do nó raiz ("Model", com dados do projeto/cliente) são descartadas;
- só um subconjunto: em cada tipo (3º nível da árvore), as primeiras N instâncias;
- --simulate-marks: preenche "Dados de identidade > Marca" (vazia em modelos de
  orçamento) com <Marca de tipo>-<nn>, uma marca por (tipo, PEÇA-Comprimento): peças
  iguais, mesma marca. Marcado como simulado no README da pasta.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.aps import build_aps_client
from app.aps import derivatives as md
from app.config import get_settings

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "aps" / "models"


def _prune(
    node: dict[str, Any], depth: int, per_type: int, keep: set[int], type_depth: int = 3
) -> dict[str, Any]:
    keep.add(node["objectid"])
    children = node.get("objects") or []
    if depth == type_depth:  # tipo (Revit) / classe por pavimento (IFC): primeiras N
        children = children[:per_type]
    out = {k: v for k, v in node.items() if k != "objects"}
    if children:
        out["objects"] = [_prune(c, depth + 1, per_type, keep, type_depth) for c in children]
    return out


def _simulate_marks(props: list[dict[str, Any]]) -> int:
    codes: dict[tuple[str, str], str] = {}
    count: dict[str, int] = {}
    filled = 0
    for p in props:
        ident = (p.get("properties") or {}).get("Dados de identidade")
        if not isinstance(ident, dict) or "Marca" not in ident:
            continue  # nós de tipo/família não têm a Marca de instância
        tipo = str(ident.get("Marca de tipo") or "X")
        length = str(((p["properties"].get("Cotas") or {}).get("PEÇA-Comprimento")) or "")
        key = (tipo, length)
        if key not in codes:
            count[tipo] = count.get(tipo, 0) + 1
            codes[key] = f"{tipo}-{count[tipo]:02d}"
        ident["Marca"] = codes[key]
        filled += 1
    return filled


async def main(
    urn: str, out: str, per_type: int, simulate: bool, type_depth: int, redact: list[str]
) -> None:
    aps = build_aps_client(get_settings())
    try:
        manifest = await aps.get_json(f"{aps.md_prefix}/{urn}/manifest")
        metadata = await aps.get_json(f"{aps.md_prefix}/{urn}/metadata")
        view = md.choose_3d_view(await md.get_metadata(aps, urn))
        tree_body = await aps.get_json(f"{aps.md_prefix}/{urn}/metadata/{view.guid}")
        props_body = await aps.get_json(f"{aps.md_prefix}/{urn}/metadata/{view.guid}/properties")
    finally:
        await aps.http.aclose()

    keep: set[int] = set()
    roots = tree_body["data"]["objects"]
    tree_body["data"]["objects"] = [_prune(r, 0, per_type, keep, type_depth) for r in roots]
    root_ids = {r["objectid"] for r in roots}
    collection = [p for p in props_body["data"]["collection"] if p["objectid"] in keep]
    spatial = {"ifcproject", "ifcsite", "ifcbuilding"}
    for p in collection:
        attrs = (p.get("properties") or {}).get("IFC Attributes") or {}
        if p["objectid"] in root_ids or str(attrs.get("IfcClass", "")).lower() in spatial:
            p["properties"] = {}  # dados do projeto/cliente/endereço
    props_body["data"]["collection"] = collection
    simulated = _simulate_marks(collection) if simulate else 0

    # urn/ids do projeto no manifest e no metadata: fictícios
    manifest["urn"] = "dXJuOnJ2dF9yZWFs"
    for d in manifest.get("derivatives") or []:
        d.pop("name", None)

    folder = FIXTURES / out
    folder.mkdir(parents=True, exist_ok=True)
    for name, body in (
        ("manifest", manifest),
        ("metadata", metadata),
        ("tree", tree_body),
        ("properties", props_body),
    ):
        text = json.dumps(body, ensure_ascii=False, indent=1) + "\n"
        for secret in redact:  # nome do projeto/arquivo que aparece em nomes de grupo/nó
            text = text.replace(secret, "MODELO-TESTE")
        (folder / f"{name}.json").write_text(text, encoding="utf-8")
    print(f"{len(collection)} nós gravados em {folder} (marcas simuladas: {simulated})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--urn", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-type", type=int, default=3)
    ap.add_argument("--simulate-marks", action="store_true")
    ap.add_argument("--type-depth", type=int, default=3, help="Revit 3; IFC 5")
    ap.add_argument("--redact", action="append", default=[], help="texto a trocar")
    a = ap.parse_args()
    asyncio.run(main(a.urn, a.out, a.per_type, a.simulate_marks, a.type_depth, a.redact))
