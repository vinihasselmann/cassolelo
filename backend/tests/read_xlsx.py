"""Lê um .xlsx exportado e imprime JSON {aba: [linhas como dicionário]} (usado pelo E2E).

cd backend && uv run python -m tests.read_xlsx <arquivo.xlsx>
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from typing import Any

from openpyxl import load_workbook


def _plain(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def read(path: str) -> dict[str, Any]:
    wb = load_workbook(path)
    out: dict[str, Any] = {}
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if ws.title == "Sobre":
            out[ws.title] = {str(r[0]): _plain(r[1]) for r in rows}
            continue
        header = [str(h) for h in rows[0]] if rows else []
        out[ws.title] = [
            {h: _plain(v) for h, v in zip(header, row, strict=True)} for row in rows[1:]
        ]
        out[f"{ws.title}:layout"] = {"freeze": ws.freeze_panes, "filter": ws.auto_filter.ref}
    return out


if __name__ == "__main__":
    print(json.dumps(read(sys.argv[1])))  # ASCII: não depende da codificação do console
