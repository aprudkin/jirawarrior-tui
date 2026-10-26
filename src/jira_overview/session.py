"""Own the asynchronous lifecycle and accepted view for one Jira overview."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
import math
from pathlib import Path
import time
from typing import Awaitable, Callable

from .core import Issue, Jira, OverviewError, ProfileBusy, Snapshot, State
from .processes import LockOwner, find_lock_owner, stop_lock_owner
from .settings import validate_refresh_seconds


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
    next_refresh_at: str | None = None
    refreshing: bool = False
    opening: bool = False
    refresh_error: str | None = None
    open_notice: str | None = None
    profile_busy: bool = False
    lock_owner: LockOwner | None = None
    recovery_busy: bool = False
    recovery_notice: str | None = None
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
        self._recovery_task: asyncio.Task | None = None
        self._conflict_path: Path | None = None
        self._started = False
        self._closing = False
        self._refresh_busy = False
        self._open_busy = False
        self._jira_closed = False
        self._next_tick: float | None = None
        self._timer_changed = asyncio.Event()

    @property
    def interval(self) -> float:
        return self._interval

    def set_interval(self, interval: float) -> None:
        interval = validate_refresh_seconds(interval)
        if self._closing:
            raise RuntimeError("session is closing")
        if interval == self._interval:
            return
        self._interval = interval
        if self._started:
            self._next_tick = time.monotonic() + interval
            self._timer_changed.set()
            self._replace_view(next_refresh_at=self._scheduled_refresh())

    @property
    def view(self) -> ReviewView:
        return self._view

    async def start(self) -> None:
        if self._closing:
            raise RuntimeError("session is closing")
        if self._started:
            return
        self._started = True
        self._next_tick = time.monotonic() + self._interval
        self._replace_view(started=True, next_refresh_at=self._scheduled_refresh())
        self.refresh()
        self._timer_task = asyncio.create_task(self._timer())

    def refresh(self) -> None:
        self._require_started()
        if (self._closing or self._refresh_busy or self._view.recovery_busy
                or self._view.lock_owner is not None):
            return
        self._refresh_busy = True
        self._replace_view(refreshing=True)
        self._refresh_task = asyncio.create_task(self._refresh())

    def open(self, shown: Issue) -> None:
        self._require_started()
        if self._closing or self._open_busy:
            return
        self._open_busy = True
        self._replace_view(opening=True, open_notice=None)
        self._open_task = asyncio.create_task(self._open(shown))

    def find_lock_owner(self) -> None:
        self._require_started()
        if (self._closing or self._refresh_busy or self._view.recovery_busy
                or not self._view.profile_busy):
            return
        self._replace_view(recovery_busy=True, lock_owner=None, recovery_notice="Поиск другого экземпляра…")
        self._recovery_task = asyncio.create_task(self._recover())

    def cancel_lock_recovery(self) -> None:
        if not self._closing:
            self._replace_view(lock_owner=None, recovery_notice=None)

    def stop_lock_owner(self, owner: LockOwner) -> None:
        self._require_started()
        if (self._closing or self._refresh_busy or self._view.recovery_busy or not self._view.profile_busy
                or owner != self._view.lock_owner):
            return
        self._replace_view(recovery_busy=True, lock_owner=None,
                           recovery_notice=f"Завершение экземпляра PID {owner.pid}…")
        self._recovery_task = asyncio.create_task(self._recover(owner))

    async def _recover(self, confirmed: LockOwner | None = None) -> None:
        path = self._conflict_path
        retry = False
        try:
            if path is None:
                return
            if confirmed is None:
                owner = await find_lock_owner(path)
                if not self._closing and path == self._conflict_path:
                    self._replace_view(lock_owner=owner, recovery_notice=None)
                    retry = owner is None
            else:
                await stop_lock_owner(path, confirmed)
                if not self._closing:
                    self._replace_view(recovery_notice=None)
                    retry = True
        except OverviewError as exc:
            if not self._closing:
                self._replace_view(lock_owner=None, recovery_notice=str(exc))
        finally:
            self._recovery_task = None
            if not self._closing:
                self._replace_view(recovery_busy=False)
                if retry:
                    self.refresh()

    def _scheduled_refresh(self) -> str | None:
        if self._next_tick is None:
            return None
        deadline = self._next_tick
        if self._jira.retry_at > deadline:
            deadline += math.ceil((self._jira.retry_at - deadline) / self._interval) * self._interval
        return datetime.fromtimestamp(time.time() + max(0, deadline - time.monotonic())).astimezone().strftime(
            "%H:%M:%S %Z")

    async def _timer(self) -> None:
        try:
            while True:
                self._timer_changed.clear()
                try:
                    await asyncio.wait_for(self._timer_changed.wait(),
                                           timeout=max(0, self._next_tick - time.monotonic()))
                    continue
                except TimeoutError:
                    if time.monotonic() < self._next_tick:
                        continue
                self._next_tick = time.monotonic() + self._interval
                self._replace_view(next_refresh_at=self._scheduled_refresh())
                # Keep the cadence, but don't animate a request that cannot run.
                if time.monotonic() >= self._jira.retry_at:
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
            self._conflict_path = None
            self._replace_view(snapshot=snapshot, items=self._items(), display_name=snapshot.display_name,
                               user_id=snapshot.user_id, updated_at=updated, refresh_error=None,
                               profile_busy=False, lock_owner=None, recovery_notice=None)
        except OverviewError as exc:
            error = str(exc)
            if not self._closing:
                self._conflict_path = exc.lock_path if isinstance(exc, ProfileBusy) else None
                self._replace_view(refresh_error=error, profile_busy=isinstance(exc, ProfileBusy),
                                   lock_owner=None)
        finally:
            self._refresh_task = None
            self._refresh_busy = False
            if not self._closing:
                self._replace_view(refreshing=False, next_refresh_at=self._scheduled_refresh())

    async def _open(self, shown: Issue) -> None:
        try:
            if not await self._browser(self._jira.browser_url(shown)):
                raise OverviewError("Браузер не принял ссылку; отметки сохранены.")
            if self._closing:
                return
            if self._state is None:
                raise OverviewError("Локальное состояние недоступно; отметки НЕ сохранены.")
            self._state.acknowledge(shown)
            self._replace_view(items=self._items())
        except OverviewError as exc:
            if not self._closing:
                self._replace_view(open_notice=str(exc))
        finally:
            self._open_task = None
            self._open_busy = False
            if not self._closing:
                self._replace_view(opening=False)

    def _items(self) -> tuple[ReviewItem, ...]:
        if self._snapshot is None or self._state is None:
            return ()
        return tuple(ReviewItem(issue, *self._state.markers(issue)) for issue in self._snapshot.issues)

    def _replace_view(self, **changes) -> None:
        self._view = replace(self._view, **changes)
        if self._on_change is not None and not self._closing:
            self._on_change()

    def _require_started(self) -> None:
        if not self._started:
            raise RuntimeError("session has not started")

    async def aclose(self) -> None:
        if self._close_task is None:
            self._closing = True
            self._close_task = asyncio.create_task(self._cleanup())
        if self._close_task.done():
            self._close_task.result()
            return
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
        for task in (self._timer_task, self._refresh_task, self._open_task, self._recovery_task):
            if task is not None and task is not asyncio.current_task():
                task.cancel()
        tasks = [task for task in (self._timer_task, self._refresh_task, self._open_task, self._recovery_task)
                 if task is not None and task is not asyncio.current_task()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._state is not None:
            self._state.close()
            self._state = None
        if not self._jira_closed:
            self._jira_closed = True
            await self._jira.close()
        self._view = replace(self._view, refreshing=False, opening=False, recovery_busy=False,
                             lock_owner=None, next_refresh_at=None, closed=True)
