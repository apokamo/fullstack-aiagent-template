"""profile ごとの model と HTTP client を所有する factory."""

from collections.abc import Callable
from contextvars import ContextVar
import os
import threading
from typing import TYPE_CHECKING, cast

import httpx
from openai import AsyncOpenAI
from pydantic_ai.models import Model, create_async_http_client
from pydantic_ai.models.openai import (
    OpenAIChatModel,
    OpenAIChatModelSettings,
    OpenAIResponsesModel,
)
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider

from apps.api.agent.responses import UnsupportedApiMode, build_responses_model_settings
from apps.api.core.config import get_llm_settings
from apps.api.core.llm_profiles import (
    API_MODE_CHAT_COMPLETIONS,
    API_MODE_RESPONSES,
    ChatProfile,
    resolve_credential,
    resolve_profile,
)
from apps.api.core.logging import get_logger

if TYPE_CHECKING:
    from openai.types.shared.reasoning_effort import ReasoningEffort

logger = get_logger(__name__)

#: `AGENT_MODEL_MODE=fake` のときに model を組む関数。
#:
#: **共通側は fake の実体を知らない。** fake モデルは用途のツール契約に依存する。
#: 共通 factory は用途を import せず、用途の lifecycle から builder を受け取る。
#: 用途の lifecycle が `ModelFactory(fake_model=...)` で渡す。
FakeModelBuilder = Callable[[ChatProfile], Model]

# pydantic-ai 2.31.0 は GPT-6 をまだ profile 判定に含めない。モデル名だけを
# 切り替えると Responses の reasoning.context と暗号化 reasoning の include が
# wire から消えるため、OpenAI 公式仕様で確認できる能力をこの profile に固定する。
GPT6_LUNA_MODEL_PROFILE = OpenAIModelProfile(
    supports_thinking=True,
    openai_supports_reasoning=True,
    openai_supports_encrypted_reasoning_content=True,
    openai_reasoning_enabled_by_default=True,
    openai_supports_reasoning_effort_none=True,
    openai_supports_phase=True,
)


def _model_profile(spec: ChatProfile) -> OpenAIModelProfile | None:
    return GPT6_LUNA_MODEL_PROFILE if spec.model == "gpt-6-luna" else None


class MissingFakeModel(RuntimeError):
    """`AGENT_MODEL_MODE=fake` なのに用途が fake を渡していない.

    **実 provider へ落とさない。** 落とすと「fake のつもりで実 API を叩く」
    経路になるので、組み立ての時点で見える失敗として止める。
    """


# 1 request の transport 予算のうち、**stall 以外の 3 phase**。
# 値は pydantic-ai の `create_async_http_client()` が現在作る
# `httpx.Timeout(timeout=600, connect=5)` と同一で、名前を与えるだけである。
# 決まったのは「無着信の継続時間」＝ read だけなので、ここを動かすと人が決めて
# いない本番 policy を変えることになる。env にしないのも同じ理由。
AGENT_REQUEST_CONNECT_TIMEOUT_SECONDS = 5.0
AGENT_REQUEST_WRITE_TIMEOUT_SECONDS = 600.0
AGENT_REQUEST_POOL_TIMEOUT_SECONDS = 600.0


def build_http_client() -> httpx.AsyncClient:
    """pydantic-ai と同じ HTTP client を作り、timeout の 4 値だけを明示する.

    factory を経由するのは transport library（`httpx`）と `User-Agent` を pydantic-ai
    既定のままに保つためである。`AsyncOpenAI` に `http_client` を渡さないと openai が
    自前の `httpx2` client を作り、両方が黙って入れ替わる。

    `create_async_http_client(timeout=...)` は使わない —— あの引数は
    read / write / pool をまとめて動かすので、決まっていない write / pool の
    予算まで変えてしまう。

    Returns:
        timeout を明示した client。閉じるのは `ModelFactory.aclose()`。
    """
    client = create_async_http_client()
    client.timeout = httpx.Timeout(
        connect=AGENT_REQUEST_CONNECT_TIMEOUT_SECONDS,
        read=get_llm_settings().agent_request_stall_timeout_seconds,
        write=AGENT_REQUEST_WRITE_TIMEOUT_SECONDS,
        pool=AGENT_REQUEST_POOL_TIMEOUT_SECONDS,
    )
    return client


