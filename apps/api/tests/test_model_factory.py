"""`ModelFactory` の所有境界."""

import pytest

from apps.api.agent import model_factory
from apps.api.agent.model_factory import (
    ModelFactory,
    install_model_factory,
)
from apps.api.core.config import get_llm_settings
from apps.api.sample.fake_model import build_sample_fake_model

pytestmark = pytest.mark.small

DS4 = "ds4-deepseek-v4-flash-chat"
LUNA = "openai-luna-chat"


@pytest.fixture(autouse=True)
def fake_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """実サーバに繋がない分岐で組む（cache の所有だけを見る）."""
    monkeypatch.setattr(get_llm_settings(), "agent_model_mode", "fake")


def test_two_factories_do_not_share_one_cache_entry() -> None:
    """別 instance は同じ profile でも別 model を持つ（runtime 間で共有しない）."""
    first = ModelFactory(fake_model=build_sample_fake_model)
    second = ModelFactory(fake_model=build_sample_fake_model)

    assert first.build(DS4) is first.build(DS4), "同じ factory で 2 個作っている"
    assert first.build(DS4) is not second.build(DS4), (
        "別 factory が cache entry を共有している"
    )
    assert first.cached_profiles() == (DS4,)
    assert second.cached_profiles() == (DS4,)


async def test_closing_one_factory_leaves_the_other_cache_intact() -> None:
    """`aclose()` は自分の cache だけを空にする."""
    closed = ModelFactory(fake_model=build_sample_fake_model)
    kept = ModelFactory(fake_model=build_sample_fake_model)
    closed.build(DS4)
    kept.build(LUNA)

    await closed.aclose()

    assert closed.cached_profiles() == ()
    assert kept.cached_profiles() == (LUNA,), "他 factory の cache まで消している"


def test_the_loop_helpers_follow_the_installed_factory() -> None:
    """`model_factory.build_model()` は「いま有効な factory」に対して働く.

    委譲が module import 時に factory を焼き付けていると、runtime が自分の
    factory を差し込んでも router と eval harness だけが既定 factory を
    使い続け、cache が二重になる。
    """
    installed = ModelFactory(fake_model=build_sample_fake_model)
    previous = install_model_factory(installed)
    # 既定 factory は他 test の残骸を持ち得るので、**差分**だけを見る。
    before = previous.cached_profiles()
    try:
        model = model_factory.build_model(DS4)

        assert installed.cached_profiles() == (DS4,)
        assert model is installed.build(DS4)
        assert model_factory.cached_model_profiles() == (DS4,)
    finally:
        install_model_factory(previous)

    assert previous.cached_profiles() == before, (
        "差し込み中の build が元の factory を汚している"
    )
