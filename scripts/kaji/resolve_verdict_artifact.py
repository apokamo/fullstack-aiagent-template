"""Resolve one missing Issue verdict marker from durable Kaji artifacts.

This helper is deliberately read-only.  It accepts only an injected current
``verdict_path`` and cross-checks the latest session-state record for one exact
producer against its permitted statuses and one unique, non-synthetic artifact.
The caller owns any provider write after inspecting the returned JSON.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import sys
from typing import Any

import yaml  # type: ignore[import-untyped]

ATTEMPT_DIRECTORY = re.compile(r"^attempt-(?P<number>[0-9]{3,})$")
STATUS = re.compile(r"^[A-Z][A-Z_]*$")
STEP_ID = re.compile(r"^[a-z][a-z0-9-]*$")
_YAML_FORBIDDEN = re.compile(
    "[^\t\n\r\x20-\x7e\x85\xa0-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]"
)


class InvalidArtifactInput(ValueError):
    """The CLI, path, state, or artifact schema is invalid."""


class ArtifactNotFound(LookupError):
    """No unique eligible producer artifact exists."""


@dataclass(frozen=True)
class CurrentArtifactPath:
    artifact_root: Path
    issue_root: Path
    issue_id: str
    run_id: str
    consumer_step: str


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidArtifactInput(f"{label} must be an object")
    return value


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), label)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InvalidArtifactInput(f"cannot read {label}: {error}") from error


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise InvalidArtifactInput(f"{label} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InvalidArtifactInput(f"{label} must be an ISO timestamp") from error
    if parsed.tzinfo is None:
        raise InvalidArtifactInput(f"{label} must include a timezone")
    return parsed


def _normalized_state_text(value: Any, label: str, *, required: bool) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise InvalidArtifactInput(f"{label} must be text")
    normalized = _YAML_FORBIDDEN.sub("\ufffd", value).strip()
    if required and not normalized:
        raise InvalidArtifactInput(f"{label} must not be empty")
    return normalized


def _normalized_verdict_scalar(value: Any, label: str, *, required: bool) -> str:
    """Normalize a YAML scalar with Kaji's verdict parser semantics."""
    if required and not value:
        raise InvalidArtifactInput(f"{label} must not be empty")
    normalized = _YAML_FORBIDDEN.sub("\ufffd", str(value)).strip()
    if required and not normalized:
        raise InvalidArtifactInput(f"{label} must not be empty")
    return normalized


def parse_current_path(path: Path, issue_id: str) -> CurrentArtifactPath:
    if not path.is_absolute() or path.name != "verdict.yaml":
        raise InvalidArtifactInput(
            "current verdict path must be an absolute verdict.yaml path"
        )
    attempt_dir = path.parent
    attempt_match = ATTEMPT_DIRECTORY.fullmatch(attempt_dir.name)
    if attempt_match is None:
        raise InvalidArtifactInput(
            "current verdict path has an invalid attempt directory"
        )
    if not attempt_dir.is_dir() or attempt_dir.is_symlink():
        raise InvalidArtifactInput("current attempt directory must be a real directory")
    step_dir = attempt_dir.parent
    steps_dir = step_dir.parent
    run_dir = steps_dir.parent
    runs_dir = run_dir.parent
    issue_root = runs_dir.parent
    artifact_root = issue_root.parent
    if steps_dir.name != "steps" or runs_dir.name != "runs":
        raise InvalidArtifactInput(
            "current verdict path does not match the Kaji artifact layout"
        )
    if issue_root.name != issue_id:
        raise InvalidArtifactInput("current verdict path belongs to a different Issue")
    if any(
        part.is_symlink()
        for part in (step_dir, steps_dir, run_dir, runs_dir, issue_root)
    ):
        raise InvalidArtifactInput("current verdict path contains a symlink")
    try:
        attempt_dir.resolve().relative_to(issue_root.resolve())
    except ValueError as error:
        raise InvalidArtifactInput(
            "current verdict path escapes the Issue artifact root"
        ) from error
    return CurrentArtifactPath(
        artifact_root=artifact_root,
        issue_root=issue_root,
        issue_id=issue_id,
        run_id=run_dir.name,
        consumer_step=step_dir.name,
    )


def parse_allowed_statuses(values: list[str], producer_step: str) -> set[str]:
    allowed: set[str] = set()
    if STEP_ID.fullmatch(producer_step) is None:
        raise InvalidArtifactInput("producer step must be a lowercase Kaji step id")
    for value in values:
        step, separator, status = value.partition("=")
        if not separator or step != producer_step or STATUS.fullmatch(status) is None:
            raise InvalidArtifactInput(f"invalid allowed status: {value}")
        allowed.add(status)
    if not allowed:
        raise InvalidArtifactInput("producer step needs at least one allowed status")
    return allowed


