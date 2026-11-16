"""Gera as fixtures SINTÉTICAS models/revisao_v1 e models/revisao_v2 (Fase 7).

    cd backend && uv run python -m tests.make_revisao_fixture

Duas versões do mesmo modelo com os 7 casos da reconciliação plantados (Pilares em
"Structural Columns", vigas em "Structural Framing"). Propriedade de revisão em texto:
"Seção" (use REVIEW_PROPERTY_NAMES=Seção); dimensões: Largura/Altura/Comprimento.

| Marca | v1 | v2 | Caso |
|---|---|---|---|
| V-01 | 2 vigas | igual | 1 inalterada |
| PP002 | 2 pilares | movidos + externalId novo (apagados e recriados) | 2 e 3 = inalterada |
| PP003 | 2 pilares | 3 pilares | 4 quantidade |
| PP001 | 2 pilares 40x60 | 40x80 | 5 seção alterada (diff) |
| PP004 | 1 pilar | renomeado PP004A | 6 removida + nova |
| PP005 | 1 pilar | some | 7 removida |
| PP006 | 1 pilar | some | removida (os testes não dão valores a ela) |
| PP007 | — | 1 pilar | nova |
| (sem Marca) | dbid 30 | dbid 30 | — |
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FOLDER = Path(__file__).resolve().parent / "fixtures" / "aps" / "models"
COLS, FRAMING = "Structural Columns", "Structural Framing"


def _pilar(
    dbid: int,
    mark: str | None,
    *,
    ext: str,
    secao: str = "40x60",
    altura: str = "60.0 cm",
    ponto: str = "0,0,0",
    nivel: str = "TÉRREO",
) -> dict[str, Any]:
    ident: dict[str, Any] = {"Tipo": f"Pilar {secao}", "Seção": secao}
    if mark is not None:
        ident["Marca"] = mark
    return {
        "objectid": dbid,
        "name": f"Pilar pré-moldado [{dbid}]",
        "externalId": ext,
        "properties": {
            "Dados de identidade": ident,
            "Dimensões": {"Largura": "40.0 cm", "Altura": altura, "Comprimento": "600.0 cm"},
            "Restrições": {"Nível base": nivel},
            "Localização": {"Ponto": ponto},
            "Other": {"Category": f"Revit {COLS}"},
        },
    }


def _viga(dbid: int, mark: str, *, ext: str) -> dict[str, Any]:
    return {
        "objectid": dbid,
        "name": f"Viga [{dbid}]",
        "externalId": ext,
        "properties": {
            "Dados de identidade": {"Marca": mark, "Tipo": "Viga 30x60", "Seção": "30x60"},
            "Dimensões": {"Comprimento": "6000 mm"},
            "Restrições": {"Nível base": "TÉRREO"},
            "Other": {"Category": f"Revit {FRAMING}"},
        },
    }


def v1() -> list[dict[str, Any]]:
    return [
        _pilar(10, "PP001", ext="r1-10"),
        _pilar(11, "PP001", ext="r1-11"),
        _pilar(12, "PP002", ext="r1-12", ponto="100,0,0"),
        _pilar(13, "PP002", ext="r1-13", ponto="200,0,0"),
        _pilar(14, "PP003", ext="r1-14"),
        _pilar(15, "PP003", ext="r1-15"),
        _pilar(17, "PP004", ext="r1-17"),
        _pilar(18, "PP005", ext="r1-18"),
        _pilar(22, "PP006", ext="r1-22"),
        _pilar(30, None, ext="r1-30"),
        _viga(20, "V-01", ext="r1-20"),
        _viga(21, "V-01", ext="r1-21"),
    ]


def v2() -> list[dict[str, Any]]:
    return [
        _pilar(10, "PP001", ext="r1-10", secao="40x80", altura="80.0 cm"),
        _pilar(11, "PP001", ext="r1-11", secao="40x80", altura="80.0 cm"),
        _pilar(40, "PP002", ext="r2-40", ponto="150,50,0"),  # apagado/recriado e movido
        _pilar(41, "PP002", ext="r2-41", ponto="250,50,0"),
        _pilar(14, "PP003", ext="r1-14"),
        _pilar(15, "PP003", ext="r1-15"),
        _pilar(16, "PP003", ext="r2-16"),
        _pilar(17, "PP004A", ext="r1-17"),  # renomeada
        _pilar(19, "PP007", ext="r2-19"),  # nova
        _pilar(30, None, ext="r1-30"),
        _viga(20, "V-01", ext="r1-20"),
        _viga(21, "V-01", ext="r1-21"),
    ]


def _tree(items: list[dict[str, Any]]) -> dict[str, Any]:
    def leaves(cat: str) -> list[dict[str, Any]]:
        return [
            {"objectid": i["objectid"], "name": i["name"]}
            for i in items
            if i["properties"]["Other"]["Category"] == f"Revit {cat}"
        ]

    return {
        "data": {
            "type": "objects",
            "objects": [
                {
                    "objectid": 1,
                    "name": "Model",
                    "objects": [
                        {
                            "objectid": 2,
                            "name": COLS,
                            "objects": [
                                {
                                    "objectid": 3,
                                    "name": "Pilar pré-moldado",
                                    "objects": leaves(COLS),
                                }
                            ],
                        },
                        {
                            "objectid": 4,
                            "name": FRAMING,
                            "objects": [
                                {"objectid": 5, "name": "Viga", "objects": leaves(FRAMING)}
                            ],
                        },
                    ],
                }
            ],
        }
    }


def write(name: str, items: list[dict[str, Any]]) -> None:
    folder = FOLDER / name
    folder.mkdir(parents=True, exist_ok=True)
    meta = {
        "data": {
            "type": "metadata",
            "metadata": [
                {"name": "{3D}", "role": "3d", "guid": f"{name}-3d", "isMasterView": True}
            ],
        }
    }
    props = {"data": {"type": "properties", "collection": items}}
    for fname, body in (("metadata", meta), ("tree", _tree(items)), ("properties", props)):
        text = json.dumps(body, ensure_ascii=False, indent=1) + "\n"
        (folder / f"{fname}.json").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    write("revisao_v1", v1())
    write("revisao_v2", v2())
    print(f"fixtures gravadas em {FOLDER / 'revisao_v1'} e {FOLDER / 'revisao_v2'}")
