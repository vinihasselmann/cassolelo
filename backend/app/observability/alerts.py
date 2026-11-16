"""Alertas operacionais (Fase 10.1), avaliados por um cron do worker a cada 5 min.

Gatilhos:
- versão com status `failed` (por versão; atualizada nos últimos 7 dias);
- versão em `no_translation` há mais de 2 h (por versão);
- nenhum webhook recebido em 24 h enquanto a verificação periódica achou versões novas
  nesse período (só quando os webhooks estão configurados: APS_WEBHOOK_CALLBACK_URL);
- erro de credencial do APS (401/403) nos últimos 15 min.

Canais (configuráveis no .env; sem nenhum, o alerta só vai para o log):
- e-mail: SMTP_HOST/PORT/USER/PASSWORD/FROM/STARTTLS + ALERT_EMAIL_TO (lista);
- Microsoft Teams: ALERT_TEAMS_WEBHOOK_URL (Workflows "post to a channel when a webhook
  request is received"; mensagem com cartão adaptativo).

Deduplicação: cada alerta tem uma chave e só é enviado de novo depois do intervalo
dela (Redis SET NX EX), mesmo com vários workers.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Protocol

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import ModelVersion, Obra, WebhookEvent
from app.models.enums import VersionStatus
from app.observability.metrics import MetricsStore

log = logging.getLogger("app.alerts")

NO_TRANSLATION_AFTER = timedelta(hours=2)
WEBHOOK_SILENCE = timedelta(hours=24)
APS_AUTH_WINDOW = timedelta(minutes=15)
LOOKBACK = timedelta(days=7)  # não alertar falhas antigas na primeira execução
DAY = 24 * 3600


@dataclass(frozen=True)
class Alert:
    key: str  # deduplicação
    title: str
    text: str
    ttl_seconds: int  # não repetir antes disso
    severity: str = "warning"


class Notifier(Protocol):
    name: str

    async def send(self, alert: Alert) -> None: ...


# --------------------------------------------------------------------------- canais


class TeamsNotifier:
    name = "teams"

    def __init__(self, url: str, http: httpx.AsyncClient | None = None) -> None:
        self.url = url
        self.http = http

    @staticmethod
    def payload(alert: Alert) -> dict[str, object]:
        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": f"⚠️ Cassol Elo · {alert.title}",
                                "weight": "Bolder",
                                "wrap": True,
                            },
                            {"type": "TextBlock", "text": alert.text, "wrap": True},
                        ],
                    },
                }
            ],
        }

    async def send(self, alert: Alert) -> None:
        client = self.http or httpx.AsyncClient(timeout=15)
        try:
            resp = await client.post(self.url, json=self.payload(alert))
            resp.raise_for_status()
        finally:
            if self.http is None:
                await client.aclose()


class EmailNotifier:
    name = "email"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def message(self, alert: Alert) -> EmailMessage:
        s = self.settings
        msg = EmailMessage()
        msg["Subject"] = f"[Cassol Elo] {alert.title}"
        msg["From"] = s.smtp_from or s.smtp_user
        msg["To"] = ", ".join(s.alert_email_list)
        msg.set_content(f"{alert.text}\n\n— Cassol Elo ({s.app_env})")
        return msg

    def _send_sync(self, msg: EmailMessage) -> None:
        s = self.settings
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
            if s.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            password = s.smtp_password.get_secret_value()
            if s.smtp_user and password:
                smtp.login(s.smtp_user, password)
            smtp.send_message(msg)

    async def send(self, alert: Alert) -> None:
        await asyncio.to_thread(self._send_sync, self.message(alert))


def notifiers_from_settings(settings: Settings) -> list[Notifier]:
    out: list[Notifier] = []
    url = settings.alert_teams_webhook_url.get_secret_value()
    if url:
        out.append(TeamsNotifier(url))
    if settings.smtp_host and settings.alert_email_list:
        out.append(EmailNotifier(settings))
    return out


# --------------------------------------------------------------------------- gatilhos


def _rev(n: int) -> str:
    return f"Rev.{n:02d}"


def _link(settings: Settings, obra_id: int) -> str:
    base = settings.app_base_url.rstrip("/")
    return f"\n{base}/obras/{obra_id}/versoes" if base else ""


async def evaluate(
    session: AsyncSession, store: MetricsStore, settings: Settings, now: datetime | None = None
) -> list[Alert]:
    """Alertas que valem agora (antes da deduplicação)."""
    now = now or datetime.now(UTC)
    alerts: list[Alert] = []

    failed = await session.execute(
        select(ModelVersion, Obra.code)
        .join(Obra, Obra.id == ModelVersion.obra_id)
        .where(
            ModelVersion.status == VersionStatus.FAILED.value,
            ModelVersion.updated_at >= now - LOOKBACK,
        )
        .order_by(ModelVersion.id)
    )
    for v, code in failed:
        alerts.append(
            Alert(
                key=f"version_failed:{v.id}",
                title=f"Versão com falha: {code} {_rev(v.version_number)}",
                text=(
                    f"A versão {_rev(v.version_number)} da obra {code} falhou: "
                    f"{v.error or 'sem detalhe'}{_link(settings, v.obra_id)}"
                ),
                ttl_seconds=30 * DAY,
                severity="error",
            )
        )

    stuck = await session.execute(
        select(ModelVersion, Obra.code)
        .join(Obra, Obra.id == ModelVersion.obra_id)
        .where(
            ModelVersion.status == VersionStatus.NO_TRANSLATION.value,
            ModelVersion.updated_at <= now - NO_TRANSLATION_AFTER,
            ModelVersion.updated_at >= now - LOOKBACK,
        )
        .order_by(ModelVersion.id)
    )
    for v, code in stuck:
        hours = int((now - v.updated_at).total_seconds() // 3600)
        alerts.append(
            Alert(
                key=f"no_translation:{v.id}",
                title=f"Sem conversão há {hours} h: {code} {_rev(v.version_number)}",
                text=(
                    f"O Docs não converteu a versão {_rev(v.version_number)} da obra {code} "
                    f"(sem visualização há {hours} h). Republicar o arquivo costuma resolver."
                    f"{_link(settings, v.obra_id)}"
                ),
                ttl_seconds=30 * DAY,
            )
        )

    snap = await store.snapshot()
    if settings.webhook_callback_url:
        found = snap.marks.get("periodic_found_versions")
        last = await session.scalar(select(func.max(WebhookEvent.received_at)))
        silent = last is None or last <= now - WEBHOOK_SILENCE
        if found is not None and found >= (now - WEBHOOK_SILENCE).timestamp() and silent:
            since = f"desde {last:%d/%m %H:%M} UTC" if last else "nenhum registrado"
            alerts.append(
                Alert(
                    key="webhook_silence",
                    title="Webhooks do APS parados",
                    text=(
                        f"Nenhum webhook recebido em 24 h ({since}), mas a verificação "
                        "periódica encontrou versões novas. Confira o registro dos webhooks "
                        "(python -m app.cli hooks register) e a URL pública."
                    ),
                    ttl_seconds=DAY,
                )
            )

    auth_at = snap.marks.get("aps_auth_error")
    if auth_at is not None and auth_at >= (now - APS_AUTH_WINDOW).timestamp():
        when = datetime.fromtimestamp(auth_at, UTC)
        alerts.append(
            Alert(
                key="aps_auth",
                title="Credenciais do APS com erro (401/403)",
                text=(
                    f"O APS recusou as credenciais do app às {when:%H:%M} UTC. Verifique "
                    "APS_CLIENT_ID/APS_CLIENT_SECRET e se o app continua liberado em "
                    "Custom Integrations do ACC."
                ),
                ttl_seconds=6 * 3600,
                severity="error",
            )
        )
    alerts.extend(_backup_alerts(snap.marks, settings, now))
    return alerts


def _backup_alerts(marks: dict[str, float], settings: Settings, now: datetime) -> list[Alert]:
    """Backup diário (10.3): o script grava backup_last_ok / backup_last_failed no Redis."""
    max_age = settings.backup_max_age_hours
    if max_age <= 0:
        return []
    ok_at = marks.get("backup_last_ok")
    failed_at = marks.get("backup_last_failed")
    if failed_at is not None and (ok_at is None or failed_at > ok_at):
        when = datetime.fromtimestamp(failed_at, UTC)
        return [
            Alert(
                key=f"backup_failed:{int(failed_at)}",
                title="Backup do banco falhou",
                text=(
                    f"O backup das {when:%d/%m %H:%M} UTC falhou. Veja o log da tarefa de "
                    "backup e o espaço na pasta (docs/RUNBOOK.md › Backup)."
                ),
                ttl_seconds=30 * DAY,
                severity="error",
            )
        ]
    if ok_at is None or ok_at < (now - timedelta(hours=max_age)).timestamp():
        since = (
            f"o último foi em {datetime.fromtimestamp(ok_at, UTC):%d/%m %H:%M} UTC"
            if ok_at
            else "nenhum registrado"
        )
        return [
            Alert(
                key="backup_late",
                title="Backup do banco atrasado",
                text=(
                    f"Nenhum backup bem-sucedido nas últimas {max_age} h ({since}). Confira a "
                    "tarefa agendada (docs/RUNBOOK.md › Backup)."
                ),
                ttl_seconds=DAY,
                severity="error",
            )
        ]
    return []


async def run_checks(
    session: AsyncSession,
    store: MetricsStore,
    settings: Settings,
    notifiers: Sequence[Notifier],
    now: datetime | None = None,
) -> list[Alert]:
    """Avalia, deduplica e envia. Devolve os alertas enviados (ou logados)."""
    sent: list[Alert] = []
    for alert in await evaluate(session, store, settings, now):
        if not await store.claim(alert.key, alert.ttl_seconds):
            continue
        log.warning(
            "ALERTA %s: %s",
            alert.title,
            alert.text,
            extra={"alert": alert.key, "severity": alert.severity},
        )
        for notifier in notifiers:
            try:
                await notifier.send(alert)
            except Exception:
                log.exception("Falha ao enviar o alerta %s por %s", alert.key, notifier.name)
        sent.append(alert)
    return sent


async def send_test(settings: Settings, notifiers: Sequence[Notifier] | None = None) -> list[str]:
    """Alerta de teste (python -m app.cli alerts test). Devolve os canais que funcionaram."""
    alert = Alert(
        key=f"test:{time.time()}",
        title="Teste de alerta",
        text="Se você recebeu esta mensagem, o canal de alertas está configurado.",
        ttl_seconds=60,
        severity="info",
    )
    ok: list[str] = []
    for notifier in notifiers if notifiers is not None else notifiers_from_settings(settings):
        await notifier.send(alert)
        ok.append(notifier.name)
    return ok
