"""サンプル agent が引く同梱文書と、その差し替え口."""

from dataclasses import dataclass
import re
from typing import Protocol

# 検索スコアの下限。これを超えるヒットが 1 件でもあれば「十分」と見なす
# （`search_docs` が返す `sufficient` の判定に使う）。素朴な語の重なり率なので、
# 1 語でも一致すれば 0 より大きくなる。
_SUFFICIENT_SCORE = 0.15

# 検索語として無視する語。日本語は形態素解析を持ち込まないので、
# 助詞レベルの除去はせず「1 文字の語を落とす」だけに留める。
_STOPWORDS = frozenset({"the", "a", "an", "of", "to", "is", "for", "and", "in"})


@dataclass(frozen=True)
class Document:
    """検索対象の 1 件."""

    doc_id: str
    title: str
    text: str


@dataclass(frozen=True)
class Hit:
    """検索結果の 1 件（スコア付き）."""

    doc_id: str
    title: str
    text: str
    score: float


class SearchSource(Protocol):
    """検索の供給元. fork 先はこの Protocol を実装して差し替える."""

    def search(self, query: str, limit: int) -> list[Hit]:
        """`query` に一致する文書をスコア降順で最大 `limit` 件返す."""
        ...


def _tokenize(text: str) -> list[str]:
    """英数字と日本語をまとめて素朴に分割する.

    形態素解析は持ち込まない（テンプレートの見本にその重さは要らない）。
    英数字は語単位、それ以外（日本語など）は 2-gram に落として重なりを取る。
    """
    lowered = text.lower()
    words = [w for w in re.findall(r"[a-z0-9_]+", lowered) if w not in _STOPWORDS]
    cjk = re.sub(r"[a-z0-9_\s]+", " ", lowered)
    bigrams = [
        chunk[i : i + 2]
        for chunk in cjk.split()
        for i in range(max(len(chunk) - 1, 1))
        if len(chunk[i : i + 2]) == 2
    ]
    return [t for t in [*words, *bigrams] if len(t) > 1]


def _score(query_tokens: list[str], document: Document) -> float:
    """query の語が文書にどれだけ含まれるかの割合（0.0〜1.0）."""
    if not query_tokens:
        return 0.0
    haystack = set(_tokenize(f"{document.title} {document.text}"))
    matched = sum(1 for token in set(query_tokens) if token in haystack)
    return matched / len(set(query_tokens))


class InMemorySearchSource:
    """モジュール内の固定コーパスを検索する既定の実装."""

    def __init__(self, documents: tuple[Document, ...]) -> None:
        self._documents = documents

    def search(self, query: str, limit: int) -> list[Hit]:
        """語の重なり率で採点し、スコア降順（同点は doc_id 順）で返す."""
        query_tokens = _tokenize(query)
        scored = [
            Hit(
                doc_id=document.doc_id,
                title=document.title,
                text=document.text,
                score=_score(query_tokens, document),
            )
            for document in self._documents
        ]
        hits = [hit for hit in scored if hit.score > 0]
        hits.sort(key=lambda hit: (-hit.score, hit.doc_id))
        return hits[:limit]


def is_sufficient(hits: list[Hit]) -> bool:
    """「これ以上検索しても得るものが無い」と言い切れるか."""
    return any(hit.score >= _SUFFICIENT_SCORE for hit in hits)


# テンプレート同梱の見本コーパス。このリポジトリ自身の決めごとを数件だけ持つ。
DEFAULT_CORPUS: tuple[Document, ...] = (
    Document(
        doc_id="testing-tiers",
        title="テストの tier",
        text=(
            "テストは small / medium / large の 3 tier に分類する。"
            "small はネットワーク・DB・filesystem を使わない。"
            "medium は localhost の DB や filesystem を使う。"
            "large は制限なし。実 LLM への疎通確認は llm marker を付け、"
            "make test-llm でのみ実行する。"
        ),
    ),
    Document(
        doc_id="agent-loop",
        title="agent loop の構成",
        text=(
            "agent loop は Pydantic AI を使い、SSE は AI SDK の "
            "UI Message Stream 語彙で流す。FastAPI 側は VercelAIAdapter の "
            "dispatch_request が担当し、フロントは useChat が受け取る。"
        ),
    ),
    Document(
        doc_id="tool-call-limit",
        title="ツール呼び出しの上限",
        text=(
            "モデルが同じ検索を繰り返す冗長呼び出しを防ぐため、"
            "1 回の run で呼べるツール数に上限を設けている。"
            "ツールの結果には十分かどうかのシグナルを載せ、"
            "再検索が不要であることをモデルに伝える。"
        ),
    ),
    Document(
        doc_id="error-contract",
        title="エラー契約",
        text=(
            "API のエラー応答は RFC 9457 互換の形式で返す。"
            "どのステータスでも CORS ヘッダ・セキュリティヘッダ・"
            "X-Request-ID が必ず付く。"
        ),
    ),
    Document(
        doc_id="environment",
        title="環境変数の置き場",
        text=(
            "秘密値と API の実行時設定は secrets/*.env に置く。"
            "ホスト実行時の差分は secrets/*.host.env が上書きする。"
            ".env には秘密でもコンテナ設定でもないものだけを置く。"
        ),
    ),
    Document(
        doc_id="quality-gate",
        title="品質ゲート",
        text=(
            "PR を作る前に lane record を確認し、同じ clean HEAD の成功記録を"
            "引用できないときだけ make check-all を実行する。"
            "backend は lint・format・型チェックとテスト、"
            "frontend は eslint・tsc・vitest が走る。"
        ),
    ),
)


def default_search_source() -> InMemorySearchSource:
    """既定の検索供給元（テンプレート同梱コーパス）を返す."""
    return InMemorySearchSource(DEFAULT_CORPUS)
