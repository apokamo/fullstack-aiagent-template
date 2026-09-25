"""Private immutable evaluation evidence, validated independently of live collectors.

No agent, suite, provider or database is imported here. Suite collectors must
apply privacy filtering before publishing live observations.
"""

from __future__ import annotations

from contextlib import contextmanager, suppress
from datetime import datetime  # noqa: TC003 - Pydantic resolves annotations at runtime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema import ValidationError as SchemaError
from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from collections.abc import Iterator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
ModelName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Commit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Count = Annotated[int, Field(ge=0)]


class EvidenceError(ValueError):
    """Untrusted evidence cannot be read, correlated or published."""


class Record(BaseModel):
    """Closed, immutable typed records; no free-form metadata dictionaries."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def canonical_bytes(value: object) -> bytes:
    """Canonical JSON rejects non-finite numbers instead of hashing them."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(value: object) -> str:
    """Content identity, independent of JSON whitespace and mapping order."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def unique(values: tuple[str, ...]) -> None:
    """Reject duplicate IDs, including duplicate planned obligations."""
    if len(values) != len(set(values)):
        raise EvidenceError("duplicate_id")


class Usage(Record):
    requests: Count
    input_tokens: Count | None
    output_tokens: Count | None
    reasoning_tokens: Count | None = None
    missing_reason: str | None

    @model_validator(mode="after")
    def missing_tokens(self) -> Self:
        if (
            self.input_tokens is None or self.output_tokens is None
        ) and not self.missing_reason:
            raise EvidenceError("usage_missing_reason")
        return self


class GenerationIdentity(Record):
    profile: Identifier
    provider: Identifier
    model: ModelName
    protocol: Identifier
    api_mode: Identifier
    effort: Identifier
    endpoint_hash: Digest
    config_hash: Digest


class VersionedHash(Record):
    version: Identifier
    digest: Digest


class EvidenceItem(Record):
    """One addressable text: a prompt, an answer, a tool call or its result.

    `text` is the span address space a judge quotes from. Tool arguments and
    results are canonical JSON text. A live collector applies its own privacy
    boundary before it builds an item.
    """

    evidence_id: Identifier
    kind: Literal["prompt", "answer", "call", "result", "final", "event"]
    text: str
    status: Literal["observed", "executed", "rejected", "error"] = "observed"
    error_kind: Identifier | None = None
    call_id: Identifier | None = None
    result_id: Identifier | None = None

    @model_validator(mode="after")
    def execution_state(self) -> Self:
        if (self.status == "error") != (self.error_kind is not None):
            raise EvidenceError("evidence_error_state")
        return self


class TurnEvidence(Record):
    turn_id: Identifier
    started_at: datetime | None = None
    finished_at: datetime | None = None
    related_turn_ids: tuple[Identifier, ...] = ()
    state: Literal["completed", "failed", "not_executed"]
    error_kind: Identifier | None = None
    executed_mutations: Count = 0
    #: Tool calls the harness approved in this turn. Mutations beyond this
    #: count were written without an approval.
    approved_calls: Count = 0
    privacy_violation: bool = False
    missing_evidence_ids: tuple[Identifier, ...] = ()
    evidence: tuple[EvidenceItem, ...]
    usage: Usage

    @model_validator(mode="after")
    def references(self) -> Self:
        if (self.started_at is None) != (self.finished_at is None):
            raise EvidenceError("partial_turn_timing")
        if (
            self.started_at is not None
            and self.finished_at is not None
            and (
                self.started_at.utcoffset() is None
                or self.finished_at.utcoffset() is None
                or self.finished_at < self.started_at
            )
        ):
            raise EvidenceError("invalid_turn_timing")
        unique(tuple(item.evidence_id for item in self.evidence))
        if (self.state == "failed") != (self.error_kind is not None):
            raise EvidenceError("turn_state_error_mismatch")
        if self.state == "not_executed" and (
            self.evidence
            or self.usage.requests
            or self.executed_mutations
            or self.approved_calls
        ):
            raise EvidenceError("unexecuted_turn_has_activity")
        return self


class CaseObservation(Record):
    schema_version: Literal["eval-observation-v1"] = "eval-observation-v1"
    #: `synthetic` for hand-built fixtures, `live` for a suite collector's output.
    source: Literal["synthetic", "live"] = "synthetic"
    observation_id: Identifier
    run_id: Identifier
    trial_id: Identifier
    case_id: Identifier
    repeat: Annotated[int, Field(ge=1)]
    source_sha: Commit
    tree_dirty: bool
    suite: Identifier
    generation: GenerationIdentity
    dataset: VersionedHash
    source_manifest_hash: Digest
    started_at: datetime
    finished_at: datetime
    turn_timeout_seconds: Annotated[float, Field(gt=0)]
    preflight: Literal["synthetic-not-required", "passed", "failed"]
    measurement_context_hash: Digest | None
    planned_turn_ids: tuple[Identifier, ...]
    turns: tuple[TurnEvidence, ...]

    @model_validator(mode="after")
    def timeline(self) -> Self:
        if (self.source == "synthetic") != (self.preflight == "synthetic-not-required"):
            raise EvidenceError("source_preflight_mismatch")
        if self.started_at.utcoffset() is None or self.finished_at.utcoffset() is None:
            raise EvidenceError("timezone_required")
        if self.finished_at < self.started_at:
            raise EvidenceError("invalid_timeline")
        if not self.planned_turn_ids:
            raise EvidenceError("empty_turn_plan")
        unique(self.planned_turn_ids)
        ids = tuple(turn.turn_id for turn in self.turns)
        unique(ids)
        if any(turn_id not in self.planned_turn_ids for turn_id in ids):
            raise EvidenceError("unplanned_turn")
        if ids != tuple(turn_id for turn_id in self.planned_turn_ids if turn_id in ids):
            raise EvidenceError("turn_order_mismatch")
        seen: set[str] = set()
        for turn in self.turns:
            if not set(turn.related_turn_ids) <= seen:
                raise EvidenceError("unknown_related_turn")
            seen.add(turn.turn_id)
        unique(tuple(item.evidence_id for turn in self.turns for item in turn.evidence))
        return self


class ArtifactRef(Record):
    kind: Literal["observations", "scores"]
    record_id: Identifier
    digest: Digest


def validate_record[T: Record](model: type[T], value: object) -> T:
    """Validate the closed JSON shape, version and cross-field invariants."""
    Draft202012Validator(
        model.model_json_schema(), format_checker=FormatChecker()
    ).validate(value)
    return model.model_validate(value)


class EvidenceStore:
    """Atomic publication under a private directory, with no overwrite/symlinks.

    Writers lock the containing directory around existence check and rename.
    Directory/file descriptors use O_NOFOLLOW, and IDs are single components.
    No exception includes raw transcript content or a provider exception.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.absolute()

    @contextmanager
    def _directory(self, kind: str) -> Iterator[int]:
        path = self.root / kind
        current = Path(path.anchor)
        for part in path.parts[1:]:
            if part in (".", ".."):
                raise EvidenceError("unsafe_path")
            current /= part
            with suppress(FileExistsError):
                current.mkdir(mode=0o700)
            if not stat.S_ISDIR(current.lstat().st_mode):
                raise EvidenceError("unsafe_directory")
        # Existing artifact roots must also be private, not silently chmodded.
        for private in (self.root, path):
            if stat.S_IMODE(private.stat().st_mode) & 0o077:
                raise EvidenceError("non_private_directory")
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield descriptor
        finally:
            os.close(descriptor)

    @staticmethod
    def _location(reference: ArtifactRef) -> tuple[str, str]:
        validate_record(ArtifactRef, reference.model_dump(mode="json"))
        if reference.kind == "scores":
            return f"scores/{reference.record_id}", "score.json"
        return "observations", f"{reference.record_id}.json"

    @staticmethod
    def _match(reference: ArtifactRef, record: Record) -> None:
        field = "observation_id" if reference.kind == "observations" else "score_id"
        if getattr(record, field, None) != reference.record_id:
            raise EvidenceError("record_identity_mismatch")

    def publish(self, reference: ArtifactRef, record: Record) -> None:
        """Publish exactly the checked bytes, never replacing an existing ID."""
        self._match(reference, record)
        value = record.model_dump(mode="json")
        validate_record(type(record), value)
        if canonical_hash(value) != reference.digest:
            raise EvidenceError("hash_mismatch")
        folder, name = self._location(reference)
        temporary = f".{uuid4().hex}.tmp"
        with self._directory(folder) as directory:
            if name in os.listdir(directory):
                raise EvidenceError("record_exists")
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(canonical_bytes(value))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.rename(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                if temporary in os.listdir(directory):
                    os.unlink(temporary, dir_fd=directory)

    def publish_diagnostic(self, score_id: str, value: dict[str, Any]) -> None:
        """Keep pre-parse judge evidence alongside, never inside public score fields."""
        ArtifactRef(kind="scores", record_id=score_id, digest=canonical_hash(value))
        with self._directory(f"scores/{score_id}") as directory:
            name = "judge-diagnostic.json"
            temporary = f".{uuid4().hex}.tmp"
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(canonical_bytes(value))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                os.unlink(temporary, dir_fd=directory)

    def read[T: Record](self, reference: ArtifactRef, model: type[T]) -> T:
        """Read without running an agent; reject corruption before grading."""
        folder, name = self._location(reference)
        try:
            with self._directory(folder) as directory:
                descriptor = os.open(
                    name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=directory,
                )
                with os.fdopen(descriptor, "rb") as stream:
                    metadata = os.fstat(stream.fileno())
                    if (
                        not stat.S_ISREG(metadata.st_mode)
                        or stat.S_IMODE(metadata.st_mode) & 0o077
                    ):
                        raise EvidenceError("unsafe_file")
                    value = json.load(stream)
            if canonical_hash(value) != reference.digest:
                raise EvidenceError("hash_mismatch")
            record = validate_record(model, value)
            self._match(reference, record)
            return record
        except EvidenceError:
            raise
        except FileNotFoundError:
            raise EvidenceError("missing_evidence") from None
        except (OSError, ValueError, SchemaError):
            raise EvidenceError("unreadable_evidence") from None
