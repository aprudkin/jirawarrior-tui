"""Offline theme picker and one atomic preference, separate from Jira profiles."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.theme import Theme
from textual.widgets import Button, OptionList, Static
from textual.widgets.option_list import Option

from .core import OverviewError


def read_theme(path: Path, available: dict[str, Theme]) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or type(data.get("version")) is not int
                or data["version"] != 1 or not isinstance(data.get("theme"), str)
                or data["theme"] not in available or data["theme"] == "textual-ansi"):
            raise ValueError()
        return data["theme"]
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise OverviewError("Не удалось загрузить сохранённую тему; используется стандартная.") from None


def write_theme(path: Path, name: str) -> None:
    temporary = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".theme-")
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "theme": name}, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        raise OverviewError("Не удалось сохранить тему. Прежняя настройка сохранена; повторите или отмените выбор.") from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


class ThemePanel(Vertical):
    """A docked picker: mouse selects a preview; Enter alone commits it."""
    BINDINGS = [Binding("enter", "app.confirm_theme", "Сохранить", priority=True),
                Binding("escape", "app.cancel_theme", "Отменить", priority=True)]
    DEFAULT_CSS = """
    ThemePanel {
        display: none;
        width: 32;
        max-width: 55%;
        height: 1fr;
        border-left: solid $border;
        background: $surface;
        padding: 0 1;
    }
    #theme-heading { height: 1; margin-bottom: 1; }
    #theme-title { width: 1fr; text-style: bold; }
    #theme-close { width: 3; min-width: 3; height: 1; border: none; padding: 0; }
    #theme-list { height: 1fr; border: none; padding: 0; }
    #theme-hints { height: auto; max-height: 4; margin-top: 1; }
    """

    def __init__(self, themes: dict[str, Theme], **kwargs):
        super().__init__(**kwargs)
        self.themes = themes

    def compose(self) -> ComposeResult:
        with Horizontal(id="theme-heading"):
            yield Static("Темы", id="theme-title")
            yield Button("×", id="theme-close", tooltip="Отменить выбор темы")
        options = []
        for dark, title in ((True, "Тёмные"), (False, "Светлые")):
            options.append(Option(Text(title, style="bold"), disabled=True))
            options.extend(Option(name, id=name) for name, theme in sorted(self.themes.items())
                           if theme.dark == dark and name != "textual-ansi")
        # Like Textual's own ThemeProvider, omit ANSI: it uses the terminal's
        # palette rather than providing a dark or light color scheme.
        yield OptionList(*options, id="theme-list", markup=False, compact=True)
        yield Static("↑↓ выбор · Enter сохранить\nEsc / t / × отменить", id="theme-hints")
