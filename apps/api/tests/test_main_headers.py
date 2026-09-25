"""応答ヘッダ契約の回帰テスト."""

from collections.abc import Iterator

from fastapi.testclient import TestClient
import pytest

from apps.api.main import app

pytestmark = [pytest.mark.small]

ORIGIN = "http://localhost:3000"
BOOM_PATH = "/__test_boom"
REQUEST_ID = "regression-id"


@pytest.fixture
def client() -> Iterator[TestClient]:
    """未処理例外を投げる一時ルートを足した `TestClient`.

    `raise_server_exceptions=False` にしないと TestClient が例外を送出してしまい、
    実際に返る 500 応答を観測できない。ルートは後片付けする（`app` は module 単位で
    共有されるため、残すと他のテストから見えてしまう）。
    """

    @app.get(BOOM_PATH, include_in_schema=False)
    async def _boom() -> None:
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

    app.router.routes[:] = [
        route
        for route in app.router.routes
        if getattr(route, "path", None) != BOOM_PATH
    ]


@pytest.mark.parametrize(
    ("path", "expected_status"),
    [
        ("/health/live", 200),
        (BOOM_PATH, 500),
    ],
)
def test_headers_are_applied_on_every_status(
    client: TestClient, path: str, expected_status: int
) -> None:
    """200 / 404 / 未処理例外の 500 すべてに 3 種のヘッダが付く."""
    response = client.get(path, headers={"X-Request-ID": REQUEST_ID, "Origin": ORIGIN})

    assert response.status_code == expected_status
    # request-id middleware（最外周）が採番した id が復路で載る
    assert response.headers["X-Request-ID"] == REQUEST_ID
    # security headers middleware
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    # CORSMiddleware
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN


def test_request_id_is_generated_when_client_sends_none(client: TestClient) -> None:
    """クライアントが `X-Request-ID` を送らなければ採番する."""
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


def test_unhandled_exception_returns_problem_json_without_internals(
    client: TestClient,
) -> None:
    """500 の body はエラー契約に従い、例外メッセージを含まない."""
    response = client.get(BOOM_PATH, headers={"X-Request-ID": REQUEST_ID})

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")

    body = response.json()
    assert body["status"] == 500
    assert body["request_id"] == REQUEST_ID
    # str(exc) を body に出さない（CWE-209）
    assert "boom" not in response.text
