"""共通Problem Details応答のクライアント向け契約（small）."""

from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
import pytest

from apps.api.core.error_contract import register_error_handlers

pytestmark = pytest.mark.small


class Payload(BaseModel):
    """bodyとqueryのvalidation pointerを同時に確認する入力."""

    name: Annotated[str, Field(min_length=2)]


app = FastAPI()


@app.post("/payload")
async def accept_payload(
    payload: Annotated[Payload, Body()],
    limit: Annotated[int, Query()],
) -> dict[str, Any]:
    return {"payload": payload.model_dump(), "limit": limit}


@app.get("/coded")
async def coded_error() -> None:
    raise HTTPException(
        status_code=409,
        detail={"error_code": "E4004", "message": "conflict"},
        headers={"Retry-After": "1"},
    )


@app.get("/uncoded")
async def uncoded_error() -> None:
    raise HTTPException(status_code=400, detail={"error_code": 400})


@app.get("/empty-client-error")
async def empty_client_error() -> None:
    raise HTTPException(status_code=418, detail=None)


@app.get("/blank-client-error")
async def blank_client_error() -> None:
    raise HTTPException(status_code=400, detail="")


@app.get("/blank-server-error")
async def blank_server_error() -> None:
    raise HTTPException(status_code=503, detail="")


register_error_handlers(app)
client = TestClient(app)


def test_validation_errors_have_stable_codes_without_reflected_input() -> None:
    """Pydanticの可変なmsg/inputを出さず、pointerと小さいcode集合だけを返す."""
    response = client.post("/payload?limit=not-an-int", json={"name": ""})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "E4001"
    assert body["request_id"] == "unknown"
    errors_by_pointer = {error["pointer"]: error["code"] for error in body["errors"]}
    assert errors_by_pointer == {
        "/query/limit": "invalid_format",
        "/name": "too_short",
    }
    assert "input" not in response.text
    assert "not-an-int" not in response.text


def test_http_exception_preserves_dict_detail_code_and_headers() -> None:
    """既存routerのdict detailを壊さず、機械判定codeだけtop-levelにも載せる."""
    response = client.get("/coded")

    assert response.status_code == 409
    assert response.headers["Retry-After"] == "1"
    assert response.json()["code"] == "E4004"
    assert response.json()["detail"] == {
        "error_code": "E4004",
        "message": "conflict",
    }


def test_empty_http_exception_uses_the_standard_status_phrase() -> None:
    """Starletteが補った標準文言もProblem Detailsのdetailとして保持する."""
    response = client.get("/empty-client-error")

    assert response.status_code == 418
    assert response.json()["title"] == "I'm a Teapot"
    assert response.json()["detail"] == "I'm a Teapot"


def test_blank_http_exception_uses_a_status_class_fallback() -> None:
    """空文字のdetailをそのまま返さず、4xx/5xx別の安全な固定文言にする."""
    client_detail = client.get("/blank-client-error").json()["detail"]
    server_detail = client.get("/blank-server-error").json()["detail"]

    assert client_detail.strip()
    assert server_detail.strip()
    assert client_detail != server_detail
