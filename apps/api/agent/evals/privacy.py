"""Evaluation-only filtering; removed required evidence is never sent to a judge."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from apps.api.agent.evals.evidence import canonical_bytes

URL = re.compile(r"(?:https?|postgres(?:ql)?(?:\+[a-z]+)?)://[^\s\"'<>]+", re.I)
AUTH = re.compile(
    r"(?:bearer\s+\S+|sk-[A-Za-z0-9_-]{8,}|(?:password|api[_-]?key|authorization)\s*[=:]\s*[^\s,;]+)",
    re.I,
)


@dataclass(frozen=True)
class PrivacyFilter:
    secrets: tuple[str, ...] = ()
    names: tuple[str, ...] = ()

    def text(self, value: str) -> tuple[str, bool]:
        clean = value
        for token in sorted(set(self.secrets + self.names), key=len, reverse=True):
            if token:
                clean = clean.replace(token, "[excluded]")
        clean = AUTH.sub("[excluded]", URL.sub("[excluded]", clean))
        return clean, clean != value

    def json(self, value: Any) -> tuple[str, bool]:
        return self.text(canonical_bytes(value).decode())
