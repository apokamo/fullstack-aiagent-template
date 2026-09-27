"""The real judge SDK against in-memory HTTP, never a provider."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from pydantic import ValidationError
import pytest

from apps.api.agent.evals.evidence import ArtifactRef, EvidenceError, canonical_hash
from apps.api.agent.evals.grading import JudgeEvidence, JudgeInput, Obligation
from apps.api.agent.evals.judge_client import (
    DIAGNOSTIC_VERSION,
    JudgeSettings,
    ResponsesJudge,
    absent_usage,
    parse_result,
    references,
    reparse_diagnostic,
)
from apps.api.agent.evals.privacy import PrivacyFilter
from apps.api.core.llm_profiles import DEFAULT_JUDGE_PROFILE

pytestmark = pytest.mark.small
RUBRIC = {"items": {"faithfulness": "State the observed value honestly."}}
SETTINGS = JudgeSettings.for_profile(DEFAULT_JUDGE_PROFILE)


def request_input() -> JudgeInput:
    return JudgeInput(
        observation=ArtifactRef(
            kind="observations", record_id="trial", digest="a" * 64
        ),
        contract_hash="b" * 64,
        identity=SETTINGS.identity(RUBRIC),
        items=(
            Obligation(
                item_id="faithfulness",
                turn_id="turn-1",
                source="judge",
                critical=True,
                evidence_ids=("answer",),
            ),
        ),
        evidence=(
            JudgeEvidence(
                evidence_id="answer", turn_id="turn-1", kind="answer", text="四件です。"
            ),
        ),
        verified_items=(),
    )


def wire() -> dict[str, Any]:
    return {
        "items": [
            {
                "item_id": "faithfulness",
                "outcome": "pass",
                "references": ["r0"],
            }
        ],
    }


def response_body() -> dict[str, Any]:
    return {
        "id": "resp_fixture",
        "object": "response",
        "created_at": 0,
        "model": SETTINGS.model,
        "status": "completed",
        "error": None,
        "output": [
            {
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(wire()),
                        "annotations": [],
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 7,
            "output_tokens": 11,
            "total_tokens": 18,
            "output_tokens_details": {"reasoning_tokens": 3},
        },
    }


def test_actual_sdk_contract_and_usage() -> None:
    value = request_input()
    calls = []

    def serve(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        assert str(request.url) == f"{SETTINGS.base_url}/responses"
        assert body["model"] == SETTINGS.model
        assert body["reasoning"] == {"effort": SETTINGS.effort}
        assert body["store"] is False and body["tools"] == []
        assert body["truncation"] == "disabled"
        assert body["max_output_tokens"] == SETTINGS.max_output_tokens
        assert body["text"]["format"]["strict"] is True
        schema = body["text"]["format"]["schema"]
        assert schema["properties"]["items"]["minItems"] == len(value.items)
        assert "input_hash" not in schema["properties"]
        assert schema["required"] == ["items"]
        assert schema["$defs"]["WireItem"]["properties"]["item_id"]["enum"] == [
            "faithfulness"
        ]
        transmitted = json.loads(body["input"][0]["content"])
        assert set(transmitted) == {"input", "references"}
        assert transmitted["references"] == [
            r.model_dump(mode="json") for r in references(value)
        ]
        assert len(body["input"]) == 1 and body["input"][0]["role"] == "user"
        return httpx.Response(200, json=response_body())

    judge = ResponsesJudge(SETTINGS, RUBRIC, transport=httpx.MockTransport(serve))
    result = asyncio.run(judge.grade(value))
    assert result.status == "ok" and result.items[0].outcome == "pass"
    assert result.input_hash == canonical_hash(value)
    assert (
        result.usage.requests == 1
        and result.usage.input_tokens == 7
        and result.usage.output_tokens == 11
        and result.usage.reasoning_tokens == 3
    )
    assert len(calls) == 1


@pytest.mark.parametrize(
    "status,fatal",
    [(401, True), (500, False)],
)
def test_http_failure_no_retry_and_fatal_stop(status: int, fatal: bool) -> None:
    value = request_input()
    calls = []

    def serve(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            status, json={"error": {"message": "PRIVATE-SENTINEL", "type": "error"}}
        )

    judge = ResponsesJudge(SETTINGS, RUBRIC, transport=httpx.MockTransport(serve))

    async def run():
        return await judge.grade(value), await judge.grade(value)

    first, second = asyncio.run(run())
    assert first.status == "provider_error" and first.usage.requests == 1
    assert first.error_code == f"judge_http_{status}"
    assert second.status == ("not_executed" if fatal else "provider_error")
    assert len(calls) == (1 if fatal else 2)
    assert "PRIVATE-SENTINEL" not in first.model_dump_json()


@pytest.mark.parametrize(
    "kind",
    ["refusal", "no-usage"],
)
def test_response_failures_are_not_model_failures(kind: str) -> None:
    value = request_input()
    body = response_body()
    if kind == "refusal":
        body["output"][0]["content"] = [
            {"type": "refusal", "refusal": "PRIVATE-SENTINEL"}
        ]
    else:
        body["usage"] = None
    judge = ResponsesJudge(
        SETTINGS,
        RUBRIC,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    )
    result = asyncio.run(judge.grade(value))
    assert result.status == ("ok" if kind == "no-usage" else "parser_error")
    assert result.usage.requests == 1
    if kind == "no-usage":
        assert result.usage.input_tokens is None
    else:
        assert result.items == ()
    assert "PRIVATE-SENTINEL" not in result.model_dump_json()


def test_an_echoed_input_hash_is_a_schema_error() -> None:
    value = request_input()
    data = wire()
    data["input_hash"] = canonical_hash(value)
    body = response_body()
    body["output"][0]["content"][0]["text"] = json.dumps(data)
    judge = ResponsesJudge(
        SETTINGS,
        RUBRIC,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    )
    result = asyncio.run(judge.grade(value))
    assert result.status == "parser_error"
    assert result.error_code == "invalid_judge_result" and result.items == ()
    assert judge.last_diagnostic is not None
    failure = json.loads(json.dumps(judge.last_diagnostic["failure"]))
    assert failure["schema_errors"] == [
        {"type": "extra_forbidden", "loc": ["input_hash"]}
    ]
    with pytest.raises(ValidationError):
        parse_result(json.dumps(data), value, absent_usage(1, "fixture"))


def test_real_network_structurally_forbidden() -> None:
    judge = ResponsesJudge(SETTINGS, RUBRIC)
    with pytest.raises(RuntimeError, match="Model requests are not allowed"):
        asyncio.run(judge.grade(request_input()))


def test_settings_require_a_known_profile_and_its_credential() -> None:
    for env in (
        {"LLM_JUDGE_PROFILE": "wrong", "OPENAI_API_KEY": "x"},
        {"LLM_JUDGE_PROFILE": DEFAULT_JUDGE_PROFILE},
    ):
        with pytest.raises(EvidenceError):
            JudgeSettings.from_environment(env)


def test_settings_and_privacy() -> None:
    settings = JudgeSettings.from_environment({"OPENAI_API_KEY": "private"})
    assert "private" not in settings.model_dump_json()
    with pytest.raises(EvidenceError):
        settings.model_copy(update={"effort": "high"}).identity(RUBRIC)
    cleaned, changed = PrivacyFilter(
        secrets=("SECRET-SENTINEL",), names=("NAME-SENTINEL",)
    ).text(
        "SECRET-SENTINEL NAME-SENTINEL http://internal.example/path postgres"
        "ql://user:pw@host/db Bearer token-value"
    )
    assert (
        changed
        and "SENTINEL" not in cleaned
        and "internal" not in cleaned
        and "token-value" not in cleaned
    )


def test_input_identity_guard_and_size_limit() -> None:
    value = request_input()
    judge = ResponsesJudge(SETTINGS, RUBRIC)
    with pytest.raises(EvidenceError):
        asyncio.run(
            judge.grade(
                value.model_copy(
                    update={
                        "identity": value.identity.model_copy(update={"model": "wrong"})
                    }
                )
            )
        )
    big = value.model_copy(
        update={
            "evidence": (value.evidence[0].model_copy(update={"text": "x" * 1000001}),)
        }
    )
    result = asyncio.run(judge.grade(big))
    assert result.error_code == "input_too_large" and result.usage.requests == 0


def test_cross_turn_and_required_evidence_are_rejected():
    value = request_input()
    value = value.model_copy(
        update={
            "evidence": value.evidence
            + (
                JudgeEvidence(
                    evidence_id="prior",
                    turn_id="turn-0",
                    kind="answer",
                    text="四件です。",
                ),
                JudgeEvidence(
                    evidence_id="result",
                    turn_id="turn-1",
                    kind="result",
                    text="四件です。",
                ),
            )
        }
    )
    for reference, error in [
        ("r1", "unknown_evidence_reference"),
        ("r2", "required_evidence_missing"),
    ]:
        data = wire()
        data["items"][0]["references"] = [reference]
        with pytest.raises(EvidenceError, match=error):
            parse_result(json.dumps(data), value, absent_usage(1, "fixture"))


def test_preparse_diagnostic_and_offline_reparse():
    value = request_input()
    body = response_body()
    data = wire()
    body["output"][0]["content"][0]["text"] = json.dumps(data)
    body["output"].append(
        {
            "type": "reasoning",
            "id": "rs_fixture",
            "summary": [],
            "encrypted_content": "REASONING-SENTINEL",
        }
    )
    judge = ResponsesJudge(
        SETTINGS,
        RUBRIC,
        privacy=PrivacyFilter(names=("NAME-SENTINEL",)),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    )
    result = asyncio.run(judge.grade(value))
    diagnostic = judge.last_diagnostic
    assert diagnostic is not None
    assert diagnostic["version"] == DIAGNOSTIC_VERSION == "judge-diagnostic-v2"
    assert diagnostic["input_hash"] == canonical_hash(value)
    assert diagnostic["usage"]["requests"] == 1
    assert "SENTINEL" not in json.dumps(diagnostic)
    analysis = reparse_diagnostic(diagnostic)
    assert analysis["mode"] == "analysis" and analysis["requests"] == 0
    assert analysis["result"] == result.model_dump(mode="json")


def test_a_legacy_diagnostic_is_refused_with_its_reason():
    value = request_input()
    judge = ResponsesJudge(
        SETTINGS,
        RUBRIC,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=response_body())
        ),
    )
    asyncio.run(judge.grade(value))
    assert judge.last_diagnostic is not None
    echoed = {"input_hash": canonical_hash(value), **wire()}
    legacy = {
        **judge.last_diagnostic,
        "version": "judge-diagnostic-v1",
        "output_text": json.dumps(echoed),
        "output_hash": canonical_hash(json.dumps(echoed)),
    }
    with pytest.raises(EvidenceError, match="legacy_judge_diagnostic"):
        reparse_diagnostic(legacy)
    unversioned = {k: v for k, v in legacy.items() if k != "version"}
    with pytest.raises(EvidenceError, match="diagnostic_version_unsupported"):
        reparse_diagnostic(unversioned)
