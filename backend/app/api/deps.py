from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.aps.client import ApsClient
from app.auth import Role
from app.workers.queue import JobQueue

# Quem cria/edita obras e navega no Docs.
EDITOR_ROLES = (Role.PROJETOS, Role.ADMIN)
# Quem pode disparar a sincronização de versões.
SYNC_ROLES = (Role.PROJETOS, Role.FABRICA, Role.ADMIN)


def get_aps_client(request: Request) -> ApsClient:
    aps: ApsClient = request.app.state.aps
    return aps


def get_queue(request: Request) -> JobQueue:
    queue: JobQueue = request.app.state.queue
    return queue


ApsDep = Annotated[ApsClient, Depends(get_aps_client)]
QueueDep = Annotated[JobQueue, Depends(get_queue)]
