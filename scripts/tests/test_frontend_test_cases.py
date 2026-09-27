"""web のテストケース台帳と注釈の突き合わせ.

subprocess も filesystem も使わず、台帳の text と収集結果の JSON を組み立てて純関数に渡す。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from scripts.testing.frontend_test_cases import (
    AnnotatedTest,
    Case,
    check,
    load_ledger,
    parse_case_tokens,
    parse_playwright,
    parse_vitest,
)

pytestmark = pytest.mark.small

VALID_CASE = {
    "id": "H1",
    "feature": "home",
    "category": "状態",
    "description": "名称、説明、チャットへの導線が表示される",
    "kinds": ["small"],
}


def _ledger(*cases: dict[str, Any]) -> str:
    return json.dumps({"cases": list(cases)}, ensure_ascii=False)


def _case(**overrides: Any) -> dict[str, Any]:
    return {**VALID_CASE, **overrides}


def _vitest(*names: str, file: str = "/repo/apps/web/src/a.test.tsx") -> str:
    return json.dumps([{"name": name, "file": file} for name in names])


def _playwright(
    specs: list[dict[str, Any]],
    *,
    suites: list[dict[str, Any]] | None = None,
    errors: list[Any] | None = None,
) -> str:
    return json.dumps(
        {
            "suites": [
                {"title": "f", "file": "f", "specs": specs, "suites": suites or []}
            ],
            "errors": errors or [],
        }
    )


def _spec(tags: list[str], project: str = "e2e", line: int = 1) -> dict[str, Any]:
    return {
        "title": "t",
        "file": "tests/e2e/ui/a.spec.ts",
        "line": line,
        "tags": tags,
        "tests": [{"projectName": project}],
    }


def _small(*case_ids: str) -> AnnotatedTest:
    return AnnotatedTest(kind="small", location="a.test.tsx › t", case_ids=case_ids)


def _e2e(*case_ids: str) -> AnnotatedTest:
    return AnnotatedTest(kind="e2e", location="a.spec.ts:1", case_ids=case_ids)


# --- 完了条件の 3 つ ---


def test_removing_a_case_from_the_ledger_fails_on_the_orphan_annotation() -> None:
    cases, errors = load_ledger(_ledger(_case(id="P3")))
    assert errors == []

    failures = check(cases, [_small("H1"), _small("P3")])

    assert failures == [
        "H1: 注釈のケース id が台帳にありません（a.test.tsx › t）",
    ]


def test_an_unknown_id_in_an_annotation_fails() -> None:
    cases, _ = load_ledger(_ledger(_case()))

    failures = check(cases, [_small("H1", "Z9")])

    assert failures == ["Z9: 注釈のケース id が台帳にありません（a.test.tsx › t）"]


def test_a_duplicated_case_id_fails() -> None:
    cases, errors = load_ledger(_ledger(_case(), _case()))
    assert errors == []

    failures = check(cases, [_small("H1")])

    assert failures == ["H1: ケース id が台帳の中で重複しています"]


# --- 突き合わせの条件 ---


def test_each_required_kind_needs_a_test() -> None:
    cases = [Case(id="S11", kinds=("e2e", "small"))]

    assert check(cases, [_small("S11")]) == [
        "S11: 必要な種類 e2e のテストが 1 つもありません"
    ]
    assert check(cases, []) == [
        "S11: 必要な種類 e2e のテストが 1 つもありません",
        "S11: 必要な種類 small のテストが 1 つもありません",
    ]


def test_tests_of_only_other_kinds_report_the_mismatch() -> None:
    cases = [Case(id="A1", kinds=("e2e",))]

    assert check(cases, [_small("A1")]) == [
        "A1: テストの種類（small）が台帳の必要な種類（e2e）のどれとも一致しません"
    ]


def test_matching_ledger_and_tests_pass() -> None:
    cases = [
        Case(id="H1", kinds=("small",)),
        Case(id="S11", kinds=("e2e", "small")),
    ]

    # 台帳に無い種類のテストが追加であっても失敗にしない。
    assert check(cases, [_small("H1", "S11"), _e2e("S11", "H1")]) == []


# --- 台帳の schema ---


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("cases: [", "YAML として読めません"),
        ("- id: H1", "top-level は `cases` だけ"),
        (json.dumps({"cases": [], "extra": 1}), "top-level は `cases` だけ"),
        (json.dumps({"cases": []}), "空でない配列"),
        (_ledger(_case(owner="x")), "未知の項目があります: owner"),
        (_ledger({"id": "H1"}), "必須の項目がありません"),
        (_ledger(_case(kinds=[])), "kinds は"),
        (_ledger(_case(kinds=["unit"])), "kinds は"),
        (_ledger(_case(kinds=["small", "small"])), "kinds が重複"),
        (_ledger(_case(category="その他")), "未知の category"),
        (_ledger(_case(id="h1")), "id が"),
        (_ledger(_case(feature="Home")), "feature が"),
        (_ledger(_case(description=" ")), "description は"),
        (json.dumps({"cases": ["H1"]}), "mapping にしてください"),
    ],
)
def test_schema_violations_fail(text: str, message: str) -> None:
    cases, errors = load_ledger(text)

    assert cases == []
    assert any(message in error for error in errors), errors


def test_a_valid_ledger_loads() -> None:
    cases, errors = load_ledger(
        _ledger(_case(), _case(id="S11", kinds=["e2e", "small"]))
    )

    assert errors == []
    assert cases == [Case("H1", ("small",)), Case("S11", ("e2e", "small"))]


# --- 注釈の読み取り ---


def test_case_tokens_are_read_from_the_head_of_the_test_name() -> None:
    assert parse_case_tokens("@case:A1 @case:A4 @case:A1 名前") == (("A1", "A4"), [])
    assert parse_case_tokens("名前") == ((), [])


@pytest.mark.parametrize(
    "title",
    ["名前 @case:H1", "@case:H1 名前 @case:P3", "名前@case:H1"],
)
def test_case_tokens_outside_the_head_fail(title: str) -> None:
    _, errors = parse_case_tokens(title)

    assert errors == ["`@case:` はテスト名の先頭に並べてください"]


def test_a_case_token_without_an_id_fails() -> None:
    _, errors = parse_case_tokens("@case: 名前")

    assert errors == ["`@case:` の後に id がありません: '@case:'"]


def test_vitest_reads_the_last_segment_of_nested_describes() -> None:
    name = "outer > inner > @case:H1 @case:P3 テスト"
    tests, errors = parse_vitest(_vitest(name, "outer > 注釈なし"), _vitest(name))

    assert errors == []
    assert tests == [
        AnnotatedTest(
            kind="small",
            location=f"/repo/apps/web/src/a.test.tsx › {name}",
            case_ids=("H1", "P3"),
        )
    ]


def test_vitest_annotation_on_a_describe_fails() -> None:
    name = "@case:H1 outer > テスト"
    _, errors = parse_vitest(_vitest(name), _vitest(name))

    assert errors == [
        f"/repo/apps/web/src/a.test.tsx › {name}: "
        "`@case:` は describe 名ではなくテスト名に付けてください"
    ]


def test_vitest_annotated_test_outside_the_small_set_fails() -> None:
    name = "outer > @case:H1 テスト"
    tests, errors = parse_vitest(_vitest(name), _vitest())

    assert tests == []
    assert len(errors) == 1
    assert "small の集合にありません" in errors[0]


def test_playwright_reads_nested_suites_and_projects() -> None:
    nested = {
        "title": "describe",
        "specs": [_spec(["case:A1", "@case:A4"], project="medium", line=7)],
    }
    tests, errors = parse_playwright(
        _playwright([_spec(["case:S11", "slow"]), _spec([])], suites=[nested]),
        prefix="apps/web/",
    )

    assert errors == []
    assert tests == [
        AnnotatedTest("e2e", "apps/web/tests/e2e/ui/a.spec.ts:1", ("S11",)),
        AnnotatedTest("medium", "apps/web/tests/e2e/ui/a.spec.ts:7", ("A1", "A4")),
    ]


# --- 収集の失敗 ---


def test_playwright_collection_errors_fail() -> None:
    tests, errors = parse_playwright(
        _playwright([_spec(["case:S11"])], errors=[{"message": "config error"}])
    )

    assert tests == []
    assert errors == ["playwright: 収集に失敗しました: config error"]


def test_playwright_unknown_project_fails() -> None:
    _, errors = parse_playwright(_playwright([_spec([], project="chromium")]))

    assert errors == ["tests/e2e/ui/a.spec.ts:1: 未知の project です: chromium"]


def test_playwright_tag_without_an_id_fails() -> None:
    _, errors = parse_playwright(_playwright([_spec(["case:"])]))

    assert errors == ["tests/e2e/ui/a.spec.ts:1: `@case:` の後に id がありません"]


def test_vitest_without_tests_fails() -> None:
    _, errors = parse_vitest("[]", "[]")

    assert errors == ["vitest: テストが 0 件です（include glob を確かめてください）"]


@pytest.mark.parametrize(
    ("all_text", "small_text"),
    [("not json", "[]"), ("[]", "{"), (json.dumps({"name": "x"}), "[]")],
)
def test_unreadable_vitest_output_fails(all_text: str, small_text: str) -> None:
    tests, errors = parse_vitest(all_text, small_text)

    assert tests == []
    assert errors


def test_unreadable_playwright_output_fails() -> None:
    assert parse_playwright("not json")[1]
    assert parse_playwright("[]")[1] == ["playwright: JSON report の形ではありません"]
