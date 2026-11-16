from __future__ import annotations

import base64

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.aps import derivatives as md
from app.aps.auth import TOKEN_PATH, TokenProvider
from app.aps.client import ApsClient
from app.aps.errors import ApsError, ApsNoTranslationError
from app.aps.schemas import Version
from tests.aps.conftest import BASE, Sleeps, fixture

RAW = "urn:adsk.wipprod:fs.file:vf.SANITIZED_FILE_ID?version=2"
URN = base64.urlsafe_b64encode(RAW.encode()).decode().rstrip("=")
MD = f"{BASE}/modelderivative/v2/designdata"
GUID = "00000000-3d00-0000-0000-000000000001"


def setup_token() -> None:
    respx.post(f"{BASE}{TOKEN_PATH}").respond(200, json=fixture("token.json"))


def test_urn_from_version() -> None:
    versions = [Version.from_api(d) for d in fixture("versions.json")["data"]]
    by_number = {v.number: v for v in versions}
    assert md.urn_from_version(by_number[2]) == URN
    assert md.urn_from_version(by_number[1]) is None
    assert md.to_urn(RAW) == URN
    assert "=" not in md.to_urn(RAW)


@respx.mock
async def test_manifest_success_and_in_progress(aps: ApsClient) -> None:
    setup_token()
    route = respx.get(f"{MD}/{URN}/manifest")
    route.respond(200, json=fixture("manifest_success.json"))
    m = await md.get_manifest(aps, URN)
    assert m.is_ready and m.has_viewable and not m.in_progress
    route.respond(200, json=fixture("manifest_inprogress.json"))
    m = await md.get_manifest(aps, URN)
    assert m.in_progress and not m.is_ready


@respx.mock
async def test_manifest_404_means_no_translation(aps: ApsClient) -> None:
    setup_token()
    respx.get(f"{MD}/{URN}/manifest").respond(404)
    with pytest.raises(ApsNoTranslationError, match="sem conversão no Docs"):
        await md.get_manifest(aps, URN)


@respx.mock
async def test_metadata_and_choose_master_3d(aps: ApsClient) -> None:
    setup_token()
    respx.get(f"{MD}/{URN}/metadata").respond(200, json=fixture("metadata.json"))
    views = await md.get_metadata(aps, URN)
    assert len(views) == 3
    assert md.choose_3d_view(views).guid == GUID
    with pytest.raises(ApsError, match="3D"):
        md.choose_3d_view([v for v in views if v.role == "2d"])


@respx.mock
async def test_properties_waits_on_202(aps: ApsClient, sleeps: Sleeps) -> None:
    setup_token()
    route = respx.get(f"{MD}/{URN}/metadata/{GUID}/properties").mock(
        side_effect=[
            httpx.Response(202, json={"result": "success"}),
            httpx.Response(202, json={"result": "success"}),
            httpx.Response(200, json=fixture("properties.json")),
        ]
    )
    props = await md.get_properties(aps, URN, GUID, poll_seconds=2, sleep=sleeps)
    assert route.call_count == 3
    assert sleeps.calls == [2, 2]
    by_id = {p.objectid: p for p in props}
    assert by_id[10].properties["Dados de identidade"]["Marca"] == "V-101"
    assert by_id[20].external_id is not None


@respx.mock
async def test_properties_gives_up_after_max_wait(aps: ApsClient, sleeps: Sleeps) -> None:
    setup_token()
    respx.get(f"{MD}/{URN}/metadata/{GUID}/properties").respond(202)
    with pytest.raises(ApsError, match="processamento"):
        await md.get_properties(aps, URN, GUID, poll_seconds=5, max_wait_seconds=10, sleep=sleeps)


@respx.mock
async def test_properties_uses_forceget_on_413(aps: ApsClient) -> None:
    setup_token()
    url = f"{MD}/{URN}/metadata/{GUID}/properties"
    forced = respx.get(url, params={"forceget": "true"}).respond(
        200, json=fixture("properties.json")
    )
    respx.get(url).respond(413)
    props = await md.get_properties(aps, URN, GUID)
    assert forced.called and len(props) == 3


@respx.mock
async def test_object_tree(aps: ApsClient) -> None:
    setup_token()
    respx.get(f"{MD}/{URN}/metadata/{GUID}").respond(200, json=fixture("object_tree.json"))
    tree = await md.get_object_tree(aps, URN, GUID)
    categories = [n.name for n in tree[0].objects]
    assert categories == ["Structural Framing", "Structural Columns"]


@respx.mock
async def test_emea_region_uses_regional_endpoint(http: httpx.AsyncClient) -> None:
    setup_token()
    tp = TokenProvider(client_id="c", client_secret=SecretStr("s"), http=http)
    c = ApsClient(http=http, tokens=tp, region="EMEA")
    route = respx.get(f"{BASE}/modelderivative/v2/regions/eu/designdata/{URN}/manifest").respond(
        200, json=fixture("manifest_success.json")
    )
    await md.get_manifest(c, URN)
    assert route.called


def test_derivatives_module_has_no_conversion_function() -> None:
    public = {n for n in dir(md) if not n.startswith("_")}
    assert not {n for n in public if "job" in n.lower() or "translate" in n.lower()}
