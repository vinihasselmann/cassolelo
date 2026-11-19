"""Validação do access token do Microsoft Entra ID (Fase 11).

O frontend (MSAL, authorization code + PKCE) pede um access token para o escopo do
app (ENTRA_API_SCOPE) e o manda em `Authorization: Bearer`. Aqui conferimos:
assinatura RS256 pela chave do JWKS do tenant, emissor do tenant (v2 ou v1), audiência
do app, tenant (`tid`), validade (`exp`/`nbf`) e o escopo (`scp`).

O JWKS fica em cache (24 h). Um `kid` desconhecido (a Microsoft girou as chaves) força
nova busca, no máximo uma por minuto. Nunca logar o token.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from jwt import PyJWK

from app.config import Settings

LOGIN_BASE = "https://login.microsoftonline.com"
JWKS_TTL_SECONDS = 24 * 3600
JWKS_MIN_REFRESH_SECONDS = 60
LEEWAY_SECONDS = 60  # relógio do servidor e da Microsoft levemente diferentes


class TokenError(Exception):
    """Token recusado (vira 401). A mensagem vai para o usuário, em português."""


class LoginUnavailableError(Exception):
    """Não foi possível buscar as chaves da Microsoft (vira 503)."""


@dataclass(frozen=True)
class EntraIdentity:
    email: str
    name: str
    oid: str
    groups: tuple[str, ...] | None  # None = grupos não vieram no token (ou excesso)
    claims: dict[str, Any] = field(repr=False)


def jwks_url(tenant_id: str) -> str:
    return f"{LOGIN_BASE}/{tenant_id}/discovery/v2.0/keys"


class EntraVerifier:
    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._http = http
        self._own_http = http is None
        self._clock = clock
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at: float | None = None

    @property
    def tenant_id(self) -> str:
        return self._settings.entra_tenant_id.strip().lower()

    @property
    def client_id(self) -> str:
        return self._settings.entra_client_id.strip().lower()

    def audiences(self) -> list[str]:
        """O app (GUID) e o App ID URI (api://<id> ou o prefixo do escopo configurado)."""
        auds = {self.client_id, f"api://{self.client_id}"}
        scope = self._settings.entra_scope
        if "/" in scope:
            auds.add(scope.rsplit("/", 1)[0].lower())
        return sorted(auds)

    def issuers(self) -> list[str]:
        return [f"{LOGIN_BASE}/{self.tenant_id}/v2.0", f"https://sts.windows.net/{self.tenant_id}/"]

    def scope_name(self) -> str:
        return self._settings.entra_scope.rsplit("/", 1)[-1]

    async def aclose(self) -> None:
        if self._own_http and self._http is not None:
            await self._http.aclose()

    # ------------------------------------------------------------------ JWKS

    async def _fetch_keys(self) -> None:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=10.0)
        try:
            res = await self._http.get(jwks_url(self.tenant_id))
            res.raise_for_status()
            data = res.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LoginUnavailableError(
                "Não foi possível validar o login agora (Microsoft fora do ar?). Tente de novo."
            ) from exc
        keys: dict[str, PyJWK] = {}
        for raw in data.get("keys", []) if isinstance(data, dict) else []:
            if not isinstance(raw, dict) or raw.get("kty") != "RSA" or not raw.get("kid"):
                continue
            try:
                keys[str(raw["kid"])] = PyJWK.from_dict(raw, algorithm="RS256")
            except jwt.PyJWTError:
                continue
        self._keys = keys
        self._fetched_at = self._clock()

    async def _key(self, kid: str) -> PyJWK:
        now = self._clock()
        stale = self._fetched_at is None or now - self._fetched_at > JWKS_TTL_SECONDS
        if stale:
            await self._fetch_keys()
        if kid not in self._keys and self._fetched_at is not None:
            if now - self._fetched_at >= JWKS_MIN_REFRESH_SECONDS:
                await self._fetch_keys()  # chave girada
        key = self._keys.get(kid)
        if key is None:
            raise TokenError("Token inválido: chave de assinatura desconhecida.")
        return key

    # ------------------------------------------------------------------ token

    async def verify(self, token: str) -> EntraIdentity:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise TokenError("Token inválido.") from None
        if header.get("alg") != "RS256":
            raise TokenError("Token inválido: algoritmo não aceito.")
        key = await self._key(str(header.get("kid", "")))
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key.key,
                algorithms=["RS256"],
                audience=self.audiences(),
                issuer=self.issuers(),
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "iss", "aud", "tid"]},
            )
        except jwt.ExpiredSignatureError:
            raise TokenError("Sessão expirada: entre de novo.") from None
        except jwt.InvalidAudienceError:
            raise TokenError("Token inválido: emitido para outro aplicativo.") from None
        except jwt.InvalidIssuerError:
            raise TokenError("Token inválido: emitido por outro tenant.") from None
        except jwt.PyJWTError:
            raise TokenError("Token inválido.") from None

        if str(claims.get("tid", "")).lower() != self.tenant_id:
            raise TokenError("Token inválido: emitido por outro tenant.")
        scopes = str(claims.get("scp", "")).split()
        if self.scope_name() not in scopes:
            raise TokenError("Token inválido: sem o escopo do aplicativo.")

        email = _email(claims)
        if not email:
            raise TokenError("Token sem e-mail: a conta precisa de um e-mail corporativo.")
        name = str(claims.get("name") or "").strip() or email
        return EntraIdentity(
            email=email,
            name=name[:200],
            oid=str(claims.get("oid", "")),
            groups=_groups(claims),
            claims=claims,
        )


def _email(claims: dict[str, Any]) -> str:
    for key in ("preferred_username", "email", "upn", "unique_name"):
        value = str(claims.get(key) or "").strip().lower()
        if "@" in value:
            return value
    return ""


def _groups(claims: dict[str, Any]) -> tuple[str, ...] | None:
    """Ids dos grupos. None quando não vieram ou houve excesso (> 200 grupos: o token
    traz `_claim_names` no lugar e a lista teria de ser lida no Graph)."""
    names = claims.get("_claim_names")
    if isinstance(names, dict) and "groups" in names:
        return None
    raw = claims.get("groups")
    if not isinstance(raw, list):
        return None
    return tuple(str(g).lower() for g in raw)
