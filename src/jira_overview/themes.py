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
    # Base16/Tinted adaptations: base00 background/cursor, base01 surfaces.
    # Stronger upstream text shades are used where base05 lacks contrast.
    Theme(
        name="atlas", primary="#14747e", secondary="#5dd7b9", accent="#9a70a4",
        foreground="#a1a19a", background="#002635", surface="#00384d", panel="#00384d",
        success="#7fc06e", warning="#ffcc1b", error="#ff6e79",
        variables={
            "block-cursor-background": "#002635",
            "block-cursor-foreground": "#a1a19a",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#002635",
        },
    ),
    Theme(
        name="ashes", primary="#ae95c7", secondary="#95aec7", accent="#c795ae",
        foreground="#c7ccd1", background="#1c2023", surface="#393f45", panel="#393f45",
        success="#95c7ae", warning="#aec795", error="#c7ae95",
        variables={
            "block-cursor-background": "#1c2023",
            "block-cursor-foreground": "#c7ccd1",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#1c2023",
        },
    ),
    Theme(
        name="bespin", primary="#5ea6ea", secondary="#afc4db", accent="#9b859d",
        foreground="#9d9b97", background="#28211c", surface="#36312e", panel="#36312e",
        success="#54be0d", warning="#f9ee98", error="#d8866e",
        variables={
            "block-cursor-background": "#28211c",
            "block-cursor-foreground": "#9d9b97",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#28211c",
        },
    ),
    Theme(
        name="brewer", primary="#3182bd", secondary="#80b1d3", accent="#756bb1",
        foreground="#b7b8b9", background="#0c0d0e", surface="#2e2f30", panel="#2e2f30",
        success="#31a354", warning="#dca060", error="#ee7172",
        variables={
            "block-cursor-background": "#0c0d0e",
            "block-cursor-foreground": "#b7b8b9",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#0c0d0e",
        },
    ),
    Theme(
        name="chalk", primary="#6fc2ef", secondary="#12cfc0", accent="#e1a3ee",
        foreground="#d0d0d0", background="#151515", surface="#202020", panel="#202020",
        success="#acc267", warning="#ddb26f", error="#fb9fb1",
        variables={
            "block-cursor-background": "#151515",
            "block-cursor-foreground": "#d0d0d0",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#151515",
        },
    ),
    Theme(
        name="darcula", primary="#9876aa", secondary="#629755", accent="#cc7832",
        foreground="#a9b7c6", background="#2b2b2b", surface="#323232", panel="#323232",
        success="#6a8759", warning="#bbb529", error="#4eade5",
        variables={
            "block-cursor-background": "#2b2b2b",
            "block-cursor-foreground": "#a9b7c6",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#2b2b2b",
        },
    ),
    Theme(
        name="eighties", primary="#6699cc", secondary="#66cccc", accent="#cc99cc",
        foreground="#d3d0c8", background="#2d2d2d", surface="#393939", panel="#393939",
        success="#99cc99", warning="#ffcc66", error="#f38386",
        variables={
            "block-cursor-background": "#2d2d2d",
            "block-cursor-foreground": "#d3d0c8",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#2d2d2d",
        },
    ),
    Theme(
        name="embers", primary="#6d5782", secondary="#576d82", accent="#82576d",
        foreground="#a39a90", background="#16130f", surface="#2c2620", panel="#2c2620",
        success="#57826d", warning="#6d8257", error="#9e8d7c",
        variables={
            "block-cursor-background": "#16130f",
            "block-cursor-foreground": "#a39a90",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#16130f",
        },
    ),
    Theme(
        name="espresso", primary="#6c99bb", secondary="#bed6ff", accent="#d197d9",
        foreground="#cccccc", background="#2d2d2d", surface="#393939", panel="#393939",
        success="#a5c261", warning="#ffc66d", error="#e18d8d",
        variables={
            "block-cursor-background": "#2d2d2d",
            "block-cursor-foreground": "#cccccc",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#2d2d2d",
        },
    ),
    Theme(
        name="flat", primary="#3498db", secondary="#1abc9c", accent="#9b59b6",
        foreground="#e0e0e0", background="#2c3e50", surface="#34495e", panel="#34495e",
        success="#2ecc71", warning="#f1c40f", error="#f3a29a",
        variables={
            "block-cursor-background": "#2c3e50",
            "block-cursor-foreground": "#e0e0e0",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#2c3e50",
        },
    ),
    Theme(
        name="github-dark-dimmed", primary="#539bf5", secondary="#39c5cf", accent="#b083f0",
        foreground="#d1d7e0", background="#0d1117", surface="#151b23", panel="#151b23",
        success="#57ab5a", warning="#c69026", error="#f47067",
        variables={
            "block-cursor-background": "#0d1117",
            "block-cursor-foreground": "#d1d7e0",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#0d1117",
        },
    ),
    Theme(
        name="gruvbox-material-dark-medium", primary="#7daea3", secondary="#89b482", accent="#d3869b",
        foreground="#ddc7a1", background="#292828", surface="#32302f", panel="#32302f",
        success="#a9b665", warning="#d8a657", error="#ec7770",
        variables={
            "block-cursor-background": "#292828",
            "block-cursor-foreground": "#ddc7a1",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#292828",
        },
    ),
    Theme(
        name="horizon-dark", primary="#df5273", secondary="#24a8b4", accent="#b072d1",
        foreground="#cbced0", background="#1c1e26", surface="#232530", panel="#232530",
        success="#efaf8e", warning="#efb993", error="#ed5b73",
        variables={
            "block-cursor-background": "#1c1e26",
            "block-cursor-foreground": "#cbced0",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#1c1e26",
        },
    ),
    Theme(
        name="material", primary="#82aaff", secondary="#89ddff", accent="#c792ea",
        foreground="#eeffff", background="#263238", surface="#2e3c43", panel="#2e3c43",
        success="#c3e88d", warning="#ffcb6b", error="#f2858b",
        variables={
            "block-cursor-background": "#263238",
            "block-cursor-foreground": "#eeffff",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#263238",
        },
    ),
    Theme(
        name="material-darker", primary="#82aaff", secondary="#89ddff", accent="#c792ea",
        foreground="#eeffff", background="#212121", surface="#303030", panel="#303030",
        success="#c3e88d", warning="#ffcb6b", error="#f07178",
        variables={
            "block-cursor-background": "#212121",
            "block-cursor-foreground": "#eeffff",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#212121",
        },
    ),
    Theme(
        name="material-palenight", primary="#82aaff", secondary="#89ddff", accent="#c792ea",
        foreground="#ffffff", background="#292d3e", surface="#444267", panel="#444267",
        success="#c3e88d", warning="#ffcb6b", error="#f59da2",
        variables={
            "block-cursor-background": "#292d3e",
            "block-cursor-foreground": "#ffffff",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#292d3e",
        },
    ),
    Theme(
        name="oceanicnext", primary="#6699cc", secondary="#5fb3b3", accent="#c594c5",
        foreground="#c0c5ce", background="#1b2b34", surface="#343d46", panel="#343d46",
        success="#99c794", warning="#fac863", error="#f18a90",
        variables={
            "block-cursor-background": "#1b2b34",
            "block-cursor-foreground": "#c0c5ce",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#1b2b34",
        },
    ),
    Theme(
        name="spaceduck", primary="#7a5ccc", secondary="#00a3cc", accent="#b3a1e6",
        foreground="#ecf0c1", background="#16172d", surface="#1b1c36", panel="#1b1c36",
        success="#5ccc96", warning="#f2ce00", error="#e8572b",
        variables={
            "block-cursor-background": "#16172d",
            "block-cursor-foreground": "#ecf0c1",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#16172d",
        },
    ),
    Theme(
        name="tomorrow-night", primary="#81a2be", secondary="#8abeb7", accent="#b294bb",
        foreground="#c5c8c6", background="#1d1f21", surface="#282a2e", panel="#282a2e",
        success="#b5bd68", warning="#f0c674", error="#d37a7a",
        variables={
            "block-cursor-background": "#1d1f21",
            "block-cursor-foreground": "#c5c8c6",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#1d1f21",
        },
    ),
    Theme(
        name="zenburn", primary="#7cb8bb", secondary="#93e0e3", accent="#dc8cc3",
        foreground="#dcdccc", background="#383838", surface="#404040", panel="#404040",
        success="#5f7f5f", warning="#e0cf9f", error="#dca3a3",
        variables={
            "block-cursor-background": "#383838",
            "block-cursor-foreground": "#dcdccc",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#383838",
        },
    ),
    Theme(
        name="ayu-light", primary="#399ee6", secondary="#4cbf99", accent="#a37acc",
        foreground="#5c6166", background="#f8f9fa", surface="#edeff1", panel="#edeff1",
        success="#6cbf49", warning="#f2ae49", error="#a84f4f", dark=False,
        variables={
            "block-cursor-background": "#f8f9fa",
            "block-cursor-foreground": "#5c6166",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#f8f9fa",
        },
    ),
    Theme(
        name="github-light", primary="#0969da", secondary="#1b7c83", accent="#8250df",
        foreground="#454c54", background="#ffffff", surface="#f6f8fa", panel="#f6f8fa",
        success="#116329", warning="#9a6700", error="#cf222e", dark=False,
        variables={
            "block-cursor-background": "#ffffff",
            "block-cursor-foreground": "#454c54",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#ffffff",
        },
    ),
    Theme(
        name="gruvbox-material-light-medium", primary="#45707a", secondary="#4c7a5d", accent="#945e80",
        foreground="#654735", background="#fbf1c7", surface="#f2e5bc", panel="#f2e5bc",
        success="#6c782e", warning="#b47109", error="#ac4242", dark=False,
        variables={
            "block-cursor-background": "#fbf1c7",
            "block-cursor-foreground": "#654735",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#fbf1c7",
        },
    ),
    Theme(
        name="horizon-light", primary="#da103f", secondary="#dc3318", accent="#1d8991",
        foreground="#403c3d", background="#fdf0ed", surface="#fadad1", panel="#fadad1",
        success="#94e1b0", warning="#fbe0d9", error="#8a5257", dark=False,
        variables={
            "block-cursor-background": "#fdf0ed",
            "block-cursor-foreground": "#403c3d",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#fdf0ed",
        },
    ),
    Theme(
        name="material-lighter", primary="#6182b8", secondary="#39adb5", accent="#7c4dff",
        foreground="#000000", background="#fafafa", surface="#e7eaec", panel="#e7eaec",
        success="#91b859", warning="#ffb62c", error="#b53b50", dark=False,
        variables={
            "block-cursor-background": "#fafafa",
            "block-cursor-foreground": "#000000",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#fafafa",
        },
    ),
    Theme(
        name="one-light", primary="#4078f2", secondary="#0184bc", accent="#a626a4",
        foreground="#383a42", background="#fafafa", surface="#f0f0f1", panel="#f0f0f1",
        success="#50a14f", warning="#c18401", error="#ca1243", dark=False,
        variables={
            "block-cursor-background": "#fafafa",
            "block-cursor-foreground": "#383a42",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#fafafa",
        },
    ),
    Theme(
        name="papercolor-light", primary="#005f87", secondary="#0087af", accent="#8700af",
        foreground="#444444", background="#eeeeee", surface="#c4c4c4", panel="#c4c4c4",
        success="#008700", warning="#d75f00", error="#a30000", dark=False,
        variables={
            "block-cursor-background": "#eeeeee",
            "block-cursor-foreground": "#444444",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#eeeeee",
        },
    ),
    Theme(
        name="selenized-light", primary="#006dce", secondary="#00978a", accent="#825dc0",
        foreground="#53676d", background="#fbf3db", surface="#ece3cc", panel="#ece3cc",
        success="#428b00", warning="#a78300", error="#c61628", dark=False,
        variables={
            "block-cursor-background": "#fbf3db",
            "block-cursor-foreground": "#53676d",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#fbf3db",
        },
    ),
    Theme(
        name="tomorrow", primary="#4271ae", secondary="#3e999f", accent="#8959a8",
        foreground="#373b41", background="#ffffff", surface="#e0e0e0", panel="#e0e0e0",
        success="#718c00", warning="#eab700", error="#bc2627", dark=False,
        variables={
            "block-cursor-background": "#ffffff",
            "block-cursor-foreground": "#373b41",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#ffffff",
        },
    ),
    Theme(
        name="atelier-sulphurpool-light", primary="#3d8fd1", secondary="#22a2c9", accent="#6679cc",
        foreground="#293256", background="#f5f7ff", surface="#dfe2f1", panel="#dfe2f1",
        success="#ac9739", warning="#c08b30", error="#ad3f1d", dark=False,
        variables={
            "block-cursor-background": "#f5f7ff",
            "block-cursor-foreground": "#293256",
            "block-cursor-text-style": "none",
            "block-cursor-blurred-background": "#f5f7ff",
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
