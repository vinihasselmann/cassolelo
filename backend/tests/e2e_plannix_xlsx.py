"""Planilha do Plannix para o E2E (2026-11-24), no formato da exportação real:

    cd backend && uv run python -m tests.e2e_plannix_xlsx <arquivo.xlsx>

Obra E2E-PLX (modelo `pecas`: P-06 com 6 pilares, V-02 com 2 vigas). P-06 1/6 traz as 6
datas, P-06 2/6 só "Data CD"; V-02 1/2 e 2/2 só "Data FO" (Seq. convertida pelo Excel em
data, formato dia/mês). Mais uma linha recusada ("Status de Projeto" vazio) e uma marca
fora do modelo (X-99). Total: 9 datas a preencher em 4 peças.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime

from openpyxl import Workbook

HEADER = [
    "Código",
    "Peça",
    "Obra",
    "Sigla",
    "Seq.",
    "Status de Projeto",
    "Data CD",
    "Data AR",
    "Data FO",
    "Data FA",
    "Data CO",
    "Data Aca",
]
D = datetime(2026, 11, 10)


def rows() -> list[list[object]]:
    all6 = [D, D, D, D, D, D]
    out: list[list[object]] = [
        [9001, "P-06", "E2E", "E2E-PLX", "1/6", "Liberado", *all6],
        [9002, "P-06", "E2E", "E2E-PLX", "2/6", "Liberado", D, None, None, None, None, None],
    ]
    out += [
        [9000 + n, "P-06", "E2E", "E2E-PLX", f"{n}/6", "Liberado", *[None] * 6] for n in range(3, 7)
    ]
    out += [
        [
            9101,
            "V-02",
            "E2E",
            "E2E-PLX",
            datetime(2026, 2, 1),
            "Liberado",
            None,
            None,
            D,
            None,
            None,
            None,
        ],
        [9102, "V-02", "E2E", "E2E-PLX", "2/2", "Liberado", None, None, D, None, None, None],
        [9199, "V-02 /R", "E2E", "E2E-PLX", "1/2", None, D, None, None, None, None, None],
        [9901, "X-99", "E2E", "E2E-PLX", "1/1", "Liberado", D, None, None, None, None, None],
    ]
    return out


def main(path: str) -> None:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(HEADER)
    for r in rows():
        ws.append(r)
    for row in ws.iter_rows(min_row=2):
        if isinstance(row[4].value, datetime):
            row[4].number_format = "d-mmm"  # como o Excel deixa "1/2"
    wb.save(path)
    print(json.dumps({"file": path, "fills": 9, "pieces": 4}))


if __name__ == "__main__":
    main(sys.argv[1])
