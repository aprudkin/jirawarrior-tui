"""Read-only Jira boundary and transactional, profile-local unread state."""
from __future__ import annotations

import asyncio
import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlsplit

import httpx


class OverviewError(Exception):
    """Safe to display: never contains an HTTP body, URL, token or raw exception."""


class ProfileBusy(OverviewError):
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        super().__init__("Другой экземпляр уже использует этот профиль.")


class RateLimited(OverviewError):
    def __init__(self, seconds: float):
        self.seconds = seconds
        super().__init__(f"Ограничение частоты (429). Повтор не раньше чем через {seconds:.0f} с.")


def plain(value: str) -> str:
    # Remove terminal controls, bidi/format controls and surrogates; Rich markup
    # is disabled separately at the rendering boundary.
    return "".join(c if not unicodedata.category(c).startswith("C") else " " for c in value)


def identity(user: dict) -> str:
    for field in ("accountId", "key", "name"):
        if isinstance(user.get(field), str) and user[field]:
            return field + ":" + user[field]
    raise OverviewError("Неполная идентичность пользователя Jira.")


def required_text(obj: dict, key: str) -> str:
    value = obj[key]
    if not isinstance(value, str) or not value:
        raise ValueError(key)
    return value


@dataclass(frozen=True)
class Issue:
    id: str
    key: str
    summary: str
    status: str
    sprints: tuple[str, ...]
    comments: frozenset[str]
    foreign_comments: frozenset[str]
    is_epic: bool = False
    epic_key: str | None = None
    # Captured with the displayed issue: context must never acknowledge a later
    # observed version of the same issue after a concurrent refresh.
    tracked: bool = True


@dataclass(frozen=True)
class Snapshot:
    user_id: str
    display_name: str
    issues: tuple[Issue, ...]


