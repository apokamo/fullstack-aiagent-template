"""サンプルのエージェント定義（共通 chat router へ渡す `AgentDefinition`）."""

from typing import Any

from apps.api.agent.definition import AgentDefinition, TurnContext
from apps.api.sample.agent import (
    SAMPLE_TOOLS,
    agent,
    default_sample_deps,
    sample_turn_usage_limits,
)


def sample_new_turn(
    execution: Any = None,  # noqa: ARG001 - 実行構成で分岐しないので読まない
) -> TurnContext:
    """1 run ぶんの deps を作る（`new_turn`）.

    **run ごとに新しく作ることが契約である。** `InMemoryNoteStore` を使い回すと、
    承認済みのメモが次の run から見えてしまう（`notes.py` の run-local 契約）。

    `execution` は使わない。**引数を受け取る形は残す** —— 共通 chat は
    `new_turn(execution)` を呼ぶので、ここで signature を削ると呼び出し側が
    定義ごとに分岐することになる。

    Args:
        execution: 解決済み実行構成。サンプルでは profile がそのまま渡る。

    Returns:
        run スコープの `TurnContext`（`output_type` と `decorate` は既定）。
    """
    return TurnContext(deps=default_sample_deps())


def sample_agent_definition() -> AgentDefinition:
    """サンプルのエージェント定義（`AgentDefinition[Deps]`）.

    Returns:
        `search_docs` / `save_note` を登録済みの agent、turn 予算
        （tool=3 / request=5）、run スコープの turn factory。
    """
    return AgentDefinition(
        agent=agent,
        approvals=SAMPLE_TOOLS,
        usage_limits=sample_turn_usage_limits,
        new_turn=sample_new_turn,
    )
