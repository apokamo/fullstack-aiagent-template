"""実行コンテキストごとの環境変数 loader."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

try:
    from dotenv import dotenv_values
except ImportError:
    # python-dotenv is declared in [project] dependencies (this module sits on the
    # production startup path via apps/api/core/config.py).
    # If not installed, provide a helpful error message
    print(
        "ERROR: python-dotenv is not installed. Install it with: uv sync",
        file=sys.stderr,
    )
    sys.exit(1)

from apps.api.core.llm_profiles import PROVIDERS

if TYPE_CHECKING:
    from collections.abc import Mapping


#: admin credential の key。test / API の process に残っていたら loader が落とす。
ADMIN_ENV_KEYS: Final = frozenset({"PGPASSWORD"})

DB_URL_KEYS: Final = frozenset({"DATABASE_URL"})

#: profile と provider 固有 credential を運ぶ key。
#: **registry から導出する** —— provider を足したときに guard 側が取り残されると、
#: その provider の key だけ `api.host.env` / `.env` から静かに入る。
LLM_IDENTITY_KEYS: Final = frozenset(
    {"LLM_PROFILE"}
    | {
        provider.credential_env
        for provider in PROVIDERS.values()
        if provider.credential_env
    }
)

#: 呼び出し側が context を明示する環境変数。**既定値は無い。**
CONTEXT_ENV_VAR: Final = "DB_ENV_CONTEXT"

#: 許可する context。
CONTEXTS: Final = ("api", "test")

# **module import 時に取る。** この module は loader の定義そのものなので、
# snapshot は必ずどの loader 呼び出しよりも前の状態を捉える。
_AMBIENT_ENV: Final[Mapping[str, str]] = MappingProxyType(dict(os.environ))


def ambient_env() -> Mapping[str, str]:
    """loader が走る前の OS environment（read-only の snapshot）.

    Returns:
        書き換え不能な mapping。loader が `os.environ` へ書いた後も変化しない。
    """
    return _AMBIENT_ENV


def project_root() -> Path:
    """リポジトリルート（テストはここを差し替えて隔離する）.

    **CWD は見ない。** この file の位置（`apps/api/core/environment.py`）から
    4 階層上がった path が root である —— `secrets/` の解決を CWD 依存にすると、
    同じ checkout を別の作業ディレクトリから起動したときに読む secret が変わる。
    """
    return Path(__file__).resolve().parents[3]


def secrets_dir() -> Path:
    """secret と接続値を置く directory（`secrets/`）."""
    return project_root() / "secrets"


def read_env_file(path: Path, *, interpolate: bool = True) -> dict[str, str]:
    """`.env` 形式の file を **`os.environ` を変更せずに** 読む."""
    if not path.is_file():
        return {}
    try:
        values = dotenv_values(path, interpolate=interpolate)
    except (OSError, UnicodeDecodeError):
        print(f"ERROR: Failed to parse {path}", file=sys.stderr)
        sys.exit(1)
    return {key: value for key, value in values.items() if value is not None}


def _apply(values: Mapping[str, str], *, exclude: frozenset[str]) -> None:
    """既存の `os.environ` を上書きせず、除外 key を読まずに値を足す.

    **比較は case-insensitive。** `os.environ.setdefault()` と `in exclude` は
    key の大文字小文字を区別するが、消費側の `Settings` は
    `case_sensitive=False` で解決する。literal 比較のままだと
    `api.env` の `database_url` が DB URL の除外を素通りし、OS の
    `DATABASE_URL` があっても file 側の case variant が勝つ組合せが出る。

    Args:
        values: file から読んだ key -> value。
        exclude: この loader が読んではいけない key（case は問わない）。
    """
    excluded = {key.upper() for key in exclude}
    # 既に決まっている設定項目（case を畳んだ名前）。file 側の variant を
    # 足すたびに更新するので、同じ file 内の case 違いも先勝ちになる。
    present = {key.upper() for key in os.environ}
    for key, value in values.items():
        normalized = key.upper()
        if normalized in excluded or normalized in present:
            continue
        os.environ[key] = value
        present.add(normalized)


def _load(path: Path, *, exclude: frozenset[str] = frozenset()) -> bool:
    """1 file を読んで `os.environ` へ足す.

    Returns:
        file が存在したら `True`。
    """
    if not path.is_file():
        return False
    _apply(read_env_file(path), exclude=exclude)
    return True


def _reject_admin_keys(context: str) -> None:
    """admin credential がこの process に残っていたら落とす.

    Args:
        context: 検出した context 名（message に載せる）。

    Raises:
        RuntimeError: `ADMIN_ENV_KEYS` が 1 つでも設定されている場合。
            **message には key 名しか載せない**（値は載せない）。
    """
    found = sorted(key for key in os.environ if key in ADMIN_ENV_KEYS)
    if not found:
        return
    raise RuntimeError(
        f"{context} context の process に管理用の環境変数が残っています: "
        f"{', '.join(found)}。管理資格情報をAPIやテストへ渡さないでください。"
    )


def _reject_llm_identity_keys(path: Path, values: Mapping[str, str]) -> None:
    """`api.host.env` / `.env` が LLM identity を宣言していたら落とす.

    `_reject_admin_keys()` と同型の fail-loud 検出。突合は `_apply()` と同じ
    case-insensitive で行う —— `Settings` が `case_sensitive=False` で解決する
    ので、`llm_profile` という綴りも同じ設定項目へ届く。

    Args:
        path: 読んだ file（message には **file 名だけ**を載せる）。
        values: その file から読んだ key -> value。

    Raises:
        RuntimeError: `LLM_IDENTITY_KEYS` のいずれかが宣言されている場合。
            **message には key 名と file 名しか載せない**（値は載せない）。
    """
    found = sorted(key for key in values if key.upper() in LLM_IDENTITY_KEYS)
    if not found:
        return
    raise RuntimeError(
        f"{path.name} が LLM identity の設定を宣言しています: {', '.join(found)}。"
        "profile と provider 固有 credential は OS environment か "
        "secrets/api.env からしか入りません。"
        f"{path.name} は "
        + (
            "host 実行専用の DB URL overlay です。"
            if path.name == "api.host.env"
            else "非 secret の一般設定であり、agent identity の正本にしません。"
        )
    )


def load_api_env() -> bool:
    """API runtime の設定を読む（`api.host.env` -> `api.env` -> `.env`）.

    先に読んだ file と OS environment の値が優先され、後の file は上書きしない。
    DB URL（`DB_URL_KEYS`）は OS environment と `api.host.env` からしか入らない。
    LLM identity（`LLM_IDENTITY_KEYS`）は OS environment と `api.env` からしか
    入らない。**除外集合は file ごとに別である** —— `api.host.env` でも
    `DB_URL_KEYS` を除外すると host 実行で DB URL の正規 source が消え、`api.env`
    と `.env` も除外しているため補完されず起動契約が壊れる。

    Returns:
        1 file でも存在したら `True`。

    Raises:
        RuntimeError: admin key がこの process に残っている場合、または
            `api.host.env` / `.env` が LLM identity を宣言している場合。
    """
    _reject_admin_keys("api")
    secrets = secrets_dir()
    host_env = secrets / "api.host.env"
    dot_env = project_root() / ".env"
    _reject_llm_identity_keys(host_env, read_env_file(host_env))
    _reject_llm_identity_keys(dot_env, read_env_file(dot_env))
    loaded = _load(host_env, exclude=LLM_IDENTITY_KEYS)
    loaded = _load(secrets / "api.env", exclude=DB_URL_KEYS) or loaded
    return _load(dot_env, exclude=DB_URL_KEYS | LLM_IDENTITY_KEYS) or loaded


def load_test_env() -> bool:
    """test context の設定を読む（`secrets/test.env` だけ）.

    Returns:
        file が存在したら `True`。

    Raises:
        RuntimeError: admin key がこの process に残っている場合。
    """
    _reject_admin_keys("test")
    return _load(secrets_dir() / "test.env")


def resolve_context() -> str:
    """呼び出し側が `DB_ENV_CONTEXT` で明示した context を返す.

    Returns:
        `"api"` または `"test"`。

    Raises:
        RuntimeError: 未設定または未知の値の場合。**message には許可値しか
            載せない**（実際に設定されていた値は載せない）。
    """
    context = os.environ.get(CONTEXT_ENV_VAR)
    if context not in CONTEXTS:
        raise RuntimeError(
            f"{CONTEXT_ENV_VAR} を明示してください（許可値: "
            f"{', '.join(CONTEXTS)}）。supported Make target は pytest / alembic /"
            " DB script を起動する前にこれを設定します。"
        )
    return context


def load_context_env(context: str) -> bool:
    """context 名で loader を選ぶ.

    Args:
        context: `resolve_context()` が返す値。

    Returns:
        1 file でも存在したら `True`。

    Raises:
        RuntimeError: 未知の context を渡した場合。
    """
    if context == "api":
        return load_api_env()
    if context == "test":
        return load_test_env()
    raise RuntimeError(f"未知の context です（許可値: {', '.join(CONTEXTS)}）。")
