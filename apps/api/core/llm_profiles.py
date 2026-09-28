"""Chat profile registry と厳密 resolver."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from collections.abc import Mapping

#: 現在 registry が持つ唯一の protocol。artifact / log の identity 軸として
#: 別 field に出す（`api_mode` と混同しない）。
PROTOCOL_OPENAI_COMPATIBLE: Final = "openai-compatible"

#: OpenAI 互換の `/chat/completions` を使う API mode。`--compare-candidate` でも
#: api_mode の相違は許さない——これは Responses 追加後も変わらない。
API_MODE_CHAT_COMPLETIONS: Final = "chat-completions"

#: OpenAI の `/responses` を使う API mode。**Chat の置換ではない。**
#: 同じ provider・同じ model でも request/response の形と reasoning の運び方が別なので、
#: profile を分けて別 identity にする。実行時に一方から他方へ落ちる経路は作らない。
API_MODE_RESPONSES: Final = "responses"

#: registry が持てる API mode の集合。**未知値は失敗させる**ための正本で、
#: model factory・preflight・artifact の分岐はすべてこの集合を基準に書く。
ALLOWED_API_MODES: Final[frozenset[str]] = frozenset(
    {API_MODE_CHAT_COMPLETIONS, API_MODE_RESPONSES}
)

#: auth 不要 provider へ渡す内部 placeholder。
#: **env から読む値ではない。** DS4 は認証不要だが OpenAI SDK が非空値を要求する
#: ため、registry 側が固定値を持つ。実 OpenAI key が process に居ても、DS4 profile
#: では environ を 1 度も読まずにこの値が渡る。
INTERNAL_PLACEHOLDER_API_KEY: Final = "unused"

#: profile id に許す綴り。artifact の path 片として使うため、traversal も
#: case 差も生まない集合に限る。
PROFILE_ID_PATTERN: Final = r"^[a-z0-9][a-z0-9-]{0,63}$"

#: `reasoning_effort` が未指定（= request の field 自体を送らない）であることの
#: **表示値**。`"none"`（= `reasoning_effort=none` を送る）と
#: 必ず別値でなければならない。registry invariant test がこの区別を固定する。
REASONING_EFFORT_UNSET_DISPLAY: Final = "unset"

#: profile が持てる reasoning effort の集合。`openai.types.shared.reasoning_effort.
#: ReasoningEffort` の Literal 集合と**完全一致**する（registry は stdlib 縛りなので
#: 値を写し、突合は test 側だけが openai を import して行う）。
ALLOWED_REASONING_EFFORTS: Final[frozenset[str]] = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)


class UnknownProfile(ValueError):
    """`LLM_PROFILE` が registry に無い値だった."""


class MissingCredential(ValueError):
    """選択中 provider の credential が欠落・空・placeholder だった."""


@dataclass(frozen=True)
class ProviderDefinition:
    """provider（固有名詞）の auth 方式と credential env 名だけを持つ."""

    name: str
    auth: Literal["none", "api-key"]
    credential_env: str | None


@dataclass(frozen=True)
class ChatProfile:
    """profile 1 個が決める実行構成の全軸."""

    profile: str
    provider: str
    model: str
    protocol: str
    api_mode: str
    base_url: str
    reasoning_effort: str | None = None
    label: str = ""


PROVIDERS: Final[Mapping[str, ProviderDefinition]] = MappingProxyType(
    {
        # DS4 は現在認証不要。認証が必要になれば専用の credential を定義する。
        "DS4": ProviderDefinition(name="DS4", auth="none", credential_env=None),
        "OpenAI": ProviderDefinition(
            name="OpenAI", auth="api-key", credential_env="OPENAI_API_KEY"
        ),
    }
)

PROFILES: Final[Mapping[str, ChatProfile]] = MappingProxyType(
    {
        "ds4-deepseek-v4-flash-chat": ChatProfile(
            profile="ds4-deepseek-v4-flash-chat",
            provider="DS4",
            model="deepseek-v4-flash",
            protocol=PROTOCOL_OPENAI_COMPATIBLE,
            api_mode=API_MODE_CHAT_COMPLETIONS,
            base_url="http://127.0.0.1:8787/v1",
            label="DeepSeek V4 Flash",
        ),
        "openai-luna-chat": ChatProfile(
            profile="openai-luna-chat",
            provider="OpenAI",
            model="gpt-6-luna",
            protocol=PROTOCOL_OPENAI_COMPATIBLE,
            api_mode=API_MODE_CHAT_COMPLETIONS,
            base_url="https://api.openai.com/v1",
            # GPT-6 Luna の Chat Completions function calling は
            # `reasoning_effort=none` の場合だけ対応する（OpenAI 公式 model
            # guide）。Responses は別 profile で `low` を使う。
            reasoning_effort="none",
            label="GPT-6 Luna（Chat）",
        ),
        "openai-luna-responses": ChatProfile(
            profile="openai-luna-responses",
            provider="OpenAI",
            model="gpt-6-luna",
            protocol=PROTOCOL_OPENAI_COMPATIBLE,
            api_mode=API_MODE_RESPONSES,
            base_url="https://api.openai.com/v1",
            # Responses profile の reasoning effort は low に固定する。
            reasoning_effort="low",
            label="GPT-6 Luna（Responses）",
        ),
    }
)


@dataclass(frozen=True)
class ModelPrice:
    """1M token あたりの USD 単価（eval の費用上限の見積りと実費の計算用）."""

    input_usd_per_million: float
    output_usd_per_million: float


#: model id ごとの単価。**profile や judge profile が使う model はすべて載せる**
#: （未掲載の model では eval が費用上限を守れないので、実行前に止める）。
#: 値は provider の公開価格表の標準料金（short context）で、reasoning token は
#: output に含まれる。価格改定や model の追加のときは価格表を確認して更新する。
MODEL_PRICES: Final[Mapping[str, ModelPrice]] = MappingProxyType(
    {
        # DS4 は手元で動かす推論サーバなので従量課金は無い。
        "deepseek-v4-flash": ModelPrice(0.0, 0.0),
        # OpenAI API pricing（2026-09-24 確認）: input $0.10 / output $0.50。
        "gpt-6-luna": ModelPrice(0.10, 0.50),
    }
)


class UnknownPrice(ValueError):
    """model の単価が `MODEL_PRICES` に無い."""


def model_price(model: str) -> ModelPrice:
    """model id の単価を返す。未掲載なら推測せず送出する.

    Raises:
        UnknownPrice: `MODEL_PRICES` に無い model の場合。
    """
    price = MODEL_PRICES.get(model)
    if price is None:
        raise UnknownPrice(
            f"model {model} の単価が MODEL_PRICES にありません。"
            "費用上限を守れないので eval を実行できません。"
        )
    return price


@dataclass(frozen=True)
class JudgeProfile:
    """LLM ジャッジ 1 個の実行構成.

    **agent の profile とは別の registry に置く。** ジャッジを agent と同じ
    `LLM_PROFILE` から選ぶと、生成側の切り替えが採点側まで動かし、同じ観測の
    採点結果が比較できなくなる。ジャッジは Responses API の構造化出力だけを使う
    ので、`api_mode` は持たない。
    """

    profile: str
    provider: str
    model: str
    base_url: str
    reasoning_effort: str


JUDGE_PROFILES: Final[Mapping[str, JudgeProfile]] = MappingProxyType(
    {
        "judge-openai-luna-responses": JudgeProfile(
            profile="judge-openai-luna-responses",
            provider="OpenAI",
            model="gpt-6-luna",
            base_url="https://api.openai.com/v1",
            # low では推論を省いて、必須の evidence の引用を落とすことがある。推論を省かない medium にする。
            reasoning_effort="medium",
        ),
    }
)

#: `LLM_JUDGE_PROFILE` を指定しないときのジャッジ。
DEFAULT_JUDGE_PROFILE: Final = "judge-openai-luna-responses"


def resolve_judge_profile(
    name: str, profiles: Mapping[str, JudgeProfile] = JUDGE_PROFILES
) -> JudgeProfile:
    """ジャッジの profile 名を解決する。未知値は fallback せず送出する.

    Args:
        name: `LLM_JUDGE_PROFILE` の値。前後の空白は落とす。
        profiles: 差し替え可能な registry。

    Returns:
        解決した `JudgeProfile`。

    Raises:
        UnknownProfile: registry に無い値の場合。message には既知の profile 名
            だけを載せる。
    """
    resolved = profiles.get(name.strip())
    if resolved is None:
        known = ", ".join(sorted(profiles))
        raise UnknownProfile(
            f"LLM_JUDGE_PROFILE が未知の値です。既知の profile: {known}"
        )
    return resolved


def resolve_profile(
    name: str, profiles: Mapping[str, ChatProfile] = PROFILES
) -> ChatProfile:
    """profile 名を解決する。未知値は fallback せず送出する.

    Args:
        name: `LLM_PROFILE` の値。前後の空白は落とす。
        profiles: 差し替え可能な registry（拡張点の test が注入する）。

    Returns:
        解決した `ChatProfile`。

    Raises:
        UnknownProfile: registry に無い値の場合。**message には既知 profile 名の
            sorted 一覧だけを載せ、入力値は載せない** —— 設定値を error message へ
            出す前例を作らない。
    """
    resolved = profiles.get(name.strip())
    if resolved is None:
        known = ", ".join(sorted(profiles))
        raise UnknownProfile(f"LLM_PROFILE が未知の値です。既知の profile: {known}")
    return resolved


class CredentialTarget(Protocol):
    """`resolve_credential()` が読む 2 field だけの形."""

    @property
    def profile(self) -> str:
        """profile id（error 文言にだけ使う）."""
        ...

    @property
    def provider(self) -> str:
        """`PROVIDERS` の key."""
        ...


def resolve_credential(
    profile: CredentialTarget,
    environ: Mapping[str, str],
    providers: Mapping[str, ProviderDefinition] = PROVIDERS,
) -> str:
    """選択中 provider の credential **だけ**を解決する.

    解決順序は profile → provider → provider 固有 env。
    `auth="none"` の provider では `environ` を **1 度も読まない**。読まないことが
    「DS4 へ OpenAI key が渡らない」の実装上の担保であり、
    `test_llm_profiles.py` が `Mapping` の参照回数を数えて固定している。

    Args:
        profile: 解決済みの `ChatProfile`、または judge の `JudgeSettings`。
        environ: 読み取り対象の environment（通常は `os.environ`）。
        providers: 差し替え可能な provider registry。

    Returns:
        client へ渡す api key。auth 不要なら `INTERNAL_PLACEHOLDER_API_KEY`。

    Raises:
        UnknownProfile: profile が指す provider が registry に無い場合。
        MissingCredential: 選択中 provider の env が欠落・空・placeholder の場合。
            **message には env 名と profile 名しか載せない**（値は載せない）。
    """
    definition = providers.get(profile.provider)
    if definition is None:
        known = ", ".join(sorted(providers))
        raise UnknownProfile(
            f"profile {profile.profile} の provider が registry にありません。"
            f"既知の provider: {known}"
        )
    if definition.auth == "none":
        return INTERNAL_PLACEHOLDER_API_KEY
    env_name = definition.credential_env
    if env_name is None:  # pragma: no cover - registry invariant test が防ぐ
        raise UnknownProfile(
            f"provider {definition.name} は auth='api-key' ですが "
            "credential_env を持ちません"
        )
    value = environ.get(env_name, "").strip()
    if not value or value == INTERNAL_PLACEHOLDER_API_KEY:
        raise MissingCredential(
            f"profile {profile.profile} は provider {definition.name} の "
            f"{env_name} を要求します。未設定・空・placeholder は受け付けません。"
        )
    return value


def profile_availability(
    environ: Mapping[str, str], profiles: Mapping[str, ChatProfile] = PROFILES
) -> dict[str, bool]:
    """profile ごとに credential が揃っているかだけを返す."""
    availability: dict[str, bool] = {}
    for profile_id, profile in profiles.items():
        try:
            resolve_credential(profile, environ)
        except MissingCredential:
            availability[profile_id] = False
        else:
            availability[profile_id] = True
    return availability


def safe_url(value: str) -> str:
    """Strip credentials and malformed port text before artifact publication.

    正本はここ 1 つで、eval runner と test はここから import する。
    """
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "invalid-provider-url"
    host = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port:
        host = f"{host}:{port}"
    return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))


def identity_fields(profile: ChatProfile) -> dict[str, str]:
    """log / artifact が別 field で持つ identity 7 軸（表示用）.

    `base_url` は `safe_url()` 済みで userinfo と query を持たない。
    `reasoning_effort` は未指定を `REASONING_EFFORT_UNSET_DISPLAY`（`"unset"`）へ
    写す。表示値でも `"none"` と別値になるので、log・lane
    record・eval artifact のいずれの読み手も
    「送らない」と「`none` を送る」を同一条件として読めない。
    **credential は 1 field も含めない。**

    Args:
        profile: 解決済み profile。

    Returns:
        `profile` / `provider` / `model` / `protocol` / `api_mode` / `base_url` /
        `reasoning_effort`。
    """
    return {
        "profile": profile.profile,
        "provider": profile.provider,
        "model": profile.model,
        "protocol": profile.protocol,
        "api_mode": profile.api_mode,
        "base_url": safe_url(profile.base_url),
        "reasoning_effort": (
            REASONING_EFFORT_UNSET_DISPLAY
            if profile.reasoning_effort is None
            else profile.reasoning_effort
        ),
    }


def identity_fingerprint(profile: ChatProfile) -> str:
    """identity 7 軸の canonical JSON の SHA-256."""
    material: dict[str, str | None] = {
        "profile": profile.profile,
        "provider": profile.provider,
        "model": profile.model,
        "protocol": profile.protocol,
        "api_mode": profile.api_mode,
        "base_url": profile.base_url,
        "reasoning_effort": profile.reasoning_effort,
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