def _latest_state_record(
    state: dict[str, Any],
    issue_id: str,
    producer_step: str,
    allowed_statuses: set[str],
) -> tuple[dict[str, Any], datetime]:
    if str(state.get("issue_number")) != issue_id:
        raise InvalidArtifactInput("session state belongs to a different Issue")
    history = state.get("step_history")
    if not isinstance(history, list):
        raise InvalidArtifactInput("session state step_history must be a list")
    producer_records: list[tuple[datetime, dict[str, Any]]] = []
    for index, raw in enumerate(history):
        record = _object(raw, f"step_history[{index}]")
        step = record.get("step_id")
        if step == producer_step:
            status = record.get("verdict_status")
            if not isinstance(status, str) or STATUS.fullmatch(status) is None:
                raise InvalidArtifactInput(
                    f"step_history[{index}].verdict_status is invalid"
                )
            producer_records.append(
                (
                    _parse_time(
                        record.get("timestamp"), f"step_history[{index}].timestamp"
                    ),
                    record,
                )
            )
    if not producer_records:
        raise ArtifactNotFound("producer does not exist in session state")
    latest_time = max(timestamp for timestamp, _ in producer_records)
    latest = [
        record for timestamp, record in producer_records if timestamp == latest_time
    ]
    if len(latest) != 1:
        raise ArtifactNotFound("latest producer session-state record is ambiguous")
    if latest[0]["verdict_status"] not in allowed_statuses:
        raise ArtifactNotFound("latest producer status is not allowed for this handoff")
    return latest[0], latest_time


def _load_verdict(path: Path) -> dict[str, str]:
    try:
        artifact_text = path.read_text(encoding="utf-8")
        raw = yaml.safe_load(_YAML_FORBIDDEN.sub("\ufffd", artifact_text))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise InvalidArtifactInput(f"cannot read verdict artifact: {error}") from error
    verdict = _object(raw, "verdict artifact")
    if "status" not in verdict:
        raise InvalidArtifactInput("verdict artifact is missing status")
    status = _normalized_verdict_scalar(
        verdict["status"], "verdict status", required=True
    )
    if STATUS.fullmatch(status) is None:
        raise InvalidArtifactInput("verdict artifact has an invalid status")
    return {
        "status": status,
        "reason": _normalized_verdict_scalar(
            verdict.get("reason"), "verdict reason", required=True
        ),
        "evidence": _normalized_verdict_scalar(
            verdict.get("evidence"), "verdict evidence", required=True
        ),
        "suggestion": _normalized_verdict_scalar(
            verdict.get("suggestion", ""), "verdict suggestion", required=False
        ),
    }


def _candidate_attempts(
    issue_root: Path, producer_step: str
) -> list[tuple[str, int, Path]]:
    candidates: list[tuple[str, int, Path]] = []
    runs_dir = issue_root / "runs"
    if not runs_dir.is_dir() or runs_dir.is_symlink():
        raise InvalidArtifactInput("Issue runs directory is missing or unsafe")
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir() or run_dir.is_symlink():
            continue
        steps_dir = run_dir / "steps"
        if not steps_dir.is_dir() or steps_dir.is_symlink():
            continue
        step_dir = steps_dir / producer_step
        if not step_dir.is_dir() or step_dir.is_symlink():
            continue
        attempts: list[tuple[int, Path]] = []
        for attempt_dir in step_dir.iterdir():
            match = ATTEMPT_DIRECTORY.fullmatch(attempt_dir.name)
            if match is None or not attempt_dir.is_dir() or attempt_dir.is_symlink():
                continue
            try:
                attempt_dir.resolve().relative_to(issue_root.resolve())
            except ValueError as error:
                raise InvalidArtifactInput(
                    "producer artifact path escapes the Issue root"
                ) from error
            attempts.append((int(match.group("number")), attempt_dir))
        if attempts:
            attempt, path = max(attempts, key=lambda item: item[0])
            candidates.append((run_dir.name, attempt, path))
    return candidates


