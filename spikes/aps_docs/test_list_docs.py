from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx

import list_docs as ld

B = ld.BASE_URL


@pytest.fixture
def http() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=B) as client:
        yield client


@pytest.fixture(autouse=True)
def creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ld, "load_dotenv", lambda *_a, **_k: None)
    monkeypatch.setenv("APS_CLIENT_ID", "cid")
    monkeypatch.setenv("APS_CLIENT_SECRET", "secret")


def _token_ok(mock: respx.MockRouter) -> respx.Route:
    return mock.post(f"{B}{ld.TOKEN_PATH}").respond(200, json={"access_token": "tok-123"})


@respx.mock
def test_get_token_uses_basic_auth_and_scopes(http: httpx.Client) -> None:
    route = _token_ok(respx.mock)
    assert ld.get_token(http, "cid", "secret") == "tok-123"
    req = route.calls.last.request
    assert req.headers["authorization"].startswith("Basic ")
    body = req.content.decode()
    assert "grant_type=client_credentials" in body
    assert "scope=data%3Aread+viewables%3Aread" in body


@respx.mock
def test_get_token_invalid_credentials(http: httpx.Client) -> None:
    respx.post(f"{B}{ld.TOKEN_PATH}").respond(401)
    with pytest.raises(ld.ApsError, match="APS_CLIENT_ID"):
        ld.get_token(http, "cid", "bad")


@pytest.mark.parametrize("status", [401, 403])
@respx.mock
def test_data_401_403_says_not_provisioned(http: httpx.Client, status: int) -> None:
    respx.get(f"{B}/project/v1/hubs").respond(status)
    docs = ld.DocsClient(http, "tok")
    with pytest.raises(ld.ApsError, match="não liberado em Custom Integrations"):
        docs.hubs()


@respx.mock
def test_pagination_and_warnings(http: httpx.Client) -> None:
    respx.get(f"{B}/project/v1/hubs/h1/projects", params={"page[number]": "1"}).respond(
        200, json={"data": [{"id": "b.2", "type": "projects", "attributes": {"name": "P2"}}]}
    )
    respx.get(f"{B}/project/v1/hubs/h1/projects").respond(
        200,
        json={
            "data": [{"id": "b.1", "type": "projects", "attributes": {"name": "P1"}}],
            "links": {"next": {"href": f"{B}/project/v1/hubs/h1/projects?page[number]=1"}},
            "meta": {"warnings": [{"Detail": "algo"}]},
        },
    )
    docs = ld.DocsClient(http, "tok")
    assert [p.name for p in docs.projects("h1")] == ["P1", "P2"]
    assert docs.warnings == ["algo"]


@respx.mock
def test_folder_tree_recurses_and_respects_depth(http: httpx.Client) -> None:
    root = f"{B}/data/v1/projects/b.1/folders/F0/contents"
    sub = f"{B}/data/v1/projects/b.1/folders/F1/contents"
    respx.get(root).respond(
        200,
        json={
            "data": [
                {"id": "F1", "type": "folders", "attributes": {"name": "Modelos"}},
                {"id": "I1", "type": "items", "attributes": {"displayName": "Obra.rvt"}},
            ]
        },
    )
    respx.get(sub).respond(
        200,
        json={"data": [{"id": "I2", "type": "items", "attributes": {"displayName": "B.rvt"}}]},
    )
    docs = ld.DocsClient(http, "tok")

    tree = docs.folder_tree("b.1", "F0")
    assert [n.name for n in tree] == ["Modelos", "Obra.rvt"]
    assert [c.name for c in tree[0].children] == ["B.rvt"]

    shallow = docs.folder_tree("b.1", "F0", max_depth=1)
    assert shallow[0].children[0].kind == "limite de profundidade"


def test_render_tree() -> None:
    nodes = [
        ld.Node("Hub", "hubs", "h1", [ld.Node("P", "projects", "b.1")]),
        ld.Node("Hub2", "hubs", "h2"),
    ]
    assert ld.render_tree(nodes) == [
        "├── Hub  [hubs]  h1",
        "│   └── P  [projects]  b.1",
        "└── Hub2  [hubs]  h2",
    ]


@respx.mock
def test_main_overview_prints_tree_without_token(
    http: httpx.Client, capsys: pytest.CaptureFixture[str]
) -> None:
    _token_ok(respx.mock)
    respx.get(f"{B}/project/v1/hubs").respond(
        200, json={"data": [{"id": "h1", "type": "hubs", "attributes": {"name": "Cassol"}}]}
    )
    respx.get(f"{B}/project/v1/hubs/h1/projects").respond(
        200, json={"data": [{"id": "b.1", "type": "projects", "attributes": {"name": "Teste"}}]}
    )
    respx.get(f"{B}/project/v1/hubs/h1/projects/b.1/topFolders").respond(
        200,
        json={"data": [{"id": "F0", "type": "folders", "attributes": {"name": "Project Files"}}]},
    )
    assert ld.main([], http=http) == 0
    out = capsys.readouterr()
    assert "Cassol" in out.out and "Teste" in out.out and "Project Files" in out.out
    assert "tok-123" not in out.out + out.err


@respx.mock
def test_main_reports_not_provisioned(
    http: httpx.Client, capsys: pytest.CaptureFixture[str]
) -> None:
    _token_ok(respx.mock)
    respx.get(f"{B}/project/v1/hubs").respond(403)
    assert ld.main([], http=http) == 1
    assert "Custom Integrations" in capsys.readouterr().err


def test_main_requires_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("APS_CLIENT_ID")
    assert ld.main([]) == 2
    assert "APS_CLIENT_ID" in capsys.readouterr().err
