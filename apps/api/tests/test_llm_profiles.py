"""LLM profile registry の契約: 不変条件・credential の隔離・identity 表現・可用性."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from apps.api.core.llm_profiles import (
    ALLOWED_API_MODES,
    ALLOWED_REASONING_EFFORTS,
    API_MODE_CHAT_COMPLETIONS,
    INTERNAL_PLACEHOLDER_API_KEY,
    JUDGE_PROFILES,
    MODEL_PRICES,
    PROFILE_ID_PATTERN,
    PROFILES,
    PROTOCOL_OPENAI_COMPATIBLE,
    PROVIDERS,
    REASONING_EFFORT_UNSET_DISPLAY,
    ChatProfile,
    MissingCredential,
    UnknownProfile,
    identity_fields,
    identity_fingerprint,
    profile_availability,
    resolve_credential,
    resolve_profile,
    safe_url,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.small

#: auth 不要（DS4）と api-key（OpenAI）の代表 profile。
AUTH_FREE_PROFILE = "ds4-deepseek-v4-flash-chat"
API_KEY_PROFILE = "openai-luna-chat"


def synthetic_profile(**overrides: str | None) -> ChatProfile:
    """identity の検査に使う、registry に無い profile."""
    values: dict[str, str | None] = {
        "profile": "synthetic-chat",
        "provider": "DS4",
        "model": "m",
        "protocol": PROTOCOL_OPENAI_COMPATIBLE,
        "api_mode": API_MODE_CHAT_COMPLETIONS,
        "base_url": "https://provider.example/v1",
        **overrides,
    }
    return ChatProfile(**values)  # type: ignore[arg-type]


class CountingEnviron(dict[str, str]):
    """参照回数を数える `Mapping`。読まないことを証明するための stub."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.reads: list[str] = []

    def __getitem__(self, key: str) -> str:
        self.reads.append(key)
        return super().__getitem__(key)

    def get(self, key: str, default: str | None = None) -> str:  # type: ignore[override]
        self.reads.append(key)
        return super().get(key, default)  # type: ignore[return-value]

    def __iter__(self) -> Iterator[str]:
        self.reads.extend(super().__iter__())
        return super().__iter__()


# =============================================================================
# registry invariants
# =============================================================================


def test_every_profile_satisfies_the_registry_invariants() -> None:
    """id・model・base URL・protocol・API mode・provider・表示名の規則を守る.

    id の綴りを固定するのは、eval の artifact root が profile 名を **path 片**
    として使うためである。traversal も case 差も生まない集合に限る。表示名は
    画面の選択肢になるので、非空かつ一意でなければならない。
    """
    for profile_id, profile in PROFILES.items():
        assert profile.profile == profile_id
        assert re.fullmatch(PROFILE_ID_PATTERN, profile_id)
        assert profile.model.strip() == profile.model != ""
        assert profile.base_url.startswith(("http://", "https://"))
        assert safe_url(profile.base_url) != "invalid-provider-url"
        assert profile.protocol == PROTOCOL_OPENAI_COMPATIBLE
        assert profile.api_mode in ALLOWED_API_MODES
        assert profile.provider in PROVIDERS
        # 表示値 `"unset"` を effort の実値として持てないこと。持てると
        # 「送らない」と「`unset` を送る」が artifact 上で同じ文字列になる。
        assert profile.reasoning_effort != REASONING_EFFORT_UNSET_DISPLAY
        if profile.reasoning_effort is not None:
            assert profile.reasoning_effort in ALLOWED_REASONING_EFFORTS

    labels = [profile.label for profile in PROFILES.values()]
    assert all(label.strip() for label in labels)
    assert len(set(labels)) == len(labels)


def test_every_judge_profile_satisfies_the_registry_invariants() -> None:
    """ジャッジの profile も同じ綴り・provider・effort の規則に従う."""
    for profile_id, profile in JUDGE_PROFILES.items():
        assert profile.profile == profile_id
        assert re.fullmatch(PROFILE_ID_PATTERN, profile_id)
        assert profile_id not in PROFILES
        assert profile.base_url.startswith(("http://", "https://"))
        assert profile.provider in PROVIDERS
        assert profile.reasoning_effort in ALLOWED_REASONING_EFFORTS


def test_every_registered_model_has_a_price() -> None:
    """eval の費用上限は単価が無いと守れないので、使う model はすべて単価を持つ."""
    models = {p.model for p in PROFILES.values()} | {
        p.model for p in JUDGE_PROFILES.values()
    }

    assert models <= set(MODEL_PRICES)


def test_every_provider_declares_its_own_credential_env() -> None:
    """api-key の provider だけが credential env を持ち、既存の key を使い回さない."""
    for provider_name, provider in PROVIDERS.items():
        assert provider.name == provider_name
        if provider.auth == "api-key":
            assert provider.credential_env
        else:
            assert provider.auth == "none"
            assert provider.credential_env is None

    declared = [p.credential_env for p in PROVIDERS.values() if p.credential_env]
    assert len(declared) == len(set(declared))


