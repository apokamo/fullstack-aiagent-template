"""What one sample eval run is keyed by, and the state it carries while it runs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from apps.api.sample.agent import SAMPLE_INSTRUCTIONS

if TYPE_CHECKING:
    from collections.abc import Mapping

    from apps.api.agent.evals.judge_client import JudgeSettings
    from apps.api.core.llm_profiles import ChatProfile
    from apps.api.sample.evals.session import SampleSession

#: The sample never asks for a typed final; every profile uses `natural`.
OUTPUT_MODE = "natural"

#: The tool definitions the agent is given. Their docstrings and signatures are
#: part of what the model reads, so a change to them is a new identity.
TOOLS_SOURCE = Path(__file__).resolve().parents[1] / "tools.py"

#: `evals` saves and grades each trial; `observe` only saves it.
RunMode = Literal["evals", "observe"]


@dataclass
class SampleExecution:
    """The run-scoped execution config of a sample eval run.

    `profile`, `mode` and `recording_reference` are fixed when the run is
    resolved. `session` is attached once the runner has created the run's
    evidence directory, and holds the run's saved observations.
    """

    profile: ChatProfile
    recording_reference: bool = False
    mode: RunMode = "evals"
    judge_settings: JudgeSettings | None = None
    session: SampleSession | None = None

    @property
    def is_research(self) -> bool:
        """A reference recording or an observe-only run is never an official pass."""
        return self.recording_reference or self.mode == "observe"


def execution_config(
    _execution: SampleExecution, *, schema_prompt_digest: str | None = None
) -> dict[str, Any]:
    """The agent configuration the artifact records and the identity folds in.

    Args:
        _execution: The resolved execution config. Nothing in it varies the
            block; it is taken so the signature matches the shared contract.
        schema_prompt_digest: Unused by this suite, which renders no schema
            prompt. The keyword exists so the shared runner can call every suite
            the same way.

    Returns:
        The output policy and the digests of the instructions and tool
        definitions the agent runs with.
    """
    del schema_prompt_digest
    return {
        "output_mode": OUTPUT_MODE,
        "instructions_digest": _digest(SAMPLE_INSTRUCTIONS.encode()),
        "tools_digest": _digest(TOOLS_SOURCE.read_bytes()),
    }


def execution_config_digest(config: Mapping[str, Any]) -> str:
    """The digest two different configs differ by."""
    canonical = json.dumps(config, ensure_ascii=False, sort_keys=True)
    return _digest(canonical.encode())


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
