"""Textual UI; refresh and browser handoff never block terminal input."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import time
from typing import Awaitable, Callable

from rich.spinner import Spinner
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, OptionList, Static
from textual.widgets.option_list import Option

from .core import Issue, Jira, OverviewError, Sprint
from .processes import LockOwner
from .presentation import IssueActivated, IssueTable, OverviewPresentation
from .session import ReviewSession
from .settings import (DEFAULT_REFRESH_SECONDS, read_refresh_seconds,
                       validate_refresh_seconds, write_refresh_seconds)
from .themes import ADDITIONAL_THEMES, ThemePanel, read_theme, write_theme


async def open_browser(url: str) -> bool:
    command = ["/usr/bin/open", url] if sys.platform == "darwin" else ["xdg-open", url]
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        return await asyncio.wait_for(process.wait(), timeout=10) == 0
    except (OSError, TimeoutError):
        return False
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()


class IntervalInput(Input):
    """Keep the sidebar's shortcuts available while entering a number."""
    def check_consume_key(self, key: str, character: str | None) -> bool:
        return key not in {"q", "r", "s", "S", "t", "T"} and super().check_consume_key(key, character)


class SettingsPanel(Vertical):
    """Docked settings list with an explicit, cancellable interval editor."""
    BINDINGS = [Binding("escape", "app.cancel_settings", "Отменить", priority=True),
                Binding("s", "app.toggle_settings", "Настройки", priority=True),
                Binding("S", "app.toggle_settings", show=False, priority=True),
                Binding("t", "app.toggle_themes", "Темы", priority=True),
                Binding("T", "app.toggle_themes", show=False, priority=True),
                Binding("r", "app.refresh", "Обновить", priority=True),
                Binding("q", "app.quit", "Выход", priority=True),
                Binding("ctrl+c", "app.quit", show=False, priority=True)]
    DEFAULT_CSS = """
    SettingsPanel {
        display: none;
        width: 32;
        max-width: 55%;
        height: 1fr;
        border-left: solid $border;
        background: $surface;
        padding: 0 1;
    }
    #settings-heading { height: 1; margin-bottom: 1; }
    #settings-title { width: 1fr; text-style: bold; }
    #settings-close { width: 3; min-width: 3; height: 1; border: none; padding: 0; }
    #settings-list { height: auto; border: none; padding: 0; }
    #interval-editor { display: none; height: auto; }
    #interval-label, #settings-error { height: auto; }
    #settings-error { display: none; color: $error; }
    #settings-hints { height: auto; margin-top: 1; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="settings-heading"):
            yield Static("Настройки", id="settings-title")
            yield Button("×", id="settings-close", tooltip="Закрыть настройки")
        yield OptionList(id="settings-list", markup=False, compact=True)
        with Vertical(id="interval-editor"):
            yield Static("Интервал в минутах (1/12–1440)", id="interval-label")
            yield IntervalInput(id="refresh-minutes", placeholder="60", select_on_focus=True)
            yield Static("", id="settings-error", markup=False)
        yield Static("Enter изменить / сохранить\nEsc / s / × отменить", id="settings-hints")


class OwnerConfirmation(ModalScreen[bool]):
    """Finding a process is not consent to stop it; cancellation is the default."""
    BINDINGS = [Binding("escape", "cancel", "Отмена", priority=True),
                Binding("q", "app.quit", "Выход", priority=True),
                Binding("ctrl+c", "app.quit", show=False, priority=True)]
    DEFAULT_CSS = """
    OwnerConfirmation { align: center middle; }
    #owner-dialog {
        width: 56; max-width: 95%; height: auto;
        border: thick $primary; background: $surface; padding: 1 2;
    }
    #owner-question { height: auto; margin-bottom: 1; }
    #owner-buttons { height: 3; }
    #owner-buttons Button { width: 1fr; min-width: 8; }
    """

    def __init__(self, owner: LockOwner):
        super().__init__()
        self.owner = owner

    def compose(self) -> ComposeResult:
        with Vertical(id="owner-dialog"):
            yield Static(f"Найден другой Jira Warrior: PID {self.owner.pid}.\n\n"
                         "Завершить его и загрузить обзор здесь?\n"
                         "Будет отправлен SIGINT. История и файлы не удаляются.",
                         id="owner-question", markup=False)
            with Horizontal(id="owner-buttons"):
                yield Button("Завершить", id="stop-owner", variant="error")
                yield Button("Отмена", id="cancel-owner")

    def on_mount(self):
        self.query_one("#cancel-owner", Button).focus()

    def action_cancel(self):
        self.dismiss(False)

    @on(Button.Pressed)
    def choose(self, event: Button.Pressed):
        self.dismiss(event.button.id == "stop-owner")


class SprintChoice(ModalScreen[Sprint | None]):
    """An explicit sprint choice is the write action; cancellation is the default."""
    BINDINGS = [Binding("escape", "cancel", "Отмена", priority=True),
                Binding("q", "app.quit", "Выход", priority=True),
                Binding("ctrl+c", "app.quit", show=False, priority=True)]
    DEFAULT_CSS = """
    SprintChoice { align: center middle; }
    #sprint-dialog {
        width: 64; max-width: 95%; height: auto; max-height: 90%;
        border: thick $primary; background: $surface; padding: 1 2;
    }
    #sprint-question { height: auto; }
    #sprint-choices { height: auto; max-height: 10; }
    #cancel-sprint { height: 3; }
    """

    def __init__(self, shown: Issue, choices: tuple[Sprint, ...]):
        super().__init__()
        self.shown, self.choices = shown, choices

    def compose(self) -> ComposeResult:
        with Vertical(id="sprint-dialog"):
            yield Static(f"Добавить {self.shown.key} в спринт:\n"
                         "Enter по спринту сразу изменит Jira.", id="sprint-question", markup=False)
            yield OptionList(*(Option(f"{sprint.name} (#{sprint.id})", id=sprint.id)
                               for sprint in self.choices), id="sprint-choices", markup=False)
            yield Button("Отмена", id="cancel-sprint")

    def on_mount(self):
        self.query_one("#cancel-sprint", Button).focus()

    def action_cancel(self):
        self.dismiss(None)

    @on(Button.Pressed, "#cancel-sprint")
    def cancel_button(self):
        self.action_cancel()

    @on(OptionList.OptionSelected, "#sprint-choices")
    def choose(self, event: OptionList.OptionSelected):
        self.dismiss(next(sprint for sprint in self.choices if sprint.id == event.option_id))


class Overview(App):
    TITLE = "Jira — мои задачи"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { layout: vertical; }
    #body { height: 1fr; }
    #overview { width: 1fr; }
    #connection, #notice { height: auto; max-height: 4; }
    #notice { display: none; }
    Footer { height: 1; }
    """
    BINDINGS = [("q", "quit", "Выход"), ("r", "refresh", "Обновить"),
                ("a", "add_to_sprint", "Спринт"),
                Binding("A", "add_to_sprint", show=False),
                ("e", "toggle_epics", "Эпики"),
                Binding("е", "toggle_epics", show=False),
                ("t", "toggle_themes", "Темы"),
                Binding("T", "toggle_themes", show=False),
                ("s", "toggle_settings", "Настройки"),
                Binding("S", "toggle_settings", show=False),
                ("p", "find_other_instance", "Найти экземпляр"),
                Binding("P", "find_other_instance", show=False),
                ("tab", "focus_next", "Область"), ("enter", "noop", "Открыть")]

    def __init__(self, jira: Jira, state_dir: Path, interval: float = DEFAULT_REFRESH_SECONDS,
                 browser: Callable[[str], Awaitable[bool]] = open_browser):
        super().__init__()
        for theme in ADDITIONAL_THEMES:
            self.register_theme(theme)
        self.session = ReviewSession(jira, state_dir, interval, browser, self.session_changed)
        self._refresh_spinner = Spinner("dots", text="Updating", style="magenta")
        self._theme_path = state_dir / "theme.json"
        self._theme_before_preview = None
        self._settings_open = False
        self._settings_path = state_dir / "settings.json"
        self._owner_dialog: OwnerConfirmation | None = None
        self._sprint_navigation = False
        self._sprint_dialog: SprintChoice | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="overview"):
                yield Static("Загрузка Jira…", id="connection", markup=False)
                yield Static("", id="notice", markup=False)
                yield OverviewPresentation(id="presentation")
            yield ThemePanel(self.available_themes, id="themes")
            yield SettingsPanel(id="settings")
        yield Footer()

    def on_mount(self):
        try:
            saved_theme = read_theme(self._theme_path, self.available_themes)
            if saved_theme is not None:
                self.theme = saved_theme
        except OverviewError as error:
            self.notify(str(error), title="Темы", severity="warning")
        try:
            saved_interval = read_refresh_seconds(self._settings_path)
            if saved_interval is not None:
                self.session.set_interval(saved_interval)
        except OverviewError as error:
            self.notify(str(error), title="Настройки", severity="warning")
        self.set_interval(0.08, self.animate_refresh)
        self.run_worker(self.session.start(), group="session", exit_on_error=False)

    @property
    def refreshing(self):
        return self.session.view.refreshing

    @property
    def opening(self):
        return self.session.view.opening

    @property
    def snapshot(self):
        return self.session.view.snapshot

    def session_changed(self):
        if self.is_mounted and self.is_running:
            self.paint_view()
            self.refresh_bindings()
            view = self.session.view
            presentation = self.query_one(OverviewPresentation)
            sprint_active = view.sprint_busy or bool(view.sprint_choices)
            if sprint_active and not self._sprint_navigation:
                self._sprint_navigation = True
                presentation.suspend_navigation()
            elif not sprint_active and self._sprint_navigation:
                self._sprint_navigation = False
                presentation.resume_navigation()
            if view.sprint_issue is not None and view.sprint_choices and self._sprint_dialog is None:
                shown = view.sprint_issue
                self._sprint_dialog = SprintChoice(shown, view.sprint_choices)
                self.push_screen(self._sprint_dialog, lambda target: self._sprint_decision(shown, target))
            if (view.lock_owner is not None and not view.recovery_busy
                    and self._owner_dialog is None):
                owner = view.lock_owner
                self._owner_dialog = OwnerConfirmation(owner)
                self.push_screen(self._owner_dialog,
                                 lambda confirmed: self._owner_decision(owner, confirmed))
            elif (not view.profile_busy and self._owner_dialog is not None
                  and self._owner_dialog.is_mounted):
                self._owner_dialog.dismiss(False)

    def _sprint_decision(self, shown: Issue, target: Sprint | None):
        self._sprint_dialog = None
        if target is None:
            self.session.cancel_sprint()
        else:
            self.session.add_to_sprint(shown, target)

    def _owner_decision(self, owner: LockOwner, confirmed: bool | None):
        self._owner_dialog = None
        if confirmed:
            self.session.stop_lock_owner(owner)
        else:
            self.session.cancel_lock_recovery()

    def action_find_other_instance(self):
        if not self._panel_open and self._owner_dialog is None:
            self.session.find_lock_owner()

    def action_noop(self):
        pass

    @property
    def _panel_open(self):
        return self._theme_before_preview is not None or self._settings_open

    def check_action(self, action, parameters):
        if ((self._owner_dialog is not None or self._sprint_dialog is not None)
                and action not in {"quit", "focus_next", "focus_previous"}):
            return False
        if self.session.view.sprint_busy and action not in {"quit", "refresh"}:
            return False
        if action == "add_to_sprint" and self._panel_open:
            return False
        if action == "find_other_instance":
            view = self.session.view
            return (view.profile_busy and not view.refreshing and not view.recovery_busy
                    and not self._panel_open)
        if action == "toggle_epics" and self._panel_open:
            return False
        return True

    def action_change_theme(self):
        # Replace Textual's other palette-based entry point as well.
        self.action_toggle_themes()

    def action_toggle_themes(self):
        if self._theme_before_preview is not None:
            self.action_cancel_theme()
            return
        if self._settings_open:
            self.query_one("#settings").display = False
            self._settings_open = False
        else:
            self._capture_panel_focus()
        self._theme_before_preview = self.theme
        self.query_one("#themes").display = True
        choices = self.query_one("#theme-list", OptionList)
        choices.highlighted = choices.get_option_index(self.current_theme.name)
        choices.focus()
        self.call_after_refresh(choices.scroll_to_highlight)

    @on(OptionList.OptionHighlighted, "#theme-list")
    def preview_theme(self, event: OptionList.OptionHighlighted):
        if self._theme_before_preview is not None and event.option_id is not None:
            self.theme = event.option_id

    @on(Button.Pressed, "#theme-close")
    def cancel_theme_button(self):
        self.action_cancel_theme()

    def action_confirm_theme(self):
        if self._theme_before_preview is None:
            return
        option = self.query_one("#theme-list", OptionList).highlighted_option
        if option is None or option.id is None:
            return
        try:
            write_theme(self._theme_path, option.id)
        except OverviewError as error:
            self.notify(str(error), title="Темы", severity="error")
            return
        self.theme = option.id
        self._close_themes()

    def action_cancel_theme(self):
        if self._theme_before_preview is not None:
            self.theme = self._theme_before_preview
            self._close_themes()

    def _close_themes(self):
        self.query_one("#themes").display = False
        self._theme_before_preview = None
        self._restore_panel_focus()

    def _capture_panel_focus(self):
        self.query_one(OverviewPresentation).suspend_navigation()

    def _restore_panel_focus(self):
        self.query_one(OverviewPresentation).resume_navigation()

    def action_toggle_settings(self):
        if self._settings_open:
            self.action_cancel_settings()
            return
        if self._theme_before_preview is not None:
            self.theme = self._theme_before_preview
            self._theme_before_preview = None
            self.query_one("#themes").display = False
        else:
            self._capture_panel_focus()
        self._settings_open = True
        self.query_one("#settings").display = True
        self.query_one("#interval-editor").display = False
        self.query_one("#settings-error").display = False
        choices = self.query_one("#settings-list", OptionList)
        choices.clear_options()
        choices.add_option(Option(f"Интервал обновления: {self.session.interval / 60:g} мин",
                                  id="refresh-interval"))
        choices.highlighted = 0
        choices.focus()

    @on(Button.Pressed, "#settings-close")
    def close_settings_button(self):
        self.action_cancel_settings()

    def action_cancel_settings(self):
        if self._settings_open:
            self.query_one("#settings").display = False
            self._settings_open = False
            self._restore_panel_focus()

    @on(OptionList.OptionSelected, "#settings-list")
    def edit_interval(self, event: OptionList.OptionSelected):
        if not self._settings_open:
            return
        self.query_one("#interval-editor").display = True
        editor = self.query_one("#refresh-minutes", Input)
        editor.value = str(self.session.interval / 60).removesuffix(".0")
        editor.focus()

    @on(Input.Submitted, "#refresh-minutes")
    def save_interval(self, event: Input.Submitted):
        if not self._settings_open:
            return
        error = self.query_one("#settings-error", Static)
        try:
            minutes = float(event.value)
            # Keep an unchanged legacy value exact despite float division/multiplication.
            interval = validate_refresh_seconds(
                self.session.interval if minutes == self.session.interval / 60 else minutes * 60)
        except ValueError:
            error.update("Введите число от 0.08333333333333333 до 1440 минут.")
            error.display = True
            return
        try:
            write_refresh_seconds(self._settings_path, interval)
        except OverviewError as exc:
            error.update(str(exc))
            error.display = True
            return
        self.session.set_interval(interval)
        self.action_cancel_settings()

    def action_add_to_sprint(self):
        if (self._panel_open or self._owner_dialog is not None or self._sprint_dialog is not None
                or self.session.view.sprint_busy):
            return
        shown = self.query_one(OverviewPresentation).selected_issue
        if shown is None:
            self.notify("Сначала выберите задачу в обзоре.", title="Спринт", severity="warning")
            return
        self.session.add_to_sprint(shown)

    def action_refresh(self):
        self.session.refresh()

    def action_toggle_epics(self):
        if self._panel_open:
            return
        self.query_one(OverviewPresentation).toggle_epics()

    def paint_view(self):
        view = self.session.view
        if view.closed or not self.is_mounted or not self.is_running:
            return
        if view.snapshot is not None:
            self.query_one(OverviewPresentation).present(view.items)
        self.paint_connection()
        notice = self.query_one("#notice", Static)
        message = (view.recovery_notice or view.sprint_notice or view.open_notice or
                   ("P — найти другой экземпляр и предложить завершение" if view.profile_busy else ""))
        notice.update(message)
        notice.display = bool(message)

    def animate_refresh(self):
        if self.session.view.refreshing:
            self.paint_connection()

    def paint_connection(self):
        view = self.session.view
        if view.closed or not self.is_mounted or not self.is_running:
            return
        if view.display_name is not None:
            freshness = (f"УСТАРЕЛО: {view.updated_at} | {view.refresh_error}"
                         if view.refresh_error else f"Обновлено {view.updated_at}")
            status = Text(f"Jira Warrior: {view.display_name} | {freshness}")
        elif view.refresh_error:
            status = Text(f"НЕТ УСПЕШНОЙ ЗАГРУЗКИ | {view.refresh_error}")
        else:
            status = Text("Загрузка Jira…")
        if view.refreshing:
            status.append(" | ")
            status.append_text(self._refresh_spinner.render(time.monotonic()))
        elif view.next_refresh_at is not None:
            status.append(f" | Следующее обновление {view.next_refresh_at}")
        self.query_one("#connection", Static).update(status)

    def on_issue_activated(self, event: IssueActivated):
        if not self._panel_open:
            self.session.open(event.shown)

    async def on_unmount(self):
        await self.session.aclose()
