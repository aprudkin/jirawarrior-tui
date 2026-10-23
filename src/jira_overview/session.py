"""Own the asynchronous lifecycle and accepted view for one Jira overview."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from .core import Issue, Jira, OverviewError, Snapshot, State


@dataclass(frozen=True)
class ReviewItem:
    issue: Issue
    new: bool
    unread_comments: int


@dataclass(frozen=True)
class ReviewView:
    snapshot: Snapshot | None = None
    items: tuple[ReviewItem, ...] = ()
    display_name: str | None = None
    user_id: str | None = None
    updated_at: str | None = None
    refreshing: bool = False
    opening: bool = False
    refresh_error: str | None = None
    open_notice: str | None = None
    started: bool = False
    closed: bool = False


class ReviewSession:
    """One fixed Jira/account review; consumers observe only immutable views."""

    def __init__(self, jira: Jira, state_dir: Path, interval: float,
                 browser: Callable[[str], Awaitable[bool]], on_change: Callable[[], object] | None = None):
        self._jira, self._state_dir, self._interval = jira, state_dir, interval
        self._browser, self._on_change = browser, on_change
        self._state: State | None = None
        self._snapshot: Snapshot | None = None
        self._view = ReviewView()
        self._refresh_task: asyncio.Task | None = None
        self._open_task: asyncio.Task | None = None
        self._timer_task: asyncio.Task | None = None
        self._close_task: asyncio.Task | None = None
        self._started = False
        self._closing = False
        self._jira_closed = False

    @property
    def view(self) -> ReviewView:
        return self._view

    async def start(self) -> None:
        if self._closing:
            raise RuntimeError("session is closing")
        if self._started:
            return
        self._started = True
        self._replace_view(started=True)
        self.refresh()
        self._timer_task = asyncio.create_task(self._timer())

    def refresh(self) -> None:
        self._require_started()
        if self._closing or self._refresh_task is not None:
            return
        self._replace_view(refreshing=True)
        self._refresh_task = asyncio.create_task(self._refresh())

    def open(self, shown: Issue) -> None:
        self._require_started()
        if self._closing or self._open_task is not None:
            return
        self._replace_view(opening=True, open_notice=None)
        self._open_task = asyncio.create_task(self._open(shown))

    async def _timer(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._interval)
                self.refresh()
        except asyncio.CancelledError:
            pass

    async def _refresh(self) -> None:
        error = None
        try:
            snapshot = await self._jira.snapshot()
            if self._closing:
                return
            if self._state and self._state.user != snapshot.user_id:
                raise OverviewError("Учётная запись изменилась; перезапустите приложение для нового профиля.")
            if self._state is None:
                self._state = State(self._state_dir, self._jira.url, snapshot.user_id)
            self._state.ingest(snapshot)
            if self._closing:
                return
            self._snapshot = snapshot
            updated = datetime.now().astimezone().strftime("%H:%M:%S %Z")
            self._replace_view(snapshot=snapshot, items=self._items(), display_name=snapshot.display_name,
                               user_id=snapshot.user_id, updated_at=updated, refresh_error=None)
        except OverviewError as exc:
            error = str(exc)
            if not self._closing:
                self._replace_view(refresh_error=error)
        finally:
            self._refresh_task = None
            if not self._closing:
                self._replace_view(refreshing=False)

    async def _open(self, shown: Issue) -> None:
        try:
            if not await self._browser(self._jira.browser_url(shown)):
                raise OverviewError("Браузер не принял ссылку; отметки сохранены.")
            if self._closing:
                return
            if self._state is None:
                raise OverviewError("Локальное состояние недоступно; отметки НЕ сохранены.")
            self._state.acknowledge(shown)
            self._replace_view(items=self._items(), open_notice=(
                "Ссылка передана браузеру. Отмечен только показанный снимок, не чтение страницы."))
        except OverviewError as exc:
            if not self._closing:
                self._replace_view(open_notice=str(exc))
        finally:
            self._open_task = None
            if not self._closing:
                self._replace_view(opening=False)

    def _items(self) -> tuple[ReviewItem, ...]:
        if self._snapshot is None or self._state is None:
            return ()
        return tuple(ReviewItem(issue, *self._state.markers(issue)) for issue in self._snapshot.issues)

    def _replace_view(self, **changes) -> None:
        self._view = replace(self._view, **changes)
        if self._on_change is not None:
            self._on_change()

    def _require_started(self) -> None:
        if not self._started:
            raise RuntimeError("session has not started")

    async def aclose(self) -> None:
        if self._close_task is None:
            self._closing = True
            self._close_task = asyncio.create_task(self._cleanup())
        cancelled = False
        while not self._close_task.done():
            try:
                await asyncio.shield(self._close_task)
            except asyncio.CancelledError:
                cancelled = True
        await self._close_task
        if cancelled:
            raise asyncio.CancelledError

    async def _cleanup(self) -> None:
        for task in (self._timer_task, self._refresh_task, self._open_task):
            if task is not None and task is not asyncio.current_task():
                task.cancel()
        tasks = [task for task in (self._timer_task, self._refresh_task, self._open_task)
                 if task is not None and task is not asyncio.current_task()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._state is not None:
            self._state.close()
            self._state = None
        if not self._jira_closed:
            self._jira_closed = True
            await self._jira.close()
        self._replace_view(refreshing=False, opening=False, closed=True)
