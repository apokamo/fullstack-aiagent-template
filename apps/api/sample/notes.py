"""`save_note` の書き込み先と、その差し替え口."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Note:
    """書き留めた 1 件."""

    title: str
    body: str


class NoteSink(Protocol):
    """note の書き込み先. fork 先はこの Protocol を実装して差し替える."""

    def save(self, note: Note) -> None:
        """`note` を書き込む."""
        ...


@dataclass
class InMemoryNoteStore:
    """プロセスのメモリに貯める既定の実装（run-local）.

    テストからは `notes` をそのまま読んで「シンクが呼ばれた事実」を確かめる。
    """

    notes: list[Note] = field(default_factory=list)

    def save(self, note: Note) -> None:
        """受け取った note をリストの末尾に足す."""
        self.notes.append(note)
