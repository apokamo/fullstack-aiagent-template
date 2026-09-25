#!/usr/bin/env python3
"""lane の成功を commit ごとに記録し、同じ commit での再実行を引用へ置き換える.

入口は 2 つある。

    uv run python -m scripts.testing.lane_record <lane> [--artifact <path>] -- <command> ...
    uv run python -m scripts.testing.lane_record --check <lane>

前者は `Makefile` の公開 target を包む wrapper で、子の出力をそのまま流しながら
`test-artifacts/logs/<lane>/<RUN_ID>.log` へ書く。**exit 0 で、実行の前後とも
tree が clean かつ HEAD が動かなかったときだけ** record を
`test-artifacts/lanes/<lane>/<commit_sha>.json` へ 1 行の JSON で書く。実 LLM lane は
profile の identity hash を 1 段挟む（`lanes/<lane>/<identity>/<commit_sha>.json`）。

後者は今の HEAD の record が引用できるかを**終了コードで**返す（0 = 引用、1 = 再実行、
2 = usage error）。規約の正本は `.claude/skills/_shared/lane-evidence.md` である。

- **不確かさはすべて再実行へ倒す。** record が無い・読めない・commit や identity が違う・
  tree が dirty なら再実行になる。
- **record の障害で lane を失敗させない。** 書けなければ warning を 1 行出し、子の
  終了コードをそのまま返す。
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import TYPE_CHECKING, BinaryIO

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: record を書く公開品質 target。
LANE_TARGETS: frozenset[str] = frozenset(
    {
        "verify-backend",
        "gate-backend",
        "verify-frontend",
        "verify-docs",
        "check-all",
        "test-on-schema-change",
        "test-e2e",
        "test-llm",
        "evals",
    }
)

#: 実 LLM を通す lane。record を profile の identity で分け、引用にその一致を要る。
REAL_LLM_LANES: frozenset[str] = frozenset({"test-llm", "evals"})

#: `--artifact` を宣言する lane。artifact を新しく出さなかった run は引用しない。
ARTIFACT_LANES: frozenset[str] = frozenset({"evals"})

#: 研究実行を表す CLI flag。測定値を残すだけで品質合格を主張しないので、
#: 成功 record を作らず、同じ commit の既存 record も消さない。
RESEARCH_FLAGS: frozenset[str] = frozenset(
    {"--record-reference", "--compare-candidate", "--observe"}
)

#: record の形。読み手は未知の値を record 不在として扱う。
SCHEMA_VERSION = "lane-record-v4"

RECORD_ROOT = Path("test-artifacts/lanes")
LOG_ROOT = Path("test-artifacts/logs")

#: `RUN_ID` と identity は path 片になるので、形を照合してから使う。
RUN_ID_PATTERN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
COMMIT_SHA_PATTERN = re.compile(r"\A[0-9a-f]{40}\Z")
FINGERPRINT_PATTERN = re.compile(r"\A[0-9a-f]{8,64}\Z")

USAGE = (
    "usage: lane_record <lane> [--artifact <path>] -- <command> ...\n"
    "       lane_record --check <lane>"
)


def warn(message: str) -> None:
    """lane を失敗させない 1 行 warning."""
    print(f"⚠️  lane-record: {message}", file=sys.stderr, flush=True)


# =============================================================================
# git
# =============================================================================


def _git(arguments: Sequence[str], root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *arguments], cwd=root, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return completed.stdout if completed.returncode == 0 else None


def git_head(root: Path) -> str | None:
    """現在の commit。読めなければ `None`."""
    output = _git(["rev-parse", "HEAD"], root)
    head = (output or "").strip()
    return head if COMMIT_SHA_PATTERN.match(head) else None


def git_dirty(root: Path) -> bool | None:
    """tree が dirty か。判定できなければ `None`（ignore 済みは dirty にしない）."""
    output = _git(["status", "--porcelain"], root)
    return None if output is None else bool(output.strip())


# =============================================================================
# 実 LLM lane の identity
# =============================================================================


def llm_identity(environ: Mapping[str, str]) -> tuple[str, str] | None:
    """実 provider を通した run の `(profile id, identity hash)`。証跡にならなければ `None`.

    fake model・`SKIP_LLM_TESTS=1`・未知や未設定の profile は実 provider の証跡に
    ならない。hash の正本は `apps.api.core.llm_profiles.identity_fingerprint()` で、
    ここでは再実装しない。
    """
    if environ.get("SKIP_LLM_TESTS") == "1":
        return None
    if environ.get("AGENT_MODEL_MODE", "real").strip().lower() != "real":
        return None
    name = environ.get("LLM_PROFILE", "").strip()
    if not name:
        return None
    from apps.api.core.llm_profiles import (
        UnknownProfile,
        identity_fingerprint,
        resolve_profile,
    )

    try:
        profile = resolve_profile(name)
    except UnknownProfile:
        return None
    fingerprint = identity_fingerprint(profile)
    if not FINGERPRINT_PATTERN.match(fingerprint):
        return None
    return profile.profile, fingerprint


def load_environment(lane: str) -> Mapping[str, str]:
    """実 LLM lane では `LLM_PROFILE` を API context の env から読む."""
    if lane in REAL_LLM_LANES:
        from apps.api.core.environment import load_api_env

        load_api_env()
    return os.environ


def record_path(
    root: Path, lane: str, commit_sha: str, fingerprint: str | None
) -> Path | None:
    """record の置き場。実 LLM lane で identity が無ければ `None`."""
    directory = root / RECORD_ROOT / lane
    if lane in REAL_LLM_LANES:
        if fingerprint is None:
            return None
        directory = directory / fingerprint
    return directory / f"{commit_sha}.json"


# =============================================================================
# 引用の判定
# =============================================================================


def citation_reason(
    *,
    lane: str,
    head: str | None,
    dirty: bool | None,
    identity_known: bool,
    record_text: str | None,
) -> str | None:
    """引用してよければ `None`、再実行すべきならその理由を返す.

    Args:
        lane: 引用したい lane。
        head: 現在の commit。読めなければ `None`。
        dirty: tree が dirty か。読めなければ `None`。
        identity_known: 実 LLM lane で、今の env から profile identity が決まったか。
            実 LLM 以外の lane では常に `True` を渡す。
        record_text: 今の HEAD（と identity）の record。無ければ `None`。
    """
    if dirty:
        return "dirty-worktree"
    if dirty is None or head is None:
        return "no-head"
    if not identity_known:
        return "env-mismatch"
    if record_text is None:
        return "no-record"
    try:
        record = json.loads(record_text)
    except ValueError:
        return "unreadable-record"
    if not isinstance(record, dict):
        return "unreadable-record"
    if record.get("schema_version") != SCHEMA_VERSION:
        return "unknown-schema"
    if record.get("lane") != lane or record.get("commit_sha") != head:
        return "inconsistent-record"
    if record.get("exit") != 0 or isinstance(record.get("exit"), bool):
        return "failed-record"
    if lane in ARTIFACT_LANES and not record.get("artifact_path"):
        return "missing-artifact"
    return None


def check(lane: str, root: Path) -> int:
    """引用可否を終了コードで返し、判断の根拠を 1 行出す."""
    head = git_head(root)
    dirty = git_dirty(root)
    fingerprint: str | None = None
    if lane in REAL_LLM_LANES:
        identity = llm_identity(load_environment(lane))
        fingerprint = identity[1] if identity else None
    target = record_path(root, lane, head, fingerprint) if head else None
    record_text: str | None = None
    if target is not None:
        try:
            record_text = target.read_text(encoding="utf-8")
        except OSError:
            record_text = None
    reason = citation_reason(
        lane=lane,
        head=head,
        dirty=dirty,
        identity_known=lane not in REAL_LLM_LANES or fingerprint is not None,
        record_text=record_text,
    )
    if reason is not None:
        print(f"RERUN {lane} reason={reason}")
        return 1
    assert target is not None and record_text is not None
    artifact = json.loads(record_text).get("artifact_path") or "-"
    print(
        f"REUSABLE {lane} record={target.as_posix()} commit={head} "
        f"exit=0 artifact={artifact}"
    )
    return 0


# =============================================================================
# 実行と記録
# =============================================================================


def stream_child(command: Sequence[str], log_file: BinaryIO) -> tuple[int, bool]:
    """子の stdout / stderr を 1 本にして流しながらログへも書く.

    Returns:
        `(終了コード, ログが完全か)`。ログの書き込み障害では lane を失敗させず、
        その run の record だけを諦める。
    """
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
    except OSError as error:
        warn(f"cannot execute {command[0]}: {error}")
        return 127, False
    assert process.stdout is not None
    log_complete = True
    with process.stdout as stream:
        # `os.read()` は届いた分だけ返すので、子の進捗をそのまま流せる。
        descriptor = stream.fileno()
        while chunk := os.read(descriptor, 65536):
            sys.stdout.buffer.write(chunk)
            sys.stdout.flush()
            if not log_complete:
                continue
            try:
                log_file.write(chunk)
                log_file.flush()
            except OSError as error:
                warn(f"cannot write the lane log ({error}); no record for this run")
                log_complete = False
    returncode = process.wait()
    # signal で落ちた子は shell と同じ `128 + N` に写す。
    return (128 - returncode if returncode < 0 else returncode), log_complete


def research_flag(command: Sequence[str]) -> str | None:
    """command が研究 flag を持つならその名前を返す（`--flag=value` 形も見る）."""
    for argument in command:
        for flag in sorted(RESEARCH_FLAGS):
            if argument == flag or argument.startswith(f"{flag}="):
                return flag
    return None


def wrap(lane: str, artifact: str | None, command: Sequence[str], root: Path) -> int:
    """lane を包んで実行し、条件を満たしたときだけ record を書く."""
    run_id = os.environ.get("RUN_ID", "")
    if not RUN_ID_PATTERN.match(run_id):
        warn(f"{lane}: RUN_ID is not usable as a path segment; no record")
        return subprocess.run(command, check=False).returncode

    log_target = root / LOG_ROOT / lane / f"{run_id}.log"
    head_before = git_head(root)
    dirty_before = git_dirty(root)
    artifact_target = root / artifact if artifact else None
    artifact_existed = artifact_target is not None and artifact_target.exists()
    environment = load_environment(lane)
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        log_target.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_target, "ab")  # noqa: SIM115 - 下の finally で閉じる
    except OSError as error:
        warn(f"{lane}: cannot open the lane log ({error}); no record")
        return subprocess.run(command, check=False).returncode
    try:
        status, log_complete = stream_child(command, log_file)
    finally:
        log_file.close()

    flag = research_flag(command)
    if flag is not None:
        warn(f"{lane}: {flag} is a research run; no record for this run")
        return status

    identity = llm_identity(environment) if lane in REAL_LLM_LANES else None
    fingerprint = identity[1] if identity else None
    target = record_path(root, lane, head_before, fingerprint) if head_before else None

    if status != 0:
        # 同じ commit の古い成功 record を残すと、失敗した再実行のあとも引用できて
        # しまう。新しい失敗を採る。
        if target is not None and target.exists():
            target.unlink(missing_ok=True)
            warn(f"{lane}: the lane failed; discarded the record for {head_before}")
        return status

    if lane in REAL_LLM_LANES and identity is None:
        warn(f"{lane}: no real-provider identity in the environment; no record")
        return status
    if not log_complete or target is None or dirty_before is not False:
        warn(f"{lane}: the tree was dirty or unreadable before the lane; no record")
        return status
    if git_dirty(root) is not False or git_head(root) != head_before:
        warn(f"{lane}: the tree or HEAD moved during the lane; no record")
        return status

    artifact_path: str | None = None
    if artifact is not None and artifact_target is not None:
        if not artifact_existed and artifact_target.exists():
            artifact_path = artifact
        else:
            warn(f"{lane}: {artifact} was not newly published; artifact_path is null")

    record = {
        "schema_version": SCHEMA_VERSION,
        "lane": lane,
        "commit_sha": head_before,
        "exit": status,
        "run_id": run_id,
        "started_at": started_at,
        "log_path": log_target.as_posix(),
        "artifact_path": artifact_path,
        "llm_profile": identity[0] if identity else None,
    }
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(record, ensure_ascii=False) + "\n", "utf-8")
        os.replace(temporary, target)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        warn(f"{lane}: cannot write the record ({error})")
    return status


# =============================================================================
# 入口
# =============================================================================


def main(argv: Sequence[str] | None = None) -> int:
    """CLI エントリポイント."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    root = Path()
    if arguments[:1] == ["--check"]:
        if len(arguments) != 2 or arguments[1] not in LANE_TARGETS:
            print(USAGE, file=sys.stderr)
            return 2
        return check(arguments[1], root)

    if not arguments or arguments[0] not in LANE_TARGETS or "--" not in arguments:
        print(USAGE, file=sys.stderr)
        return 2
    lane = arguments[0]
    separator = arguments.index("--")
    options = arguments[1:separator]
    command = arguments[separator + 1 :]
    artifact: str | None = None
    if options:
        if len(options) != 2 or options[0] != "--artifact":
            print(USAGE, file=sys.stderr)
            return 2
        artifact = options[1]
    if not command:
        print(USAGE, file=sys.stderr)
        return 2
    return wrap(lane, artifact, command, root)


if __name__ == "__main__":
    sys.exit(main())
