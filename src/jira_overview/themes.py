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


# Static adaptations, not editor/terminal plugins. Pinned upstream sources and
# their MIT notices are included in THIRD_PARTY_NOTICES.md (also in the wheel).
ADDITIONAL_THEMES = (
    Theme(
        name="rose-pine", primary="#9ccfd8", secondary="#c4a7e7", accent="#ebbcba",
        foreground="#e0def4", background="#191724", surface="#1f1d2e", panel="#26233a",
        success="#9ccfd8", warning="#f6c177", error="#eb6f92",
        variables={
            "block-cursor-background": "#26233a",
            "block-cursor-foreground": "#e0def4",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#26233a",
        },
    ),
    Theme(
        name="rose-pine-dawn", primary="#286983", secondary="#907aa9", accent="#b4637a",
        foreground="#464261", background="#faf4ed", surface="#fffaf3", panel="#f2e9e1",
        success="#286983", warning="#ea9d34", error="#b4637a", dark=False,
        variables={
            "block-cursor-background": "#f2e9e1",
            "block-cursor-foreground": "#464261",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#f2e9e1",
        },
    ),
    Theme(
        name="everforest-dark", primary="#a7c080", secondary="#7fbbb3", accent="#d699b6",
        foreground="#d3c6aa", background="#2d353b", surface="#343f44", panel="#3d484d",
        success="#a7c080", warning="#dbbc7f", error="#e67e80",
        variables={
            "block-cursor-background": "#232a2e",
            "block-cursor-foreground": "#d3c6aa",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#232a2e",
        },
    ),
    Theme(
        name="everforest-light", primary="#3a94c5", secondary="#35a77c", accent="#df69ba",
        foreground="#5c6a72", background="#fdf6e3", surface="#f4f0d9", panel="#efebd4",
        success="#8da101", warning="#dfa000", error="#f85552", dark=False,
        variables={
            "block-cursor-background": "#efebd4",
            "block-cursor-foreground": "#5c6a72",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#efebd4",
        },
    ),
    Theme(
        name="kanagawa-wave", primary="#7e9cd8", secondary="#957fb8", accent="#e6c384",
        foreground="#dcd7ba", background="#1f1f28", surface="#16161d", panel="#2a2a37",
        success="#98bb6c", warning="#ff9e3b", error="#e82424",
        variables={
            "block-cursor-background": "#2a2a37",
            "block-cursor-foreground": "#dcd7ba",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#2a2a37",
        },
    ),
    Theme(
        name="gruvbox-light", primary="#076678", secondary="#427b58", accent="#8f3f71",
        foreground="#3c3836", background="#fbf1c7", surface="#ebdbb2", panel="#d5c4a1",
        success="#79740e", warning="#b57614", error="#9d0006", dark=False,
        variables={
            "block-cursor-background": "#d5c4a1",
            "block-cursor-foreground": "#3c3836",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#d5c4a1",
        },
    ),
    Theme(
        name="one-dark", primary="#61afef", secondary="#c678dd", accent="#56b6c2",
        foreground="#abb2bf", background="#282c34", surface="#21252b", panel="#282c34",
        success="#98c379", warning="#e5c07b", error="#e06c75",
        variables={
            "block-cursor-background": "#21252b",
            "block-cursor-foreground": "#abb2bf",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#21252b",
        },
    ),
    Theme(
        name="solarized-dark", primary="#268bd2", secondary="#2aa198", accent="#6c71c4",
        foreground="#93a1a1", background="#002b36", surface="#073642", panel="#073642",
        success="#859900", warning="#b58900", error="#dc322f",
        variables={
            "block-cursor-background": "#002b36",
            "block-cursor-foreground": "#93a1a1",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#002b36",
        },
    ),
    Theme(
        name="ayu-dark", primary="#e6b450", secondary="#59c2ff", accent="#d2a6ff",
        foreground="#bfbdb6", background="#0d1017", surface="#10141c", panel="#141821",
        success="#aad94c", warning="#ffb454", error="#d95757",
        variables={
            "block-cursor-background": "#141821",
            "block-cursor-foreground": "#bfbdb6",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#141821",
        },
    ),
    Theme(
        name="ayu-mirage", primary="#ffcc66", secondary="#73d0ff", accent="#dfbfff",
        foreground="#cccac2", background="#1f2430", surface="#242936", panel="#282e3b",
        success="#d5ff80", warning="#ffcd66", error="#ff6666",
        variables={
            "block-cursor-background": "#282e3b",
            "block-cursor-foreground": "#cccac2",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#282e3b",
        },
    ),
    Theme(
        name="night-owl", primary="#82aaff", secondary="#c792ea", accent="#7fdbca",
        foreground="#d6deeb", background="#011627", surface="#0b253a", panel="#1d3b53",
        success="#9ccc65", warning="#ffca28", error="#ef5350",
        variables={
            "block-cursor-background": "#1d3b53",
            "block-cursor-foreground": "#d6deeb",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#1d3b53",
        },
    ),
    Theme(
        name="github-dark", primary="#79b8ff", secondary="#b392f0", accent="#ffab70",
        foreground="#e1e4e8", background="#24292e", surface="#1b1f23", panel="#2f363d",
        success="#85e89d", warning="#ffdf5d", error="#f97583",
        variables={
            "block-cursor-background": "#2f363d",
            "block-cursor-foreground": "#e1e4e8",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#2f363d",
        },
    ),
    Theme(
        name="catppuccin-frappe", primary="#8caaee", secondary="#ca9ee6", accent="#f4b8e4",
        foreground="#c6d0f5", background="#303446", surface="#292c3c", panel="#414559",
        success="#a6d189", warning="#e5c890", error="#e78284",
        variables={
            "block-cursor-background": "#414559",
            "block-cursor-foreground": "#c6d0f5",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#414559",
        },
    ),
    Theme(
        name="catppuccin-macchiato", primary="#8aadf4", secondary="#c6a0f6", accent="#f5bde6",
        foreground="#cad3f5", background="#24273a", surface="#1e2030", panel="#363a4f",
        success="#a6da95", warning="#eed49f", error="#ed8796",
        variables={
            "block-cursor-background": "#363a4f",
            "block-cursor-foreground": "#cad3f5",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#363a4f",
        },
    ),
    Theme(
        name="rose-pine-moon", primary="#9ccfd8", secondary="#c4a7e7", accent="#ea9a97",
        foreground="#e0def4", background="#232136", surface="#2a273f", panel="#393552",
        success="#9ccfd8", warning="#f6c177", error="#eb6f92",
        variables={
            "block-cursor-background": "#393552",
            "block-cursor-foreground": "#e0def4",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#393552",
        },
    ),
    Theme(
        name="kanagawa-dragon", primary="#8ba4b0", secondary="#8992a7", accent="#c4b28a",
        foreground="#c5c9c5", background="#181616", surface="#12120f", panel="#282727",
        success="#87a987", warning="#c4b28a", error="#c4746e",
        variables={
            "block-cursor-background": "#282727",
            "block-cursor-foreground": "#c5c9c5",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#282727",
        },
    ),
)


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
