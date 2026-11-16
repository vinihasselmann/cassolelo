from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import webhook_server as ws

SECRET = "segredo-de-teste-123"
PAYLOAD = {
    "version": "1.0",
    "resourceUrn": "urn:adsk.wipprod:fs.file:vf.ABC?version=3",
    "hook": {
        "hookId": "h1",
        "event": "dm.version.added",
        "hookAttribute": {"obra_id": "OBRA-1"},
    },
    "payload": {"name": "Obra.rvt", "version": 3},
}


def client(tmp_path: Path, secret: str = SECRET) -> tuple[TestClient, Path]:
    log = tmp_path / "webhooks.log"
    return TestClient(ws.create_app(secret=secret, log_path=log)), log


def test_signature_roundtrip() -> None:
    body = b'{"a":1}'
    sig = ws.compute_signature(SECRET, body)
    assert sig.startswith("sha1hash=") and len(sig) == len("sha1hash=") + 40
    assert ws.verify_signature(SECRET, body, sig)
    assert ws.verify_signature(SECRET, body, sig.upper().replace("SHA1HASH=", "sha1hash="))
    assert ws.verify_signature(SECRET, body, sig.removeprefix("sha1hash="))
    assert not ws.verify_signature(SECRET, body + b" ", sig)
    assert not ws.verify_signature("outro", body, sig)
    assert not ws.verify_signature(SECRET, body, None)


def test_valid_signature_is_logged(tmp_path: Path) -> None:
    c, log = client(tmp_path)
    body = json.dumps(PAYLOAD).encode()
    r = c.post(
        "/hooks/aps",
        content=body,
        headers={"x-adsk-signature": ws.compute_signature(SECRET, body)},
    )
    assert r.status_code == 200
    rec = json.loads(log.read_text(encoding="utf-8").strip())
    assert rec["event"] == "dm.version.added"
    assert rec["obra_id"] == "OBRA-1"
    assert rec["version"] == 3
    assert rec["payload"] == PAYLOAD


def test_invalid_or_missing_signature_rejected(tmp_path: Path) -> None:
    c, log = client(tmp_path)
    body = json.dumps(PAYLOAD).encode()
    bad = c.post("/hooks/aps", content=body, headers={"x-adsk-signature": "sha1hash=00"})
    missing = c.post("/hooks/aps", content=body)
    assert bad.status_code == 401 and missing.status_code == 401
    assert not log.exists()


def test_secret_not_configured(tmp_path: Path) -> None:
    c, _ = client(tmp_path, secret="")
    assert c.post("/hooks/aps", content=b"{}").status_code == 503
    assert c.get("/health").json() == {"ok": True, "secret_configured": False}


def test_bad_json_with_valid_signature(tmp_path: Path) -> None:
    c, log = client(tmp_path)
    body = b"not json"
    r = c.post(
        "/hooks/aps", content=body, headers={"x-adsk-signature": ws.compute_signature(SECRET, body)}
    )
    assert r.status_code == 400
    assert not log.exists()