def _validated_result(result: dict[str, Any]) -> tuple[str, int, str, datetime]:
    step = result.get("step_id")
    attempt = result.get("attempt")
    status = result.get("status")
    if not isinstance(step, str) or STEP_ID.fullmatch(step) is None:
        raise InvalidArtifactInput("result step_id is invalid")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise InvalidArtifactInput("result attempt is invalid")
    if not isinstance(status, str) or STATUS.fullmatch(status) is None:
        raise InvalidArtifactInput("result status is invalid")
    if "synthetic" not in result or not isinstance(result["synthetic"], bool):
        raise InvalidArtifactInput("result synthetic must be a boolean")
    if "error" not in result or (
        result["error"] is not None and not isinstance(result["error"], str)
    ):
        raise InvalidArtifactInput("result error must be null or text")
    ended_at = _parse_time(result.get("ended_at"), "result ended_at")
    return step, attempt, status, ended_at


def resolve_verdict_artifact(
    *,
    issue_id: str,
    current_verdict_path: Path,
    producer_step: str,
    allowed_statuses: set[str],
) -> dict[str, Any]:
    if re.fullmatch(r"[1-9][0-9]*", issue_id) is None:
        raise InvalidArtifactInput("Issue ID must be a positive integer")
    if STEP_ID.fullmatch(producer_step) is None:
        raise InvalidArtifactInput("producer step must be a lowercase Kaji step id")
    if not allowed_statuses or any(
        STATUS.fullmatch(status) is None for status in allowed_statuses
    ):
        raise InvalidArtifactInput("allowed statuses must be non-empty Kaji statuses")
    current = parse_current_path(current_verdict_path, issue_id)
    state_path = current.issue_root / "session-state.json"
    if state_path.is_symlink():
        raise InvalidArtifactInput("session state must not be a symlink")
    state = _read_json(state_path, "session state")
    state_record, state_time = _latest_state_record(
        state, issue_id, producer_step, allowed_statuses
    )
    state_status = state_record["verdict_status"]
    state_attempt = state_record.get("attempt")
    if (
        not isinstance(state_attempt, int)
        or isinstance(state_attempt, bool)
        or state_attempt < 1
    ):
        raise InvalidArtifactInput(
            "producer session-state attempt must be a positive integer"
        )
    state_fields = {
        "status": state_status,
        "reason": _normalized_state_text(
            state_record.get("verdict_reason"), "state reason", required=True
        ),
        "evidence": _normalized_state_text(
            state_record.get("verdict_evidence"), "state evidence", required=True
        ),
        "suggestion": _normalized_state_text(
            state_record.get("verdict_suggestion", ""),
            "state suggestion",
            required=False,
        ),
    }

    matched: list[dict[str, Any]] = []
    for run_id, attempt, attempt_dir in _candidate_attempts(
        current.issue_root, producer_step
    ):
        verdict_path = attempt_dir / "verdict.yaml"
        result_path = attempt_dir / "result.json"
        if (
            not verdict_path.is_file()
            or not result_path.is_file()
            or verdict_path.is_symlink()
            or result_path.is_symlink()
        ):
            continue
        verdict = _load_verdict(verdict_path)
        result = _read_json(result_path, "result artifact")
        result_step, result_attempt, result_status, ended_at = _validated_result(result)
        if result.get("synthetic") is not False or result.get("error") is not None:
            continue
        if (
            result_step != producer_step
            or result_attempt != attempt
            or result_attempt != state_attempt
            or result_status != state_status
            or verdict != state_fields
        ):
            continue
        if not ended_at <= state_time <= ended_at + timedelta(seconds=5):
            continue
        matched.append(
            {
                "current_run_id": current.run_id,
                "producer_run_id": run_id,
                "step": producer_step,
                "attempt": attempt,
                "status": state_status,
                "verdict_path": str(verdict_path),
                "result_path": str(result_path),
                "ended_at": result["ended_at"],
            }
        )
    if len(matched) != 1:
        raise ArtifactNotFound(
            f"expected one matching producer artifact, found {len(matched)}"
        )
    return matched[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue-id", required=True)
    parser.add_argument("--current-verdict-path", required=True, type=Path)
    parser.add_argument("--producer-step", action="append", required=True)
    parser.add_argument("--allow-status", action="append", required=True)
    args = parser.parse_args()
    try:
        if len(args.producer_step) != 1:
            raise InvalidArtifactInput("exactly one producer step is required")
        producer = args.producer_step[0]
        allowed = parse_allowed_statuses(args.allow_status, producer)
        resolved = resolve_verdict_artifact(
            issue_id=args.issue_id,
            current_verdict_path=args.current_verdict_path,
            producer_step=producer,
            allowed_statuses=allowed,
        )
    except InvalidArtifactInput as error:
        print(f"invalid artifact input: {error}", file=sys.stderr)
        return 2
    except ArtifactNotFound as error:
        print(f"artifact not found: {error}", file=sys.stderr)
        return 4
    print(json.dumps(resolved, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
