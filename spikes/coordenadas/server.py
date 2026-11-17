"""Spike "coordenadas": serve a página de medição do eixo da peça e o token do Viewer.

Reaproveita o token do spike 0.4 (2-legged, SOMENTE viewables:read, em cache; as
credenciais do APS ficam no servidor, em spikes/.env). Não faz parte do app.

    spikes/.venv/Scripts/python spikes/coordenadas/server.py
    http://127.0.0.1:8010/?urn=<URN base64>&debug=1
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "viewer"))

import viewer_app  # noqa: E402  (spike 0.4: token e /config)

STATIC = {"axis.js": "text/javascript", "coordenadas.js": "text/javascript"}


def create_app(cache: viewer_app.TokenCache | None = None) -> FastAPI:
    app = viewer_app.create_app(cache=cache)
    app.title = "Spike coordenadas"
    # a página do spike 0.4 fica em "/"; esta substitui a raiz
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/"]

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(HERE / "coordenadas.html", media_type="text/html")

    @app.get("/{name}")
    def static(name: str) -> FileResponse:
        if name not in STATIC:
            from fastapi import HTTPException

            raise HTTPException(status_code=404)
        return FileResponse(HERE / name, media_type=STATIC[name])

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8010)
