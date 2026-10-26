"""Synthetic TOML configuration; no Jira requests or private configuration."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jira_overview.__main__ import configuration


class ConfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_refresh_interval_is_one_hour(self):
        await self.assert_interval(None, 3600)

    async def test_explicit_refresh_interval_still_overrides_default(self):
        for interval in (5, 60, 3600, 86400):
            with self.subTest(interval=interval):
                await self.assert_interval(interval, interval)

    async def assert_interval(self, configured, expected):
        with tempfile.TemporaryDirectory(prefix="jira-config-") as directory:
            root = Path(directory)
            config = root / "config.toml"
            contents = ('url = "https://jira.example.invalid/jira"\n'
                        'token_env = "SYNTHETIC_HOURLY_PAT"\n')
            if configured is not None:
                contents += f"refresh_seconds = {configured}\n"
            config.write_text(contents)
            with patch.dict(os.environ, {"SYNTHETIC_HOURLY_PAT": "synthetic-token",
                                         "XDG_STATE_HOME": str(root / "state")}):
                jira, state_dir, interval = configuration(config)
            try:
                self.assertEqual(interval, expected)
                self.assertEqual(state_dir, root / "state/jira-overview")
                self.assertFalse(state_dir.exists())
            finally:
                await jira.close()


if __name__ == "__main__":
    unittest.main()
