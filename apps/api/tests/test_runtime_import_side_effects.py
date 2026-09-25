"""import だけでは環境変数や settings、engine、model を変更しない。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.medium, pytest.mark.uses_resource("filesystem")]

REPO_ROOT = Path(__file__).resolve().parents[3]

#: 子 process へ渡す env。**必須設定を 1 つも入れない** —— import だけで設定が
#: 構築される実装なら、ここで `ValidationError` になって probe が非 0 で終わる。
#: `PATH` と `HOME` は uv / python 自身が要求するので残す。
_PASSTHROUGH_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "VIRTUAL_ENV", "PYTHONPATH")


def _probe_env() -> dict[str, str]:
    """必須設定を持たない子 process の環境を組む."""
    env = {key: os.environ[key] for key in _PASSTHROUGH_ENV_KEYS if key in os.environ}
    # secrets/ を読ませない。loader が走ったかどうかを差分で見たいので、
    # 「読める file が無い」状態ではなく「読んでいない」ことを見る必要がある ——
    # そのため root 自体は本物のまま使い、判定は os.environ の差分で行う。
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run_probe(source: str) -> dict[str, object]:
    """probe を子 process で実行し、JSON 1 行を読む.

    Args:
        source: `python -c` へ渡す source。最後に `print(json.dumps(...))` すること。

    Returns:
        probe が報告した mapping。
    """
    result = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=_probe_env(),
        check=False,
    )
    assert result.returncode == 0, (
        f"probe が非 0 で終了しました（exit {result.returncode}）。"
        f"stderr:\n{result.stderr[-2000:]}"
    )
    payload: dict[str, object] = json.loads(result.stdout.strip().splitlines()[-1])
    return payload


CONFIG_PROBE = """
import json, os
before = sorted(os.environ)
import apps.api.core.config as config
after = sorted(os.environ)
print(json.dumps({
    "added_env": [name for name in after if name not in before],
    "has_module_settings": hasattr(config, "settings"),
    "cached": {
        getter.__name__: getter.cache_info().currsize
        for getter in config.SETTINGS_GETTERS
    },
}))
"""


def test_importing_the_config_module_reads_no_environment() -> None:
    """`core.config` の import は `os.environ` を 1 key も書き換えない.

    loader を走らせるのは読み手別 getter が呼ばれた時点である。ここが崩れると、
    import の順序が設定の内容を決める状態へ戻る。
    """
    payload = _run_probe(CONFIG_PROBE)

    assert payload["added_env"] == []
    assert payload["has_module_settings"] is False
    cached = payload["cached"]
    assert isinstance(cached, dict)
    assert cached
    assert set(cached.values()) == {0}


SHARED_IMPORT_PROBE = """
import json, os
before = sorted(os.environ)
from apps.api.agent import model_factory, persistence, runtime
from apps.api.sample import agent as sample_agent
from apps.api.core import config, dependencies
after = sorted(os.environ)
print(json.dumps({
    "added_env": [name for name in after if name not in before],
    "settings_cached": sum(
        getter.cache_info().currsize for getter in config.SETTINGS_GETTERS
    ),
    "conversation_engines": dependencies.get_engine.cache_info().currsize,
    "models": len(model_factory.cached_model_profiles()),
}))
"""


def test_importing_the_shared_runtime_creates_no_settings_engine_or_model() -> None:
    """共通 runtime とサンプル agent の import は設定も接続も model も作らない."""
    payload = _run_probe(SHARED_IMPORT_PROBE)

    assert payload["added_env"] == []
    assert payload["settings_cached"] == 0
    assert payload["conversation_engines"] == 0
    assert payload["models"] == 0
