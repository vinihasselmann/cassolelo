from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

import read_model as rm

B = rm.BASE_URL
MD = rm.MD_PREFIX["US"]
RAW = "urn:adsk.wipprod:fs.file:vf.ABC?version=2"
URN = base64.urlsafe_b64encode(RAW.encode()).decode().rstrip("=")


@pytest.fixture
def http() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=B) as client:
        yield client


def reader(http: httpx.Client, **kw: Any) -> rm.ModelReader:
    return rm.ModelReader(http, "tok", sleep=lambda _s: None, poll_seconds=1, **kw)


# --------------------------------------------------------------------------- helpers


def test_to_urn_encodes_raw_and_normalizes_encoded() -> None:
    assert rm.to_urn(RAW) == URN
    assert "=" not in rm.to_urn(RAW)
    assert rm.to_urn("ab+c/d==") == "ab-c_d"


def test_find_prop_searches_all_groups_case_insensitive_in_preference_order() -> None:
    props = {"Dados": {"MARK": "V-01"}, "Identidade": {"marca": "P-12"}, "x": "não-dict"}
    assert rm.find_prop(props, ["Marca", "Mark"]) == "P-12"
    assert rm.find_prop(props, ["Mark"]) == "V-01"
    assert rm.find_prop({"g": {"Marca": "  "}}, ["Marca"]) is None
    assert rm.find_prop({"g": {"Marca": ["L1"]}}, ["Marca"]) == "L1"


def test_safe_name() -> None:
    assert rm.safe_name("urn:adsk.wipprod:dm.lineage:Ab-1_x") == "Ab-1_x"
    assert rm.safe_name("a?b") == "a_b"


def test_check_manifest() -> None:
    ok = {"status": "success", "progress": "complete", "derivatives": [{"outputType": "svf2"}]}
    assert rm.check_manifest(ok).startswith("success")
    with pytest.raises(rm.ApsError, match="em andamento"):
        rm.check_manifest({"status": "inprogress", "progress": "40%"})
    with pytest.raises(rm.ApsError, match="failed"):
        rm.check_manifest({"status": "failed", "derivatives": [{"messages": [{"message": "x"}]}]})
    with pytest.raises(rm.NoTranslationError):
        rm.check_manifest({"status": "success", "derivatives": [{"outputType": "thumbnail"}]})


def test_choose_3d_view_prefers_master() -> None:
    views: list[dict[str, Any]] = [
        {"role": "2d", "guid": "a"},
        {"role": "3d", "guid": "b"},
        {"role": "3d", "guid": "c", "isMasterView": True},
    ]
    assert rm.choose_3d_view(views)["guid"] == "c"
    with pytest.raises(rm.ApsError):
        rm.choose_3d_view([{"role": "2d", "guid": "a"}])


# --------------------------------------------------------------------------- extração

TREE = [
    {
        "objectid": 1,
        "name": "Model",
        "objects": [
            {
                "objectid": 2,
                "name": "Structural Framing",
                "objects": [
                    {
                        "objectid": 3,
                        "name": "Viga",
                        "objects": [
                            # peça com marca e componente aninhado (inserto)
                            {"objectid": 10, "name": "V [1]", "objects": [{"objectid": 11}]},
                            {"objectid": 12, "name": "V [2]"},
                        ],
                    }
                ],
            },
            {"objectid": 4, "name": "Generic Models", "objects": [{"objectid": 20}]},
        ],
    }
]
PROPS = [
    {"objectid": 10, "name": "V [1]", "externalId": "e10", "properties": {"Id": {"Marca": "V1"}}},
    {"objectid": 11, "name": "Inserto", "externalId": "e11", "properties": {}},
    {
        "objectid": 12,
        "name": "V [2]",
        "externalId": "e12",
        "properties": {"Id": {"Mark": "V1"}, "Other": {"Category": "Revit Structural Framing"}},
    },
    {"objectid": 20, "name": "Caixa", "externalId": "e20", "properties": {}},
]


def test_extract_elements_counts_marked_parent_and_skips_nested() -> None:
    elements, nested = rm.extract_elements(TREE, PROPS, ["Marca", "Mark"], ["Category"])
    by_id = {e["dbid"]: e for e in elements}
    assert set(by_id) == {10, 12, 20}
    assert nested == 1
    assert by_id[10]["mark"] == "V1" and by_id[10]["category"] == "Structural Framing"
    assert by_id[12]["category"] == "Structural Framing"  # prefixo "Revit " removido
    assert by_id[20]["mark"] is None and by_id[20]["category"] == "Generic Models"
    assert by_id[10]["external_id"] == "e10"


def test_compute_and_format_stats() -> None:
    elements, nested = rm.extract_elements(TREE, PROPS, ["Marca", "Mark"], ["Category"])
    s = rm.compute_stats(elements)
    assert s.total == 3 and s.without_mark == 1
    assert s.by_category[0] == ("Structural Framing", 2)
    assert s.top_marks == [(("V1", "Structural Framing"), 2)]
    text = "\n".join(rm.format_stats(s, nested))
    assert "Sem Marca: 1 (33.3%)" in text


# --------------------------------------------------------------------------- HTTP


