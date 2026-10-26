"""Installed metadata and CLI are the standalone package's public boundary."""
from importlib import metadata
from itertools import product
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


COMMANDS = ("jirawarrior", "jw")


class DistributionTests(unittest.TestCase):
    def test_standalone_metadata_exposes_only_the_new_commands(self):
        distribution = metadata.distribution("jirawarrior-tui")
        self.assertEqual(distribution.version, "0.1.0")
        self.assertEqual(distribution.metadata["License-Expression"], "MIT")
        self.assertEqual(
            sorted((entry.name, entry.value) for entry in distribution.entry_points
                   if entry.group == "console_scripts"),
            [(name, "jira_overview.__main__:main") for name in COMMANDS],
        )

    def test_removed_command_is_not_installed(self):
        self.assertFalse(os.path.lexists(Path(sys.executable).parent / "jira-overview"))

    def test_installed_commands_run_from_an_unrelated_directory(self):
        for name in COMMANDS:
            command = Path(sys.executable).parent / name
            with self.subTest(command=name), tempfile.TemporaryDirectory(prefix="jira-cli-") as directory:
                env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
                result = subprocess.run(
                    [str(command), "--help"], cwd=directory, env=env,
                    capture_output=True, text=True, timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"usage: {name} ", result.stdout)
                self.assertIn("--check", result.stdout)
                self.assertIn("--config", result.stdout)

    def test_legacy_config_paths_and_failed_check_preserve_state(self):
        for name, xdg in product(COMMANDS, (False, True)):
            command = Path(sys.executable).parent / name
            with self.subTest(command=name, xdg=xdg), tempfile.TemporaryDirectory(prefix="jira-cli-") as directory:
                root = Path(directory)
                config_home = root / ("xdg config" if xdg else ".config")
                config = config_home / "jira-overview/config.toml"
                config.parent.mkdir(parents=True)
                config.write_text('url = "https://jira.example.invalid/jira"\n'
                                  'token_env = "SYNTHETIC_ABSENT_PAT"\n')
                state = root / "state/jira-overview/legacy.json"
                state.parent.mkdir(parents=True)
                state.write_text('{"version":1,"baseline":true,"issues":{}}')
                before = state.read_bytes()
                env = {"PATH": os.environ["PATH"], "HOME": str(root),
                       "XDG_STATE_HOME": str(root / "state")}
                if xdg:
                    env["XDG_CONFIG_HOME"] = str(config_home)
                result = subprocess.run(
                    [str(command), "--check"], cwd=root, env=env,
                    capture_output=True, text=True, timeout=15,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("Переменная окружения с токеном", result.stderr)
                self.assertEqual(state.read_bytes(), before)
                self.assertEqual(list(state.parent.iterdir()), [state])


if __name__ == "__main__":
    unittest.main()
