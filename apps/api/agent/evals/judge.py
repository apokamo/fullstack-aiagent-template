"""Judge protocol and a scripted test double.

The real client lives in `judge_client.py`.
"""

from typing import Protocol

from apps.api.agent.evals.grading import JudgeInput, JudgeResult


class JudgeClient(Protocol):
    async def grade(self, value: JudgeInput) -> JudgeResult:
        """Grade a saved conversation, independently of the generating model."""
        ...


class FakeJudge:
    """Consume explicitly scripted responses, without constructing a provider."""

    def __init__(self, responses: tuple[JudgeResult | Exception, ...]) -> None:
        self.responses = iter(responses)
        self.inputs: list[JudgeInput] = []

    async def grade(self, value: JudgeInput) -> JudgeResult:
        self.inputs.append(value)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response