class Jira:
    def __init__(self, url: str, token: str, *, allow_local_http: bool = False):
        parts = urlsplit(url)
        if (parts.scheme != "https" and not (
            allow_local_http and parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost")
        )) or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise OverviewError("Нужен HTTPS URL Jira без пароля, query и fragment.")
        self.url = url.rstrip("/")
        # Never follow redirects, even same-origin. No auth can escape the origin.
        self.client = httpx.AsyncClient(
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
            timeout=httpx.Timeout(15.0), follow_redirects=False,
        )
        self.retry_at = 0.0

    async def close(self):
        await self.client.aclose()

    async def get(self, path: str, params: dict | None = None):
        if time.monotonic() < self.retry_at:
            raise RateLimited(self.retry_at - time.monotonic())
        try:
            response = await self.client.get(self.url + path, params=params)
        except httpx.HTTPError:
            raise OverviewError("Сетевая ошибка или ошибка TLS; повторите обновление.") from None
        code = response.status_code
        if code == 401:
            raise OverviewError("Авторизация истекла или токен неверен (401).")
        if code == 403:
            raise OverviewError("Недостаточно прав Jira (403).")
        if code == 429:
            retry = response.headers.get("Retry-After", "60")
            try:
                delay = float(retry)
            except ValueError:
                try:
                    delay = parsedate_to_datetime(retry).timestamp() - time.time()
                except (ValueError, TypeError, OverflowError):
                    delay = 60
            delay = max(1, delay) if math.isfinite(delay) else 60
            self.retry_at = time.monotonic() + delay
            raise RateLimited(delay)
        if 300 <= code < 400:
            raise OverviewError("Перенаправление Jira отклонено; проверьте адрес конфигурации.")
        if code != 200:
            raise OverviewError(f"Ошибка Jira HTTP {code}; последний обзор сохранён.")
        try:
            return response.json()
        except (ValueError, UnicodeError):
            raise OverviewError("Jira вернула некорректный JSON; обновление отклонено.") from None

    async def pages(self, path: str, field: str, params: dict | None = None) -> list[dict]:
        result, seen, total = [], set(), None
        while True:
            page = await self.get(path, {**(params or {}), "startAt": len(result), "maxResults": 100})
            try:
                items = page[field]
                count = page["total"]
                if (type(count) is not int or count < 0 or type(page["startAt"]) is not int
                        or page["startAt"] != len(result) or not isinstance(items, list)
                        or (total is not None and total != count)):
                    raise ValueError()
                total = count
                for item in items:
                    item_id = required_text(item, "id")
                    if item_id in seen:
                        raise ValueError()
                    seen.add(item_id)
                if len(result) + len(items) > total or (not items and len(result) < total):
                    raise ValueError()
                result.extend(items)
                if len(result) == total:
                    return result
            except (KeyError, TypeError, ValueError):
                raise OverviewError("Неполная или изменившаяся пагинация Jira; повторите обновление.") from None

    async def snapshot(self) -> Snapshot:
        # A finite full-cycle timeout in addition to per-request deadlines.
        try:
            async with asyncio.timeout(120):
                return await self._snapshot()
        except TimeoutError:
            raise OverviewError("Истекло время полной загрузки; последний обзор сохранён.") from None
        except (KeyError, TypeError, ValueError, AttributeError):
            raise OverviewError("Неполный или несовместимый ответ Jira; обновление отклонено.") from None

    async def _snapshot(self) -> Snapshot:
        me = await self.get("/rest/api/2/myself")
        user_id = identity(me)
        fields = await self.get("/rest/api/2/field")
        if not isinstance(fields, list):
            raise ValueError()
        detected = []
        for kind, label in (("gh-sprint", "Sprint"), ("gh-epic-label", "Epic Name"),
                            ("gh-epic-link", "Epic Link")):
            matches = [required_text(f, "id") for f in fields
                       if f.get("schema", {}).get("custom") == "com.pyxis.greenhopper.jira:" + kind]
            if len(matches) != 1:
                raise OverviewError(f"Не удалось однозначно определить поле {label} по метаданным Jira.")
            detected.append(matches[0])
        sprint_field, epic_name_field, epic_link_field = detected
        context_fields = "summary,status,parent," + epic_name_field + "," + epic_link_field
        raw = await self.pages("/rest/api/2/search", "issues", {
            "jql": 'assignee = currentUser() AND resolution = Unresolved '
                   'AND status != "Verifying" ORDER BY key ASC',
            "fields": context_fields + "," + sprint_field,
        })
        by_key: dict[str, dict] = {}
        ids: dict[str, str] = {}

        def checked_key(value):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*-\d+", value):
                raise ValueError()
            return value

        def cache(item):
            key = checked_key(required_text(item, "key"))
            iid = required_text(item, "id")
            if (not iid.isdigit() or key in by_key or iid in ids
                    or not isinstance(item["fields"], dict)):
                raise ValueError()
            by_key[key], ids[iid] = item, key
            return item

        for item in raw:
            cache(item)
        # Filter only after full pagination; excluded tasks must not load related
        # data or comments, or enter local observation. Keep them cached in case
        # a remaining task needs one as its contextual parent/epic.
        raw = [item for item in raw
               if required_text(item["fields"]["status"], "name").casefold() != "verifying"]

        def is_epic(item):
            # Epic Name is the mandatory, Epic-only locked Jira Software field.
            # Its schema is stable even when type/field names are translated.
            name = item["fields"].get(epic_name_field)
            if name is not None and (not isinstance(name, str) or not name):
                raise ValueError()
            return name is not None

        async def related(key):
            key = checked_key(key)
            if key not in by_key:
                item = await self.get("/rest/api/2/issue/" + quote(key, safe=""),
                                      {"fields": context_fields})
                if item["key"] != key:
                    raise ValueError()
                cache(item)
            return by_key[key]

        async def parent_epic(item):
            visited = set()
            while True:
                key = item["key"]
                if key in visited:
                    raise ValueError()
                visited.add(key)
                if is_epic(item):
                    return key
                data = item["fields"]
                link = data.get(epic_link_field)
                if link is not None:
                    link = checked_key(link)
                    if link in visited or not is_epic(await related(link)):
                        raise ValueError()
                    return link
                parent = data.get("parent")
                if parent is None:
                    return None
                item = await related(required_text(parent, "key"))

        memberships = {item["key"]: None if is_epic(item) else await parent_epic(item)
                       for item in raw}
        sprint_cache: dict[str, dict] = {}
        issues = []
        for item in raw:
            data = item["fields"]
            sprints = []
            values = data[sprint_field]
            if values is None:
                values = []
            if not isinstance(values, list):
                raise ValueError()
            for sprint in values:
                # Server/DC versions return either objects or legacy GreenHopper strings.
                if isinstance(sprint, dict):
                    sid = str(sprint["id"])
                elif isinstance(sprint, str):
                    match = re.search(r"\bid=(\d+)(?:,|\])", sprint)
                    if not match:
                        raise ValueError()
                    sid = match[1]
                else:
                    raise ValueError()
                if not sid.isdigit():
                    raise ValueError()
                if sid not in sprint_cache:
                    sprint_cache[sid] = await self.get("/rest/agile/1.0/sprint/" + sid)
                metadata = sprint_cache[sid]
                state = required_text(metadata, "state")
                if state not in ("active", "closed", "future"):
                    raise ValueError()
                if state == "active":
                    sprints.append(plain(required_text(metadata, "name")) + " (#" + sid + ")")
            issue_id = required_text(item, "id")
            key = required_text(item, "key")
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*-\d+", key) or not issue_id.isdigit():
                raise ValueError()
            comments = await self.pages("/rest/api/2/issue/" + quote(issue_id, safe="") + "/comment", "comments")
            all_ids, foreign_ids = set(), set()
            for comment in comments:
                cid = required_text(comment, "id")
                required_text(comment, "created")
                author = identity(comment["author"])
                all_ids.add(cid)
                if author != user_id:
                    foreign_ids.add(cid)
            issues.append(Issue(issue_id, key, plain(required_text(data, "summary")),
                                plain(required_text(data["status"], "name")),
                                tuple(sorted(set(sprints))), frozenset(all_ids), frozenset(foreign_ids),
                                is_epic(item), memberships[key]))
        own_keys = {item["key"] for item in raw}
        for key in sorted(set(memberships.values()) - {None} - own_keys):
            item = by_key[key]
            data = item["fields"]
            issues.append(Issue(item["id"], key, plain(required_text(data, "summary")),
                                plain(required_text(data["status"], "name")), (),
                                frozenset(), frozenset(), is_epic=True, tracked=False))
        return Snapshot(user_id, plain(required_text(me, "displayName")),
                        tuple(sorted(issues, key=lambda i: i.key)))

    def browser_url(self, issue: Issue) -> str:
        return self.url + "/browse/" + quote(issue.key, safe="")


