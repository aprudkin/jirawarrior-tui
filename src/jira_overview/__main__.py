"""CLI configuration is private TOML; secrets are read only from the environment."""
import argparse
import asyncio
import os
from pathlib import Path
import sys
import tomllib

from .app import Overview
from .core import Jira, OverviewError


def configuration(path: Path):
    try:
        data = tomllib.loads(path.read_text())
        url, variable = data["url"], data["token_env"]
        interval = data.get("refresh_seconds", 60)
        if (not isinstance(url, str) or not isinstance(variable, str) or not variable
                or type(interval) not in (int, float) or not 5 <= interval <= 86400):
            raise ValueError()
        token = os.environ.get(variable)
        if not token or any(c.isspace() for c in token):
            raise OverviewError("Переменная окружения с токеном отсутствует или некорректна.")
        state_dir = Path(data.get("state_dir", str(Path(os.environ.get(
            "XDG_STATE_HOME", Path.home() / ".local/state")) / "jira-overview"))).expanduser()
        return Jira(url, token), state_dir, interval
    except (OSError, ValueError, KeyError, TypeError):
        raise OverviewError("Не удалось прочитать конфигурацию Jira TUI. Проверьте TOML: url, token_env, refresh_seconds.") from None


async def check(jira):
    try:
        snapshot = await jira.snapshot()
        print(f"GET-проверка успешна: задач {len(snapshot.issues)}, "
              f"в активных спринтах {sum(bool(i.sprints) for i in snapshot.issues)}. "
              "Комментарии загружены полностью. Состояние не изменялось.")
    finally:
        await jira.close()


def main():
    parser = argparse.ArgumentParser(description="Read-only Jira TUI; локальные отметки просмотра")
    parser.add_argument("--config", type=Path, default=Path(os.environ.get(
        "XDG_CONFIG_HOME", Path.home() / ".config")) / "jira-overview/config.toml")
    parser.add_argument("--check", action="store_true", help="Проверить GET-загрузку без UI и записи baseline")
    args = parser.parse_args()
    try:
        jira, state_dir, interval = configuration(args.config)
        if args.check:
            asyncio.run(check(jira))
        else:
            Overview(jira, state_dir, interval).run()
    except OverviewError as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