def resolve_build_profile(profile: ChatProfile | str | None) -> ChatProfile:
    """`ModelFactory.build()` の引数を profile 定義へ正規化する.

    Args:
        profile: `None` なら起動 profile（`LLM_PROFILE`）。`str` は registry で
            解決する。`ChatProfile` はそのまま使う。

    Returns:
        解決済み profile。

    Raises:
        UnknownProfile: `str` が registry に無い値だった場合。
    """
    if profile is None:
        return get_llm_settings().llm_profile_spec
    if isinstance(profile, str):
        return resolve_profile(profile)
    return profile


def build_openai_provider(
    spec: ChatProfile, http_client: httpx.AsyncClient | None = None
) -> OpenAIProvider:
    """profile 1 個ぶんの client を組む（API mode で 1 バイトも変わらない）.

    Chat / Responses のどちらでも transport・timeout・retry・credential 解決は
    同じである。**変わるのは model 型と settings だけ**なので、この
    factory を共有して cache key も profile 単位のまま保つ。

    Args:
        spec: 解決済み profile。
        http_client: 差し替える HTTP client。決定的 test が自分の transport で
            provider へ送る wire を観測するために渡す。`None` なら
            `build_http_client()` が作る。**共有 client や SDK の method を
            monkeypatch する経路は作らない。**

    Returns:
        その profile の provider。
    """
    client = build_http_client() if http_client is None else http_client
    return OpenAIProvider(
        openai_client=AsyncOpenAI(
            base_url=spec.base_url,
            # **選択中 provider の credential だけ**を解決する。`auth="none"` の
            # provider では environ を 1 度も読まないので、DS4 profile へ
            # OpenAI key が渡る経路は存在しない。
            api_key=resolve_credential(spec, os.environ),
            max_retries=get_llm_settings().agent_request_max_retries,
            # openai 3.1.0 の型は `httpx2.AsyncClient` を宣言するが、実行時は
            # duck typing で `httpx` の client を受ける。pydantic-ai 自身も
            # `_create_openai_client()` で `httpx.AsyncClient` を渡している。
            http_client=client,  # type: ignore[arg-type]
        )
    )


def create_model(
    spec: ChatProfile,
    http_client: httpx.AsyncClient | None = None,
    *,
    fake_model: FakeModelBuilder | None = None,
) -> Model:
    """profile 1 個ぶんの model を実際に組み立てる（cache を見ない）.

    **API mode で明示分岐する**。未知 API mode は失敗させ、Chat へは
    落とさない —— 落とすと artifact の identity と実際の wire がずれた run が
    生まれる。

    Args:
        spec: 解決済み profile。
        http_client: 差し替える HTTP client（wire を観測する test だけが渡す）。
        fake_model: `AGENT_MODEL_MODE=fake` のときに使う用途の builder。

    Returns:
        組み立てた model。

    Raises:
        MissingFakeModel: fake mode なのに `fake_model` が無い場合。
        UnsupportedApiMode: profile の `api_mode` が registry の許容集合に無い場合。
    """
    if get_llm_settings().agent_model_mode == "fake":
        if fake_model is None:
            raise MissingFakeModel(
                "AGENT_MODEL_MODE=fake ですが、用途が fake モデルを渡していません"
                "（ModelFactory(fake_model=...) / 用途の lifecycle を参照）。"
            )
        return fake_model(spec)

    if spec.api_mode == API_MODE_RESPONSES:
        # `store=false` / reasoning item 再送 / `reasoning.context` の固定は
        # `agent/responses.py` が 1 か所で持つ（preflight と artifact も同じ値を読む）。
        return OpenAIResponsesModel(
            spec.model,
            provider=build_openai_provider(spec, http_client),
            profile=_model_profile(spec),
            settings=build_responses_model_settings(spec),
        )

    if spec.api_mode != API_MODE_CHAT_COMPLETIONS:
        raise UnsupportedApiMode(
            f"profile {spec.profile} の api_mode を model factory が知りません"
        )

    # profile が reasoning effort を持つときだけ key を足す。
    # `ModelSettings` も `OpenAIChatModelSettings` も `TypedDict` なので、
    # effort を持たない profile では **dict に effort の key が載らない**。
    # pydantic-ai は未設定を `OMIT` に写す（`models/openai.py:1039-1050`）ため、
    # provider へ送る request body にも reasoning effort の field が載らない。
    model_settings = OpenAIChatModelSettings(
        max_tokens=get_llm_settings().agent_request_max_output_tokens
    )
    effort = spec.reasoning_effort
    if effort is not None:
        # registry は stdlib しか import しないので effort は `str` で持つ。
        # 値が SDK の `ReasoningEffort` 集合に収まることは、`ALLOWED_REASONING_EFFORTS`
        # と SDK の Literal の完全一致を突き合わせる registry invariant test
        # （`test_llm_profiles.py`）が決定的 lane で固定している。
        model_settings["openai_reasoning_effort"] = cast("ReasoningEffort", effort)

    return OpenAIChatModel(
        spec.model,
        # `OpenAIProvider` に `max_retries` を渡す口が無いので、`AsyncOpenAI` を
        # 自分で組んで渡す。
        provider=build_openai_provider(spec, http_client),
        profile=_model_profile(spec),
        settings=model_settings,
    )