class State:
    """Only IDs and unread flags persist. One lock per instance/account profile."""
    def __init__(self, directory: Path, instance: str, user: str):
        self.lock = None
        self.user = user
        self.data = {"version": 1, "baseline": False, "issues": {}}
        profile = hashlib.sha256((instance + "\0" + user).encode()).hexdigest()
        self.path = directory / (profile + ".json")
        try:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(directory / (profile + ".lock"), os.O_CREAT | os.O_RDWR, 0o600)
            self.lock = os.fdopen(fd, "a+")
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ProfileBusy(directory / (profile + ".lock")) from None
            if self.path.exists():
                data = json.loads(self.path.read_text())
                self.validate(data)
                self.data = data
        except OverviewError:
            self.close()
            raise
        except (ValueError, TypeError, KeyError):
            self.close()
            raise OverviewError("Состояние повреждено; файл сохранён. Восстановите резервную копию перед повтором.") from None
        except OSError:
            self.close()
            raise OverviewError("Не удалось открыть локальное состояние; проверьте доступ к каталогу.") from None

    @staticmethod
    def validate(data):
        if (not isinstance(data, dict) or data.get("version") != 1
                or type(data.get("baseline")) is not bool or not isinstance(data.get("issues"), dict)):
            raise ValueError()
        if not data["baseline"] and data["issues"]:
            raise ValueError()
        for key, value in data["issues"].items():
            if (not isinstance(key, str) or not isinstance(value, dict)
                    or type(value.get("new")) is not bool
                    or not isinstance(value.get("seen"), list)
                    or not all(isinstance(c, str) for c in value["seen"])):
                raise ValueError()

    def close(self):
        if self.lock is not None:
            self.lock.close()
            self.lock = None

    def save(self, data):
        temp = None
        try:
            fd, temp = tempfile.mkstemp(dir=self.path.parent, prefix=".state-")
            with os.fdopen(fd, "w") as stream:
                json.dump(data, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
        except OSError:
            raise OverviewError("Не удалось сохранить отметки на диск; изменения НЕ сохранены.") from None
        finally:
            if temp:
                try:
                    os.unlink(temp)
                except OSError:
                    # A leftover private temporary file must not mask the safe error.
                    pass
        self.data = data

    def ingest(self, snapshot: Snapshot):
        data = copy.deepcopy(self.data)
        for issue in snapshot.issues:
            if issue.tracked and issue.id not in data["issues"]:
                data["issues"][issue.id] = {"new": data["baseline"], "seen": sorted(issue.comments)}
        data["baseline"] = True
        self.save(data)

    def markers(self, issue: Issue) -> tuple[bool, int]:
        if not issue.tracked:
            return False, 0
        record = self.data["issues"][issue.id]
        return record["new"], len(issue.foreign_comments - set(record["seen"]))

    def acknowledge(self, shown: Issue):
        if not shown.tracked:
            return
        data = copy.deepcopy(self.data)
        record = data["issues"][shown.id]
        record["new"] = False
        record["seen"] = sorted(set(record["seen"]) | shown.comments)
        self.save(data)
