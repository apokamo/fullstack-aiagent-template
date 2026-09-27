#!/usr/bin/env python3
"""web のテストケース台帳とテストの注釈を突き合わせる.

    uv run python -m scripts.testing.frontend_test_cases [--print-map]

repository root から実行する。`apps/web` を cwd にして次の 3 つを収集する（browser は
起動しない）。

- `vitest list --json`（全件）
- `vitest list --tagsFilter=small --json`（`make verify-frontend` が実行する集合）
- `playwright test --list --reporter=json`（project `e2e` / `medium`）

台帳（`apps/web/tests/coverage/frontend-test-cases.yml`）が唯一の手書きの正本で、
注釈は Vitest のテスト名の先頭の `@case:<id>` と Playwright の `@case:<id>` tag である。
規約の正本は `docs/reference/frontend/testing.md`。

- **収集・解釈のどの失敗でも exit 1 にする。** 0 件や読めない出力で黙って成功しない。
- 読み込み・解釈・判定は subprocess を持たない純関数に分け、`main()` だけが収集する。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import yaml  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

WEB_DIR = Path("apps/web")
LEDGER_PATH = WEB_DIR / "tests/coverage/frontend-test-cases.yml"

KINDS: tuple[str, ...] = ("small", "medium", "large", "e2e")
CATEGORIES: frozenset[str] = frozenset(
    {
        "画面遷移",
        "操作",
        "入力チェック",
        "APIエラー",
        "状態",
        "アクセシビリティ",
        "データの形",
        "秘密値の表示",
    }
)
CASE_FIELDS: frozenset[str] = frozenset(
    {"id", "feature", "category", "description", "kinds"}
)
#: Playwright の project 名がそのまま種類になる。
PLAYWRIGHT_PROJECTS: frozenset[str] = frozenset({"e2e", "medium"})

ID_PATTERN = re.compile(r"\A[A-Z]+[0-9]+\Z")
FEATURE_PATTERN = re.compile(r"\A[a-z][a-z0-9-]*\Z")
CASE_TOKEN = re.compile(r"\A@case:(\S+)\Z")
CASE_PREFIX = "@case:"
VITEST_NAME_SEPARATOR = " > "

COMMANDS: dict[str, list[str]] = {
    "vitest-all": ["npx", "--no-install", "vitest", "list", "--json"],
    "vitest-small": [
        "npx",
        "--no-install",
        "vitest",
        "list",
        "--tagsFilter=small",
        "--json",
    ],
    "playwright": [
        "npx",
        "--no-install",
        "playwright",
        "test",
        "--list",
        "--reporter=json",
    ],
}


@dataclass(frozen=True)
class Case:
    """台帳の 1 ケース."""

    id: str
    kinds: tuple[str, ...]


@dataclass(frozen=True)
class AnnotatedTest:
    """`@case:` の注釈を 1 つ以上持つテスト."""

    kind: str
    location: str
    case_ids: tuple[str, ...]


def load_ledger(text: str) -> tuple[list[Case], list[str]]:
    """台帳の YAML を読み、ケースと schema 違反の message を返す."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        return [], [f"ledger: YAML として読めません: {error}"]
    if not isinstance(data, dict) or set(data) != {"cases"}:
        return [], ["ledger: top-level は `cases` だけを持つ mapping にしてください"]
    entries = data["cases"]
    if not isinstance(entries, list) or not entries:
        return [], ["ledger: `cases` は空でない配列にしてください"]

    cases: list[Case] = []
    errors: list[str] = []
    for index, entry in enumerate(entries):
        where = f"ledger: cases[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: mapping にしてください")
            continue
        entry_errors = _case_errors(entry)
        if entry_errors:
            case_id = entry.get("id")
            label = f"{where} ({case_id})" if isinstance(case_id, str) else where
            errors.extend(f"{label}: {message}" for message in entry_errors)
            continue
        cases.append(Case(id=entry["id"], kinds=tuple(entry["kinds"])))
    return cases, errors


