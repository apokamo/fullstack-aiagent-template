"""Command-line pieces every eval entry point shares."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import math
import os
from pathlib import Path
import secrets
import subprocess
import sys
from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Provider reachability budget. A preflight is one short
#: non-streaming POST whose only job is to fail fast, so it never shares the
#: turn budget: setting a 30-minute turn must not buy a 30-minute preflight.
DEFAULT_PREFLIGHT_TIMEOUT_SECONDS = 30.0

#: Wall-clock budget for **one whole turn**, tool executions and every provider
#: request included. Two stalled requests at 900 s each is the worst shape the
#: agent can produce inside one turn, so 1,800 s is the safety valve rather
#: than an expected duration. Shared by every mode: the number comes from the
#: agent's own shape, not from what a suite asserts afterwards.
DEFAULT_TURN_TIMEOUT_SECONDS = 1800.0

#: Wall-clock budget for the whole trial loop (the statistical modes). Checked
#: **before each trial starts**, never inside one, so the guaranteed ceiling is
#: `suite + turn * 2` for a two-turn case begun just under the deadline.
DEFAULT_SUITE_TIMEOUT_SECONDS = 3600.0

#: The repository an artifact's `commit_sha` is read from. `cli.py` sits at
#: `apps/api/agent/evals/`, so the root is four parents up.
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]

#: Where every suite's tracked baseline lives: `<suite>/<profile>.json`. A
#: baseline is a measurement record, not app code, so it sits under the
#: repository's `evals-evidence/` rather than next to the dataset.
BASELINES_ROOT = REPOSITORY_ROOT / "evals-evidence" / "baselines"


#: Spending ceiling of one eval command, in USD, unless `--max-cost-usd` or
#: `EVAL_MAX_COST_USD` says otherwise. Sized for one pass of the sample suite
#: with its judge on GPT-6 Luna.
DEFAULT_MAX_COST_USD = 0.05

#: The environment variable that overrides `DEFAULT_MAX_COST_USD`.
MAX_COST_ENV = "EVAL_MAX_COST_USD"

#: Tokens one agent request is assumed to use before it is sent. These are
#: planning figures for the pre-run estimate, not limits: the actual spend is
#: always computed from the usage the provider returns.
NOMINAL_REQUEST_INPUT_TOKENS = 4000
NOMINAL_REQUEST_OUTPUT_TOKENS = 1000

#: Agent requests one turn is assumed to take: a tool call and the answer. A
#: turn that stops for approval takes one more, for the resumed run.
NOMINAL_REQUESTS_PER_TURN = 2
NOMINAL_REQUESTS_PER_APPROVAL = 1


def positive_cost(value: str) -> float:
    """Parse one strictly positive USD ceiling."""
    try:
        cost = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("cost must be a number") from exc
    if not math.isfinite(cost) or cost <= 0:
        raise argparse.ArgumentTypeError(
            "cost must be a finite number greater than zero"
        )
    return cost


def resolve_max_cost(parser: argparse.ArgumentParser, cli_value: float | None) -> float:
    """Resolve the USD ceiling as CLI -> env -> default.

    A malformed env value is a usage error, never a silent fall back to the
    default: an operator who set a ceiling must not run under another one.
    """
    if cli_value is not None:
        return cli_value
    raw = os.environ.get(MAX_COST_ENV)
    if not raw:
        return DEFAULT_MAX_COST_USD
    try:
        return positive_cost(raw)
    except argparse.ArgumentTypeError as exc:
        parser.error(f"{MAX_COST_ENV}: {exc}")


@dataclass
class CostBudget:
    """The spending ceiling of one command, checked before each unit of work.

    A unit (one trial, one judge request) starts only when what was already
    spent plus that unit's estimate stays within `max_usd`. A unit is never
    cut off once it has started, so the actual spend can exceed the ceiling by
    at most the difference between one unit's cost and its estimate.
    """

    max_usd: float
    spent_usd: float = 0.0

    def allows(self, estimate_usd: float) -> bool:
        """Whether a unit estimated at `estimate_usd` may start now."""
        return self.spent_usd + estimate_usd <= self.max_usd

    def charge(self, usd: float) -> None:
        """Record what a finished unit actually cost."""
        self.spent_usd += usd


def positive_timeout(value: str) -> float:
    """Parse one strictly positive eval/preflight timeout."""
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a number") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError(
            "timeout must be a finite number greater than zero"
        )
    return timeout


def resolve_timeout(
    parser: argparse.ArgumentParser,
    cli_value: float | None,
    env_name: str,
    default: float,
) -> float:
    """Resolve one budget as CLI -> env -> default.

    A malformed env value is a usage error (exit 2), not a silent fall back to
    the default: `EVAL_TURN_TIMEOUT_SECONDS=abc` must not run the suite at
    1,800 s while the operator believes it is running at something else.
    """
    if cli_value is not None:
        return cli_value
    raw = os.environ.get(env_name)
    if not raw:
        return default
    try:
        return positive_timeout(raw)
    except argparse.ArgumentTypeError as exc:
        parser.error(f"{env_name}: {exc}")


def usage_error(message: str) -> NoReturn:
    """Stop with argparse's own exit code 2: bad input, and **nothing ran**.

    Some refusals can only be made after `git` and the artifact root are read,
    which is past `parse_args()`. The meaning of the exit code must not change
    because the check moved.
    """
    print(f"{Path(sys.argv[0]).name}: error: {message}", file=sys.stderr)
    raise SystemExit(2)


def safe_message(exc: BaseException) -> str:
    """Describe a failure without letting a DSN or a credential out."""
    text = " ".join(str(exc).split())[:300]
    for marker in ("://", "password", "@"):
        if marker in text:
            return type(exc).__name__
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def new_run_id(environ: Mapping[str, str] | None = None) -> str:
    """The run id of a lane-driven run, honouring the `RUN_ID` the Makefile exports.

    Args:
        environ: The environment to read; defaults to the process environment.

    Returns:
        `RUN_ID` when the caller exported one, otherwise a timestamped id.
    """
    source = os.environ if environ is None else environ
    return source.get("RUN_ID") or timestamped_run_id()


def timestamped_run_id() -> str:
    """A run id whose lexicographic order is chronological order.

    **`RUN_ID` is deliberately not honoured here.** The attempt scan
    orders past records by directory name instead of reading a clock, so one
    caller exporting a differently shaped id would silently reorder the chain.
    """
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


def repository_state() -> tuple[str, bool]:
    """The commit every attempt of a run is keyed by, and whether it is dirty.

    Resolved through `git` rather than guessed. An unresolvable checkout stops
    the run: writing `commit_sha: null` would produce an artifact that belongs
    to no HEAD and therefore chains to nothing.

    Returns:
        `(commit_sha, tree_dirty)`.

    Raises:
        RuntimeError: The checkout's state cannot be resolved.
    """
    root = str(REPOSITORY_ROOT)
    try:
        head = subprocess.run(
            ["git", "-C", root, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        status = subprocess.run(
            ["git", "-C", root, "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "cannot resolve the repository state the attempt chain is keyed by"
        ) from exc
    commit_sha = head.stdout.strip()
    if not commit_sha:
        raise RuntimeError("git rev-parse HEAD produced no commit")
    return commit_sha, bool(status.stdout.strip())