class ModelFactory:
    """profile ごとの model を 1 個ずつ持ち、まとめて閉じる cache の所有者.

    **instance ごとに独立した cache である**。同じ profile を
    2 つの factory から組めば model は 2 個できる。`AgentRuntime` はこの
    instance を 1 個所有し、shutdown で `aclose()` する。

    **`lru_cache` を使わない。** 格納した値を列挙する API が無く、
    「作成済みの client をすべて閉じる」を実装できないためである。
    """

    def __init__(self, *, fake_model: FakeModelBuilder | None = None) -> None:
        """空の cache と、その get-or-create を囲む lock を作る.

        Args:
            fake_model: `AGENT_MODEL_MODE=fake` のときに model を組む関数。用途の
                lifecycle が自分の fake を渡す。`None` のまま fake mode で
                `build()` すると `MissingFakeModel` になる —— 実 provider へは
                落とさない。
        """
        #: 用途が渡した fake builder（fake mode 以外では読まれない）。
        self._fake_model = fake_model
        #: profile id → 組み立て済み model。
        self._cache: dict[str, Model] = {}
        #: `build()` は await を持たない同期 method なので event loop 内では
        #: interleave しないが、threadpool から呼ばれても同じ profile の client を
        #: 2 個作らないようにする（同 profile の競合生成を直列化するため）。
        self._lock = threading.Lock()

    def build(
        self,
        profile: ChatProfile | str | None = None,
        *,
        fake_model: FakeModelBuilder | None = None,
    ) -> Model:
        """profile が決めるモデルを組み立てる（**profile ごとに**この factory で 1 個）."""
        spec = resolve_build_profile(profile)
        builder = self._fake_model if fake_model is None else fake_model
        key = (
            spec.profile
            if fake_model is None
            else f"{spec.profile}#{fake_model.__name__}"
        )
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            model = create_model(spec, fake_model=builder)
            self._cache[key] = model
            return model

    def cached_profiles(self) -> tuple[str, ...]:
        """cache に載っている profile id（決定的 test と fixture が読む）.

        Returns:
            作成済み model の profile id。作成順ではなく dict の挿入順。
        """
        with self._lock:
            return tuple(self._cache)

    def clear(self) -> None:
        """**client を閉じずに** cache だけを空にする（同期の後始末用）.

        `lru_cache.cache_clear()` の置き換えで、決定的 test と fixture が
        「次の build を作り直させる」ためだけに使う。**client を閉じる必要がある
        経路は `aclose()` を使うこと。**
        """
        with self._lock:
            self._cache.clear()

    async def aclose(self) -> None:
        """この factory が抱えている HTTP client を**すべて**閉じる."""
        with self._lock:
            models = list(self._cache.items())
            self._cache.clear()

        failures: list[Exception] = []
        for profile_id, model in models:
            # **Chat / Responses の両方を閉じる**。片方だけを閉じる実装だと、
            # 画面から切り替えた分の client がプロセス終了まで残る。
            if not isinstance(model, OpenAIChatModel | OpenAIResponsesModel):
                continue
            try:
                await model.client.close()
            except Exception as exc:  # 後始末は 1 個の失敗で止めない
                logger.warning(
                    "model_client_close_failed",
                    profile=profile_id,
                    error_type=type(exc).__name__,
                )
                failures.append(exc)

        if failures:
            # **全部試し終えてから上げる。** 先に上げると残りの client が閉じない。
            raise ExceptionGroup("model client close failed", failures)


