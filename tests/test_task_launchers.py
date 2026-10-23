"""Public Go Task contract; real Task, fake installed CLI, no Jira or credentials."""
import json
import os
from pathlib import Path
import pty
import select
import shutil
import subprocess
import tempfile
import unittest


TASK = shutil.which("task")
TASKFILE = Path(__file__).resolve().parents[1] / "Taskfile.yml"


@unittest.skipUnless(TASK, "Go Task is needed only for launcher integration tests")
class TaskLaunchers(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="jira-task-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        home = root / "home with spaces"
        self.project = home / ".config/jira-overview"
        self.project.mkdir(parents=True)
        if TASKFILE.exists():
            shutil.copyfile(TASKFILE, self.project / "Taskfile.yml")
        (home / "Taskfile.yml").write_text(json.dumps({
            "version": "3", "includes": {"jira": {
                "taskfile": "~/.config/jira-overview/Taskfile.yml",
                "optional": True, "flatten": True,
            }},
        }))
        self.caller = root / "unrelated caller"
        self.caller.mkdir()
        (self.caller / "Taskfile.yml").write_text('{"version":"3","tasks":{}}')
        binary = root / "bin"
        binary.mkdir()
        command = binary / "jira-overview"
        command.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "print(json.dumps({'args': sys.argv[1:], 'cwd': os.getcwd(),\n"
            " 'token': os.environ.get('SYNTHETIC_TOKEN'),\n"
            " 'tty': all(os.isatty(fd) for fd in (0, 1, 2))}))\n"
            "sys.exit(int(os.environ.get('PROBE_EXIT', '0')))\n"
        )
        command.chmod(0o700)
        # A tool install needs uv only at installation time, not to launch the CLI.
        uv = binary / "uv"
        uv.write_text("#!/bin/sh\necho 'Unexpected uv dependency at launch' >&2\nexit 99\n")
        uv.chmod(0o700)
        self.env = {
            "HOME": str(home), "PATH": f"{binary}:{os.environ['PATH']}",
            "SYNTHETIC_TOKEN": "synthetic-environment-only",
        }

    def run_task(self, *arguments):
        return subprocess.run(
            [TASK, "--global", *arguments], cwd=self.caller, env=self.env,
            text=True, capture_output=True, timeout=15,
        )

    def test_check_from_an_unrelated_directory(self):
        result = self.run_task("jira:check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "args": ["--check"],
            "cwd": str(self.project), "token": "synthetic-environment-only", "tty": False,
        })

    def test_interactive_launch_keeps_the_terminal(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        result = subprocess.run(
            [TASK, "--global", "jira"], cwd=self.caller, env=self.env,
            stdin=slave, stdout=slave, stderr=slave, timeout=15,
        )
        # The bounded probe fits the PTY buffer; a missing probe must fail, not hang.
        self.assertTrue(select.select([master], [], [], 1)[0], "No launcher output")
        output = os.read(master, 8192).decode()
        self.assertEqual(result.returncode, 0, output)
        self.assertEqual(json.loads(output), {
            "args": [],
            "cwd": str(self.project), "token": "synthetic-environment-only", "tty": True,
        })

    def test_failures_stay_nonzero_and_exact_status_is_available(self):
        self.env["PROBE_EXIT"] = "37"
        for name in ("jira", "jira:check", "open:jira", "check:jira"):
            with self.subTest(task=name):
                self.assertNotEqual(self.run_task(name).returncode, 0)
                self.assertEqual(self.run_task("--exit-code", name).returncode, 37)


if __name__ == "__main__":
    unittest.main()
