"""ジャッジの校正 (`validate`) は、採点できなかった例の理由と診断を残す.

実 provider は使わない。本物の `ResponsesJudge` を MockTransport に向け、次を固定する。

1. ジャッジが `ok` 以外を返した例は、report に status・error_code・sanitize した
   failure が残り、採点できなかった項目は分母に残って校正は未受理のままになる。
2. 生の応答を含む診断は run directory の `diagnostics/` に owner だけが読める形で
   保存され、report には生の応答も秘密値も載らない。
3. 校正の report を変えても `scoring_identity_hash` は変わらず、baseline v1 との
   比較の preflight を通る。
"""

from __future__ import annotations

import asyncio
import json
import stat
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from apps.api.agent.evals.evidence import canonical_hash
from apps.api.agent.evals.judge_client import JudgeSettings, ResponsesJudge
from apps.api.agent.evals.privacy import PrivacyFilter
from apps.api.core.llm_profiles import DEFAULT_JUDGE_PROFILE
from apps.api.sample.evals.baseline import (
    REQUIRED_IDENTITY_FIELDS,
    baseline_failures,
    load_baseline,
)
from apps.api.sample.evals.cli import (
    CALIBRATION_PATH,
    VALIDATION_REPORT_VERSION,
    validate_judge,
)
from apps.api.sample.evals.session import load_json, load_rubric, scoring_identity

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.medium, pytest.mark.uses_resource("filesystem")]

SETTINGS = JudgeSettings.for_profile(DEFAULT_JUDGE_PROFILE)
#: 既定のジャッジで記録した、tracked な baseline の profile。
BASELINE_PROFILE = "openai-luna-responses"
#: ジャッジの応答に紛れ込ませる文字列。診断には残り、report には載ってはならない。
RAW = "RAW-ANSWER-SENTINEL"
#: provider の credential に見立てた秘密値。どこにも書かれてはならない。
SECRET = "SECRET-CREDENTIAL-SENTINEL"
EXAMPLES = load_json(CALIBRATION_PATH)["examples"]
#: この例だけが壊れた応答を受け取る。ほかの例はラベルどおりに採点される。
BROKEN = EXAMPLES[0]["example_id"]
LABELS = {example["example_id"]: example["expected"] for example in EXAMPLES}


def _response(text: str) -> dict[str, Any]:
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
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 7,
            "output_tokens": 11,
            "total_tokens": 18,
            "output_tokens_details": {"reasoning_tokens": 3},
        },
    }


def _example_id(request: httpx.Request) -> str:
    sent = json.loads(json.loads(request.content)["input"][0]["content"])
    return sent["input"]["observation"]["record_id"]


def _answer(request: httpx.Request, kind: str) -> str:
    """The labelled answer, broken in the way `kind` names for `BROKEN` only."""
    sent = json.loads(json.loads(request.content)["input"][0]["content"])
    example_id = _example_id(request)
    if example_id != BROKEN:
        kind = "labelled"
    items = []
    for obligation in sent["input"]["items"]:
        cited = [
            reference["reference_id"]
            for reference in sent["references"]
            if reference["turn_id"] == obligation["turn_id"]
            and (kind != "unquoted_answer" or reference["kind"] != "answer")
        ]
        items.append(
            {
                "item_id": obligation["item_id"],
                "outcome": LABELS[example_id][
                    obligation["item_id"].removeprefix("turn-1-")
                ],
                "references": cited,
            }
        )
    answer: dict[str, Any] = {"items": items}
    if kind == "echoed_input_hash":
        # 旧契約のエコー。値が正しくても、今の schema には無い欄である。
        answer["input_hash"] = canonical_hash(sent["input"])
    elif kind == "duplicate_item":
        answer["items"] = [items[0], *items]
    elif kind == "schema":
        # ジャッジが書いたキーは schema error の `loc` に現れる。
        items[0][RAW] = "judge text"
    return json.dumps(answer, ensure_ascii=False)


def _judge(kind: str) -> ResponsesJudge:
    def serve(request: httpx.Request) -> httpx.Response:
        if kind == "http" and _example_id(request) == BROKEN:
            return httpx.Response(500, json={"error": {"message": RAW}})
        return httpx.Response(200, json=_response(_answer(request, kind)))

    return ResponsesJudge(
        SETTINGS,
        load_rubric(),
        transport=httpx.MockTransport(serve),
        privacy=PrivacyFilter(secrets=(SECRET,)),
    )


