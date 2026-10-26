"""Bounded macOS discovery and confirmed SIGINT for one busy profile only."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import fcntl
import hashlib
import os
from pathlib import Path
import re
import shlex
import signal
import stat

from .core import OverviewError


_CHANGED = "Владелец профиля изменился; выполните поиск снова."
_UNKNOWN = "Не удалось однозначно найти другой Jira Warrior. Закройте его вручную и нажмите R."


@dataclass(frozen=True)
class LockOwner:
    pid: int
    uid: int
    started: str
    command_hash: str
    device: int
    inode: int


def _probe(path: Path) -> tuple[tuple[int, int], bool] | None:
    """Probe the existing inode, never create/unlink/write a profile file."""
    try:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError:
        raise OverviewError(_UNKNOWN) from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise OverviewError(_UNKNOWN)
        identity = info.st_dev, info.st_ino
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return identity, True
        return identity, False
    except OSError:
        raise OverviewError(_UNKNOWN) from None
    finally:
        os.close(fd)


async def _command(*arguments: str) -> tuple[int, str]:
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"})
        output, _ = await asyncio.wait_for(process.communicate(), timeout=3)
        return process.returncode, output.decode("utf-8", errors="replace")
    except (OSError, TimeoutError):
        raise OverviewError("Поиск процесса недоступен; закройте другой экземпляр вручную и нажмите R.") from None
    finally:
        if process is not None and process.returncode is None:
            try:
                process.kill()  # Our lsof/ps utility only, never the owner.
            except ProcessLookupError:
                pass
            await process.wait()


def _warrior_command(command: str) -> bool:
    try:
        arguments = shlex.split(command)
    except ValueError:
        return False
    if not arguments:
        return False
    name = Path(arguments[0]).name
    if name in {"jirawarrior", "jw"}:
        return True
    if not re.fullmatch(r"python(?:[0-9]+(?:\.[0-9]+)*)?", name):
        return False
    arguments = arguments[1:]
    while arguments and arguments[0] in {"-I", "-B", "-u", "-s", "-E"}:
        arguments = arguments[1:]
    return (len(arguments) >= 2 and arguments[:2] == ["-m", "jira_overview"]
            or bool(arguments) and Path(arguments[0]).name in {"jirawarrior", "jw"})


async def _identity(pid: int, inode: tuple[int, int]) -> LockOwner | None:
    code, before = await _command("/bin/ps", "-p", str(pid), "-o", "uid=,lstart=")
    if code != 0:
        return None
    fields = before.split()
    if len(fields) != 6 or not fields[0].isdigit() or int(fields[0]) != os.getuid():
        return None
    code, command = await _command("/bin/ps", "-ww", "-p", str(pid), "-o", "command=")
    if code != 0 or not _warrior_command(command):
        return None
    code, after = await _command("/bin/ps", "-p", str(pid), "-o", "uid=,lstart=")
    if code != 0 or before != after:
        return None
    return LockOwner(pid, int(fields[0]), " ".join(fields[1:]),
                     hashlib.sha256(command.encode()).hexdigest(), *inode)


async def find_lock_owner(path: Path) -> LockOwner | None:
    """Return a verified candidate, None for a free lock, or a safe refusal."""
    initial = _probe(path)
    if initial is None or not initial[1]:
        return None
    inode = initial[0]
    code, output = await _command("/usr/sbin/lsof", "-nP", "-Fp", "--", str(path))
    if code not in (0, 1):
        raise OverviewError(_UNKNOWN)
    pids = {int(line[1:]) for line in output.splitlines()
            if line.startswith("p") and line[1:].isdigit()}
    pids.discard(os.getpid())
    pids.difference_update({0, 1})
    owner = await _identity(next(iter(pids)), inode) if len(pids) == 1 else None
    current = _probe(path)
    if current is None or not current[1]:
        return None
    if current[0] != inode:
        raise OverviewError(_CHANGED)
    if owner is None:
        raise OverviewError(_UNKNOWN)
    return owner


async def stop_lock_owner(path: Path, expected: LockOwner) -> None:
    """Revalidate the confirmed candidate; send at most one SIGINT, no escalation."""
    current = await find_lock_owner(path)
    if current is None:
        return
    if current != expected or current.pid in {0, 1, os.getpid()}:
        raise OverviewError(_CHANGED)
    try:
        os.kill(current.pid, signal.SIGINT)
    except ProcessLookupError:
        pass
    except OSError:
        raise OverviewError("Не удалось завершить другой экземпляр; сигнал не будет повторён автоматически.") from None
    for _ in range(60):
        probe = _probe(path)
        if probe is None or not probe[1]:
            return
        if probe[0] != (expected.device, expected.inode):
            raise OverviewError(_CHANGED)
        await asyncio.sleep(0.05)
    raise OverviewError("Другой экземпляр не освободил профиль. Принудительное завершение не выполнялось; повторите R позже.")