# =============================================================================
# resolve_profile
# =============================================================================


def test_an_unknown_profile_lists_the_known_names_and_not_the_input() -> None:
    """未知の名前は既知の名前を挙げて落ち、入力を復唱しない。前後の空白は落とす."""
    with pytest.raises(UnknownProfile) as caught:
        resolve_profile("zzz-not-a-profile-name")

    message = str(caught.value)
    assert all(name in message for name in PROFILES)
    assert "zzz-not-a-profile-name" not in message

    assert resolve_profile(f"  {API_KEY_PROFILE} \n").profile == API_KEY_PROFILE


# =============================================================================
# resolve_credential: 隔離
# =============================================================================


def test_each_provider_reads_only_its_own_credential_env() -> None:
    """auth 不要な profile は environ を読まず、api-key の profile は自分の key だけを読む.

    **`environ` を参照しないこと自体を固定する。** 「値を返さない」だけでは、
    後から「key があれば渡す」分岐を足したときに気付けない。
    """
    environ = CountingEnviron({"OPENAI_API_KEY": "sk-live-must-not-leak"})
    resolved = resolve_credential(resolve_profile(AUTH_FREE_PROFILE), environ)
    assert resolved == INTERNAL_PLACEHOLDER_API_KEY
    assert environ.reads == []

    environ = CountingEnviron(
        {"OPENAI_API_KEY": "sk-test", "PROVIDER_X_API_KEY": "other"}
    )
    resolved = resolve_credential(resolve_profile(API_KEY_PROFILE), environ)
    assert resolved == "sk-test"
    assert environ.reads == ["OPENAI_API_KEY"]


def test_a_missing_empty_or_placeholder_credential_is_rejected() -> None:
    """欠落・空・空白のみ・placeholder は「設定済み」と数えない."""
    for environ in (
        {},
        {"OPENAI_API_KEY": ""},
        {"OPENAI_API_KEY": "   "},
        {"OPENAI_API_KEY": INTERNAL_PLACEHOLDER_API_KEY},
    ):
        with pytest.raises(MissingCredential) as caught:
            resolve_credential(resolve_profile(API_KEY_PROFILE), environ)

        message = str(caught.value)
        assert "OPENAI_API_KEY" in message
        assert API_KEY_PROFILE in message


# =============================================================================
# identity 表現
# =============================================================================


def test_identity_fields_sanitize_the_base_url() -> None:
    """userinfo と query は表示値に残さない."""
    profile = synthetic_profile(
        base_url="https://user:s3cret@provider.example:8787/v1/?token=t0ken"
    )

    assert identity_fields(profile)["base_url"] == "https://provider.example:8787/v1"


def test_every_identity_axis_changes_the_fingerprint() -> None:
    """identity の軸はどれを変えても fingerprint が変わる."""
    baseline = synthetic_profile()

    for axis in identity_fields(baseline):
        changed = ChatProfile(**{**vars(baseline), axis: "changed-value"})
        assert identity_fingerprint(baseline) != identity_fingerprint(changed), axis


def test_the_fingerprint_uses_the_raw_base_url_not_the_display_value() -> None:
    """表示値で照合すると別の接続先を同一と誤判定する."""
    plain = synthetic_profile()
    with_credentials = ChatProfile(
        **{**vars(plain), "base_url": "https://user:s3cret@provider.example/v1"}
    )

    assert (
        identity_fields(plain)["base_url"]
        == (identity_fields(with_credentials)["base_url"])
    )
    assert identity_fingerprint(plain) != identity_fingerprint(with_credentials)


# =============================================================================
# 可用性
# =============================================================================


def test_availability_follows_each_profiles_own_credential() -> None:
    """auth 不要な profile は常に使え、api-key の profile は自分の key があるときだけ使える.

    非選択 profile の credential 欠落が他 profile の利用を妨げない。並び順は
    registry が決め、auth 不要な profile のために environ を 1 度も読まない。
    """

    def needs_key(profile_id: str) -> bool:
        return PROVIDERS[PROFILES[profile_id].provider].auth == "api-key"

    missing = profile_availability({"OPENAI_API_KEY": INTERNAL_PLACEHOLDER_API_KEY})
    assert list(missing) == list(PROFILES)
    assert missing == {profile_id: not needs_key(profile_id) for profile_id in PROFILES}

    environ = CountingEnviron({"OPENAI_API_KEY": "sk-live"})
    assert all(profile_availability(environ).values())
    assert set(environ.reads) == {"OPENAI_API_KEY"}
    assert len(environ.reads) == sum(1 for p in PROFILES if needs_key(p))