def _case_errors(entry: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    unknown = sorted(str(key) for key in set(entry) - CASE_FIELDS)
    if unknown:
        errors.append(f"未知の項目があります: {', '.join(unknown)}")
    missing = sorted(CASE_FIELDS - set(entry))
    if missing:
        errors.append(f"必須の項目がありません: {', '.join(missing)}")

    case_id = entry.get("id")
    if "id" in entry and not (isinstance(case_id, str) and ID_PATTERN.match(case_id)):
        errors.append(f"id が `{ID_PATTERN.pattern}` に一致しません: {case_id!r}")
    feature = entry.get("feature")
    if "feature" in entry and not (
        isinstance(feature, str) and FEATURE_PATTERN.match(feature)
    ):
        errors.append(
            f"feature が `{FEATURE_PATTERN.pattern}` に一致しません: {feature!r}"
        )
    category = entry.get("category")
    if "category" in entry and category not in CATEGORIES:
        errors.append(f"未知の category です: {category!r}")
    description = entry.get("description")
    if "description" in entry and not (
        isinstance(description, str) and description.strip()
    ):
        errors.append("description は空でない文字列にしてください")
    kinds = entry.get("kinds")
    if "kinds" in entry:
        if (
            not isinstance(kinds, list)
            or not kinds
            or not all(isinstance(kind, str) and kind in KINDS for kind in kinds)
        ):
            errors.append(
                f"kinds は {', '.join(KINDS)} から 1 つ以上にしてください: {kinds!r}"
            )
        elif len(set(kinds)) != len(kinds):
            errors.append(f"kinds が重複しています: {kinds!r}")
    return errors


def _load_json(label: str, text: str) -> tuple[Any, list[str]]:
    try:
        return json.loads(text), []
    except json.JSONDecodeError as error:
        return None, [f"{label}: 出力が JSON として読めません: {error}"]


def _vitest_entries(label: str, data: Any) -> tuple[list[tuple[str, str]], list[str]]:
    if not isinstance(data, list) or not all(
        isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and isinstance(item.get("file"), str)
        for item in data
    ):
        return [], [f"{label}: `{{name, file}}` の配列ではありません"]
    return [(item["file"], item["name"]) for item in data], []


def _relative(file: str, root: Path | None) -> str:
    if root is None:
        return file
    try:
        return Path(file).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return file


def parse_case_tokens(title: str) -> tuple[tuple[str, ...], list[str]]:
    """テスト名の先頭から続く `@case:<id>` を読み、位置の誤りを返す."""
    tokens = title.split()
    ids: list[str] = []
    errors: list[str] = []
    index = 0
    while index < len(tokens) and tokens[index].startswith(CASE_PREFIX):
        matched = CASE_TOKEN.match(tokens[index])
        if matched is None:
            errors.append(f"`{CASE_PREFIX}` の後に id がありません: {tokens[index]!r}")
        else:
            ids.append(matched.group(1))
        index += 1
    if any(CASE_PREFIX in token for token in tokens[index:]):
        errors.append("`@case:` はテスト名の先頭に並べてください")
    return tuple(dict.fromkeys(ids)), errors


def parse_vitest(
    all_text: str, small_text: str, root: Path | None = None
) -> tuple[list[AnnotatedTest], list[str]]:
    """`vitest list --json` の全件と small 集合から注釈付きテストを得る."""
    all_data, errors = _load_json("vitest", all_text)
    small_data, small_errors = _load_json("vitest --tagsFilter=small", small_text)
    errors += small_errors
    if errors:
        return [], errors
    entries, errors = _vitest_entries("vitest", all_data)
    small_entries, small_errors = _vitest_entries(
        "vitest --tagsFilter=small", small_data
    )
    errors += small_errors
    if errors:
        return [], errors
    if not entries:
        return [], ["vitest: テストが 0 件です（include glob を確かめてください）"]

    small = set(small_entries)
    tests: list[AnnotatedTest] = []
    for file, name in entries:
        *describes, title = name.split(VITEST_NAME_SEPARATOR)
        location = f"{_relative(file, root)} › {name}"
        if any(CASE_PREFIX in describe for describe in describes):
            errors.append(
                f"{location}: `@case:` は describe 名ではなくテスト名に付けてください"
            )
        ids, token_errors = parse_case_tokens(title)
        errors.extend(f"{location}: {message}" for message in token_errors)
        if not ids:
            continue
        if (file, name) not in small:
            errors.append(
                f"{location}: 注釈付きのテストが small の集合にありません"
                '（describe に `tags: ["small"]` を付けてください）'
            )
            continue
        tests.append(AnnotatedTest(kind="small", location=location, case_ids=ids))
    return tests, errors


def parse_playwright(
    text: str, prefix: str = ""
) -> tuple[list[AnnotatedTest], list[str]]:
    """`playwright test --list --reporter=json` から注釈付きテストを得る."""
    data, errors = _load_json("playwright", text)
    if errors:
        return [], errors
    if not isinstance(data, dict):
        return [], ["playwright: JSON report の形ではありません"]
    for error in data.get("errors") or []:
        message = error.get("message") if isinstance(error, dict) else error
        errors.append(f"playwright: 収集に失敗しました: {message}")
    if errors:
        return [], errors

    tests: list[AnnotatedTest] = []
    for spec in _walk_specs(data.get("suites") or []):
        location = f"{prefix}{spec.get('file')}:{spec.get('line')}"
        # JSON reporter は tag の先頭の `@` を落として出す（`@case:A1` → `case:A1`）。
        tags = ("@" + tag.removeprefix("@") for tag in spec.get("tags") or [])
        ids = tuple(
            dict.fromkeys(
                tag[len(CASE_PREFIX) :] for tag in tags if tag.startswith(CASE_PREFIX)
            )
        )
        if "" in ids:
            errors.append(f"{location}: `{CASE_PREFIX}` の後に id がありません")
            continue
        projects = {test.get("projectName") for test in spec.get("tests") or []}
        unknown = sorted(str(name) for name in projects - PLAYWRIGHT_PROJECTS)
        if unknown:
            errors.append(f"{location}: 未知の project です: {', '.join(unknown)}")
            continue
        if not ids:
            continue
        tests.extend(
            AnnotatedTest(kind=str(project), location=location, case_ids=ids)
            for project in sorted(projects)
        )
    return tests, errors


def _walk_specs(suites: Iterable[Any]) -> Iterable[Mapping[str, Any]]:
    for suite in suites:
        if not isinstance(suite, dict):
            continue
        for spec in suite.get("specs") or []:
            if isinstance(spec, dict):
                yield spec
        yield from _walk_specs(suite.get("suites") or [])


def check(cases: Sequence[Case], tests: Sequence[AnnotatedTest]) -> list[str]:
    """台帳と注釈付きテストを突き合わせ、失敗の message を返す."""
    errors: list[str] = []
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            errors.append(f"{case.id}: ケース id が台帳の中で重複しています")
        seen.add(case.id)

    for test in tests:
        errors.extend(
            f"{case_id}: 注釈のケース id が台帳にありません（{test.location}）"
            for case_id in test.case_ids
            if case_id not in seen
        )

    kinds_by_id = _kinds_by_case(tests)
    reported: set[str] = set()
    for case in cases:
        if case.id in reported:
            continue
        reported.add(case.id)
        found = kinds_by_id.get(case.id, set())
        if found and not found & set(case.kinds):
            errors.append(
                f"{case.id}: テストの種類（{', '.join(sorted(found))}）が台帳の"
                f"必要な種類（{', '.join(case.kinds)}）のどれとも一致しません"
            )
            continue
        errors.extend(
            f"{case.id}: 必要な種類 {kind} のテストが 1 つもありません"
            for kind in case.kinds
            if kind not in found
        )
    return errors


def _kinds_by_case(tests: Iterable[AnnotatedTest]) -> dict[str, set[str]]:
    kinds: dict[str, set[str]] = {}
    for test in tests:
        for case_id in test.case_ids:
            kinds.setdefault(case_id, set()).add(test.kind)
    return kinds


def render_map(cases: Sequence[Case], tests: Sequence[AnnotatedTest]) -> str:
    """ケースごとに種類とテストの位置を並べた対応表を返す."""
    lines: list[str] = []
    for case in cases:
        lines.append(f"{case.id} [{', '.join(case.kinds)}]")
        lines.extend(
            f"  {test.kind}: {test.location}"
            for test in sorted(tests, key=lambda item: (item.kind, item.location))
            if case.id in test.case_ids
        )
    return "\n".join(lines)


def _collect(name: str) -> tuple[str, list[str]]:
    try:
        completed = subprocess.run(
            COMMANDS[name],
            cwd=WEB_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        return "", [f"{name}: 収集を起動できません: {error}"]
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1:] or [""]
        return "", [
            f"{name}: 収集が exit {completed.returncode} で失敗しました: {detail[0]}"
        ]
    return completed.stdout, []


def main(argv: Sequence[str] | None = None) -> int:
    """台帳と注釈を突き合わせ、1 件でも失敗があれば 1 を返す."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    print_map = "--print-map" in arguments
    if [argument for argument in arguments if argument != "--print-map"]:
        print("usage: frontend_test_cases [--print-map]", file=sys.stderr)
        return 2

    try:
        ledger_text = LEDGER_PATH.read_text(encoding="utf-8")
    except OSError as error:
        print(f"ledger: 読めません: {error}", file=sys.stderr)
        return 1
    cases, errors = load_ledger(ledger_text)

    outputs: dict[str, str] = {}
    for name in COMMANDS:
        outputs[name], collect_errors = _collect(name)
        errors += collect_errors

    tests: list[AnnotatedTest] = []
    if not errors:
        vitest_tests, vitest_errors = parse_vitest(
            outputs["vitest-all"], outputs["vitest-small"], root=Path.cwd()
        )
        playwright_tests, playwright_errors = parse_playwright(
            outputs["playwright"], prefix=f"{WEB_DIR.as_posix()}/"
        )
        tests = vitest_tests + playwright_tests
        errors += vitest_errors + playwright_errors
    if not errors:
        errors = check(cases, tests)

    if errors:
        for message in errors:
            print(f"❌ {message}", file=sys.stderr)
        print(f"frontend test-case ledger: {len(errors)} 件の失敗", file=sys.stderr)
        return 1
    if print_map:
        print(render_map(cases, tests))
    print(
        f"✅ frontend test-case ledger: {len(cases)} ケース、"
        f"注釈付きテスト {len(tests)} 件が一致しました"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
