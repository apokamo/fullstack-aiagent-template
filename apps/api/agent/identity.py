"""選択した LLM profile の identity を 1 か所から記録する."""

from apps.api.core.config import get_llm_settings
from apps.api.core.llm_profiles import ChatProfile, identity_fields
from apps.api.core.logging import get_logger


def log_llm_identity(
    spec: ChatProfile | None = None, *, echo: bool = False, **extra: str
) -> dict[str, str]:
    """profile identity を 1 回記録し、記録した mapping を返す.

    **出力の正本はこの 1 関数だけである。** 起動時の logだけを
    変えると、FastAPI lifespan を通らない eval runner と `make test-llm` の log に
    identity が残らない —— とくに artifact を 1 件も書けずに終わった run で証跡が
    消える。起動時の呼び出し点は 2 つある。API の lifespan と `make test-llm` は
    `apps/api/sample/lifecycle.py` の `agent_runtime()` 先頭で、eval runner
    （`make evals` と `make evals-observe`）は provider preflight の直前で呼ぶ。
    runner が `agent_runtime()` に任せないのは、preflight が `agent_runtime()`
    **より前**に走り、最初の provider request が identity log より前になるため
    である。

    **credential は 1 field も載せない。** `base_url` は `safe_url()` 済みで
    userinfo と query を持たない。

    **7 軸は構造化 logger の key として渡す。** 標準 logging の `extra=` で渡すと、
    `configure_logging()` が敷く formatter が `%(message)s` なので、出力へ届くのは
    `llm_identity` という event 名だけになり 7 軸が丸ごと落ちる。
    `get_logger()` は毎回取り直す —— structlog は
    `cache_logger_on_first_use=True` で bind 済み logger を module 変数に固定する
    ので、module 読み込みが `configure_logging()` より前に来る経路（eval runner と
    実 LLM test）で古い設定のまま焼き付く。

    **request 単位でも同じ 1 関数から出す**。chat router は
    その request が解決した profile を `spec` で渡し、相関のための `request_id` を
    `extra` で足す。**`extra` に credential を渡さない** —— 呼び出し側が渡せる
    のは相関 id のような非秘密の短い文字列だけで、`identity_fields()` が返す 7 軸を
    上書きすることもできない（衝突は `TypeError` になる）。

    Args:
        spec: 記録する profile。`None` は起動 profile（`LLM_PROFILE`）。
        echo: `True` なら同じ内容を `key=value` 1 行で stdout へも出す。lane
            wrapper が child の stdout を捕捉するので、lane record を残せずに
            終わった run でも `test-artifacts/logs/<lane>/<RUN_ID>.log` に
            identity が残る。
        **extra: identity 7 軸に足す非秘密の相関 field（`request_id` など）。

    Returns:
        `profile` / `provider` / `model` / `protocol` / `api_mode` / `base_url` /
        `reasoning_effort` の 7 field に `extra` を足したもの。`reasoning_effort` は
        未指定 profile では `"unset"` で、`"none"` と同じ値にはならない。
        返り値を持つのは決定的 test が field 集合と非露出を直接固定できるように
        するためである。

    Raises:
        TypeError: `extra` が identity 7 軸と同じ key を使った場合。
    """
    fields = identity_fields(
        get_llm_settings().llm_profile_spec if spec is None else spec
    )
    collision = sorted(set(fields) & set(extra))
    if collision:
        raise TypeError(f"identity 軸を extra で上書きできません: {collision}")
    fields.update(extra)
    get_logger(__name__).info("llm_identity", **fields)
    if echo:
        print("llm_identity " + " ".join(f"{k}={v}" for k, v in fields.items()))
    return fields
