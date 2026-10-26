"""Refresh preference, independent of Jira profiles and private TOML."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .core import OverviewError


DEFAULT_REFRESH_SECONDS = 3600


def validate_refresh_seconds(value: object) -> int | float:
    if type(value) not in (int, float) or not 5 <= value <= 86400:
        raise ValueError("Интервал должен быть числом от 5 до 86400 секунд.")
    return value


def read_refresh_seconds(path: Path) -> int | float | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or type(data.get("version")) is not int
                or data["version"] != 1):
            raise ValueError()
        return validate_refresh_seconds(data.get("refresh_seconds"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise OverviewError("Не удалось загрузить интервал; используется значение из конфигурации.") from None


def write_refresh_seconds(path: Path, value: int | float) -> None:
    value = validate_refresh_seconds(value)
    temporary = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".settings-")
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "refresh_seconds": value}, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        raise OverviewError("Не удалось сохранить интервал. Прежняя настройка сохранена; повторите или отмените ввод.") from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