@respx.mock
def test_poll_waits_on_202_then_returns(http: httpx.Client) -> None:
    route = respx.get(f"{B}{MD}/{URN}/metadata/g/properties").mock(
        side_effect=[
            httpx.Response(202, json={"result": "success"}),
            httpx.Response(200, json={"data": {"collection": [{"objectid": 1}]}}),
        ]
    )
    assert reader(http).properties(URN, "g") == [{"objectid": 1}]
    assert route.call_count == 2


@respx.mock
def test_poll_gives_up_after_max_wait(http: httpx.Client) -> None:
    respx.get(f"{B}{MD}/{URN}/metadata/g/properties").respond(202)
    with pytest.raises(rm.ApsError, match="processamento"):
        reader(http, max_wait_seconds=3).properties(URN, "g")


@respx.mock
def test_poll_uses_forceget_on_413(http: httpx.Client) -> None:
    url = f"{B}{MD}/{URN}/metadata/g/properties"
    forced = respx.get(url, params={"forceget": "true"}).respond(
        200, json={"data": {"collection": []}}
    )
    respx.get(url).respond(413)
    assert reader(http).properties(URN, "g") == []
    assert forced.called


@respx.mock
def test_manifest_404_is_no_translation(http: httpx.Client) -> None:
    respx.get(f"{B}{MD}/{URN}/manifest").respond(404)
    with pytest.raises(rm.NoTranslationError, match="sem conversão"):
        reader(http).manifest(URN)


@respx.mock
def test_403_says_not_provisioned(http: httpx.Client) -> None:
    respx.get(f"{B}/data/v1/projects/b.1/items/I/versions").respond(403)
    with pytest.raises(rm.ApsError, match="Custom Integrations"):
        reader(http).versions("b.1", "I")


def test_emea_region_prefix(http: httpx.Client) -> None:
    r = rm.ModelReader(http, "t", region="EMEA")
    assert r._md.endswith("/regions/eu/designdata")
    with pytest.raises(rm.ApsError):
        rm.ModelReader(http, "t", region="XX")


# --------------------------------------------------------------------------- ponta a ponta


def _version(n: int, deriv: str | None) -> dict[str, Any]:
    v: dict[str, Any] = {
        "id": f"urn:adsk.wipprod:fs.file:vf.ABC?version={n}",
        "type": "versions",
        "attributes": {
            "versionNumber": n,
            "displayName": "Obra.rvt",
            "createUserName": "Ana",
            "createTime": f"2026-11-0{n}T10:00:00Z",
        },
        "relationships": {},
    }
    if deriv:
        v["relationships"]["derivatives"] = {"data": {"type": "derivatives", "id": deriv}}
    return v


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(rm, "load_dotenv", lambda *_a, **_k: None)
    monkeypatch.setattr(rm, "OUT_DIR", tmp_path)
    for k, v in {"APS_CLIENT_ID": "cid", "APS_CLIENT_SECRET": "s", "APS_REGION": "US"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("MARK_PROPERTY_NAMES", raising=False)
    monkeypatch.delenv("CATEGORY_PROPERTY_NAMES", raising=False)
    return tmp_path


@respx.mock
def test_main_end_to_end_writes_json_and_never_posts_job(
    http: httpx.Client, env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.post(f"{B}/authentication/v2/token").respond(200, json={"access_token": "tok-xyz"})
    respx.get(f"{B}/data/v1/projects/b.1/items/urn:adsk.wipprod:dm.lineage:L1/versions").respond(
        200, json={"data": [_version(1, URN), _version(2, URN)]}
    )
    respx.get(f"{B}{MD}/{URN}/manifest").respond(
        200,
        json={"status": "success", "progress": "complete", "derivatives": [{"outputType": "svf2"}]},
    )
    respx.get(f"{B}{MD}/{URN}/metadata").respond(
        200, json={"data": {"metadata": [{"role": "3d", "guid": "g3", "name": "{3D}"}]}}
    )
    respx.get(f"{B}{MD}/{URN}/metadata/g3").respond(200, json={"data": {"objects": TREE}})
    respx.get(f"{B}{MD}/{URN}/metadata/g3/properties").respond(
        200, json={"data": {"collection": PROPS}}
    )
    job = respx.post(url__regex=r".*/designdata/job").respond(500)

    code = rm.main(["--project", "b.1", "--item", "urn:adsk.wipprod:dm.lineage:L1"], http=http)
    out = capsys.readouterr()
    assert code == 0, out.err
    assert not job.called
    assert "tok-xyz" not in out.out + out.err
    saved = json.loads((env / "L1_v2.json").read_text(encoding="utf-8"))
    assert saved["version_number"] == 2
    assert len(saved["elements"]) == 3
    assert "Total de elementos: 3" in out.out


@respx.mock
def test_main_stops_when_version_has_no_derivative(
    http: httpx.Client, env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.post(f"{B}/authentication/v2/token").respond(200, json={"access_token": "t"})
    respx.get(f"{B}/data/v1/projects/b.1/items/I/versions").respond(
        200, json={"data": [_version(1, None)]}
    )
    assert rm.main(["--project", "b.1", "--item", "I"], http=http) == 3
    assert "arquivo sem conversão no Docs" in capsys.readouterr().err
    assert not list(env.iterdir())