#: runtime を持たない経路（決定的 test、script）が使う既定 factory。
#:
#: **これは「所有者が居ないときの置き場」であって、共有 cache の設計ではない。**
#: `AgentRuntime` は `install_model_factory()` で自分の factory を**自分の
#: 実行 context へ**差し込む。だからその runtime の中で `current_model_factory()`
#: が返すのはその runtime の factory であり、runtime 間で cache は混ざらない。
_DEFAULT_FACTORY = ModelFactory()

#: いま有効な factory。`install_model_factory()` だけが書き換える。
#:
#: **process global ではなく `ContextVar` である**。
#: module 変数に「前の値を返して呼び出し側が戻す」方式だと、退出順が LIFO の
#: ときしか正しくない。2 つの runtime が重なって A → B の順に起き A → B の順に
#: 退出すると、A の退出が B の factory を **A より前の値へ**戻し、B の退出が
#: 終了済みの A を current に残す。`ContextVar` なら差し込みは差し込んだ task の
#: context に閉じるので、重なった runtime は互いの cache を上書きしない。
_CURRENT_FACTORY: ContextVar[ModelFactory] = ContextVar(
    "current_model_factory", default=_DEFAULT_FACTORY
)


def current_model_factory() -> ModelFactory:
    """いま有効な factory を返す.

    Returns:
        `install_model_factory()` が差し込んだ factory。runtime の外では既定 factory。
    """
    return _CURRENT_FACTORY.get()


def install_model_factory(factory: ModelFactory) -> ModelFactory:
    """factory を差し込み、**差し込む前のもの**を返す（呼び出し側が戻す）.

    `AgentRuntime` が `__aenter__` / `__aexit__` の対で使う。

    **差し込みは呼び出した実行 context に閉じる。** `ContextVar.set()` は
    その context だけを書き換え、`asyncio.Task` は生成時に context を複製する
    ので、同時に起きている別 task の runtime へは伝わらない。入れ子の runtime は
    これまでどおり前の値で元へ戻る。

    **request 経路はこれを読まない。** Starlette の request handler は lifespan と
    は別の task context で走るので、lifespan で差し込んだ値は router からは
    見えない。`create_app()` が起動済み runtime を `app.state` へ結び、
    `apps/api/core/runtime_scope.py` の `runtime_of(request)` がその所有者を返す
    （既定 factory へ落とさない）。

    Args:
        factory: 差し込む factory。

    Returns:
        差し込む前に有効だった factory。
    """
    previous = _CURRENT_FACTORY.get()
    _CURRENT_FACTORY.set(factory)
    return previous


# ------------------------------------------------------------------------------
# module 関数としての委譲
#
# どの関数も `current_model_factory()` が返す factory に委譲する。
# `AgentRuntime` が起きている間はその runtime の factory なので、runtime 間で
# cache は混ざらない（`agent/runtime.py`）。
# ------------------------------------------------------------------------------


def build_model(profile: ChatProfile | str | None = None) -> Model:
    """いま有効な factory から profile の model を得る（profile ごとに 1 個）.

    Args:
        profile: 使う profile。`None` は起動 profile。`str` は registry で解決する。

    Returns:
        その profile の model（同じ factory・同じ profile なら同一 instance）。

    Raises:
        UnknownProfile: `str` が registry に無い値だった場合。
        MissingCredential: 選択中 provider の credential が欠落していた場合。
    """
    return current_model_factory().build(profile)


def cached_model_profiles() -> tuple[str, ...]:
    """いま有効な factory の cache に載っている profile id.

    Returns:
        作成済み model の profile id。
    """
    return current_model_factory().cached_profiles()


def clear_model_cache() -> None:
    """**client を閉じずに** cache だけを空にする（同期の後始末用）."""
    current_model_factory().clear()


async def aclose_model() -> None:
    """いま有効な factory が抱えている HTTP client を**すべて**閉じる.

    呼ぶ経路は 3 つある —— `apps/api/application.py` の lifespan（process 1 個）、
    `agent/evals/runner.py` の run 単位、`apps/api/tests/test_sample_agent_llm.py` の実 LLM
    テスト単位。`AgentRuntime` の shutdown も同じ factory を閉じるので、
    2 度呼んでも 2 度目は何もしない。
    """
    await current_model_factory().aclose()
