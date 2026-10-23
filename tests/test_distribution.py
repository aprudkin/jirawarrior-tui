"""Installed metadata and CLI are the standalone package's public boundary."""
from importlib import metadata
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DistributionTests(unittest.TestCase):
    def test_standalone_metadata_preserves_the_command(self):
        distribution = metadata.distribution("jirawarrior-tui")
        self.assertEqual(distribution.version, "0.1.0")
        self.assertEqual(distribution.metadata["License-Expression"], "MIT")
        self.assertEqual(
            [(entry.name, entry.value) for entry in distribution.entry_points
             if entry.group == "console_scripts"],
            [("jira-overview", "jira_overview.__main__:main")],
        )

    def test_installed_command_runs_from_an_unrelated_directory(self):
        command = Path(sys.executable).parent / "jira-overview"
        with tempfile.TemporaryDirectory(prefix="jira-cli-") as directory:
            env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            result = subprocess.run(
                [str(command), "--help"], cwd=directory, env=env,
                capture_output=True, text=True, timeout=15,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--check", result.stdout)
        self.assertIn("--config", result.stdout)

    def test_legacy_config_paths_and_failed_check_preserve_state(self):
        command = Path(sys.executable).parent / "jira-overview"
        for xdg in (False, True):
            with self.subTest(xdg=xdg), tempfile.TemporaryDirectory(prefix="jira-cli-") as directory:
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
