"""Comandos administrativos.

    uv run python -m app.cli hooks register --obra 1   # registra dm.version.added/modified
    uv run python -m app.cli hooks list [--obra 1]
    uv run python -m app.cli hooks delete --obra 1
    uv run python -m app.cli hooks set-secret          # registra APS_WEBHOOK_SECRET no APS
    uv run python -m app.cli hooks reregister --all    # PUBLIC_BASE_URL nova: refaz os hooks
    uv run python -m app.cli alerts test               # manda um alerta de teste (Teams/e-mail)
    uv run python -m app.cli versions retry --version 7   # reconsulta o Docs e reprocessa
    uv run python -m app.cli sync --obra 1 | --all     # "Sincronizar agora" pela linha de comando
    uv run python -m app.cli dates list [--obra 12]    # datas fora de 1900–2100 (por marca e peça)
    uv run python -m app.cli dates fix p:34 --clear | --set 2026-05-05 [--user email]

O callback é PUBLIC_BASE_URL + /api/webhooks/aps (ex.: URL do túnel).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aps import build_aps_client
from app.aps import webhooks as wh
from app.aps.client import ApsClient
from app.aps.errors import ApsError
from app.config import Settings, get_settings
from app.db import create_engine, create_sessionmaker
from app.models import ModelVersion, Obra, User
from app.models.enums import Role, VersionStatus
from app.observability import alerts
from app.services import invalid_dates, piece_props
from app.services import versions as versions_service
from app.services import webhooks as hooks_service
from app.services.errors import DomainError
from app.services.translation import PROCESS_VERSION_JOB, Outcome, check_translation
from app.workers.queue import ArqQueue, JobQueue


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="group", required=True)
    hooks = sub.add_parser("hooks", help="webhooks do APS por obra")
    cmds = hooks.add_subparsers(dest="cmd", required=True)
    for name, needs_obra in (("register", True), ("list", False), ("delete", True)):
        c = cmds.add_parser(name)
        c.add_argument("--obra", type=int, required=needs_obra, help="id da obra")
    cmds.add_parser("set-secret")
    rereg = cmds.add_parser("reregister", help="refaz os hooks de todas as obras (URL nova)")
    rereg.add_argument("--all", action="store_true", required=True, help="todas as obras")
    alerts_cmd = sub.add_parser("alerts", help="alertas operacionais")
    alerts_cmds = alerts_cmd.add_subparsers(dest="cmd", required=True)
    alerts_cmds.add_parser("test", help="envia um alerta de teste pelos canais configurados")
    versions_cmd = sub.add_parser("versions", help="versões dos modelos")
    versions_cmds = versions_cmd.add_subparsers(dest="cmd", required=True)
    retry = versions_cmds.add_parser(
        "retry", help="reconsulta a conversão no Docs e reprocessa uma versão failed/no_translation"
    )
    retry.add_argument("--version", type=int, required=True, help="id da versão")
    pp_cmd = sub.add_parser("piece-props", help="motor de filtros: valores das peças")
    pp_cmds = pp_cmd.add_subparsers(dest="cmd", required=True)
    backfill = pp_cmds.add_parser(
        "backfill", help="monta piece_props de versões já processadas (sem chamar o APS)"
    )
    pp_target = backfill.add_mutually_exclusive_group(required=True)
    pp_target.add_argument("--version", type=int, help="id da versão")
    pp_target.add_argument("--all", action="store_true", help="todas as versões prontas")
    dates_cmd = sub.add_parser("dates", help="datas gravadas fora de 1900–2100")
    dates_cmds = dates_cmd.add_subparsers(dest="cmd", required=True)
    dates_list = dates_cmds.add_parser("list", help="lista as datas inválidas")
    dates_list.add_argument("--obra", type=int, help="só esta obra")
    dates_fix = dates_cmds.add_parser("fix", help="limpa ou corrige uma data inválida (auditado)")
    dates_fix.add_argument("key", help='id da lista ("m:12" por marca, "p:34" por peça)')
    action = dates_fix.add_mutually_exclusive_group(required=True)
    action.add_argument("--clear", action="store_true", help="apaga o valor")
    action.add_argument("--set", metavar="AAAA-MM-DD", help="grava esta data")
    dates_fix.add_argument("--user", help="e-mail de quem corrige (padrão: 1º admin)")
    sync_cmd = sub.add_parser("sync", help='"Sincronizar agora" (uma obra ou todas as ativas)')
    target = sync_cmd.add_mutually_exclusive_group(required=True)
    target.add_argument("--obra", type=int, help="id da obra")
    target.add_argument("--all", action="store_true", help="todas as obras ativas vinculadas")
    return p


async def _obra(session: AsyncSession, obra_id: int) -> Obra:
    obra = await session.get(Obra, obra_id)
    if obra is None:
        raise SystemExit(f"Obra {obra_id} não encontrada.")
    return obra


RETRYABLE = {VersionStatus.FAILED.value, VersionStatus.NO_TRANSLATION.value}


async def _retry_version(
    session: AsyncSession, aps: ApsClient, queue: JobQueue, version_id: int
) -> int:
    """RUNBOOK › versão com falha: só GET no manifest (nunca POST /job)."""
    version = await session.get(ModelVersion, version_id)
    if version is None:
        print(f"Versão {version_id} não encontrada.", file=sys.stderr)
        return 2
    if version.status not in RETRYABLE:
        print(
            f"Versão {version_id} está '{version.status}': só failed/no_translation são "
            "reprocessadas por aqui.",
            file=sys.stderr,
        )
        return 2
    outcome = await check_translation(session, aps, version)
    await session.commit()
    if outcome is not Outcome.READY:
        print(
            f"Versão {version_id}: a conversão do Docs continua '{version.status}' "
            f"({version.error or 'sem detalhe'}). Republique o arquivo no Docs."
        )
        return 1
    # id de job novo: o Arq guarda o resultado do job anterior com o id padrão
    job_id = f"{PROCESS_VERSION_JOB}:{version_id}:retry:{datetime.now(UTC):%Y%m%d%H%M%S}"
    await queue.enqueue(PROCESS_VERSION_JOB, version_id, job_id=job_id)
    print(f"Versão {version_id}: conversão pronta; reprocessamento enfileirado ({job_id}).")
    return 0


async def _sync(session: AsyncSession, aps: ApsClient, queue: JobQueue, obra_id: int | None) -> int:
    """RUNBOOK › sync manual: o mesmo do botão "Sincronizar agora", com o resultado."""
    if obra_id is None:
        ids = list(
            await session.scalars(
                select(Obra.id)
                .where(Obra.active.is_(True), Obra.acc_item_id.is_not(None))
                .order_by(Obra.id)
            )
        )
    else:
        ids = [(await _obra(session, obra_id)).id]
    errors = 0
    for oid in ids:
        try:
            r = await versions_service.sync_versions(session, aps, queue, oid)
        except ApsError as exc:
            await session.rollback()
            print(f"obra {oid}: ERRO {exc}", file=sys.stderr)
            errors += 1
            continue
        print(
            f"obra {oid}: {r.total_in_docs} no Docs, {len(r.created_ids)} nova(s), "
            f"{r.enqueued} para processar, {r.translating} convertendo, "
            f"{r.no_translation} sem conversão, {r.failed} com falha"
        )
    return 1 if errors else 0


async def _backfill_piece_props(session: AsyncSession, version_id: int | None) -> int:
    """Versões já processadas antes do motor de filtros: monta piece_props a partir do
    que está no banco (elements.props, marcas, valores). Um commit por versão."""
    stmt = select(ModelVersion).where(ModelVersion.status == VersionStatus.READY.value)
    if version_id is not None:
        stmt = select(ModelVersion).where(ModelVersion.id == version_id)
    versions = list(await session.scalars(stmt.order_by(ModelVersion.id)))
    if not versions:
        print("Nenhuma versão encontrada.", file=sys.stderr)
        return 2
    for v in versions:
        rows = await piece_props.rebuild_version(session, v.id)
        await session.commit()
        print(f"versão {v.id} (obra {v.obra_id}, v{v.version_number}): {rows} valores")
    return 0


async def _dates(session: AsyncSession, args: argparse.Namespace) -> int:
    """Datas inválidas (docs/bugs/data-por-peca.md): listar, limpar ou corrigir."""
    if args.cmd == "list":
        found = await invalid_dates.list_invalid(session, args.obra)
        for d in found:
            print(f"{d.key}\t{d.obra}\t{d.level}\t{d.where}\t{d.param}\t{d.value}")
        print(f"{len(found)} data(s) inválida(s).")
        return 0
    actor = await session.scalar(
        select(User)
        .where(User.email == args.user if args.user else User.role == Role.ADMIN.value)
        .order_by(User.id)
        .limit(1)
    )
    if actor is None:
        print("ERRO: usuário não encontrado (use --user com o e-mail).", file=sys.stderr)
        return 2
    try:
        item = await invalid_dates.fix(session, args.key, None if args.clear else args.set, actor)
    except DomainError as exc:
        print(f"ERRO: {exc.message}", file=sys.stderr)
        return 2
    await session.commit()
    what = "apagada" if args.clear else f"corrigida para {args.set}"
    print(f"{item.obra} · {item.where} · {item.param}: {item.value} {what} (por {actor.name}).")
    return 0


async def run(
    argv: Sequence[str],
    settings: Settings,
    session: AsyncSession,
    aps: ApsClient,
    queue: JobQueue | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if args.group == "piece-props":
        return await _backfill_piece_props(session, None if args.all else args.version)
    if args.group == "dates":
        return await _dates(session, args)
    if args.group == "sync":
        if queue is None:  # pragma: no cover - _main sempre passa
            raise RuntimeError("fila não configurada")
        return await _sync(session, aps, queue, None if args.all else args.obra)
    if args.group == "versions":
        if queue is None:  # pragma: no cover - _main sempre passa
            raise RuntimeError("fila não configurada")
        return await _retry_version(session, aps, queue, args.version)
    if args.group == "alerts":
        notifiers = alerts.notifiers_from_settings(settings)
        if not notifiers:
            print(
                "Nenhum canal configurado: defina ALERT_TEAMS_WEBHOOK_URL e/ou SMTP_HOST + "
                "ALERT_EMAIL_TO em infra/.env.",
                file=sys.stderr,
            )
            return 2
        ok = await alerts.send_test(settings, notifiers)
        print(f"Alerta de teste enviado por: {', '.join(ok)}.")
        return 0
    if args.cmd == "set-secret":
        secret = settings.aps_webhook_secret.get_secret_value()
        if len(secret) < 16:
            print("Defina APS_WEBHOOK_SECRET (16+ caracteres) em infra/.env.", file=sys.stderr)
            return 2
        print(f"Secret de assinatura {await wh.set_secret(aps, secret)}.")
        return 0

    if args.cmd == "reregister":
        callback = settings.webhook_callback_url
        if not callback:
            print(
                "Defina PUBLIC_BASE_URL (URL pública de produção do backend). Sem ela os "
                "webhooks ficam desligados e as versões chegam pela verificação periódica.",
                file=sys.stderr,
            )
            return 2
        obras = list(await session.scalars(select(Obra).order_by(Obra.id)))
        rr = await hooks_service.reregister_all_hooks(aps, obras, callback)
        print(f"Callback: {callback}")
        print(f"{len(rr.deleted)} hook(s) com URL antiga apagado(s).")
        for obra_id, events in rr.created.items():
            parts = [f"{ev} {'criado' if hid else 'já existia'}" for ev, hid in events.items()]
            print(f"obra {obra_id}: {', '.join(parts)}")
        for obra_id, reason in rr.skipped.items():
            print(f"obra {obra_id}: ignorada ({reason})")
        return 0

    if args.cmd == "register":
        callback = settings.webhook_callback_url
        if not callback:
            print("Defina PUBLIC_BASE_URL (URL pública do backend) em infra/.env.", file=sys.stderr)
            return 2
        obra = await _obra(session, args.obra)
        result = await hooks_service.register_obra_hooks(aps, obra, callback)
        for event, hook_id in result.items():
            print(f"{event}: {'criado ' + hook_id if hook_id else 'já existia'}")
        return 0

    if args.cmd == "list":
        target = await _obra(session, args.obra) if args.obra else None
        hooks = await hooks_service.list_obra_hooks(aps, target)
        if not hooks:
            print("(nenhum hook)")
        for h in hooks:
            attrs = h.get("hookAttribute") or {}
            print(
                f"{h.get('hookId')}  {h.get('event'):<22} {h.get('status', '?'):<9} "
                f"obra={attrs.get('obra_id', '-')}  {h.get('callbackUrl')}"
            )
        return 0

    obra = await _obra(session, args.obra)
    deleted = await hooks_service.delete_obra_hooks(aps, obra)
    print(f"{len(deleted)} hook(s) apagado(s).")
    return 0


async def _main(argv: Sequence[str]) -> int:
    for stream in (sys.stdout, sys.stderr):  # console do Windows: acentos corretos
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    settings = get_settings()
    engine = create_engine(settings.database_url)
    aps = build_aps_client(settings)
    queue = ArqQueue(settings.redis_url)
    try:
        async with create_sessionmaker(engine)() as session:
            return await run(argv, settings, session, aps, queue)
    except ApsError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    finally:
        await queue.close()
        await aps.http.aclose()
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
