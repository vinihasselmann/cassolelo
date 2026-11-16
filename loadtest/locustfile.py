"""Teste de carga (10.2): usuários da fábrica abrindo a obra, buscando e editando.

Cada usuário do Locust é um usuário próprio (tests/load_users.py), com a sua conta no
limite de escritas. No início cria o parâmetro "Teste de carga" (escopo da obra) e no
fim o desativa. As edições ficam na auditoria, como qualquer edição.

    cd backend && uv run python -m tests.load_users up 30      # imprime os ids
    LOAD_USER_IDS=<ids> LOAD_ADMIN_ID=<id> LOAD_OBRA_ID=5 \
      uvx --from locust==2.46.7 --with httpx locust -f ../loadtest/locustfile.py --headless \
      -u 30 -r 5 -t 5m --host http://127.0.0.1:8000 --csv ../loadtest/out/carga
    cd backend && uv run python -m tests.load_users down

Variáveis: LOAD_OBRA_ID (obra com versão pronta), LOAD_USER_IDS (ids separados por
vírgula ou JSON), LOAD_ADMIN_ID (cria/desativa o parâmetro), LOAD_PARAM_NAME.
"""

from __future__ import annotations

import itertools
import json
import os
import random
import threading
from typing import Any

from locust import HttpUser, between, events, task
from locust.env import Environment

OBRA_ID = int(os.getenv("LOAD_OBRA_ID", "5"))
ADMIN_ID = os.getenv("LOAD_ADMIN_ID", "")
PARAM_NAME = os.getenv("LOAD_PARAM_NAME", "Teste de carga")
_raw_ids = os.getenv("LOAD_USER_IDS", "").strip()
USER_IDS: list[int] = (
    json.loads(_raw_ids)
    if _raw_ids.startswith("[")
    else [int(x) for x in _raw_ids.split(",") if x.strip()]
)
_next_user = itertools.cycle(USER_IDS or [0])
_lock = threading.Lock()

SEARCH_TERMS = ["", "V", "P", "50x90", "40x60", "PP", "V01", "pilar", "viga"]

state: dict[str, Any] = {"param_def_id": None, "version_id": None}


def _admin_headers() -> dict[str, str]:
    return {"X-Dev-User": ADMIN_ID, "Content-Type": "application/json"}


@events.test_start.add_listener
def on_test_start(environment: Environment, **_kwargs: Any) -> None:
    """Parâmetro do teste (escopo da obra) e versão ativa, uma vez só."""
    import httpx

    if not USER_IDS or not ADMIN_ID:
        raise RuntimeError("Defina LOAD_USER_IDS e LOAD_ADMIN_ID (tests/load_users.py).")
    host = environment.host or "http://127.0.0.1:8000"
    with httpx.Client(base_url=host, headers=_admin_headers(), timeout=30) as c:
        versions = c.get(f"/api/obras/{OBRA_ID}/versions").raise_for_status().json()
        ready = [v for v in versions if v["status"] == "ready"]
        state["version_id"] = max(v["id"] for v in ready)
        existing = c.get("/api/param-defs", params={"obra_id": OBRA_ID}).json()
        found = [d for d in existing if d["name"] == PARAM_NAME and d.get("obra_id") == OBRA_ID]
        if found:
            state["param_def_id"] = found[0]["id"]
        else:
            body = {"name": PARAM_NAME, "type": "text", "scope": "obra", "obra_id": OBRA_ID}
            state["param_def_id"] = c.post("/api/param-defs", json=body).raise_for_status().json()[
                "id"
            ]
    print(f"Carga: obra {OBRA_ID}, versão {state['version_id']}, parâmetro {state['param_def_id']}")


@events.test_stop.add_listener
def on_test_stop(environment: Environment, **_kwargs: Any) -> None:
    import httpx

    if state["param_def_id"] is None:
        return
    host = environment.host or "http://127.0.0.1:8000"
    with httpx.Client(base_url=host, headers=_admin_headers(), timeout=30) as c:
        c.delete(f"/api/param-defs/{state['param_def_id']}")
    print(f"Parâmetro {state['param_def_id']} ({PARAM_NAME}) desativado.")


class FabricaUser(HttpUser):
    """Uma pessoa da fábrica no tablet: pausa de 1 a 3 s entre ações."""

    wait_time = between(1, 3)

    def on_start(self) -> None:
        with _lock:
            self.user_id = next(_next_user)
        self.client.headers.update({"X-Dev-User": str(self.user_id)})
        self.marks: list[int] = []
        self.open_obra()

    @property
    def version(self) -> int:
        return int(state["version_id"])

    @task(1)
    def open_obra(self) -> None:
        """O que a tela da obra e o modelo 3D pedem ao abrir."""
        v = self.version
        self.client.get("/api/me")
        self.client.get("/api/obras", name="/api/obras")
        self.client.get(f"/api/obras/{OBRA_ID}", name="/api/obras/[id]")
        self.client.get(f"/api/obras/{OBRA_ID}/versions", name="/api/obras/[id]/versions")
        self.client.get("/api/param-defs", params={"obra_id": OBRA_ID}, name="/api/param-defs")
        self.client.get(f"/api/versions/{v}/report", name="/api/versions/[v]/report")
        self.client.get(f"/api/versions/{v}/marks/status", name="/api/versions/[v]/marks/status")
        self.client.get(f"/api/versions/{v}/progress", name="/api/versions/[v]/progress")
        self.client.get(f"/api/versions/{v}/marks/facets", name="/api/versions/[v]/marks/facets")
        self.client.get("/api/viewer-token", name="/api/viewer-token")
        r = self.client.get(
            f"/api/versions/{v}/marks/search",
            params={"page_size": 200},
            name="/api/versions/[v]/marks/search (abrir)",
        )
        if r.ok:
            self.marks = [m["mark_id"] for m in r.json()["items"]]

    @task(3)
    def search(self) -> None:
        params: dict[str, Any] = {"q": random.choice(SEARCH_TERMS), "page_size": 50}
        if random.random() < 0.3:
            params["shortcut"] = random.choice(["all", "pending", "partial"])
        self.client.get(
            f"/api/versions/{self.version}/marks/search",
            params=params,
            name="/api/versions/[v]/marks/search",
        )

    @task(2)
    def edit(self) -> None:
        """Abre a marca, edita "Teste de carga" e salva com o row_version lido. Duas
        pessoas na mesma marca ao mesmo tempo dão 409 (trava otimista): esperado."""
        if not self.marks:
            return
        mark = random.choice(self.marks)
        url = f"/api/obras/{OBRA_ID}/marks/{mark}/values"
        r = self.client.get(url, name="/api/obras/[id]/marks/[m]/values (GET)")
        if not r.ok:
            return
        field = next((f for f in r.json()["values"] if f["def_id"] == state["param_def_id"]), None)
        if field is None:
            return
        body = {
            "changes": [
                {
                    "def_id": field["def_id"],
                    "value": f"U{self.user_id}-{random.randint(1, 10_000)}",
                    "row_version": field["row_version"],
                }
            ]
        }
        with self.client.put(
            url, json=body, name="/api/obras/[id]/marks/[m]/values (PUT)", catch_response=True
        ) as resp:
            if resp.status_code == 409:
                resp.success()  # conflito de edição simultânea: comportamento correto
                events.request.fire(
                    request_type="INFO",
                    name="conflito 409 (mesma marca ao mesmo tempo)",
                    response_time=0,
                    response_length=0,
                    exception=None,
                    context={},
                )
            elif resp.status_code == 429:
                resp.failure("429: limite de escritas por usuário")