def _validate(judge: ResponsesJudge, output: Path) -> dict[str, Any]:
    return asyncio.run(
        validate_judge(
            EXAMPLES,
            judge=judge,
            identity=scoring_identity(judge.identity),
            judge_price=None,
            estimate_usd=0.0,
            max_cost_usd=1.0,
            output=output,
        )
    )


@pytest.mark.parametrize(
    ("kind", "status", "error_code", "failure"),
    [
        (
            "echoed_input_hash",
            "parser_error",
            "invalid_judge_result",
            {
                "reason": "invalid_judge_result",
                # `input_hash` はもう応答の欄ではないので、report では伏せる。
                "schema_errors": [{"type": "extra_forbidden", "loc": [None]}],
            },
        ),
        (
            "duplicate_item",
            "parser_error",
            "duplicate_id",
            {
                "reason": "duplicate_id",
                "item": None,
                "reference": None,
                "schema_errors": [],
            },
        ),
        (
            "unquoted_answer",
            "parser_error",
            "required_evidence_missing",
            {
                "reason": "required_evidence_missing",
                "reference": None,
                "schema_errors": [],
            },
        ),
        ("http", "provider_error", "judge_http_500", None),
    ],
)
def test_an_example_the_judge_could_not_grade_keeps_its_reason(
    tmp_path: Path,
    kind: str,
    status: str,
    error_code: str,
    failure: dict[str, Any] | None,
) -> None:
    """非 `ok` の例は理由ごと report に残り、分母に残って校正は受理されない."""
    output = tmp_path / "run"
    result = _validate(_judge(kind), output)

    assert result["schema_version"] == VALIDATION_REPORT_VERSION
    entries = {entry["example_id"]: entry for entry in result["results"]}
    assert set(entries) == set(LABELS)
    assert all(entries[name]["status"] == "ok" for name in entries if name != BROKEN)
    entry = entries[BROKEN]
    assert entry["status"] == status and entry["error_code"] == error_code
    assert entry["usage"]["requests"] == 1
    if failure is None:
        assert entry["failure"] is None
    else:
        assert {key: entry["failure"][key] for key in failure} == failure
    if kind == "unquoted_answer":
        assert entry["failure"]["item"] == "turn-1-relevance"
    report = result["report"]
    coverage = report["judge_coverage"]
    assert coverage["numerator"] < coverage["denominator"]
    assert report["false_pass"]["numerator"] == report["false_fail"]["numerator"] == 0
    assert report["accepted"] is False

    assert entry["diagnostic"] == f"diagnostics/{entry['example_id']}.json"
    saved = output / entry["diagnostic"]
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    assert stat.S_IMODE((output / "diagnostics").stat().st_mode) == 0o700
    diagnostic = json.loads(saved.read_text(encoding="utf-8"))
    assert diagnostic["error_code"] == error_code
    if kind == "echoed_input_hash":
        # 非公開の診断には、どの欄が余分だったかが残る。
        assert diagnostic["failure"]["schema_errors"] == [
            {"type": "extra_forbidden", "loc": ["input_hash"]}
        ]
    written = json.dumps(result, ensure_ascii=False)
    if kind != "http":
        # 生の応答は診断にだけ残る。
        assert diagnostic["output_text"]
        assert diagnostic["output_text"] not in written
    assert RAW not in written
    assert SECRET not in written and SECRET not in saved.read_text(encoding="utf-8")


def test_a_schema_error_reports_its_type_and_loc_without_judge_text(
    tmp_path: Path,
) -> None:
    """schema error は `type` と `loc` だけが残り、ジャッジが書いたキーは伏せる."""
    output = tmp_path / "run"
    result = _validate(_judge("schema"), output)

    entry = next(entry for entry in result["results"] if entry["example_id"] == BROKEN)
    assert entry["status"] == "parser_error"
    assert entry["error_code"] == "invalid_judge_result"
    errors = entry["failure"]["schema_errors"]
    assert errors == [{"type": "extra_forbidden", "loc": ["items", 0, None]}]
    assert RAW not in json.dumps(result, ensure_ascii=False)
    assert RAW in (output / entry["diagnostic"]).read_text(encoding="utf-8")


def test_the_validation_report_keeps_the_baseline_scoring_identity() -> None:
    """校正の report を変えても、採点 identity は baseline v1 と一致する."""
    judge = ResponsesJudge(SETTINGS, load_rubric())
    baseline = load_baseline(BASELINE_PROFILE)
    expected = {key: baseline[key] for key in REQUIRED_IDENTITY_FIELDS} | {
        "scoring_identity_hash": canonical_hash(scoring_identity(judge.identity))
    }

    assert baseline["version"] == "v1"
    assert baseline_failures(baseline, expected) == []
