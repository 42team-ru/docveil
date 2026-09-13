"""Изоляция тестов провайдера от локального `masker.yaml`.

Тесты выбора провайдера читают конфигурацию проекта через
``masker.config.project_section``, а тот без ``MASKER_CONFIG`` находит
`backend/masker.yaml` — файл РАЗРАБОТЧИКА. Стоит переключить в нём
`llm.profile` на `gigachat` (обычное дело при живом прогоне), и восемь
тестов падают на машине, где код ни при чём: `test_openrouter_requires_key`
не получает ошибку, `verify_ssl_certs` приезжает `false` из чужого профиля.
Замерено 14.09.2026: те же тесты зелёные с закоммиченным конфигом и
красные с локальным.

Фикстура подставляет заведомо нейтральный конфиг. Тесты, которые
проверяют саму работу с YAML, задают ``MASKER_CONFIG`` сами — их значение
сильнее, потому что ставится позже.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from masker.config import CONFIG_ENV_VAR

_NEUTRAL_CONFIG = """\
llm:
  profile: fake
  profiles:
    fake:
      provider: fake
"""


@pytest.fixture(autouse=True)
def neutral_project_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Подставить нейтральный `masker.yaml` вместо локального файла проекта."""
    config = tmp_path_factory.mktemp("llm-config") / "masker.yaml"
    config.write_text(_NEUTRAL_CONFIG, encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(config))
    return config
