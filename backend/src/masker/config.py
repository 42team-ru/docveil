"""Чтение необязательного общего YAML-конфига проекта.

Модуль намеренно принадлежит ``masker`` и не импортирует API, БД или MinIO:
CLI должен оставаться пригодным для запуска на машине без веб-слоя.  Конфиг
тоже необязателен — при его отсутствии потребители используют свои дефолты.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

CONFIG_ENV_VAR = "MASKER_CONFIG"
CONFIG_FILE_NAME = "masker.yaml"


def load_project_config() -> dict[str, Any]:
    """Вернуть общий YAML-конфиг либо пустой объект, если файла нет.

    ``MASKER_CONFIG`` задаёт явный путь. Без него сначала ищется файл в
    текущем каталоге, затем рядом с исходным деревом проекта; второй вариант
    делает стандартный ``backend/masker.yaml`` доступным и при запуске из
    корня репозитория. Явно указанный, но отсутствующий файл — ошибка, чтобы
    опечатка в пути не превращалась в тихий запуск с другими настройками.
    """
    explicit = os.environ.get(CONFIG_ENV_VAR)
    if explicit is not None:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ValueError(f"не найден YAML-конфиг проекта {path}")
        return _read_mapping(path)

    for path in _default_paths():
        if path.is_file():
            return _read_mapping(path)
    return {}


def project_section(name: str) -> dict[str, Any]:
    """Вернуть секцию общего конфига, проверив, что она является объектом."""
    value = load_project_config().get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"секция {name} в YAML-конфиге должна быть объектом")
    return value


def _default_paths() -> tuple[Path, ...]:
    source_tree_config = Path(__file__).resolve().parents[2] / CONFIG_FILE_NAME
    working_directory_config = Path.cwd() / CONFIG_FILE_NAME
    return (working_directory_config, source_tree_config)


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"не удалось прочитать YAML-конфиг проекта {path}: {error}") from error
    except yaml.YAMLError as error:
        raise ValueError(f"некорректный YAML в конфиге проекта {path}: {error}") from error
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("YAML-конфиг проекта должен быть объектом")
    return dict(raw)
