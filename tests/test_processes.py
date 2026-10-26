"""Real child-owned temporary locks; no user processes or live Jira."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from jira_overview.core import OverviewError, State
from jira_overview.processes import find_lock_owner, stop_lock_owner


@asynccontextmanager
async def locked_process(root, state_dir, instance="https://jira.example.invalid", user="key:me",
                         *, name="jirawarrior", ignore_interrupt=False):
    executable = root / "bin" / name
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text('''import signal, sys
from pathlib import Path
from jira_overview.core import State
state = State(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
signal.signal(signal.SIGINT, signal.SIG_IGN if sys.argv[4] == "ignore" else signal.default_int_handler)
print("READY", flush=True)
try:
    while True:
        signal.pause()
except KeyboardInterrupt:
    pass
finally:
    state.close()
''')
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-I", "-B", str(executable), str(state_dir), instance, user,
        "ignore" if ignore_interrupt else "interrupt",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        ready = await asyncio.wait_for(process.stdout.readline(), 5)
        if ready != b"READY\n":
            raise AssertionError("Synthetic lock-owning child failed to start")
        yield process
    finally:
        if process.returncode is None:
            process.terminate()  # Only the child created by this fixture.
        await asyncio.wait_for(process.wait(), 5)


@unittest.skipUnless(sys.platform == "darwin", "macOS lsof/ps recovery contract")
class ProcessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jira-owner-")
        self.root = Path(self.temp.name)
        self.state_dir = self.root / "state"

    def tearDown(self):
        self.temp.cleanup()

    async def test_find_and_stop_exact_owner_without_changing_lock_or_history(self):
        async with locked_process(self.root, self.state_dir) as process:
            lock = next(self.state_dir.glob("*.lock"))
            before = lock.read_bytes(), lock.stat().st_ino
            owner = await find_lock_owner(lock)
            self.assertEqual(owner.pid, process.pid)
            self.assertEqual(owner.uid, os.getuid())
            self.assertEqual(before, (lock.read_bytes(), lock.stat().st_ino))
            await stop_lock_owner(lock, owner)
            await asyncio.wait_for(process.wait(), 3)
            self.assertEqual(process.returncode, 0)
            self.assertIsNone(await find_lock_owner(lock))
            self.assertEqual(before, (lock.read_bytes(), lock.stat().st_ino))
            self.assertFalse(list(self.state_dir.glob("*.json")))
            state = State(self.state_dir, "https://jira.example.invalid", "key:me")
            state.close()

    async def test_free_or_missing_profile_never_signals_another_profile(self):
        async with locked_process(self.root, self.state_dir) as process:
            free = self.state_dir / "different.lock"
            free.touch()
            owner = await find_lock_owner(next(p for p in self.state_dir.glob("*.lock") if p != free))
            with patch("jira_overview.processes.os.kill") as kill:
                self.assertIsNone(await find_lock_owner(free))
                self.assertIsNone(await find_lock_owner(self.state_dir / "missing.lock"))
                await stop_lock_owner(free, owner)
                kill.assert_not_called()
            self.assertIsNone(process.returncode)

    async def test_current_process_is_not_a_stop_candidate(self):
        state = State(self.state_dir, "https://jira.example.invalid", "key:me")
        try:
            with self.assertRaises(OverviewError):
                await find_lock_owner(next(self.state_dir.glob("*.lock")))
        finally:
            state.close()

    async def test_unrecognized_lock_owner_is_not_a_stop_candidate(self):
        async with locked_process(self.root, self.state_dir, name="unrelated.py") as process:
            with self.assertRaises(OverviewError):
                await find_lock_owner(next(self.state_dir.glob("*.lock")))
            self.assertIsNone(process.returncode)

    async def test_changed_start_time_or_inode_refuses_signal(self):
        async with locked_process(self.root, self.state_dir) as process:
            lock = next(self.state_dir.glob("*.lock"))
            owner = await find_lock_owner(lock)
            for stale in (replace(owner, started="a previous process"),
                          replace(owner, inode=owner.inode + 1), replace(owner, pid=os.getpid())):
                with self.subTest(stale=stale), patch("jira_overview.processes.os.kill") as kill:
                    with self.assertRaises(OverviewError):
                        await stop_lock_owner(lock, stale)
                    kill.assert_not_called()
            self.assertIsNone(process.returncode)

    async def test_other_uid_and_ambiguous_pids_refuse_without_signal(self):
        async with locked_process(self.root, self.state_dir) as process:
            lock = next(self.state_dir.glob("*.lock"))
            with patch("jira_overview.processes.os.getuid", return_value=os.getuid() + 1):
                with self.assertRaises(OverviewError):
                    await find_lock_owner(lock)
            with patch("jira_overview.processes._command", AsyncMock(return_value=(
                    0, f"p{process.pid}\np{process.pid + 1}\n"))):
                with self.assertRaises(OverviewError):
                    await find_lock_owner(lock)
            self.assertIsNone(process.returncode)

    async def test_unavailable_utility_has_safe_error_and_does_not_signal(self):
        async with locked_process(self.root, self.state_dir) as process:
            with patch("jira_overview.processes.asyncio.create_subprocess_exec",
                       side_effect=OSError("private URL and path")):
                with self.assertRaises(OverviewError) as error:
                    await find_lock_owner(next(self.state_dir.glob("*.lock")))
                self.assertNotIn("private", str(error.exception))
            self.assertIsNone(process.returncode)

    async def test_ignoring_interrupt_does_not_escalate_or_repeat_signal(self):
        async with locked_process(self.root, self.state_dir, ignore_interrupt=True) as process:
            lock = next(self.state_dir.glob("*.lock"))
            owner = await find_lock_owner(lock)
            with patch("jira_overview.processes.os.kill", wraps=os.kill) as kill:
                with self.assertRaises(OverviewError):
                    await stop_lock_owner(lock, owner)
                kill.assert_called_once_with(process.pid, signal.SIGINT)
            self.assertIsNone(process.returncode)

    async def test_cancelled_lookup_reaps_its_real_utility_without_signalling_owner(self):
        async with locked_process(self.root, self.state_dir) as owner:
            spawn = asyncio.create_subprocess_exec
            spawned, started = [], asyncio.Event()
            async def slow_utility(*arguments, **kwargs):
                process = await spawn(sys.executable, "-I", "-B", "-c",
                                      "import time; time.sleep(60)", **kwargs)
                spawned.append(process)
                started.set()
                return process
            with patch("jira_overview.processes.asyncio.create_subprocess_exec", side_effect=slow_utility):
                task = asyncio.create_task(find_lock_owner(next(self.state_dir.glob("*.lock"))))
                await asyncio.wait_for(started.wait(), 2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertEqual(len(spawned), 1)
            self.assertIsNotNone(spawned[0].returncode)
            self.assertIsNone(owner.returncode)

    async def test_cancelled_lookup_does_not_signal_owner(self):
        async with locked_process(self.root, self.state_dir) as process:
            started = asyncio.Event()
            async def waiting(*args):
                started.set()
                await asyncio.Event().wait()
            with patch("jira_overview.processes._command", side_effect=waiting):
                task = asyncio.create_task(find_lock_owner(next(self.state_dir.glob("*.lock"))))
                await asyncio.wait_for(started.wait(), 2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertIsNone(process.returncode)


if __name__ == "__main__":
    unittest.main()
