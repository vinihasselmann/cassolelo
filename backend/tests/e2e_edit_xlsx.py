"""Apoio do E2E da importação: preenche, no Excel exportado, a 1ª célula VAZIA da coluna
pedida (aba Marcas) e imprime {"mark": código, "row": linha} em JSON.

    uv run python -m tests.e2e_edit_xlsx <arquivo.xlsx> "<coluna>" "<valor>"
"""

from __future__ import annotations

import json
import sys

from openpyxl import load_workbook


def main(path: str, column: str, value: str) -> None:
    wb = load_workbook(path)
    ws = wb["Marcas"]
    headers = [c.value for c in ws[1]]
    col = headers.index(column) + 1
    for row_no, row in enumerate(ws.iter_rows(min_row=2), start=2):
        cell = ws.cell(row=row_no, column=col)
        if cell.value in (None, "") and cell.fill.fgColor.rgb in (None, "00000000"):
            cell.value = value
            wb.save(path)
            print(json.dumps({"mark": row[0].value, "row": row_no}))
            return
    raise SystemExit(f"nenhuma célula vazia em {column}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
